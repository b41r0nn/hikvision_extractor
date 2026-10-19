# Sistema de Asistencia Biométrica — REDIHOS S.A.S

> **Versión actual:** `v1.6-security-fixes`

Sistema de control de asistencia para **REPRESENTACIONES Y DISTRIBUCIONES
HOSPITALARIAS S.A.S. (REDIHOS)**. Extrae marcaciones de un dispositivo
Hikvision mediante su API ISAPI, las almacena en **PostgreSQL**, expone una
API REST con **FastAPI** y ofrece un panel web con **Nginx + HTML/JS** sobre HTTPS.

El sistema genera informes Excel con formato dinámico, calcula tardanzas,
envía reportes automáticos por correo y permite administrar empleados,
roles, permisos y configuración de correo desde una interfaz web.

---

## 1. Stack y arquitectura

### 1.1 Servicios

| Servicio      | Tecnología                       | Puerto expuesto (prod)  | Responsabilidad                                                               |
| ------------- | -------------------------------- | ----------------------- | ----------------------------------------------------------------------------- |
| Base de datos | PostgreSQL 15 (Alpine)           | interno (no expuesto)   | Persistencia de empleados, marcas, festivos, usuarios, roles y configuración. |
| Backend API   | FastAPI + Uvicorn (Python 3.11)  | interno (proxy nginx)   | Extracción, reportes, autenticación, RBAC, scheduler y configuración.         |
| Frontend      | Nginx + HTML/JS                  | `80` (→443), `443` HTTPS| Panel de login, dashboard, reportes y administración. Hace proxy de `/api/`.  |
| Scheduler     | APScheduler (dentro del backend) | —                       | Jobs de extracción diaria, sync de empleados y reportes semanal/mensual.      |

> En producción el backend **no se expone directamente**: Nginx hace proxy de
> `/api/` a `http://backend:8000/api/`. PostgreSQL tampoco es accesible desde fuera
> de la red Docker interna.

### 1.2 Diagrama de flujo

```text
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Biométrico     │────▶│  extractor_       │────▶│  PostgreSQL    │
│  Hikvision      │ ISAPI│ hikvision.py     │     │  (registros)    │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                                            │
                                  ┌─────────────────────────┘
                                  ▼
                         ┌──────────────────┐
                         │  backend/main.py  │
                         │  FastAPI + UI     │
                         └──────────────────┘
                                  │
               ┌─────────────────┼─────────────────┐
               ▼                 ▼                 ▼
         ┌──────────┐      ┌──────────┐      ┌──────────┐
         │ KPIs /   │      │ Reportes │      │ Correo   │
         │ Tardanzas│      │  Excel   │      │ SMTP     │
         └──────────┘      └──────────┘      └──────────┘
```

---

## 2. Estructura del proyecto

```text
.
├── alembic/                        # Migraciones de base de datos
│   └── versions/
│       ├── ...baseline_schema.py
│       ├── b7c4e19a2f30_...py      # Unique constraint en registros_asistencia
│       └── c9d1e2f3a4b5_add_performance_indexes.py  # Índices de performance (v1.6)
├── backend/
│   ├── auth.py                     # JWT, Argon2id, RBAC
│   ├── config_service.py           # Configuración persistente y alertas
│   ├── config_correo_service.py    # Configuración SMTP encriptada (Fernet)
│   ├── crypto_service.py           # Encriptación simétrica con Fernet
│   ├── database.py                 # Conexión SQLAlchemy + SessionLocal
│   ├── email_service.py            # Envío SMTP de reportes
│   ├── logging_config.py           # Logging rotativo a /app/logs/app.log (v1.6)
│   ├── main.py                     # API FastAPI, lifespan, rate limiting
│   ├── models.py                   # Modelos SQLAlchemy
│   ├── report_service.py           # Motor de Excel y tardanzas
│   ├── scheduler.py                # Jobs programados con APScheduler
│   ├── sync_empleados.py           # Sincronización de empleados desde el biométrico
│   └── timezone.py                 # Helpers de zona horaria Bogotá
├── frontend/
│   ├── index.html                  # UI del panel
│   ├── app.js                      # Lógica del frontend (usa /api relativo para HTTPS)
│   └── nginx.conf                  # Configuración Nginx: HTTPS, redirect, proxy /api/ (v1.6)
├── tests/                          # Suite de tests automatizados (v1.6)
│   ├── conftest.py                 # Fixtures SQLite en memoria, rollback por test
│   ├── test_auth.py                # Tests de hash, JWT, RBAC (11 tests)
│   ├── test_extractor.py           # Tests de normalize, fetch_range, save_to_db (12 tests)
│   ├── test_report_service.py      # Tests de tardanzas, fusión de marcas (14 tests)
│   └── test_api_endpoints.py       # Tests de integración REST (17 tests)
├── extractor_hikvision.py          # Script/CLI de extracción ISAPI
├── generar_informe.py              # CLI para generar Excel desde PostgreSQL
├── migrate_csv.py                  # CLI para migrar CSV de iVMS-4200 a PostgreSQL
├── docker-compose.yml              # Orquestación de desarrollo
├── docker-compose.prod.yml         # Orquestación de producción (HTTPS, backend interno)
├── backend.Dockerfile              # Imagen del backend
├── frontend.Dockerfile             # Imagen del frontend (genera cert SSL auto-firmado)
├── backup.ps1                      # Backup manual/automático en Windows (PowerShell)
├── backup.sh                       # Backup manual/automático en Linux/WSL
├── .env.example                    # Variables de entorno documentadas
├── requirements.txt                # Dependencias Python
├── handoff_hikvision_asistencia.md # Notas internas de handoff
└── README.md                       # Este archivo
```

---

## 3. Base de datos

### 3.1 Conexión

La conexión se define en `backend/database.py`:

```python
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")
if not SQLALCHEMY_DATABASE_URL: |
    raise RuntimeError(
        "DATABASE_URL no está configurada. Revisá el .env — "
        "no hay fallback por diseño, para evitar arrancar silenciosamente "
        "contra una BD equivocada."
    )

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
```

En Docker, `DATABASE_URL` apunta al servicio `db` definido en
`docker-compose.yml`. En desarrollo local se puede usar SQLite con
`DATABASE_URL=sqlite:///./test.db`. Si la variable no está configurada, el
proceso falla al arrancar.

### 3.2 Tablas principales

| Tabla                  | Propósito                                                                                     |
| ---------------------- | --------------------------------------------------------------------------------------------- |
| `turnos`               | Catálogo legacy de turnos. La UI actual usa turno individual por empleado.                    |
| `empleados`            | Personas registradas en el sistema. `employee_id` enlaza con el biométrico.                   |
| `festivos`             | Festivos colombianos poblados automáticamente por `holidays`.                                 |
| `registros_asistencia` | Cada marca de entrada/salida extraída del biométrico.                                         |
| `configuracion`        | Clave-valor persistente: destinatarios de correo, periodicidad, última extracción, alertas.   |
| `configuracion_correo` | Fila única con la configuración SMTP encriptada (host, puerto, usuario, password, seguridad). |
| `permisos`             | Lista canónica de permisos del sistema (ej. `ver_dashboard`, `admin_roles`).                  |
| `roles`                | Roles definidos por el administrador.                                                         |
| `rol_permiso`          | Relación muchos-a-muchos entre roles y permisos.                                              |
| `usuarios`             | Usuarios del panel web con `password_hash`, rol y bandera de cambio de contraseña.            |

### 3.3 Relaciones clave

- `Empleado.employee_id` se relaciona con
  `RegistroAsistencia.empleado_id` y `RegistroAsistencia.nombre_empleado`.
- La relación es `viewonly=True` porque `employee_id` puede ser `NULL` en
  registros de personas no enroladas o eventos de sistema.
- `Usuario.rol_id` apunta a `roles.id`; un rol tiene muchos permisos.
- `Configuracion` almacena JSON serializado para listas complejas (destinatarios,
  alertas de extracción incompleta).

---

## 4. Componentes del backend

### 4.1 `backend/main.py` — API FastAPI

Es el punto de entrada del backend. Define:

- `lifespan(app)`: se ejecuta al arrancar Uvicorn y hace lo siguiente:
  1. Configura el logging rotativo (`setup_logging()`).
  2. Ejecuta `alembic upgrade head` para migrar el esquema.
  3. Puebla festivos colombianos (`init_festivos`).
  4. Inicializa roles, permisos y usuario admin (`init_rbac`).
  5. Crea configuración por defecto (`config_service.init_defaults`).
  6. Si la última extracción exitosa es anterior a hoy, lanza un **backfill**
     en segundo plano para recuperar los días faltantes.
  7. Inicia el scheduler de APScheduler.
- **Rate limiting** con `slowapi`: `10 req/min` en `/api/auth/login` y
  `5 req/min` en `/api/extraer`. Devuelve `429 Too Many Requests` al superarlo.
- Middleware CORS con métodos y headers explícitos: solo `GET, POST, PUT, DELETE`
  y `Content-Type, Authorization`.
- Endpoints agrupados por dominio: autenticación, roles, usuarios, empleados,
  registros, KPIs, reportes, configuración de correo y extracción manual.
- Estados globales `extraction_state` y `sync_state` para que el frontend
  pueda consultar el progreso de operaciones en background.
- Validación de rango de fechas en `/api/extraer`: formato ISO, orden
  cronológico y máximo 365 días.

### 4.2 `backend/auth.py` — Autenticación y autorización

- **JWT**: tokens firmados con `SECRET_KEY` del `.env`; expiran según
  `ACCESS_TOKEN_EXPIRE_MINUTES` (default 480 min = 8 horas).
- **Hash**: contraseñas hasheadas con **Argon2id** usando `passlib` +
  `argon2-cffi`. Nunca se almacena texto plano.
- **RBAC**: roles y permisos almacenados en tablas. `require_perm("perm")`
  es una factory de dependencias FastAPI que devuelve 403 si el usuario no
  tiene el permiso.
- **Primer login**: usuarios creados desde el admin o sembrados desde `.env`
  nacen con `requiere_cambio_password=True`. El frontend bloquea la app hasta
  que el usuario cambia su contraseña.
- Permisos canónicos: `ver_dashboard`, `generar_reportes`, `forzar_extraccion`,
  `sync_empleados`, `admin_empleados`, `admin_correo`, `admin_roles`.

### 4.3 `backend/models.py` — Modelos SQLAlchemy

Define las clases mapeadas a tablas. Cada modelo hereda de `Base` declarative.
Destacados:

- `Empleado`: `employee_id`, `nombre`, `departamento`, `activo`,
  `turno_id` ( FK a `turnos`). Las columnas `hora_entrada` y
  `tolerancia_minutos` quedan deprecadas en Fase A.
- `Turno`: nombre del turno. Su horario real vive en `turno_horario`.
- `TurnoHorario`: horario versionado por día de semana (`dia_semana`
  0=lunes...4=viernes) y fecha de vigencia (`vigente_desde`). Permite
  cambiar el horario de un día a partir de una fecha sin perder el
  historial.
- `RegistroAsistencia`: guarda `evento_raw` (timestamp ISO original del
  dispositivo) para auditoría.
- `Usuario`: `password_hash`, `rol_id`, `activo`, `requiere_cambio_password`.

### 4.4 `backend/database.py`

Crea el `engine`, `SessionLocal` y `get_db()` que se inyecta como dependencia
FastAPI. Todas las sesiones se cierran automáticamente con `try/finally`.

### 4.5 `backend/timezone.py`

Todo el negocio opera en `America/Bogota`. Proporciona:

- `hoy_bogota()` → `date` local.
- `ahora_bogota()` → `datetime` consciente de zona.
- `ahora_utc()` → para tokens y auditoría.

El `backend.Dockerfile` instala `tzdata`, define `TZ=America/Bogota` y vincula
`/etc/localtime`.

### 4.6 `backend/scheduler.py` — Tareas programadas

Usa `BackgroundScheduler` de APScheduler con los siguientes jobs:

| Job                     | Horario                       | Función                                             |
| ----------------------- | ----------------------------- | --------------------------------------------------- |
| `sync_empleados_diaria` | 7:00 AM                       | Sincroniza empleados enrolados desde el biométrico. |
| `extraccion_periodica`  | 6:00 AM - 8:00 PM (cada hora) | Extrae las marcaciones del día en horario laboral.  |
| `reporte_semanal`       | Configurable                  | Envía por correo el informe de la semana pasada.    |
| `reporte_mensual`       | Configurable                  | Envía por correo el informe del mes anterior.       |

Parámetros importantes:

- `misfire_grace_time=60`: si el contenedor estuvo caído en la hora programada,
  el job solo se recupera si el retraso es de 60 segundos o menos. Si el
  retraso es mayor, APScheduler descarta esa ejecución y espera la siguiente.
- `coalesce=True`: si se acumulan varias ejecuciones perdidas, se colapsan en una.
- `replace_existing=True`: permite reprogramar los jobs sin reiniciar.

### 4.7 `backend/config_service.py` — Configuración persistente

Abstrae la tabla `Configuracion` como clave-valor:

- `get_recipients`, `add_recipient`, `remove_recipient`: destinatarios de
  reportes automáticos.
- `get_periodicidad`, `set_periodicidad`: día/hora de reportes semanal y mensual.
- `get_ultima_extraccion`, `set_ultima_extraccion`: timestamp de la última
  extracción exitosa.
- `add_alerta_extraccion`, `get_alertas_extraccion`: alertas de extracción
  incompleta. Mantiene solo los últimos 14 días.

### 4.8 `backend/email_service.py` — Envío de correos

- Lee la configuración SMTP desde la tabla `configuracion_correo`
  (`config_correo_service.get_config_desencriptada`). La contraseña se
  almacena encriptada con Fernet usando `FERNET_KEY` del `.env`.
- Lee destinatarios desde la base de datos (`config_service.get_recipients`).
- `enviar_reporte_semanal`: semana laboral pasada (lunes a viernes).
- `enviar_reporte_mensual`: mes anterior completo.
- `enviar_correo_prueba_a`: envía un correo de prueba a una dirección específica.
- Adjunta el Excel generado por `report_service.generar_reporte`.
- Si no hay configuración de correo guardada, los jobs loguean un mensaje claro
  en lugar de intentar conectar con credenciales vacías.

### 4.9 `backend/report_service.py` — Motor de Excel y tardanzas

- `init_festivos`: carga festivos colombianos con la librería `holidays`
  (incluye Ley Emiliani).
- `es_dia_laboral`: lunes a viernes, sin festivos.
- `_fusionar_marcas_por_empleado_dia`: agrupa marcas del mismo empleado/día
  dentro de `MARCA_FUSION_MINUTOS` (default 2 min). El Excel muestra solo la
  primera de cada grupo; la base de datos conserva todas.
- `generar_reporte`: produce un `.xlsx` con dos modos:
  - `entrada_salida`: dos columnas por día (Entrada / Salida).
  - `completo`: columnas dinámicas `Marca 1`, `Marca 2`, ... según la máxima
    cantidad de marcas de un día.
- `obtener_horario_vigente`: consulta `turno_horario` para devolver el horario
  vigente de un turno, día de semana y fecha. Lanza
  `HorarioNoConfiguradoError` si no existe.
- `calcular_tardanzas_dia`: compara la primera marca del día con la hora de
  entrada vigente del turno + tolerancia. No usa variables de `.env` ni
  horarios individuales deprecados.

### 4.10 `backend/sync_empleados.py` — Sincronización de empleados

Consulta `/ISAPI/AccessControl/UserInfo/Search` del biométrico con paginación
(`BATCH_SIZE=1000`).

- Si el `employee_id` ya existe, actualiza el nombre.
- Si no existe, crea el empleado con `activo=True` y sin departamento/turno.
- **Nunca elimina empleados**; el admin los desactiva manualmente.

### 4.11 `extractor_hikvision.py` — Extracción del biométrico

Puede ejecutarse como script independiente o ser llamado desde el backend.

#### 4.11.1 Conectividad y autenticación

- Lee `DEVICE_IP`, `DEVICE_USER`, `DEVICE_PASS` del `.env` como valores por
  defecto, pero los acepta también como parámetros (`ip`, `user`, `password`,
  `url`) en `fetch_range()`, `fetch_day()` y `main()`.
- **Los globales `IP`, `USER`, `PASS`, `URL` nunca se mutan** en tiempo de
  ejecución: `main()` usa variables locales en lugar de `global`. Esto permite
  llamadas concurrentes con distintas credenciales sin condición de carrera.
- Usa autenticación HTTP Digest contra `http://<IP>/ISAPI/AccessControl/AcsEvent?format=json`.
- Antes de extraer un rango, hace un `socket.create_connection((IP, 80), timeout=3)`
  para detectar rápidamente si el dispositivo no responde.
- Si hay falla de red, lanza `DeviceUnavailableError` para que el llamador
  aborte sin marcar la extracción como exitosa.

#### 4.11.2 Paginación y fallback

- `BATCH_SIZE=50` para el endpoint de eventos.
- Cada llamada usa un `searchID` UUID nuevo para evitar que el dispositivo
  pise resultados entre paginaciones.
- Un `threading.Lock` global (`backend/device_lock.py`) serializa **todas** las
  llamadas HTTP al dispositivo, tanto de extracción de marcas (`extractor_hikvision.py`)
  como de sincronización de empleados (`backend/sync_empleados.py`). Evita
  condiciones de carrera entre job programado, extracción manual y sync de empleados.
- Si la primera consulta de 24h devuelve menos eventos que `totalMatches`,
  divide el día en AM/PM. Si alguna mitad sigue truncada, divide en Q1-Q4.
- Filtra eventos de autenticación de personas: `Fingerprint Recognition Passed`,
  `Face Authentication Passed`, `Card Authentication Passed`.

#### 4.11.3 Persistencia

- `save_to_db`: inserta solo marcas nuevas (deduplicación por empleado, fecha,
  hora). Luego `main()` hace `commit()` solo si todo el rango se procesó sin
  errores de red.
- Si ocurre `DeviceUnavailableError` en medio de un rango, se hace `rollback`,
  se cierra la sesión y se relanza la excepción. Los días anteriores ya
  commiteados se conservan.

---

## 5. Cómo funciona el sistema paso a paso

### 5.1 Arranque del backend

1. Uvicorn ejecuta `backend/main.py`.
2. El `lifespan` corre `alembic upgrade head`.
3. Puebla festivos, roles, permisos y usuario admin.
4. Lee `ultima_extraccion_exitosa` de `configuracion`.
5. Si `ultima < hoy_bogota()`, lanza un hilo daemon que ejecuta
   `extractor_hikvision.main(start, end)` para el rango faltante.
6. Inicia APScheduler.

### 5.2 Backfill automático

- Si el contenedor estuvo apagado varios días, al reiniciar recupera los días
  faltantes uno por uno.
- Cada día se commitea individualmente; si el watchdog mata el proceso a mitad
  del backfill, el siguiente arranque retoma desde el último día exitoso.
- El watchdog lee `BACKFILL_TIMEOUT_SEC` (default 3600 s). Si el backfill
  supera ese tiempo, llama `os._exit(1)` para que Docker lo reinicie.

### 5.3 Extracción periódica programada

- El scheduler ejecuta `tarea_extraccion_periodica()` cada hora en punto entre
  las 6:00 AM y las 8:00 PM (`cron hour=6-20, minute=0`).
- Llama `extractor_hikvision.main()` para el día de hoy.
- Si termina sin error, actualiza `ultima_extraccion_exitosa` con la hora UTC
  actual.

### 5.4 Sincronización de empleados

- A las 7:00 AM el scheduler ejecuta `tarea_sync_empleados_diaria()`.
- Descarga todos los empleados enrolados del biométrico y hace upsert en la
  tabla `empleados`.

### 5.5 Cálculo de tardanzas

- Para un día laboral, `calcular_tardanzas_dia` obtiene la primera marca de
  cada empleado.
- Obtiene el horario vigente del turno asignado al empleado para ese día de
  la semana y fecha mediante `obtener_horario_vigente`.
- Compara la marca con la hora de entrada vigente más la tolerancia.
- Si la marca es posterior al límite, se reporta la tardanza en minutos.
- Si el empleado no tiene turno_id o el turno no tiene horario configurado,
  lanza `HorarioNoConfiguradoError` (falla ruidosa).
- El dashboard filtra llegadas tarde mayores a 30 minutos para no distorsionar
  los KPIs con permisos/autorizaciones.
- El endpoint `GET /api/tardanzas/acumulado` permite obtener el acumulado
  mensual y anual por empleado, omitiendo tardanzas mayores a 30 minutos.

### 5.6 Reportes Excel

- El usuario o el scheduler solicita un reporte con rango, filtros y modo.
- `report_service.generar_reporte` consulta solo empleados `activo=True`.
- Excluye sábados, domingos y festivos colombianos.
- Fusiona marcas cercanas y genera el archivo con encabezados, metadatos,
  filas alternadas y totales.
- El backend devuelve el archivo como `StreamingResponse`.

### 5.7 Reportes automáticos por correo

- El admin configura el servidor SMTP (host, puerto, usuario, contraseña,
  seguridad) desde el panel Admin; la contraseña se guarda encriptada en
  `configuracion_correo`.
- `email_service` lee la configuración desde la BD, genera el Excel del período
  y lo envía a los destinatarios configurados.
- La periodicidad se edita desde el panel admin y se reprograma en caliente
  llamando `scheduler.reschedule_report_jobs()`.
- Si la tabla `configuracion_correo` está vacía, los jobs de reportes loguean
  "Correo no configurado" y no intentan conectar.

---

## 6. Logs y monitoreo

### 6.1 Dónde se escriben los logs

El backend tiene **logging dual**: stdout (visible con `docker compose logs`) y
archivo rotativo (`/app/logs/app.log` dentro del contenedor).

#### Archivo rotativo (`backend/logging_config.py`)

- Ruta: `/app/logs/app.log` (fallback `./logs/app.log` fuera de Docker).
- Rotación automática: máximo **10 MB** por archivo, **5 copias** de historial.
- Codificación: UTF-8.
- Captura logs de: `uvicorn`, `sqlalchemy`, `apscheduler`, `backend.*`.
- `sqlalchemy.engine` y `passlib` reducidos a nivel `WARNING` para no saturar
  el archivo con SQL de cada consulta.

Para leer el log dentro del contenedor:

```bash
docker compose exec backend tail -f /app/logs/app.log
```

#### Stdout (Docker)

```bash
docker compose logs -f backend
```

Los logs incluyen prefijos claros:
- `[SCHEDULER]` para jobs programados.
- `[EXTRACCION]` para extracciones manuales/backfill.
- `[BACKFILL]` para el backfill de arranque.
- `[BACKFILL WATCHDOG]` si el watchdog mató el proceso.
- `[SYNC EMPLEADOS]` para sincronización.
- `[EMAIL]` para envío de correos.
- `[MIGRACIONES]`, `[FESTIVOS]`, `[RBAC]`, `[CONFIG]` para el lifespan.
- `[LOGGING]` al inicializar el handler del archivo rotativo.

### 6.2 Estado del sistema

El endpoint `GET /api/status` devuelve:

- `ultima_extraccion_exitosa`: timestamp ISO de la última extracción.
- `horas_desde_ultima_extraccion`: diferencia en horas.
- `alerta_retraso_extraccion`: `true` si pasaron más de 26 horas.
- `extraccion_incompleta`: lista de días con gap entre eventos esperados y obtenidos.
- `alerta_extraccion_incompleta`: `true` si hay alertas.
- `is_running` y `progress`: estado de la extracción manual.

### 6.3 Logs del frontend

- Nginx escribe a `/var/log/nginx/` dentro del contenedor.
- Se consultan con:

  ```bash
  docker compose logs -f frontend
  ```

---

## 7. Seguridad

### 7.1 Credenciales

Todas las credenciales viven en el archivo `.env` y **nunca están hardcodeadas
en el código**. El repositorio incluye `.env.example` y `.gitignore` ignora el
`.env` real.

- La contraseña SMTP se guarda encriptada en la base de datos mediante Fernet;
  la clave maestra (`FERNET_KEY`) es la única pieza que permanece en `.env`.
- Si `FERNET_KEY` o `DATABASE_URL` no están configuradas, el backend falla al
  arrancar con un mensaje claro (fail-loud).

### 7.2 HTTPS

En producción el tráfico va **siempre por HTTPS** gracias a nginx:

- Certificado **auto-firmado** generado en tiempo de build del contenedor
  (`frontend.Dockerfile`) para la IP `192.168.1.250` (SAN incluida).
- Duración del cert: 10 años (`-days 3650`).
- Protocolos: TLS 1.2 y 1.3 únicamente.
- HTTP (puerto 80) redirige permanentemente (301) a HTTPS.
- Headers de seguridad: `Strict-Transport-Security`, `X-Frame-Options`,
  `X-Content-Type-Options`.
- El frontend usa la ruta relativa `/api` (no `http://host:8000/api`) para
  evitar mixed-content en HTTPS.

> Los navegadores mostrarán advertencia de certificado por ser auto-firmado.
> Agregar excepción manualmente o instalar el cert en el almacén del SO.

### 7.3 Rate Limiting

`slowapi` protege los endpoints más sensibles:

| Endpoint | Límite |
|----------|--------|
| `POST /api/auth/login` | 10 req/min por IP |
| `POST /api/extraer` | 5 req/min por IP |

Al superar el límite devuelve `429 Too Many Requests`.

### 7.4 CORS

Solo se permiten los orígenes definidos en `CORS_ORIGINS` (`.env`), con métodos
`GET, POST, PUT, DELETE` y headers `Content-Type, Authorization`.

### 7.5 JWT

- `SECRET_KEY` firma los tokens. En producción debe generarse con:

  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

- `ACCESS_TOKEN_EXPIRE_MINUTES` controla la expiración (default 8 horas).
- Los tokens se pasan en el header `Authorization: Bearer <token>`.

### 7.6 Contraseñas

- Hasheadas con Argon2id.
- Los usuarios creados por el admin y los sembrados desde `.env` nacen con
  `requiere_cambio_password=True`.
- El endpoint `POST /api/auth/cambiar-password` permite al usuario cambiar su
  propia contraseña después de validar la actual.

### 7.7 RBAC

- Cada endpoint protegido exige un permiso específico con `require_perm()`.
- El frontend oculta o muestra pestañas según los permisos del usuario.
- El rol `Admin` tiene todos los permisos; el rol `Reportes` solo dashboard y
  reportes.

---

## 8. Variables de entorno

Copiar `.env.example` a `.env` y completar los valores reales.

| Variable                      | Ejemplo                                                    | Descripción                                                                                                                                                 |
| ----------------------------- | ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DATABASE_URL`                | `postgresql://admin:<POSTGRES_PASSWORD>@db:5432/hikvision` | URL de conexión a PostgreSQL.                                                                                                                               |
| `POSTGRES_USER`               | `admin`                                                    | Usuario de PostgreSQL (debe coincidir con `docker-compose.yml`).                                                                                            |
| `POSTGRES_PASSWORD`           | `<POSTGRES_PASSWORD>`                                      | Contraseña de PostgreSQL.                                                                                                                                   |
| `POSTGRES_DB`                 | `hikvision`                                                | Nombre de la base de datos.                                                                                                                                 |
| `DEVICE_IP`                   | `192.168.1.127`                                            | IP del biométrico en la red local.                                                                                                                          |
| `DEVICE_USER`                 | `admin`                                                    | Usuario del biométrico.                                                                                                                                     |
| `DEVICE_PASS`                 | `tu_password`                                              | Contraseña del biométrico.                                                                                                                                  |
| `BACKFILL_TIMEOUT_SEC`        | `3600`                                                     | Techo duro en segundos para el backfill de arranque.                                                                                                        |
| `FERNET_KEY`                  | `<tu_fernet_key>`                                          | Clave para encriptar la contraseña SMTP en reposo. Generar con `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |
| `SMTP_HOST`                   | `smtp.gmail.com`                                           | **DEPRECADO** — ahora se configura en el panel Admin.                                                                                                       |
| `SMTP_PORT`                   | `587`                                                      | **DEPRECADO** — ahora se configura en el panel Admin.                                                                                                       |
| `SMTP_USER`                   | `tu_correo@gmail.com`                                      | **DEPRECADO** — ahora se configura en el panel Admin.                                                                                                       |
| `SMTP_APP_PASSWORD`           | `xxxxxxxxxxxxxxxx`                                         | **DEPRECADO** — ahora se guarda encriptado en la BD.                                                                                                        |
| `REPORT_RECIPIENTS`           | `rrhh@redihos.com`                                         | Destinatarios iniciales de reportes automáticos.                                                                                                            |
| `DEFAULT_TURNO_ENTRADA`       | `07:30`                                                    | **DEPRECADO** en Fase A. Ya no se usa; todo empleado debe tener turno_id real.                                                                              |
| `DEFAULT_TOLERANCIA_MINUTOS`  | `10`                                                       | **DEPRECADO** en Fase A. Ya no se usa; el horario se lee desde `turno_horario`.                                                                             |
| `MARCA_FUSION_MINUTOS`        | `2`                                                        | Ventana para fusionar marcas en el Excel.                                                                                                                   |
| `SECRET_KEY`                  | `...`                                                      | Clave para firmar JWT. Generar en producción.                                                                                                               |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480`                                                      | Duración del token en minutos.                                                                                                                              |
| `ADMIN_USERNAME`              | `admin`                                                    | Usuario admin inicial.                                                                                                                                      |
| `ADMIN_PASSWORD`              | `Ingreso2026*`                                             | Contraseña temporal del admin; cambiar en producción.                                                                                                       |
| `REPORTES_USERNAME`           | `reportes`                                                 | (Opcional) Usuario de solo reportes.                                                                                                                        |
| `REPORTES_PASSWORD`           | `reportes`                                                 | (Opcional) Contraseña del usuario de reportes.                                                                                                              |

---

## 9. Instalación y deploy

### 9.1 Preparar el entorno

```bash
# 1. Clonar o copiar el proyecto
# 2. Copiar y editar variables de entorno
cp .env.example .env
# Editar .env con credenciales reales

# 3. Generar SECRET_KEY real
python -c "import secrets; print(secrets.token_urlsafe(32))"
# Pegar el resultado en SECRET_KEY del .env
```

### 9.2 Levantar con Docker (desarrollo)

```bash
docker compose up -d --build
```

Servicios disponibles en desarrollo:

- Frontend: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- API: `http://localhost:8000`

### 9.3 Deploy en producción

```bash
# Usar siempre docker-compose.prod.yml en producción:
docker compose -f docker-compose.prod.yml build --no-cache
docker compose -f docker-compose.prod.yml up -d
```

Servicios disponibles en producción:

- Frontend HTTPS: `https://<IP_SERVIDOR>` (cert auto-firmado)
- HTTP → HTTPS redirect: `http://<IP_SERVIDOR>` (redirige a HTTPS automáticamente)
- API: solo accesible internamente vía nginx en `/api/`
- PostgreSQL: solo accesible internamente en la red Docker

### 9.4 Actualizar solo el backend

```bash
docker compose -f docker-compose.prod.yml build --no-cache backend
docker compose -f docker-compose.prod.yml up -d backend
```

### 9.5 Reiniciar el frontend

```bash
docker compose -f docker-compose.prod.yml up -d --force-recreate frontend
```

### 9.6 Deploy en producción (Ubuntu Server — guía completa)

Para migrar el sistema completo (código, base de datos y configuración) a un
servidor Ubuntu Server con Docker, seguir la guía detallada:

📄 [`MIGRACION_UBUNTU.md`](MIGRACION_UBUNTU.md)

Incluye: requisitos previos, empaquetado en Windows, exportación con
`pg_dump`, transferencia `scp`, restauración, generación de claves,
configuración de DNS, backups automáticos con `cron`, troubleshooting y
checklist de seguridad.

> **Importante:** en producción usar siempre `docker-compose.prod.yml`, que no
> expone PostgreSQL ni el backend directamente, no usa bind mounts, no arranca
> Uvicorn con `--reload` y habilita HTTPS con nginx.

---

## 10. Comandos útiles

### 10.1 Generar informe manualmente

```bash
python generar_informe.py --start 2026-07-01 --end 2026-07-31 --output reporte.xlsx
```

### 10.2 Migrar CSV de iVMS-4200

```bash
python migrate_csv.py legacy/eventos.csv
```

### 10.3 Forzar extracción vía API

```bash
# Login (en producción usar https:// y -k para cert auto-firmado)
curl -X POST https://192.168.1.250/api/auth/login \
  -k -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<TU_PASSWORD>"}'

# Extracción manual (usar el token del paso anterior)
# Rango máximo: 365 días. fecha_inicio debe ser <= fecha_fin.
curl -X POST https://192.168.1.250/api/extraer \
  -k -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>" \
  -d '{"fecha_inicio":"2026-07-01","fecha_fin":"2026-07-31"}'
```

### 10.4 Ver logs en tiempo real

```bash
# Stdout de contenedores
docker compose -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.prod.yml logs -f frontend

# Archivo rotativo dentro del contenedor backend
docker exec hikvision_backend tail -f /app/logs/app.log
```

### 10.5 Conectarse a la base de datos

Las credenciales están en el `.env`:

```env
POSTGRES_USER=admin
POSTGRES_PASSWORD=<POSTGRES_PASSWORD>
POSTGRES_DB=hikvision
```

#### Opción A: Desde el contenedor Docker (recomendada)

```bash
docker compose exec db psql -U admin -d hikvision
```

Dentro de `psql` podés ejecutar consultas como:

```sql
-- Listar tablas
\dt

-- Ver empleados activos
SELECT * FROM empleados WHERE activo = true ORDER BY nombre;

-- Ver últimas marcaciones
SELECT * FROM registros_asistencia ORDER BY fecha DESC, hora DESC LIMIT 20;

-- Ver usuarios del panel
SELECT username, activo, requiere_cambio_password FROM usuarios;

-- Salir
\q
```

#### Opción B: Desde un cliente gráfico

| Campo         | Valor                                            |
| ------------- | ------------------------------------------------ |
| Host          | `localhost` (o la IP del servidor en producción) |
| Puerto        | `5432`                                           |
| Base de datos | `hikvision`                                      |
| Usuario       | `admin`                                          |
| Contraseña    | valor de `POSTGRES_PASSWORD` en `.env`           |

Clientes soportados: DBeaver, pgAdmin, DataGrip, TablePlus, etc.

#### Opción C: Desde PowerShell con `psql` instalado

```powershell
psql -h localhost -p 5432 -U admin -d hikvision
```

#### Opción D: Desde Python

```python
from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql://admin:<POSTGRES_PASSWORD>@localhost:5432/hikvision"
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    result = conn.execute(text("SELECT * FROM empleados LIMIT 5"))
    for row in result:
        print(row)
```

#### Opción E: En producción (servidor remoto)

Si la base de datos está en un servidor remoto, conectate usando la IP del
servidor y asegurate de que el puerto `5432` esté accesible o de usar un túnel
SSH:

```powershell
ssh -L 5432:localhost:5432 usuario@ip-servidor
```

Luego conectate como si fuera `localhost`.

### 10.6 Ejecutar migraciones manualmente

```bash
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

### 10.7 Ejecutar tests

```bash
# Requiere Python con dependencias instaladas (venv o global)
pip install -r requirements.txt

# Todos los tests con cobertura
python -m pytest tests/ -v --cov=backend --cov=extractor_hikvision --cov-report=term-missing

# Solo un módulo
python -m pytest tests/test_api_endpoints.py -v
```

Los tests usan **SQLite en memoria** (`StaticPool`) para no requerir PostgreSQL.
Las variables de entorno necesarias se configuran automáticamente en `conftest.py`.

### 10.7 Backup y restauración local

El repositorio incluye dos scripts de backup que siempre sobrescriben el mismo
archivo, manteniendo solo la última copia:

- `backup.ps1` — para Windows/PowerShell.
- `backup.sh` — para Linux/WSL/bash.

Ambos generan en la carpeta `backups/`:

- `hikvision_latest.sql` — dump de PostgreSQL.
- `.env.backup` — copia del archivo `.env`.
- `backup.log` — log de ejecuciones.

#### Backup manual

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy Bypass -File backup.ps1
```

**Linux/WSL:**

```bash
bash backup.sh
```

#### Backup automático

- **Windows:** usar el Programador de tareas para ejecutar `backup.ps1` todos
  los días a la hora deseada (ej. 8:00 AM).
- **Linux/WSL:** agregar una línea a `crontab -e`:

  ```cron
  0 8 * * * /ruta/al/proyecto/backup.sh >> /ruta/al/proyecto/backups/backup.log 2>&1
  ```

#### Restaurar desde el backup

```bash
# Restaurar la base de datos
docker compose exec -T db psql -U admin -d hikvision < backups/hikvision_latest.sql

# Restaurar el .env
cp backups/.env.backup .env
```

> La carpeta `backups/` está en `.gitignore` para evitar subir secretos o datos
> al repositorio.

---

## 11. Buenas prácticas aplicadas

- **Separación de responsabilidades**: cada módulo tiene una función clara
  (extracción, reportes, correo, auth, config, etc.).
- **Sin credenciales hardcodeadas**: todo se lee desde `.env`.
- **Zona horaria explícita**: todo el negocio usa `America/Bogota` mediante
  `backend/timezone.py`.
- **RBAC granular**: permisos almacenados en base de datos; endpoints protegidos.
- **Hashes seguros**: Argon2id para contraseñas (passlib + argon2-cffi).
- **Encriptación en reposo**: contraseña SMTP guardada cifrada con Fernet (AES-128).
- **HTTPS en producción**: nginx con TLS 1.2/1.3 y cert auto-firmado para IP local;
  HTTP redirige automáticamente a HTTPS.
- **Rate limiting**: protección brute-force en login y extracción manual.
- **CORS restrictivo**: solo origins, methods y headers necesarios.
- **Sin mutación de globales**: `extractor_hikvision.py` usa parámetros en lugar
  de `global IP, USER, PASS, URL`; permite llamadas concurrentes seguras.
- **Serialización del acceso al biométrico**: `device_lock` (`backend/device_lock.py`)
  evita llamadas HTTP concurrentes al biométrico, ya sea por extracción de marcas
  o sincronización de empleados.
- **Idempotencia**: el extractor deduplica por empleado/fecha/hora; la
  sincronización de empleados no elimina; `init_rbac` puede ejecutarse en cada
  arranque.
- **Recuperación ante fallos**: backfill día por día, rollback parcial ante falla
  de red, watchdog de backfill y `misfire_grace_time` correcto en APScheduler.
- **Migraciones versionadas**: Alembic gestiona el esquema de base de datos.
- **Logging persistente**: archivo rotativo 10 MB × 5 copias en `/app/logs/app.log`.
- **Suite de tests automatizados**: 56 tests con SQLite en memoria; corren sin
  PostgreSQL ni biométrico; CI-friendly.

---

## 12. Limitaciones y consideraciones de operación

- El dispositivo Hikvision no distingue explícitamente entrada de salida. El
  sistema infiere: **entrada** = primera marca del día, **salida** = última
  marca del día.
- Las marcas de personas no registradas en la tabla `empleados` aparecen en el
  panel "Marcas sin asociar" y no se incluyen en KPIs ni reportes.
- El panel de festivos es de solo lectura; los festivos se recargan desde la
  librería `holidays` en cada arranque.
- Para que los reportes automáticos funcionen se debe configurar el servidor
  SMTP, usuario y contraseña desde el panel Admin, y al menos un destinatario.
  Es agnóstico del proveedor (Gmail, Outlook, servidor propio, etc.).
- El contenedor `backend` usa `restart: always`; si el watchdog mata el proceso
  por timeout de backfill, Docker lo levanta de nuevo.

---

## 13. Historial de versiones

| Versión | Fecha | Cambios principales |
|---------|-------|---------------------|
| `v1.6-security-fixes` | 2026-10-19 | Rate limiting (slowapi), HTTPS auto-signed + nginx proxy, CORS restrictivo, logging rotativo, refactor globales extractor, fix fusión de marcas (bug `hoy_bogota()`), índices de performance en BD, suite de 56 tests |
| `v1.5` | 2026-09-29 | Correcciones varias, backup scripts |
| `v1.0` | 2026-08-xx | Deploy inicial en producción Ubuntu |

## 14. Pendientes operacionales

1. **Rotar credenciales** del `.env` en producción: `ADMIN_PASSWORD`,
   `SECRET_KEY`, `FERNET_KEY`, `DEVICE_PASS`, `POSTGRES_PASSWORD`.
   > El certificado SSL auto-firmado requiere aceptación manual en el navegador.
   > Para eliminar la advertencia, instalar el cert en el almacén del SO o usar
   > un certificado de una CA privada interna.
2. Verificar que el servidor SMTP esté configurado en el panel Admin y que los
   reportes automáticos lleguen correctamente.
3. Confirmar que todos los empleados activos tienen `turno_id` asignado (sin turno
   no se calculan tardanzas).

---

## 15. Documentación adicional

- `handoff_hikvision_asistencia.md`: notas internas de handoff, decisiones de
  negocio, evidencia de pruebas y próximos pasos.
- `MIGRACION_UBUNTU.md`: guía paso a paso para migrar el sistema a un servidor
  Ubuntu Server con Docker en producción.
- `http://localhost:8000/docs`: documentación interactiva de la API generada
  automáticamente por FastAPI (solo disponible en desarrollo).
