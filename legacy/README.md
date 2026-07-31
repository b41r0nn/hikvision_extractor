# Artefactos legacy

Esta carpeta contiene datos y archivos históricos de las Fases 1 y 2 del
proyecto hikvision_extractor. No se borran para preservar el contexto, pero ya
no son parte del sistema de producción actual.

## Archivos

| Archivo | Origen | Estado |
| --- | --- | --- |
| `hikvision.db` | Base SQLite de Fase 1. | Deprecado. Producción usa PostgreSQL. |
| `eventos.csv` | CSV de ejemplo exportado de iVMS-4200. | Deprecado. Útil para pruebas de `migrate_csv.py`. |
| `eventos_hikvision.csv` | CSV de eventos extraído vía ISAPI en Fase 1/2. | Deprecado. Reemplazado por extracción directa a BD. |
| `Informe_Asistencia12.xlsx` | Informe de ejemplo generado en Fase 1/2. | Deprecado. Reemplazado por generación dinámica. |

## Uso

- `migrate_csv.py` busca por defecto `legacy/eventos.csv` si no se le pasa
  argumento.
- Ningún código de producción referencia estos archivos directamente.
- Pueden archivarse o eliminarse en una futura limpieza sin impacto operativo.

## Historia

- Fase 1: prototipo local con SQLite, CSVs y XLSX manuales.
- Fase 2: migración a PostgreSQL + FastAPI, extracción automática vía ISAPI.
- Fase 1 de refactor: se agrupan los artefactos viejos en este directorio.
