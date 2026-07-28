# Sistema de Asistencia Biométrica — REDIHOS S.A.S

Sistema de control de asistencia para **REPRESENTACIONES Y DISTRIBUCIONES
HOSPITALARIAS S.A.S. (REDIHOS)**. Extrae marcaciones de un dispositivo
Hikvision mediante su API ISAPI, las almacena en **PostgreSQL**, expone una
API REST con **FastAPI** y ofrece un panel web con **Nginx + HTML/JS**.

El sistema genera informes Excel con formato dinámico, calcula tardanzas,
envía reportes automáticos por correo y permite administrar empleados,
roles, permisos y configuración de correo desde una interfaz web.

---

## 1. Stack y arquitectura

### 1.1 Servicios

| Servicio | Tecnología | Puerto expuesto | Responsabilidad |
| --- | --- | --- | --- |
| Base de datos | PostgreSQL 15 (Alpine) | `5432` | Persistencia de empleados, marcas, festivos, usuarios, roles y configuración. |
| Backend API | FastAPI + Uvicorn (Python 3.11) | `8000` | Extracción, reportes, autenticación, RBAC, scheduler y configuración. |
| Frontend | Nginx + HTML/JS | `3000` | Panel de login, dashboard, reportes y administración. |
| Scheduler | APScheduler (dentro del backend) | — | Jobs de extracción diaria, sync de empleados y reportes semanal/mensual. |

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
│   └── versions/90d3e571a1b6_baseline_schema.py
├── backend/
│   ├── auth.py                     # JWT, Argon2id, RBAC
│   ├── config_service.py           # Configuración persistente y alertas
│   ├── database.py                 # Conexión SQLAlchemy + SessionLocal
│   ├── email_service.py            # Envío SMTP de reportes
│   ├── main.py                     # API FastAPI y lifespan
│   ├── models.py                   # Modelos SQLAlchemy
│   ├── report_service.py           # Motor de Excel y tardanzas
│   ├── scheduler.py                # Jobs programados con APScheduler
│   ├── sync_empleados.py           # Sincronización de empleados desde el biométrico
│   └── timezone.py                 # Helpers de zona horaria Bogotá
├── frontend/
│   ├── index.html                  # UI del panel
│   └── app.js                      # Lógica del frontend
├── extractor_hikvision.py          # Script/CLI de extracción ISAPI
├── generar_informe.py              # CLI para generar Excel desde PostgreSQL
├── migrate_csv.py                  # CLI para migrar CSV de iVMS-4200 a PostgreSQL
├── docker-compose.yml              # Orquestación de los 3 servicios
├── backend.Dockerfile              # Imagen del backend
├── frontend.Dockerfile             # Imagen del frontend
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
if not SQLALCHEMY_DATABASE_URL:
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

| Tabla | Propósito |
| --- | --- |
| `turnos` | Catálogo legacy de turnos. La UI actual usa turno individual por empleado. |
| `empleados` | Personas registradas en el sistema. `employee_id` enlaza con el biométrico. |
| `festivos` | Festivos colombianos poblados automáticamente por `holidays`. |
| `registros_asistencia` | Cada marca de entrada/salida extraída del biométrico. |
| `configuracion` | Clave-valor persistente: destinatarios de correo, periodicidad, última extracción, alertas. |
| `permisos` | Lista canónica de permisos del sistema (ej. `ver_dashboard`, `admin_roles`). |
| `roles` | Roles definidos por el administrador. |
| `rol_permiso` | Relación muchos-a-muchos entre roles y permisos. |
| `usuarios` | Usuarios del panel web con `password_hash`, rol y bandera de cambio de contraseña. |

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
  1. Ejecuta `alembic upgrade head` para migrar el esquema.
  2. Puebla festivos colombianos (`init_festivos`).
  3. Inicializa roles, permisos y usuario admin (`init_rbac`).
  4. Crea configuración por defecto (`config_service.init_defaults`).
  5. Si la última extracción exitosa es anterior a hoy, lanza un **backfill**
     en segundo plano para recuperar los días faltantes.
  6. Inicia el scheduler de APScheduler.
- Middleware CORS para permitir llamadas desde el frontend.
- Endpoints agrupados por dominio: autenticación, roles, usuarios, empleados,
  registros, KPIs, reportes, configuración de correo y extracción manual.
- Estados globales `extraction_state` y `sync_state` para que el frontend
  pueda consultar el progreso de operaciones en background.

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

| Job | Horario | Función |
| --- | --- | --- |
| `sync_empleados_diaria` | 7:00 AM | Sincroniza empleados enrolados desde el biométrico. |
| `extraccion_diaria` | 8:00 PM | Extrae las marcaciones del día. |
| `reporte_semanal` | Configurable | Envía por correo el informe de la semana pasada. |
| `reporte_mensual` | Configurable | Envía por correo el informe del mes anterior. |

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

- Lee `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_APP_PASSWORD` del `.env`.
- Lee destinatarios desde la base de datos (`config_service.get_recipients`).
- `enviar_reporte_semanal`: semana laboral pasada (lunes a viernes).
- `enviar_reporte_mensual`: mes anterior completo.
- `enviar_correo_prueba`: envía un correo sin adjunto para verificar SMTP.
- Adjunta el Excel generado por `report_service.generar_reporte`.

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

- Lee `DEVICE_IP`, `DEVICE_USER`, `DEVICE_PASS` del `.env`.
- Usa autenticación HTTP Digest contra `http://<IP>/ISAPI/AccessControl/AcsEvent?format=json`.
- Antes de extraer un rango, hace un `socket.create_connection((IP, 80), timeout=3)`
  para detectar rápidamente si el dispositivo no responde.
- Si hay falla de red, lanza `DeviceUnavailableError` para que el llamador
  aborte sin marcar la extracción como exitosa.

#### 4.11.2 Paginación y fallback

- `BATCH_SIZE=50` para el endpoint de eventos.
- Cada llamada usa un `searchID` UUID nuevo para evitar que el dispositivo
  pise resultados entre paginaciones.
- Un `threading.Lock` global `_device_lock` serializa todas las llamadas al
  dispositivo, evitando condiciones de carrera entre job programado, extracción
  manual y sync de empleados.
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

### 5.3 Extracción diaria programada

- A las 8:00 PM el scheduler ejecuta `tarea_extraccion_diaria()`.
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

### 5.6 Reportes Excel

- El usuario o el scheduler solicita un reporte con rango, filtros y modo.
- `report_service.generar_reporte` consulta solo empleados `activo=True`.
- Excluye sábados, domingos y festivos colombianos.
- Fusiona marcas cercanas y genera el archivo con encabezados, metadatos,
  filas alternadas y totales.
- El backend devuelve el archivo como `StreamingResponse`.

### 5.7 Reportes automáticos por correo

- `email_service` genera el Excel del período y lo envía a los destinatarios
  configurados en la base de datos.
- La periodicidad se edita desde el panel admin y se reprograma en caliente
  llamando `scheduler.reschedule_report_jobs()`.

---

## 6. Logs y monitoreo

### 6.1 Dónde se imprimen los logs

- El backend usa `print()` para logs de operación. Uvicorn los envía a stdout.
- En Docker se ven con:

  ```bash
  docker compose logs -f backend
  ```

- Los logs incluyen prefijos claros:
  - `[SCHEDULER]` para jobs programados.
  - `[EXTRACCION]` para extracciones manuales/backfill.
  - `[BACKFILL]` para el backfill de arranque.
  - `[BACKFILL WATCHDOG]` si el watchdog mató el proceso.
  - `[SYNC EMPLEADOS]` para sincronización.
  - `[EMAIL]` para envío de correos.
  - `[MIGRACIONES]`, `[FESTIVOS]`, `[RBAC]`, `[CONFIG]` para el lifespan.

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

### 7.2 JWT

- `SECRET_KEY` firma los tokens. En producción debe generarse con:

  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

- `ACCESS_TOKEN_EXPIRE_MINUTES` controla la expiración (default 8 horas).
- Los tokens se pasan en el header `Authorization: Bearer <token>`.

### 7.3 Contraseñas

- Hasheadas con Argon2id.
- Los usuarios creados por el admin y los sembrados desde `.env` nacen con
  `requiere_cambio_password=True`.
- El endpoint `POST /api/auth/cambiar-password` permite al usuario cambiar su
  propia contraseña después de validar la actual.

### 7.4 RBAC

- Cada endpoint protegido exige un permiso específico con `require_perm()`.
- El frontend oculta o muestra pestañas según los permisos del usuario.
- El rol `Admin` tiene todos los permisos; el rol `Reportes` solo dashboard y
  reportes.

---

## 8. Variables de entorno

Copiar `.env.example` a `.env` y completar los valores reales.

| Variable | Ejemplo | Descripción |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql://admin:<POSTGRES_PASSWORD>@db:5432/hikvision` | URL de conexión a PostgreSQL. |
| `POSTGRES_USER` | `admin` | Usuario de PostgreSQL (debe coincidir con `docker-compose.yml`). |
| `POSTGRES_PASSWORD` | `<POSTGRES_PASSWORD>` | Contraseña de PostgreSQL. |
| `POSTGRES_DB` | `hikvision` | Nombre de la base de datos. |
| `DEVICE_IP` | `192.168.1.127` | IP del biométrico en la red local. |
| `DEVICE_USER` | `admin` | Usuario del biométrico. |
| `DEVICE_PASS` | `tu_password` | Contraseña del biométrico. |
| `BACKFILL_TIMEOUT_SEC` | `3600` | Techo duro en segundos para el backfill de arranque. |
| `SMTP_HOST` | `smtp.gmail.com` | Servidor SMTP. |
| `SMTP_PORT` | `587` | Puerto SMTP. |
| `SMTP_USER` | `tu_correo@gmail.com` | Cuenta de correo. |
| `SMTP_APP_PASSWORD` | `xxxxxxxxxxxxxxxx` | Contraseña de aplicación de 16 caracteres. |
| `REPORT_RECIPIENTS` | `rrhh@redihos.com` | Destinatarios iniciales de reportes automáticos. |
| `DEFAULT_TURNO_ENTRADA` | `07:30` | **DEPRECADO** en Fase A. Ya no se usa; todo empleado debe tener turno_id real. |
| `DEFAULT_TOLERANCIA_MINUTOS` | `10` | **DEPRECADO** en Fase A. Ya no se usa; el horario se lee desde `turno_horario`. |
| `MARCA_FUSION_MINUTOS` | `2` | Ventana para fusionar marcas en el Excel. |
| `SECRET_KEY` | `...` | Clave para firmar JWT. Generar en producción. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | Duración del token en minutos. |
| `ADMIN_USERNAME` | `admin` | Usuario admin inicial. |
| `ADMIN_PASSWORD` | `Ingreso2026*` | Contraseña temporal del admin; cambiar en producción. |
| `REPORTES_USERNAME` | `reportes` | (Opcional) Usuario de solo reportes. |
| `REPORTES_PASSWORD` | `reportes` | (Opcional) Contraseña del usuario de reportes. |

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

### 9.2 Levantar con Docker

```bash
docker compose up -d --build
```

Servicios disponibles:

- Frontend: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- API: `http://localhost:8000`

### 9.3 Actualizar solo el backend

```bash
docker compose build --no-cache backend
docker compose up -d backend
```

### 9.4 Reiniciar el frontend

```bash
docker compose up -d --force-recreate frontend
```

---

## 10. Comandos útiles

### 10.1 Generar informe manualmente

```bash
python generar_informe.py --start 2026-07-01 --end 2026-07-31 --output reporte.xlsx
```

### 10.2 Migrar CSV de iVMS-4200

```bash
python migrate_csv.py eventos.csv
```

### 10.3 Forzar extracción vía API

```bash
# Login
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Ingreso2026*"}'

# Extracción manual (usar el token del paso anterior)
curl -X POST http://localhost:8000/api/extraer \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>" \
  -d '{"fecha_inicio":"2026-07-01","fecha_fin":"2026-07-31"}'
```

### 10.4 Ver logs en tiempo real

```bash
docker compose logs -f backend
docker compose logs -f db
docker compose logs -f frontend
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

| Campo | Valor |
| --- | --- |
| Host | `localhost` (o la IP del servidor en producción) |
| Puerto | `5432` |
| Base de datos | `hikvision` |
| Usuario | `admin` |
| Contraseña | valor de `POSTGRES_PASSWORD` en `.env` |

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
docker compose exec backend alembic upgrade head
```

---

## 11. Buenas prácticas aplicadas

- **Separación de responsabilidades**: cada módulo tiene una función clara
  (extracción, reportes, correo, auth, config, etc.).
- **Sin credenciales hardcodeadas**: todo se lee desde `.env`.
- **Zona horaria explícita**: todo el negocio usa `America/Bogota` mediante
  `backend/timezone.py`.
- **RBAC granular**: permisos almacenados en base de datos; endpoints protegidos.
- **Hashes seguros**: Argon2id para contraseñas.
- **Serialización del acceso al biométrico**: `_device_lock` evita extracciones
  concurrentes que corrompan la paginación.
- **Idempotencia**: el extractor deduplica por empleado/fecha/hora; la
  sincronización de empleados no elimina; `init_rbac` puede ejecutarse en cada
  arranque.
- **Recuperación ante fallos**: backfill día por día, rollback parcial ante falla
  de red, watchdog de backfill y `misfire_grace_time` correcto en APScheduler.
- **Migraciones versionadas**: Alembic gestiona el esquema de base de datos.
- **Tests de evidencia**: la carpeta `test_evidencia/` contiene scripts
  reproducibles que verifican comportamientos críticos (misfire, backfill,
  seguridad, concurrencia).

---

## 12. Limitaciones y consideraciones de operación

- El dispositivo Hikvision no distingue explícitamente entrada de salida. El
  sistema infiere: **entrada** = primera marca del día, **salida** = última
  marca del día.
- Las marcas de personas no registradas en la tabla `empleados` aparecen en el
  panel "Marcas sin asociar" y no se incluyen en KPIs ni reportes.
- El panel de festivos es de solo lectura; los festivos se recargan desde la
  librería `holidays` en cada arranque.
- Para que los reportes automáticos funcionen se debe configurar una cuenta
  Gmail con contraseña de aplicación y al menos un destinatario.
- El contenedor `backend` usa `restart: always`; si el watchdog mata el proceso
  por timeout de backfill, Docker lo levanta de nuevo.

---

## 13. Pendientes antes del primer deploy en producción

1. Cambiar `ADMIN_PASSWORD` en `.env` y resetear el usuario admin contra la
   base de datos PostgreSQL real.
2. Generar un `SECRET_KEY` real y reemplazarlo en `.env`.
3. Configurar credenciales SMTP reales y un destinatario.
4. Cargar/verificar los empleados reales de REDIHOS en la tabla `empleados`.
5. Realizar una validación visual del frontend en navegador.

---

## 14. Documentación adicional

- `handoff_hikvision_asistencia.md`: notas internas de handoff, decisiones de
  negocio, evidencia de pruebas y próximos pasos.
- `http://localhost:8000/docs`: documentación interactiva de la API generada
  automáticamente por FastAPI.
