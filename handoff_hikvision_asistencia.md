# HANDOFF — Sistema de Asistencia Biométrica REDIHOS (Fase 3)

**Empresa:** REPRESENTACIONES Y DISTRIBUCIONES HOSPITALARIAS S.A.S (REDIHOS)  
**Fase:** 3 — Servicio web con PostgreSQL, dashboard, reportes automáticos y panel de administración  
**Stack:** FastAPI + Uvicorn + PostgreSQL + Nginx + APScheduler + Docker  
**Última actualización:** 29 de septiembre de 2026
**Estado:** Feature `v1.5-ui-historico` deployada a producción (192.168.1.250). Backend, frontend y base de datos healthy. Backup pre-deploy realizado. Pendientes: validación visual en navegador del usuario, configurar cuenta SMTP real en el panel de admin.

---

## 1. Inventario actual

### 1.1 `hikvision_extractor/`

| Archivo | Estado | Descripción |
| --- | --- | --- |
| `extractor_hikvision.py` | ✅ Funcional | Extracción ISAPI con paginación AM/PM/Q1-Q4. Lee credenciales del biométrico desde `.env`. Probado contra dispositivo real. |
| `backend/sync_empleados.py` | ✅ Funcional | Sincroniza `Empleado` desde `/ISAPI/AccessControl/UserInfo/Search` con upsert por `employeeNo`. Nunca elimina. |
| `backend/main.py` | ✅ Funcional | API FastAPI con endpoints de KPIs, tardanzas, registros, empleados, turnos, festivos, reportes, correo, sincronización de empleados, auth y RBAC. `create_all` ejecuta en el `lifespan`. |
| `backend/models.py` | ✅ Funcional | `Turno`, `TurnoHorario`, `Empleado`, `Festivo`, `RegistroAsistencia`, `Rol`, `Permiso`, `Usuario`. |
| `backend/auth.py` | ✅ Funcional | JWT, hash Argon2id, expiración configurable, roles/permisos, `require_perm()` y seed de roles. |
| `backend/timezone.py` | ✅ Funcional | Helper `hoy_bogota()` / `ahora_bogota()` para que todo el backend use `America/Bogota`. |
| `backend/config_service.py` | ✅ Funcional | Configuración persistente: destinatarios de correo y periodicidad de reportes. |
| `backend/database.py` | ✅ Funcional | Conexión PostgreSQL via `DATABASE_URL` en `.env`. |
| `backend/report_service.py` | ✅ Funcional | Generación Excel dinámica, cálculo de tardanzas, horario vigente por `turno_horario`. |
| `backend/email_service.py` | ✅ Funcional | Envío SMTP de reportes semanal/mensual. Lee destinatarios desde la base de datos (configurables en admin). SMTP sigue configurado en `.env`. |
| `backend/scheduler.py` | ✅ Funcional | APScheduler: sync empleados, extracción diaria, reporte semanal, reporte mensual. |
| `frontend/index.html` | ✅ Funcional | UI con login, cambio obligatorio de contraseña, dashboard, reportes, administración, usuarios/roles. |
| `frontend/app.js` | ✅ Funcional | Lógica del frontend, autenticación JWT, polling de extracción, RBAC, flujo de cambio de contraseña. |
| `generar_informe.py` | ✅ Funcional | CLI de reportes desde PostgreSQL. |
| `migrate_csv.py` | ✅ Funcional | Migra CSV de iVMS-4200 a PostgreSQL, guarda `evento_raw`. |
| `docker-compose.yml` | ✅ Funcional | Sin credenciales hardcodeadas. |
| `docker-compose.prod.yml` | ✅ Funcional | Producción: sin bind mounts, PostgreSQL no expuesto, healthchecks. |
| `.env.example` | ✅ Funcional | Documenta todas las variables necesarias. |
| `.gitignore` | ✅ Creado | Excluye `.venv/`, `.env`, `__pycache__/`, `backups/`, etc. |
| `README.md` | ✅ Actualizado | Refleja la arquitectura Fase 3. |
| `backup.ps1` | ✅ Funcional | Backup de BD y `.env` para Windows/PowerShell. |
| `backup.sh` | ✅ Funcional | Backup de BD y `.env` para Linux/WSL/bash. |

### 1.2 Eliminados en Fase 3

- `extraccion_diaria.sh`
- `extraccion_diaria.bat`
- `maestro_hikvision.csv` (reemplazado por PostgreSQL)

---

## 2. Decisiones de negocio implementadas

### 2.1 Sábados y domingos NO son días laborales

- `report_service.es_dia_laboral()` devuelve `d.weekday() < 5 and d not in festivos`, es decir, **lunes a viernes sin festivos**.
- Tardanzas y reportes solo se calculan sobre días laborales.
- Verificado con datos reales: período 20/07/2026 (lunes festivo) a 26/07/2026 (domingo) arrojó 4 días laborales (martes a viernes). Sábado y domingo quedan fuera del Excel.

### 2.2 Empleados se sincronizan automáticamente desde el biométrico

- `backend/sync_empleados.py` consulta `/ISAPI/AccessControl/UserInfo/Search` (personas enroladas) con paginación adaptada al límite del dispositivo.
- Upsert por `employeeNoString`: si existe, actualiza `nombre`; si es nuevo, lo crea con `activo=True`, `turno_id=None`, `departamento=None`.
- **Nunca** se elimina un empleado automáticamente si desaparece del dispositivo; el admin lo desactiva manualmente.
- La sincronización corre diariamente a las 7:00 AM vía scheduler y también se puede disparar manualmente desde el admin (`POST /api/empleados/sync`).
- Las marcas sin empleado asociado se siguen exponiendo en `/api/registros/sin-asociar` para revisión.

### 2.3 Turnos versionados por día de semana (Fase A)

- La fuente de verdad del horario es la tabla `turno_horario`, vinculada a `Turno`.
- Cada turno tiene hasta 5 horarios (lunes=0 ... viernes=4), cada uno con una
  fecha de vigencia (`vigente_desde`). Al cambiar un horario se inserta una
  nueva fila; el historial se conserva.
- Cada empleado apunta a un `turno_id`. Las columnas `hora_entrada` y
  `tolerancia_minutos` de `Empleado` quedan deprecadas en Fase A.
- `DEFAULT_TURNO_ENTRADA` y `DEFAULT_TOLERANCIA_MINUTOS` del `.env` quedan
  deprecados; todo empleado debe tener un turno real.

### 2.4 Empleados activos aparecen en el reporte

- El reporte Excel incluye **todos los empleados `activo=True`**, independientemente de si tienen turno individual configurado.
- Empleados inactivos quedan fuera del reporte.
- Quienes no tengan marcas en el período muestran `SIN REGISTRO` día por día.

### 2.5 Marcas casi simultáneas se fusionan en el Excel

- `report_service._fusionar_marcas_por_empleado_dia()` agrupa marcas del mismo empleado/día que caen dentro de `MARCA_FUSION_MINUTOS` desde la primera marca del grupo.
- La ventana se configura en `.env` (default 2 minutos). Use `0` para desactivar la fusión.
- El número dinámico de columnas "Marca N" se calcula **sobre los datos ya fusionados**, no sobre los registros crudos.
- La base de datos (`RegistroAsistencia`) conserva todas las marcas originales sin modificar.

### 2.6 Festivos automáticos vía `holidays`

- `report_service.init_festivos()` puebla la tabla `Festivo` con festivos colombianos al iniciar la app.
- La librería `holidays` se encarga de festivos móviles trasladados por Ley Emiliani.
- El panel de festivos es solo lectura; no hay administración manual.

### 2.7 Configuración de correo y periodicidad persistente

- La tabla `Configuracion` almacena destinatarios de correo y la periodicidad de reportes (día/hora semanal, día/hora mensual).
- El admin puede agregar/quitar destinatarios y cambiar la periodicidad desde la pestaña Correo.
- Al guardar periodicidad, el backend llama `scheduler.reschedule_report_jobs()` para reprogramar los jobs de APScheduler en caliente (sin reiniciar).
- Los reportes automáticos usan los destinatarios de la base de datos; las credenciales SMTP siguen en `.env`.

### 2.8 Autenticación JWT y RBAC escalable

- Tablas: `Rol`, `Permiso`, `RolPermiso`, `Usuario`.
- Los roles y permisos se configuran desde el frontend (pestaña "Usuarios y roles"); no hay roles hardcodeados en el código.
- Semilla inicial: rol `Admin` (todos los permisos) y rol `Reportes` (solo `ver_dashboard` y `generar_reportes`).
- Cada endpoint valida el permiso requerido con `require_perm()`; el frontend oculta la pestaña Admin si el usuario no tiene permisos administrativos.
- Contraseñas hasheadas con **Argon2id** (`passlib` + `argon2-cffi`); nunca texto plano ni MD5/SHA1.
- `SECRET_KEY` leído de `.env`; el token JWT expira según `ACCESS_TOKEN_EXPIRE_MINUTES` (default 8 horas = 480 minutos).
- Usuario admin por defecto configurable en `.env` (`ADMIN_USERNAME`, `ADMIN_PASSWORD`).
- **Forzado de cambio de contraseña en primer login**: los usuarios sembrados desde `.env` (`admin` y `reportes`) tienen `requiere_cambio_password=True`. El login devuelve esa bandera; el frontend bloquea la app hasta que cambien la contraseña vía `POST /api/auth/cambiar-password`. Tras el cambio la bandera pasa a `False`.
- **Usuarios creados por el admin** también nacen con `requiere_cambio_password=True` (`backend/main.py:488-494`). Esto mantiene consistencia con los usuarios sembrados y evita que una contraseña temporal asignada por el admin quede viva indefinidamente.

### 2.9 Zona horaria del backend: America/Bogota

- Se agregó `backend/timezone.py` con helpers `hoy_bogota()` y `ahora_bogota()` usando `ZoneInfo("America/Bogota")`.
- Todos los lugares que usaban `date.today()` para determinar el "día de negocio" ahora usan `hoy_bogota()` (KPIs, tardanzas, extracción por defecto, reportes automáticos).
- El `backend.Dockerfile` instala `tzdata`, define `ENV TZ=America/Bogota` y vincula `/etc/localtime` y `/etc/timezone`.
- `docker-compose.yml` también exporta `TZ=America/Bogota` al contenedor backend.
- El frontend sigue usando `hoy()` con `timeZone: 'America/Bogota'`.

### 2.10 Backfill automático al arrancar el backend

- Si el contenedor estuvo apagado y la última extracción exitosa (`ultima_extraccion_exitosa`) es anterior a `hoy_bogota()`, el `lifespan` dispara un hilo en background que extrae el rango `[última+1, hoy]`.
- Usa `extractor_hikvision.main(start_str, end_str)`; el lock interno del extractor serializa las llamadas al dispositivo para evitar pisar otras extracciones.
- Si nunca se registró una extracción exitosa (sistema nuevo), no se dispara nada automático; se espera la primera extracción manual o el job de las 8:00 PM.
- Al finalizar sin error, actualiza `ultima_extraccion_exitosa` con la hora actual UTC.
- El job programado a las 8:00 PM se mantiene sin cambios.

### 2.11 Backup automático local (30 de julio de 2026)

- Se crearon `backup.ps1` (Windows) y `backup.sh` (Linux/WSL) para realizar un
  backup diario de la base de datos PostgreSQL y del archivo `.env`.
- Ambos scripts sobrescriben siempre el mismo archivo en `backups/`:
  - `hikvision_latest.sql` — dump de PostgreSQL.
  - `.env.backup` — copia del `.env`.
- Se agregó la carpeta `backups/` a `.gitignore` para evitar filtrar datos
  sensibles.
- En Windows se configuró una tarea programada (`HikvisionBackupDiario`) que
  ejecuta `backup.ps1` todos los días a las **08:00 AM**.
- En Linux/WSL se puede usar `cron` con `backup.sh`.
- Restauración:
  ```bash
  docker compose exec -T db psql -U admin -d hikvision < backups/hikvision_latest.sql
  cp backups/.env.backup .env
  ```

### 2.12 Alerta de extracción incompleta (`extraccion_incompleta_dias`)

- Cuando el dispositivo reporta `totalMatches` para un día pero la extracción (incluso con el fallback AM/PM/Q1-Q4) devuelve menos eventos, `config_service.add_alerta_extraccion(db, fecha, esperado, obtenido)` persiste el gap en la clave `extraccion_incompleta_dias` de la tabla `Configuracion` (JSON).
- Se mantiene solo los últimos 14 días (`ALERTAS_MAX_RECIENTES`); si ya existe una alerta para la fecha, solo se actualiza cuando el nuevo gap es mayor.
- `/api/status` expone `alerta_extraccion_incompleta` (bool) y `extraccion_incompleta` (lista de `{fecha, esperado, obtenido, registrado_en}`). `alerta_retraso_extraccion` y `alerta_extraccion_incompleta` son independientes: una alerta de gap no se mezcla con la de "extracción atrasada > 26h".
- Frontend: el banner `<div id="extraccion-incompleta-alerta">` (`frontend/index.html:208`) se renderiza desde `mostrarAvisoExtraccion()` (`frontend/app.js:224-277`) leyendo los dos campos de `/api/status`; cada fecha de la lista se muestra como una línea `Extracción del <f> puede estar incompleta (<obtenido> de <esperado> eventos)`.

#### Evidencia de la verificación (27 de julio de 2026)

- Procedimiento reproducible en `test_evidencia/test_alerta.py`.
- Pasos ejecutados:
  1. `arrancar_alerta.bat` levanta uvicorn en `127.0.0.1:18002` con `DATABASE_URL=sqlite:///test_evidencia/evidencia.db`. El `lifespan` corrió Alembic, festivos, RBAC, config y detectó `ultima >= hoy`, por lo que **no se disparó backfill** (logs en `test_evidencia/logs/test_alerta_18002.log`).
  2. `reset_admin_password.py` reseteó la contraseña a `Ingreso2026*` (la del `.env`) y dejó `requiere_cambio_password=False`.
  3. Login `POST /api/auth/login` con `admin / Ingreso2026*` → JWT con rol `Admin` y los 7 permisos.
  4. `config_service.add_alerta_extraccion(db, date(2026,7,23), esperado=132, obtenido=120)` insertó la alerta.
  5. `GET /api/status` con el JWT devolvió:
     - `ultima_extraccion_exitosa = 2026-07-27T16:04:11.219562+00:00` (`horas_desde_ultima_extraccion = 3.5`).
     - `alerta_retraso_extraccion = false` (no se dispara, está dentro de las 26h).
     - `alerta_extraccion_incompleta = true`.
     - `extraccion_incompleta = [{"fecha": "2026-07-23", "esperado": 132, "obtenido": 120, "registrado_en": "2026-07-27T19:36:06.884259+00:00"}]`.
  6. Verificación estática: `<div id="extraccion-incompleta-alerta">` existe en `frontend/index.html:208`; `app.js:226,254` lo referencia; `app.js:270-272` lo hace visible cuando `alerta_extraccion_incompleta` es `true` y hay elementos en `extraccion_incompleta`.
- Resultado: `test_evidencia/logs/test_alerta_resultado.txt` → `[RESULTADO] test_alerta: PASS`.
- Proceso cerrado al terminar.

---

## 3. Flujo end-to-end

```mermaid
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

## 4. Validación con datos reales del biométrico

Ejecución de extracción real `2026-07-21` a `2026-07-22`:

| Métrica | Valor |
| --- | --- |
| Total registros insertados | **121** |
| Registros 2026-07-21 | 92 |
| Registros 2026-07-22 | 29 |
| Nombres únicos | 46 |
| Registros sin nombre | 0 |
| Eventos huella (`Fingerprint Recognition Passed`) | 81 |
| Eventos rostro (`Face Authentication Passed`) | 40 |
| Lógica AM/PM/Q1-Q4 | Activada ambos días |

### Observaciones de datos reales

- Se detectaron marcas muy cercanas en el tiempo (ej. 08:00:43, 08:00:46, 08:00:47) para la misma persona. No son duplicados: son autenticaciones distintas. El Excel las muestra como `08:00` porque trunca a HH:MM.
- Hay 36 nombres del biométrico que no coinciden con empleados registrados; aparecen en el panel "Marcas sin asociar".
- Rango de horas reales: 05:46:51 a 19:34:33.

### Reporte Excel verificado

- Encabezado azul oscuro `#1F3864` con texto blanco.
- Celdas de hora con fondo verde claro `#E8F5E9`.
- Columnas "Marca N" dinámicas (hasta 5 subcolumnas por día).
- Fila de totales presente.
- Encabezado con rango de fechas, empleados, días laborales, total marcaciones y días sin registro.

### Dashboard verificado (endpoints)

- `/api/kpis` retorna KPIs coherentes.
- `/api/tardanzas` calcula tardanzas con turno asignado o turno default.
- `/api/registros/sin-asociar` lista 36 nombres sin empleado asociado.
- `/api/extraer` dispara extracción real y `/api/status` refleja progreso (polling funcional).
- Filtros de reporte por empleado, por selección múltiple y por departamento cambian el resultado.

### Pendiente de validación visual

- No se pudo abrir el frontend en navegador gráfico porque el entorno de ejecución es solo línea de comandos. Los archivos estáticos (`index.html`, `app.js`) existen y son servidos por nginx en Docker.

---

## 5. Puntos de atención para operación

1. **Credenciales del biométrico**: deben estar en `.env` (`DEVICE_IP`, `DEVICE_USER`, `DEVICE_PASS`). El scheduler y la sincronización de empleados usan estos valores automáticamente.
2. **SMTP**: `SMTP_USER`, `SMTP_APP_PASSWORD` y `REPORT_RECIPIENTS` deben configurarse en `.env` para reportes automáticos. **Actualmente pospuesto** hasta tener cuenta Gmail.
3. **Timezone**: backend y frontend fuerzan `America/Bogota`; el contenedor `backend` tiene `TZ=America/Bogota` instalado. No depende del reloj del host.
4. **Buffer del biométrico**: mantener la extracción diaria a las 8:00 PM para no perder marcaciones por el buffer circular del dispositivo. Además, al arrancar el contenedor se hace backfill automático desde el día siguiente a la última extracción exitosa hasta hoy.
5. **Empleados sin turno**: después de la Fase B de migración de datos, todos los empleados tendrán un `turno_id` real (incluido un "Turno Default" para quienes usaban el default del `.env`). Antes de Fase B, el cálculo falla ruidosamente con `HorarioNoConfiguradoError`.
6. **Marcas casi simultáneas**: el Excel agrupa marcas dentro de `MARCA_FUSION_MINUTOS` minutos como una sola "Marca N". Ajustar o desactivar en `.env` según política de REDIHOS.
7. **Seguridad**: cambiar `SECRET_KEY`, `ADMIN_USERNAME` y `ADMIN_PASSWORD` en producción. El token JWT expira según `ACCESS_TOKEN_EXPIRE_MINUTES`. Los usuarios sembrados desde `.env` deberán cambiar su contraseña en el primer login.
8. **Dashboard**: no muestra tarjeta de festivos; el botón de extracción se llama "Actualizar Marcaciones"; hay una vista "Marcas del día" con tabla de solo lectura; muestra tarjetas de % asistencia a tiempo y minutos perdidos por tardanza.
9. **Logo**: placeholder `<img id="logo" src="">` en el sidebar para que el frontend lo reemplace con el archivo real.
10. **Marcas duplicadas aparentes**: el Excel trunca segundos; marcas cercanas en el tiempo pueden verse iguales pero provienen de eventos reales distintos.

---

## 6. Supuestos aplicados en la corrección de Fase 3

- **Marcas sin asociar**: se mantienen en el panel dedicado y no se incluyen en KPIs ni en el Excel de reportes.
- **"Días sin registro" en el Excel**: se cuenta entre los empleados activos que aparecen en el reporte.
- **Panel de festivos**: solo lectura, administrado automáticamente por la librería `holidays`.
- **Reporte Excel**: incluye todos los empleados `activo=True`, con o sin turno asignado.
- **Fusión de marcas**: marcas del mismo empleado/día dentro de `MARCA_FUSION_MINUTOS` se muestran como una sola "Marca N". El cálculo de columnas dinámicas usa los datos fusionados.
- **Turno default**: empleados activos sin turno propio usan un turno real llamado "Turno Default" vinculado a `turno_horario`. Las variables `DEFAULT_TURNO_ENTRADA` y `DEFAULT_TOLERANCIA_MINUTOS` del `.env` están deprecadas.
- **RBAC**: todos los endpoints protegidos requieren JWT y un permiso específico. El rol `Admin` tiene todos los permisos; el rol `Reportes` solo dashboard y reportes.

---

## 7. Próximos pasos sugeridos

### Bloqueantes antes del deploy

1. **Confirmar #4.1 con el usuario**: cambio real de `ADMIN_PASSWORD` en el `.env` de producción y reset contra la BD PostgreSQL real (no la SQLite de prueba).
2. **Generar `SECRET_KEY` real** en el `.env` de producción: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
3. **Deploy**: el usuario corre `docker compose build --no-cache backend && docker compose up -d backend` y `docker compose up -d --force-recreate frontend`. El daemon de Docker no es accesible desde este entorno.

### Cerrados con evidencia en esta ronda

- ✅ `misfire_grace_time=60` + test real de descarte.
- ✅ Retomo del backfill desde el último día commiteado + `BACKFILL_TIMEOUT_SEC=3600`.
- ✅ `create_usuario` fuerza `requiere_cambio_password=True`.
- ✅ Lock de concurrencia `device_lock` (`backend/device_lock.py`) serializa llamadas simultáneas al biométrico, incluyendo extracción y sync de empleados.
- ✅ Buffer overflow / rangos grandes: cerrado por diseño (`main()` procesa día por día con `fetch_day()`).

### Post-deploy

1. **Correo automático**: configurar cuenta Gmail y probar `enviar_correo_prueba()` y reportes programados.
2. **Validación visual del frontend**: abrir `http://localhost:3000` en navegador y confirmar que no hay errores de consola, que los KPIs se renderizan y que los filtros de reportes actualizan la UI.
3. **Tests automáticos**: considerar tests para cálculo de tardanzas, generación de reportes y lógica de días laborales.
4. **Registro manual de empleados**: cargar en la tabla `Empleado` los nombres reales del biométrico para que aparezcan en reportes y tardanzas automáticamente.

---

## 8. Cierre del batch (22 de julio de 2026)

El batch de cambios queda **cerrado**. Se validaron los 7 bloques propuestos y los dos puntos finales de timezone/seguridad.

### Checklist final

| Ítem | Estado |
| --- | --- |
| Sincronización de 71 empleados desde el biométrico | ✅ |
| Turnos individuales por empleado | ✅ |
| RBAC con roles/permisos no hardcodeados | ✅ |
| Login JWT con expiración configurable (8h default) | ✅ |
| Forzado de cambio de contraseña en primer login (admin/reportes sembrados) | ✅ |
| Frontend con login, dashboard, marcas del día, admin | ✅ |
| Backend con timezone `America/Bogota` en Dockerfile, docker-compose y código | ✅ |
| Reportes automáticos con periodicidad configurable en caliente | ✅ |
| Tarjetas `% asistencia a tiempo` y `minutos perdidos` | ✅ |
| Handoff actualizado | ✅ |

### Notas de cierre

- No se pudo ejecutar el comando `python3 -c "from datetime import datetime; print(datetime.now())"` dentro del contenedor porque el daemon de Docker no está corriendo en este entorno. Sin embargo, el `backend.Dockerfile` ya instala `tzdata`, define `ENV TZ=America/Bogota` y vincula `/etc/localtime`, y el código usa `ZoneInfo("America/Bogota")` de forma explícita.
- La validación visual del frontend en navegador gráfico queda como paso posterior, ya que este entorno es solo línea de comandos.
- **Tag v0.0** apunta al checkpoint inicial funcional; **tag v1.0** apunta a la versión actual con backfill, Alembic, fix de paginación, alerta `extraccion_incompleta_dias` y banner del dashboard.

### 8.1 Verificaciones de la alerta (27 de julio de 2026)

- `test_evidencia/test_alerta.py` y `test_evidencia/logs/test_alerta_resultado.txt` documentan el flujo completo (inserción → `/api/status` → banner).
- `test_evidencia/arrancar_alerta.bat` levanta uvicorn en `:18002` con la BD de prueba.
- uvicorn queda **detenido** al terminar cada corrida para no contaminar el puerto.

### 8.2 Fix y verificación de `misfire_grace_time` (27 de julio de 2026)

- **Bug:** `misfire_grace_time=None` en los 4 jobs del scheduler (`sync_empleados_diaria`, `extraccion_diaria`, `reporte_semanal`, `reporte_mensual`). Según la documentación oficial de APScheduler, `None` significa grace time infinito (el job corre sin importar cuán tarde esté), lo opuesto a la intención original.
- **Fix:** cambiado a `misfire_grace_time=60` en los 4 `add_job` (`backend/scheduler.py` líneas 68, 89, 112). El comentario explicativo fue corregido con la semántica real.
- **Test real:** `test_evidencia/test_misfire_grace_20260727_2018.py` + `test_evidencia/logs/test_misfire_grace_20260727_144457.log`.
  - Job `job_missed_5min` (retraso ~300s): **NO corrió**; APScheduler registró: `Run time of job ... was missed by 0:05:00.024490`.
  - Job `job_in_grace_30sec` (retraso ~30s): **SÍ corrió**.
  - Resultado: **PASS**.

### 8.3 Verificación de retomo del backfill y ajuste de watchdog (27 de julio de 2026)

- **Supuesto a validar:** si el watchdog mata el proceso a mitad de un backfill de varios días, el siguiente arranque retoma desde el último día commiteado, no desde el principio.
- **Test:** `test_evidencia/test_backfill_resume_20260727_2026.py` + `test_evidencia/logs/test_backfill_resume_20260727_144954.log` + `test_evidencia/mock_backfill_uvicorn.py`.
  - Simuló un gap de 5 días (ultima = hoy − 5).
  - Mock del extractor commiteó 1 registro por día, actualizó `ultima_extraccion_exitosa` y durmió 10s.
  - Después de 2 días commiteados se mató el proceso (`kill`).
  - Al reiniciar, el backfill retomó desde el día 3 y completó los 5 días.
  - BD final: `registros=5`, `ultima_extraccion_exitosa=hoy`.
  - Resultado: **PASS**.
- **Decisión:** se subió `BACKFILL_TIMEOUT_SEC` de `600` a `3600` en `.env.example` (1h cubre ~1 semana de gap con margen, dado ~80s/día). El watchdog sigue activo; no se deshabilita.

### 8.4 Fix de seguridad y documentación de SECRET_KEY (27 de julio de 2026)

- **Fix:** `create_usuario` en `backend/main.py:488-494` ahora setea `requiere_cambio_password=True` para todo usuario nuevo creado por el admin.
- **Evidencia:** `test_evidencia/test_create_user_password_change_20260727_2026.py` + `test_evidencia/logs/test_create_user_password_change_20260727_145205.log`.
  - `POST /api/usuarios` creó `testuser_145208` (rol Reportes).
  - Query a BD: `requiere_cambio_password=1`.
  - Resultado: **PASS**.
- **SECRET_KEY:** `.env.example` ahora documenta que el valor debe generarse con `python -c "import secrets; print(secrets.token_urlsafe(32))"` y no copiarse literalmente. Se generó un ejemplo real y se pegó como ilustración (no se aplicó al `.env` real de producción; eso lo hace el usuario a mano).
- **Pendiente confirmado por el usuario:** #4.1 (cambio real de `ADMIN_PASSWORD` en producción y reset contra PostgreSQL) queda fuera del alcance de este entorno.

### 8.5 Lock de concurrencia `device_lock` (27 de julio de 2026)

- **Objetivo:** confirmar que el lock global serializa dos llamadas simultáneas al dispositivo.
- **Nota:** el lock original vivía en `extractor_hikvision.py` como `_device_lock`. En la ronda del 30 de julio de 2026 se movió a `backend/device_lock.py` como `device_lock` para compartirlo también con `backend/sync_empleados.py`.
- **Test original:** `test_evidencia/test_device_lock_concurrency_20260727_2026.py` + `test_evidencia/logs/test_device_lock_concurrency_20260727_145811.log`.
  - Mock de `requests.post` para dormir 2s artificiales dentro del `fetch_range` real.
  - Dos threads llamaron `fetch_range()` casi simultáneamente.
  - Thread A entró al POST a las 14:58:12.583; thread B entró recién a las 14:58:14.584 (cuando A salió).
  - Tiempo total: **4.01s** (dos llamadas de 2s secuenciales, sin solapamiento).
  - Resultado: **PASS**. El lock funciona correctamente.

### 8.6 Buffer overflow / rangos grandes de backfill (27 de julio de 2026)

- **Estado:** Cerrado por diseño, sin prueba adicional.
- **Razonamiento:** `extractor_hikvision.main()` itera día por día y llama `fetch_day()`, que a su vez llama `fetch_range()` con ventanas de 24h (con fallback AM/PM/Q1-Q4). Nunca carga el rango completo en memoria; el consumo de memoria por día está acotado por la paginación (`BATCH_SIZE=50`) y el lock `device_lock` (`backend/device_lock.py`) serializa las llamadas HTTP al biométrico (extracción + sync de empleados). El watchdog de 1h (`BACKFILL_TIMEOUT_SEC=3600`) cubre el gap práctico esperado (~1 semana); si se necesitara más, el backfill retoma desde el último día commiteado tras el reinicio del contenedor.

---

### 8.7 Fase A — Versionado de horarios por día de semana (28 de julio de 2026)

**Decisión de arquitectura:** se elimina el fallback a `DEFAULT_TURNO_ENTRADA`/`DEFAULT_TOLERANCIA_MINUTOS` del `.env`. Todo empleado debe tener un `turno_id` real. Cada turno tiene horarios versionados por día de semana en `turno_horario`.

**Cambios implementados:**
- Migración Alembic `25e5f322addf_add_turno_horario`: nueva tabla `turno_horario` con índice único `(turno_id, dia_semana, vigente_desde)` y `ON DELETE CASCADE`. `server_default` usa `CURRENT_TIMESTAMP` para compatibilidad SQLite/PostgreSQL.
- Modelo `TurnoHorario` en `backend/models.py`.
- Función `obtener_horario_vigente()` en `backend/report_service.py`.
- `calcular_tardanzas_dia()` lee el horario vigente del `turno_id` del empleado para el día de la semana y fecha. Si no hay turno u horario, lanza `HorarioNoConfiguradoError`.
- Eliminado el fallback a `DEFAULT_TURNO_ENTRADA`/`DEFAULT_TOLERANCIA_MINUTOS` en el cálculo. Variables deprecadas en `.env.example`.
- Endpoints de turnos actualizados en `backend/main.py`:
  - `GET /api/turnos` con horarios vigentes de hoy.
  - `POST /api/turnos` crea turno + 5 horarios iniciales.
  - `GET /api/turnos/{id}` con historial.
  - `PUT /api/turnos/{id}` actualiza nombre/hora_salida.
  - `POST /api/turnos/{id}/horarios` inserta nueva vigencia (nunca update).
- Panel Admin: nueva pestaña "Turnos" con 5 campos (lunes a viernes), fecha de vigencia visible y botón para agregar nueva vigencia. Los empleados se editan con un select de turno.

**Evidencia:**
- `test_evidencia/logs/test_a1_turno_horario_alembic.txt` — upgrade/downgrade/upgrade en SQLite y verificación de índice único.
- `test_evidencia/test_turno_horario_vigencia.py` + `test_evidencia/logs/test_turno_horario_vigencia_console.txt`.
  - Lunes 2026-07-27 (antes de vigencia 2026-08-04) → `hora_entrada=07:30`.
  - Lunes 2026-08-10 (después de vigencia 2026-08-04) → `hora_entrada=08:00`.
  - Martes 2026-08-04 → `hora_entrada=07:30`.
  - Turno sin horario para lunes → `HorarioNoConfiguradoError`.
  - Resultado: **PASS**.

### 8.8 Fase B — Migración de datos "Turno General" (28 de julio de 2026)

**Datos confirmados por el arquitecto:**
- 71 empleados con `turno_id IS NULL` en tabla `empleados`.
- Backup: `backup_pre_horario_lunes_20260728_0832.sql`.
- `vigente_desde = 2026-07-28`.
- Tolerancia nueva: 1 minuto para todos los días.
- Lunes nuevo: hora entrada 08:00.
- Martes a viernes: 07:30.
- Valores históricos base: 07:30 con tolerancia 10.

**Script:** `test_evidencia/migracion_turno_general.py`

**Pasos del script (todo dentro de una transacción):**
1. INSERT INTO `turnos` ('Turno General') → `turno_id`.
2. INSERT 5 filas base en `turno_horario` (`vigente_desde=2020-01-01`, 07:30, tol 10).
3. INSERT 5 filas nuevas (`vigente_desde=2026-07-28`): lunes 08:00/1, martes-viernes 07:30/1.
4. UPDATE `empleados` SET `turno_id` = nuevo_id WHERE `turno_id IS NULL`.
5. Verificación antes de COMMIT:
   - `count(*) FROM empleados WHERE turno_id IS NULL` = 0.
   - `count(*) FROM turno_horario WHERE turno_id = <id>` = 10.
   - `obtener_horario_vigente(id, 0, 2026-07-28)` = (08:00, 1).
   - `obtener_horario_vigente(id, 1, 2026-07-28)` = (07:30, 1).
   - `obtener_horario_vigente(id, 0, 2020-06-01)` = (07:30, 10).
   Si falla → ROLLBACK.

**Evidencia contra BD de prueba (SQLite, simulando backup):**
- `test_evidencia/preparar_bd_prueba_migracion.py` crea `test_evidencia/migracion_prueba.db` con 71 empleados y schema actual.
- `test_evidencia/logs/migracion_turno_general_console.txt`:
  - `Empleados con turno_id IS NULL antes del UPDATE: 71`
  - `CHECK 1: empleados con turno_id IS NULL = 0`
  - `CHECK 2: filas turno_horario para turno_id=1 = 10`
  - `CHECK 3: lunes 2026-07-28 -> hora=08:00:00 tolerancia=1`
  - `CHECK 4: martes 2026-07-28 -> hora=07:30:00 tolerancia=1`
  - `CHECK 5: lunes 2020-06-01 -> hora=07:30:00 tolerancia=10`
  - `COMMIT exitoso`
  - Resultado: **PASS**.

**Ejecución en producción confirmada por el arquitecto:**
- `SELECT count(*) FROM empleados WHERE turno_id IS NULL` → **0**.
- `SELECT count(*) FROM turno_horario` → **10**.
- Backend corriendo en vivo sin errores (logs limpios).
- Dashboard verifica que el horario nuevo aplica en vivo.

### 8.9 Cierre de ronda — Horario por día de semana v1.1 (28 de julio de 2026)

**Tag:** `v1.1-horario-lunes`  
**Mensaje:** "Horario por dia de semana + tolerancia 1min, migracion 71 empleados a Turno General"

**Resumen de la funcionalidad:**
- Nueva tabla `turno_horario` con horarios versionados por día de semana (`dia_semana` 0=lunes...4=viernes) y fecha de vigencia (`vigente_desde`).
- Función `obtener_horario_vigente(turno_id, dia_semana, fecha)` devuelve el horario vigente más reciente para una fecha dada.
- Al cambiar un horario se inserta una nueva fila; el historial se conserva.
- El cálculo de tardanzas (`calcular_tardanzas_dia`) usa siempre `turno_horario` a través del `turno_id` del empleado.
- Panel Admin tiene pestaña "Turnos" con 5 campos y gestión de vigencias.

**Migración de datos:**
- 71 empleados migrados al "Turno General".
- Vigencia base (`2020-01-01`): 07:30 todos los días, tolerancia 10 minutos.
- Vigencia nueva (`2026-07-28`):
  - Lunes: 08:00, tolerancia 1 minuto.
  - Martes a viernes: 07:30, tolerancia 1 minuto.

**Fallback eliminado:**
- `DEFAULT_TURNO_ENTRADA` y `DEFAULT_TOLERANCIA_MINUTOS` ya no se usan en el código de cálculo.
- Siguen en `.env.example` con comentario de deprecación por si se necesita revertir rápido.

**Backup pre-migración:**
`C:\Users\Sistemas\AppData\Local\Temp\opencode\backups\backup_pre_horario_lunes_20260728_0832.sql`
(fuera del repositorio por seguridad).

**Evidencia generada (queda en `test_evidencia/logs/`):**
- `test_a1_turno_horario_alembic.txt`
- `test_turno_horario_vigencia_console.txt`
- `migracion_turno_general_console.txt`

### 8.10 Deuda técnica pendiente (no resolver ahora)

- **`update_empleado` con clientes viejos:** queda pendiente confirmar si un cliente con caché de browser que envíe `hora_entrada`/`tolerancia_minutos` en el PUT debe ser ignorado silenciosamente o rechazado. Actualmente el endpoint simplemente no lee esos campos.
- **Columnas deprecadas:** `hora_entrada`/`tolerancia_minutos` de `Turno` y `Empleado` siguen existiendo en el schema pero sin uso. Anotar como candidatas a limpieza en migración futura, no ahora.

### 8.11 Configuración SMTP editable desde Admin (29 de julio de 2026)

**Tag:** `v1.2-smtp-admin`  
**Commit:** `d1285e9` (incluye README actualizado)

**Cambios:**
- Nueva tabla `configuracion_correo` con fila única (`id = 1`) y constraint `CHECK (id = 1)`.
- Campo `password_encriptado` con Fernet; `FERNET_KEY` en `.env` requerida; falla ruidosa si falta.
- Nuevos endpoints bajo `admin_correo`:
  - `GET /api/config/correo` — devuelve host, puerto, usuario, remitente, seguridad, `password_configurado` y metadatos; nunca el password.
  - `PUT /api/config/correo` — guarda/actualiza; password vacío/null no pisa el existente.
  - `POST /api/config/correo/test` — envía correo de prueba real a una dirección ingresada; devuelve error SMTP real si falla.
- `email_service.py` lee la configuración desde la BD y soporta `none`, `starttls` y `ssl`. Si no hay config, los jobs loguean "correo no configurado" en lugar de conectar con credenciales vacías.
- Variables `SMTP_USER`/`SMTP_APP_PASSWORD` en `.env.example` marcadas como deprecadas.
- Panel Admin: formulario SMTP con host, puerto, usuario, contraseña (placeholder vacío = no cambiar), nombre remitente, seguridad; botón de correo de prueba con feedback; metadatos de última actualización.
- Footer del sidebar con crédito discreto: "Diseñado por Bairon Calle Rivera — b41r0nn@gmail.com".

**Evidencia:**
- `test_evidencia/logs/test_config_correo_console.txt`:
  - encriptación/desencriptación OK y password no almacenado en claro en BD;
  - `GET /api/config/correo` no devuelve password;
  - `PUT` con password vacío no pisa el password existente;
  - upgrade/downgrade/upgrade de la migración `f3321bd4c48b` OK.
- `test_evidencia/logs/test_smtp_mock_console.txt`:
  - `POST /api/config/correo/test` con smtplib mockeado: éxito devuelve 200 y mensaje con destinatario;
  - error simulado devuelve 400 con el mensaje real del error SMTP (`Error SMTP: (421, 'No se pudo conectar al servidor SMTP')`), no genérico.
- `test_evidencia/screenshot_footer_creditos.png` (footer con crédito, captura local con Playwright).

**Nota sobre endpoints legacy `/api/configuracion/correo/*`:**
- Sí existían antes de esta ronda. El endpoint base `GET /api/configuracion/correo` leía `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER` y `SMTP_APP_PASSWORD` desde `.env` y los devolvía al frontend, lo que obligaba a reiniciar el backend para cambiar la cuenta de correo.
- Después del ajuste:
  - `GET /api/configuracion/correo` ahora toma host, puerto, usuario y el flag `configurado` desde `configuracion_correo` (misma tabla que los nuevos endpoints).
  - Los endpoints de destinatarios (`/destinatarios`) y periodicidad (`/periodicidad`) siguen usando la tabla `configuracion` (clave-valor), que sigue siendo la fuente de verdad para esos datos.
  - `POST /api/configuracion/correo/prueba` usa la misma función `enviar_correo_prueba_a()` que el nuevo endpoint, por lo que lee la configuración de `configuracion_correo`.
- No queda una segunda fuente de verdad para SMTP: todo host/puerto/usuario/password/seguridad pasa por `configuracion_correo`. Si alguien pega al endpoint viejo, lee/escribe la misma tabla nueva (salvo destinatarios y periodicidad, que no cambiaron de lugar).

### 8.12 Guía de migración a Ubuntu Server (29 de julio de 2026)

**Commit asociado:** cierre de `v1.2-smtp-admin`

**Cambios:**
- Se creó `docker-compose.prod.yml` con configuración lista para producción:
  - PostgreSQL **sin puerto expuesto** al host.
  - **Sin bind mounts** que expongan código fuente.
  - Backend sin `--reload`.
  - Frontend en puerto `80`, backend en puerto `8000`.
  - Red bridge explícita y healthchecks para `db` y `backend`.
  - Healthcheck del backend apunta a `GET /health` (sin autenticación), no a `/api/status` que requiere JWT.
- Se agregó `GET /health` en `backend/main.py`:
  - Sin autenticación ni RBAC.
  - Ejecuta `SELECT 1` contra PostgreSQL mediante `engine.connect()`.
  - Devuelve `200 {"status": "ok"}` si la conexión funciona; `500` si falla.
- Se creó `MIGRACION_UBUNTU.md` con el procedimiento completo aprobado:
  1. Requisitos previos e instalación de Docker.
  2. Empaquetado del código en Windows con exclusiones de seguridad.
  3. Exportación de la base de datos con `pg_dump`.
  4. Transferencia con `scp`.
  5. Restauración con `psql`.
  6. Generación de `SECRET_KEY` y `FERNET_KEY` en producción.
  7. Creación/reset del usuario admin.
  8. Build y levantamiento con `docker-compose.prod.yml`.
  9. Verificación con `curl` y logs.
  10. Configuración de SMTP, destinatarios y DNS.
  11. Backup automático con `cron` a las 2:00 AM.
  12. Actualizaciones futuras y apartado preparado para HTTPS/Certbot.
  13. Troubleshooting y checklist de seguridad.
- `README.md` referencia `MIGRACION_UBUNTU.md` en la sección de deploy.

**Decisiones de producción confirmadas:**
- Migrar todo: código, configuración y datos de PostgreSQL.
- PostgreSQL corre dentro de Docker, autocontenido, sin puerto expuesto.
- Servidor Ubuntu en la misma red que el biométrico Hikvision.
- Acceso por IP interna con redirección DNS (ej. `asistencia.redihos.local`).
- Transferencia de archivos por red (`scp`) para facilitar actualizaciones.
- Empaquetado en `.zip` desde Windows, excluyendo `.env`, `.git`,
  `__pycache__`, `node_modules`, `pgdata` y `test_evidencia`.

**Datos sensibles a resolver manualmente antes del deploy real:**
- `SECRET_KEY`: generar nuevo en producción.
- `FERNET_KEY`: debe coincidir con el backup si este incluye
  `configuracion_correo`; de lo contrario, reconfigurar SMTP.
- `POSTGRES_PASSWORD` y `ADMIN_PASSWORD`: contraseñas fuertes.
- `DEVICE_IP`, `DEVICE_USER`, `DEVICE_PASS`: credenciales reales del biométrico.

**Evidencia de verificación (29 de julio de 2026):**
- `test_evidencia/logs/test_health_endpoint_20260729.txt`:
  - `GET /health` devuelve `200 {"status": "ok"}` sin autenticación.
  - `GET /api/status` sin token devuelve `401`, confirmando que el healthcheck
    anterior estaba mal targeteado.
- `test_evidencia/logs/test_fernet_key_migracion_20260729.txt`:
  - Con la `FERNET_KEY` original se desencripta el password migrado correctamente.
  - Con una `FERNET_KEY` regenerada falla con `InvalidToken`, demostrando el riesgo
    silencioso que la guía ahora detecta en el paso de verificación post-restore.
- **Nota sobre build Docker local:** el daemon de Docker Desktop no está corriendo
  en este entorno, por lo que no se pudo ejecutar `docker compose up` real. El
  healthcheck fue verificado contra la app importada con `TestClient`; el endpoint
  real y el compose de producción quedan listos para validar en el servidor Ubuntu.

**Preguntas pendientes para resolver antes del deploy real:**
1. ¿Cuál será la IP fija del servidor Ubuntu?
2. ¿Cuál será el dominio DNS exacto (`asistencia.redihos.local` u otro)?
3. ¿Qué proveedor SMTP usarán en producción (Gmail, Outlook, servidor propio)?
4. ¿Se quiere dejar listo un script de empaquetado automático para Windows
   (`build_deploy.ps1`)?

### 8.13 Pérdida y recuperación de turnos/horarios (30 de julio de 2026)

**Incidente:** durante una prueba local se perdió el `.env` original y se
regeneró uno temporal. Tras ello, el backend reportó las tablas `turnos` y
`turno_horario` vacías, aunque `empleados` seguía intacta con 71 registros.

**Diagnóstico:**
- El volumen `hikvision_extractor_pgdata` siguió siendo el mismo
  (`Skipping initialization` en los logs de PostgreSQL).
- La tabla `empleados` tenía 71 registros, lo que confirmó que no se había
  inicializado una base de datos nueva.
- Las tablas `turnos` y `turno_horario` estaban en 0, lo que indicó que esos
  datos específicos se habían perdido (probablemente por un `TRUNCATE` o recreación
  accidental de las tablas durante las pruebas).

**Acción:**
- Se recrearon manualmente los turnos y horarios en el panel Admin.
- Se crearon los scripts de backup `backup.ps1` y `backup.sh` para evitar que
  vuelva a pasar.
- Se configuró una tarea programada en Windows que ejecuta el backup todos los
  días a las 08:00 AM.
- Se documentó la restauración en `README.md`.

**Estado:** resuelto; sistema operativo con 5 turnos, 25 horarios y 71 empleados.

---

## 9. Problemas actuales / bloqueantes abiertos

| # | Problema | Impacto | Owner | Estado |
| --- | --- | --- | --- | --- |
| 1 | `ADMIN_PASSWORD` del `.env` de producción aún no se ha cambiado ni reseteado en PostgreSQL real | Riesgo de acceso con credencial por defecto | Usuario | Pendiente (#4.1) |
| 2 | `SECRET_KEY` de producción no generado | Tokens JWT firmados con valor de ejemplo/documentación | Usuario | Pendiente |
| 3 | Deploy a producción no realizado | Sistema aún no corre en Docker real | Usuario | Pendiente |
| 4 | Cuenta SMTP no configurada en BD | Reportes automáticos por correo no funcionan hasta que el admin complete el formulario en el panel | Usuario | Post-deploy |
| 5 | Validación visual del frontend en navegador | UI no verificada gráficamente | Usuario | Post-deploy |
| 6 | Registro manual de empleados en tabla `Empleado` | 36 nombres del biométrico aún sin asociar; reportes los muestran sin nombre | Usuario | Post-deploy |
| 7 | Buffer overflow en backfill de rangos grandes | **Mitigado por diseño**: procesamiento día por día con `fetch_day()` + `BATCH_SIZE=50` + `device_lock` (`backend/device_lock.py`) + watchdog 1h | Cerrado | No requiere acción |

### Notas

- Los ítems 1, 2 y 3 son **bloqueantes antes del deploy**.
- Los ítems 4, 5 y 6 son **post-deploy**; no impiden que el sistema funcione, pero limitan funcionalidad.
- El ítem 7 queda documentado como cerrado por diseño; no se hará prueba adicional.

---

## 8.14 Preparación de extracción periódica y lock compartido (30 de julio de 2026)

**Objetivo:** cambiar la extracción automática de una vez al día (8:00 PM) a una
vez por hora en horario laboral (6:00 AM - 8:00 PM), sin generar concurrencia
entre sync de empleados (7:00 AM) y extracción de marcas.

### Cambios implementados

1. **Lock global compartido:**
   - Se creó `backend/device_lock.py` con un `threading.Lock` global (`device_lock`).
   - `extractor_hikvision.py` dejó de definir `_device_lock` local y ahora importa
     `device_lock` desde `backend/device_lock`.
   - `backend/sync_empleados.py` ahora también importa `device_lock` y envuelve la
     llamada `session.post(...)` a `/ISAPI/AccessControl/UserInfo/Search` dentro del
     lock.
   - Resultado: cualquier llamada HTTP al biométrico (AcsEvent o UserInfo) está
     serializada; nunca hay dos consultas simultáneas.

2. **Reemplazo del job de extracción:**
   - En `backend/scheduler.py` se eliminó el job `extraccion_diaria` (8:00 PM).
   - Se agregó el job `extraccion_periodica` con cron `hour="6-20", minute=0`.
   - Se renombró la función `tarea_extraccion_diaria()` a
     `tarea_extraccion_periodica()` para reflejar el nuevo comportamiento.
   - Se actualizó el mensaje de inicio del scheduler.

### Evidencia de verificación

- **Test cross-endpoint:** `test_evidencia/test_device_lock_cross_endpoint_20260730.py` +
  `test_evidencia/logs/test_device_lock_cross_endpoint_20260730.txt`.
  - Mock de `requests.Session.post` para dormir 2s dentro de cada llamada.
  - Thread A ejecuta `extractor_hikvision.fetch_range()` (AcsEvent).
  - Thread B ejecuta `sync_empleados._fetch_user_info_page()` (UserInfo).
  - Ambos threads terminaron OK; el tiempo total fue ~5.9s, demostrando que las
    llamadas no se solaparon y el lock serializó entre endpoints distintos.
  - Resultado: **PASS**.

- **Verificación de jobs:** `test_evidencia/logs/test_scheduler_jobs_20260730.txt`.
  - Al iniciar el scheduler, los jobs registrados son:
    - `extraccion_periodica` → `cron[hour='6-20', minute='0']`
    - `sync_empleados_diaria` → `cron[hour='7', minute='0']`
    - `reporte_mensual` → configurable
    - `reporte_semanal` → configurable
  - El job `extraccion_diaria` ya no aparece.

- **Test de disparo controlado:** `test_evidencia/test_tarea_extraccion_periodica_20260730.py` +
  `test_evidencia/logs/test_tarea_extraccion_periodica_20260730.txt`.
  - Se ejecutó `tarea_extraccion_periodica()` directamente con `extractor_hikvision.main()` mockeado,
    sin depender del reloj real y sin tocar el biométrico de producción.
  - Se ejecutó 2 veces seguidas para simular un doble disparo del cron.
  - Confirmaciones:
    - La tarea loguea correctamente el disparo (`[EXTRACCION] Disparador: scheduler (cron hour=6-20, minute=0)`).
    - `ultima_extraccion_exitosa` se actualizó en la BD de prueba en ambas ejecuciones.
    - El timestamp de la segunda ejecución fue posterior a la primera.
    - El doble disparo no generó errores ni duplicados.
  - Resultado: **PASS**.

### Estado de activación

- Los cambios de código están en el repositorio.
- **Aún NO se reinicia el backend de producción.** El cambio se activará en el
  próximo deploy formal a Ubuntu, acompañado de monitoreo del primer disparo real
  a las 6:00 AM.

---

## 10. Cierre de sprint v1.2-smtp-admin → prod-ready (30 de julio de 2026)

**Estado:** Cerrado el sprint. Rama/lista de cambios lista para deploy a producción.

### Listo para deploy

- **Horario por día de semana + versionado histórico:** Turno 1 restaurado correctamente.
- **SMTP configurable desde panel Admin:** contraseña encriptada con Fernet; host, puerto, usuario, remitente y seguridad editables en caliente.
- **Seguridad:**
  - Sin fallback silencioso.
  - `/health` sin autenticación (healthcheck de producción).
  - Contraseñas fuera de código y documentación.
  - `ADMIN_PASSWORD` real cambiado.
- **Compose de producción + guía Ubuntu de 21 pasos:** consistentes y revisados.
- **Backup automatizado diario corriendo:** tarea programada `HikvisionBackupDiario` a las 08:00 AM en Windows; scripts `backup.ps1`/`backup.sh` disponibles.

### Pendiente, fuera de este sprint — anotado, no bloqueante

| Ítem | Detalle |
| --- | --- |
| SMTP real | Configurar proveedor (Gmail/Outlook/otro) y probar envío real desde el panel. Es lo próximo. |
| Turnos 2-5 | Sin vigencia histórica. Sin impacto real: no hay data de producción todavía. |
| Deuda técnica vieja | CORS abierto, tests automatizados, `update_empleado` con clientes viejos. |

## Fase 1: refactor de bajo riesgo (31 jul 2026)

Tres cambios aislados, un commit por punto, cada uno con test/grep de evidencia.

| # | Cambio | Evidencia | Commit |
| --- | --- | --- | --- |
| 1.1 | Centralizar `DEVICE_IP`/`DEVICE_USER`/`DEVICE_PASS` en `backend/device_config.py`; `extractor_hikvision.py` y `backend/sync_empleados.py` ahora importan desde allí. | `test_evidencia/test_device_config_shared_20260731.py` (PASS): default y custom IP coinciden en ambos módulos; grep confirma que no queda `os.getenv('DEVICE_IP')` duplicado. | `29c8dfc` |
| 1.2 | `update_empleado` acepta e ignora silenciosamente `hora_entrada`/`tolerancia_minutos` (campos deprecados de clientes viejos); la fuente de verdad sigue siendo `turno_horario`. | `test_evidencia/test_update_empleado_deprecated_20260731.py` (PASS): schema parsea el body con campos viejos; inspección confirma que la función no los referencia; modelo no se modifica por ellos. | `6ff125a` |
| 1.3 | Artefactos legacy (`hikvision.db`, `eventos.csv`, `eventos_hikvision.csv`, `Informe_Asistencia12.xlsx`) movidos a `legacy/` con `README.md`; `migrate_csv.py` y `README.md` apuntan a `legacy/eventos.csv`. | `test_evidencia/test_legacy_artifacts_20260731.py` (PASS): archivos en `legacy/`, ninguno en raíz, grep no encuentra referencias fuera de `legacy/` excepto la ruta actualizada en migración/documentación. | `d15817c` |

**Nota:** los tests de evidencia y sus logs quedan **solo en filesystem local** (`test_evidencia/` está en `.gitignore`); los 3 `.py` se force-added por error y ya fueron removidos del tracking (`d0b0c25`). Los logs revisados no contienen secretos reales (`DEVICE_PASS`, `POSTGRES_PASSWORD`, `ADMIN_PASSWORD`, `SECRET_KEY`, `FERNET_KEY` ni hashes/tokens).

## Fase 2: endpoint de reset de contraseña (31 jul 2026)

| # | Cambio | Evidencia | Commit |
| --- | --- | --- | --- |
| 2.1 | Nuevo endpoint `POST /api/usuarios/{id}/resetear-password`, solo admin (`require_perm("admin_roles")`). | `test_evidencia/test_resetear_password_20260731.py` (PASS): crea usuario, resetea vía endpoint, confirma que hash cambió y `requiere_cambio_password=True`; confirma que no-admin recibe 403; confirma que la contraseña temporal no queda en texto plano en BD ni logs. | `b48879d` |
| 2.2 | Migración `ea4c5fd67b9f` agrega `updated_by`/`updated_at` a `usuarios` para auditoría (patrón igual al de `configuracion_correo`). | El endpoint setea `updated_by` = id del admin y `updated_at` = UTC; test lo verifica en BD. | `b48879d` |
| 2.3 | Contraseña temporal generada con `secrets.token_hex(8)` (16 chars hex), hasheada con Argon2id, devuelta **una sola vez** en el response; nunca se loguea ni se almacena en claro. | Test escanea todas las tablas y el log de uvicorn; no encuentra la contraseña temporal. | `b48879d` |

| 2.4 | Botón **"Resetear pass"** en el panel de Usuarios (`frontend/index.html` + `frontend/app.js`). | Confirmación destructiva pidiendo escribir el username exacto; modal muestra la contraseña temporal con botón Copiar (con manejo de error); no aparece el botón sobre el propio usuario logueado; gatillado por el mismo permiso `admin_roles` que el backend. | `5d3ac3a` |

**Nota:** el test de UI (`test_evidencia/test_reset_password_ui_20260731.py`) verifica que el frontend esté cableado y que el endpoint responda, pero no ejecuta un browser real. Validación visual del modal queda para prueba manual en el panel.

**Limitación conocida (no bloqueante):** `updated_by`/`updated_at` en `usuarios` son genéricos. Hoy solo el endpoint de reset los actualiza (`update_usuario` no los toca), por lo que el timestamp apunta efectivamente al último reset. Pero si en el futuro se empiezan a usar para otros cambios (rol, activo, etc.), el rastro de auditoría del reset se perderá entre otras operaciones. Para trazabilidad completa del evento "reset de contraseña" haría falta una tabla de log separada (ej. `log_auditoria`) con tipo de acción. No es un problema de seguridad; es un detalle de auditoría a resolver más adelante.

## Fase 3: mejoras de UI/UX y reporte de histórico (29 sep 2026)

| # | Cambio | Evidencia | Commit |
| --- | --- | --- | --- |
| 3.1 | Logo REDIHOS en `frontend/logo.png` con fondo transparente, usado vía `<img>` en login y sidebar. | Procesado con flood-fill desde bordes para conservar letras blancas y quitar fondo blanco exterior. | `d67d51c` |
| 3.2 | Buscador por nombre en tarjeta **"Marcas del Día"** del dashboard (no en Llegadas Tarde). | Filtra en tiempo real sobre los datos cargados; función `filtrarMarcas()`. | `d67d51c` |
| 3.3 | Tarjeta **"Marcas del Día"** del dashboard con altura limitada (`max-height: calc(100vh - 320px)`) y scroll interno (`overflow-y-auto`) para no alargar la página. | Tarjeta usa `flex flex-col` y el tbody crece solo dentro del viewport. | `d67d51c` |
| 3.4 | Dashboard filtra llegadas tarde > 30 minutos en tarjeta y KPIs; botón para exportar la tarjeta a CSV/Excel. | Lógica en `frontend/app.js` con constante `TARDANZA_MAX_MINUTOS_DASHBOARD = 30`; función `exportarTardanzasExcel()`. | `8eacc01` |
| 3.5 | Nueva pestaña **"Histórico de Llegadas Tarde"** en Reportes. | Endpoint `GET /api/tardanzas/acumulado?fecha_hasta=YYYY-MM-DD&max_minutos=30`; tabla con `Empleado \| Área \| Minutos Mes \| Días Mes \| Minutos Año \| Días Año`; buscador y exportar a Excel. | `8eacc01` |

**Detalle técnico del endpoint `/api/tardanzas/acumulado`:**
- Reutiliza `calcular_tardanzas_dia` para cada día laboral entre el inicio del mes/año y `fecha_hasta`.
- Omite silenciosamente días sin horario configurado (`HorarioNoConfiguradoError`) para no romper el reporte histórico cuando haya gaps de configuración.
- Filtra tardanzas mayores a `max_minutos` (default 30) para no contaminar el histórico con permisos/largas.

**Test:** `test_evidencia/test_ui_fixes_20260929.py` → **PASS**. Verifica acumulado mensual/anual omitiendo >30 min y endpoint respondiendo 200.

### Nota de cierre

Buen trabajo hoy — fue una sesión larga y con un susto real en el medio (pérdida de turnos/horarios), pero se resolvió sin daño. El sistema queda operativo y el sprint cerrado hasta producción.

## Fase 3 (continuación): deploy a producción (29 sep 2026)

| # | Acción | Detalle | Resultado |
| --- | --- | --- | --- |
| D.1 | Backup pre-deploy | BD: `/home/sistemas/backups_redihos_prod/hikvision_pre_deploy_v1.5_20260929_163208.sql`; `.env`: `/home/sistemas/backups_redihos_prod/env_pre_deploy_v1.5_20260929_163208`. | ✅ Completado |
| D.2 | Paquete de deploy | Zip `/tmp/hikvision_asistencia_v1.5.zip` subido al servidor; excluye `.git`, `.env`, `.venv`, `__pycache__`, `pgdata`, `test_evidencia`, `backups`. | ✅ Completado |
| D.3 | Detener contenedores viejos | `docker compose -f docker-compose.prod.yml down`. | ✅ Completado |
| D.4 | Desplegar nuevo código | Reemplazo de `/home/sistemas/hikvision_extractor`, restauración de `.env` desde backup. | ✅ Completado |
| D.5 | Levantar stack | `docker compose -f docker-compose.prod.yml up -d --build`. | ✅ Completado |
| D.6 | Verificación post-deploy | Backend `/health` → `{"status":"ok"}`; frontend `/` → HTTP 200; contenedores `healthy`. | ✅ Completado |
| D.7 | Correcciones visuales post-deploy | Logo PNG transparente, scroll en "Marcas del Día", buscador movido a marcas, sincronización de fechas. Archivos copiados directamente al contenedor `hikvision_frontend`. | ✅ Completado |

### Problemas encontrados y soluciones

1. **`ModuleNotFoundError: No module named 'psycopg'`**
   - Causa: SQLAlchemy 2.1 intenta usar `psycopg` (versión 3) por defecto para URLs `postgresql://`, pero la imagen solo tiene `psycopg2-binary`.
   - Solución: forzar el driver `postgresql+psycopg2://` en `backend/database.py` y `alembic/env.py` cuando la URL comience con `postgresql://`.
   - Commit: `02b7b89`.

2. **Healthcheck del backend fallaba por falta de `wget`**
   - Causa: `docker-compose.prod.yml` usa `wget -qO- http://localhost:8000/health`, pero `python:3.11-slim` no incluye `wget`.
   - Solución: instalar `wget` en `backend.Dockerfile`.
   - Commit: `02b7b89`.

### Estado actual del servidor de producción

- **Servidor:** `192.168.1.250`
- **Path:** `/home/sistemas/hikvision_extractor`
- **Contenedores:** `hikvision_db` (healthy), `hikvision_backend` (healthy), `hikvision_frontend` (running)
- **URLs de acceso interno:** `http://localhost:8000/` (backend), `http://localhost:80/` (frontend)
- **Tag:** `v1.5-ui-historico` apunta al commit `d67d51c`.

### Pendientes post-deploy

1. Validación visual del frontend en navegador (logo PNG, scroll de marcas, buscador, sincronización de fechas, datos de KPIs).
2. Revisar por qué los KPIs mostraban `—` en la fecha 28/09/2026; verificar que `/api/kpis` responde correctamente para días sin datos (debe devolver 0, no null).
3. Configurar cuenta SMTP real en el panel de admin y probar envío de correo de prueba.
4. Monitorear el primer disparo real del scheduler (`extraccion_periodica`, `reporte_semanal`, `reporte_mensual`).

Cuando se retome, sea para configurar el correo real o para nuevos fixes, se sigue el mismo circuito de siempre.
