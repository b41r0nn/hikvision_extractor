# Sistema de Asistencia Biométrica — REDIHOS S.A.S.

Sistema de control de asistencia para REDIHOS. Extrae marcaciones de un dispositivo Hikvision vía ISAPI, las almacena en PostgreSQL, genera informes Excel con formato dinámico de marcas y los envía automáticamente por correo semanal y mensual. Incluye panel web con dashboard, reportes y administración.

## Arquitectura Fase 3

| Servicio | Tecnología | Puerto |
|---|---|---|
| Base de datos | PostgreSQL 15 | `5432` |
| Backend API | FastAPI + Uvicorn | `8000` |
| Frontend | Nginx + HTML/JS | `3000` |
| Scheduler | APScheduler (inside backend) | — |

## Archivos principales

| Archivo | Descripción |
|---|---|
| `extractor_hikvision.py` | Extrae eventos del biométrico Hikvision vía ISAPI REST y guarda en PostgreSQL. |
| `backend/main.py` | API FastAPI: KPIs, reportes, CRUD empleados/turnos, festivos, configuración. |
| `backend/models.py` | Modelos SQLAlchemy: `Turno`, `Empleado`, `Festivo`, `RegistroAsistencia`. |
| `backend/report_service.py` | Motor Excel dinámico y cálculo de tardanzas. |
| `backend/email_service.py` | Envío SMTP de reportes programados. |
| `backend/scheduler.py` | Tareas programadas: extracción diaria 20:00, reporte semanal lunes 7:00, mensual día 1 7:00. |
| `frontend/index.html` + `app.js` | Panel web: dashboard, generación de reportes, administración. |
| `generar_informe.py` | CLI para generar Excel desde PostgreSQL. |
| `migrate_csv.py` | Migra un CSV exportado de iVMS-4200 a PostgreSQL. |
| `docker-compose.yml` | Orquesta db + backend + frontend. |
| `.env.example` | Variables de entorno documentadas. |

## Reglas de negocio implementadas

- **Sábados no son día laboral**: cálculo de tardanzas y días del reporte excluyen sábados, domingos y festivos colombianos.
- **Empleados solo manual**: el extractor nunca crea empleados automáticamente. Las marcas sin empleado asociado se guardan en `RegistroAsistencia` y se muestran en un panel de administración para decisión del admin.
- **Festivos automáticos**: se poblan con la librería `holidays` (Colombia, incluye Ley Emiliani) al iniciar la aplicación. El panel de festivos es solo lectura.
- **Extracción segura**: el extractor mantiene la lógica de paginación AM/PM/Q1-Q4 necesaria por los límites de hardware del biométrico.

## Instalación y ejecución

1. Copiar variables de entorno:

   ```bash
   cp .env.example .env
   # Editar .env con credenciales reales del biométrico y SMTP
   ```

2. Levantar con Docker:

   ```bash
   docker compose up -d --build
   ```

3. Acceder al frontend:

   ```
   http://localhost:3000
   ```

4. Documentación interactiva de la API:

   ```
   http://localhost:8000/docs
   ```

## Comandos útiles

### Generar informe manualmente

```bash
python generar_informe.py --start 2026-07-01 --end 2026-07-31
```

### Migrar CSV de iVMS-4200

```bash
python migrate_csv.py eventos.csv
```

### Forzar extracción (vía API)

```bash
curl -X POST http://localhost:8000/api/extraer \
  -H "Content-Type: application/json" \
  -d '{"fecha_inicio":"2026-07-01","fecha_fin":"2026-07-31"}'
```

## Notas de operación

- Las credenciales del biométrico se leen desde `.env` (`DEVICE_IP`, `DEVICE_USER`, `DEVICE_PASS`). El scheduler usa estos valores automáticamente.
- Los reportes automáticos se envían con la configuración SMTP definida en `.env`.
- El panel de festivos es solo lectura; los festivos se recargan automáticamente al iniciar el backend.
- El extractor diario corre a las 8:00 PM para evitar pérdida de datos por el buffer circular del dispositivo.

## Limitaciones conocidas

- El dispositivo Hikvision no distingue entrada de salida; el sistema infiere ingreso (primera marca) y salida (última marca) del día.
- Si el servidor no está en timezone `America/Bogota`, configurar APScheduler/uptime para evitar desfases en horarios programados.
