"""
generar_informe.py
CLI para generar informes Excel de asistencia directamente desde PostgreSQL.
Delega la generación al motor report_service.py.

Uso:
  python generar_informe.py --start 2026-07-01 --end 2026-07-14
  python generar_informe.py --start 2026-07-01 --end 2026-07-14 --output mi_reporte.xlsx
"""
import argparse
import sys
from datetime import date

from backend.database import SessionLocal
from backend.report_service import generar_reporte


def main():
    parser = argparse.ArgumentParser(
        description="Genera informe de asistencia Excel desde la base de datos."
    )
    parser.add_argument("--start",  required=True, help="Fecha inicio (YYYY-MM-DD)")
    parser.add_argument("--end",    required=True, help="Fecha fin    (YYYY-MM-DD)")
    parser.add_argument("--output", default="",    help="Archivo Excel de salida")
    args = parser.parse_args()

    inicio = date.fromisoformat(args.start)
    fin    = date.fromisoformat(args.end)
    output = args.output or f"Asistencia_{args.start}_{args.end}.xlsx"

    print(f"Generando informe: {inicio} → {fin}")
    db = SessionLocal()
    try:
        excel_bytes = generar_reporte(db, inicio, fin)
        with open(output, "wb") as f:
            f.write(excel_bytes)
        print(f"Informe guardado en: {output}")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
