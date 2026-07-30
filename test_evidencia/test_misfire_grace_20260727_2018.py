"""
test_evidencia/test_misfire_grace_20260727_2018.py
Prueba real de misfire_grace_time=60 en APScheduler.
- Job A: trigger 'date' hace 5 minutos -> retraso 300s > 60s -> NO debe correr.
- Job B: trigger 'date' hace 30 segundos -> retraso 30s < 60s -> SI debe correr.
Evidencia: log completo con timestamp por linea.
"""
import sys
import os
import time
import datetime
from apscheduler.schedulers.background import BackgroundScheduler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LOG_PATH = os.path.join(
    ROOT, "test_evidencia", "logs",
    f"test_misfire_grace_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
)


def log(msg):
    ts = datetime.datetime.now().isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def dummy_job(label):
    log(f"[JOB RAN] {label}")


def main():
    log(f"=== test_misfire_grace iniciado ===")
    log(f"log_path = {LOG_PATH}")
    log(f"cwd = {os.getcwd()}")

    now = datetime.datetime.now()
    five_min_ago = now - datetime.timedelta(minutes=5)
    thirty_sec_ago = now - datetime.timedelta(seconds=30)

    log(f"[CONFIG] misfire_grace_time=60, coalesce=True para ambos jobs")
    log(f"[SCHEDULE] job_missed_5min: run_date={five_min_ago.isoformat()} (retraso esperado ~300s)")
    log(f"[SCHEDULE] job_in_grace_30sec: run_date={thirty_sec_ago.isoformat()} (retraso esperado ~30s)")

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        dummy_job, "date", run_date=five_min_ago,
        args=["job_missed_5min"],
        id="job_missed_5min",
        misfire_grace_time=60, coalesce=True, replace_existing=True,
    )
    scheduler.add_job(
        dummy_job, "date", run_date=thirty_sec_ago,
        args=["job_in_grace_30sec"],
        id="job_in_grace_30sec",
        misfire_grace_time=60, coalesce=True, replace_existing=True,
    )

    log("[SCHEDULER] Starting...")
    scheduler.start()
    log("[SCHEDULER] Started, waiting 10s for missed jobs to be processed...")
    time.sleep(10)
    log("[SCHEDULER] Shutting down...")
    scheduler.shutdown()
    log("[SCHEDULER] Shutdown complete")

    # Reporte final
    log("[RESULTADO ESPERADO]")
    log("  job_missed_5min: NO debe haber corrido (retraso > 60s)")
    log("  job_in_grace_30sec: SI debe haber corrido (retraso <= 60s)")
    log("=== test_misfire_grace finalizado ===")


if __name__ == "__main__":
    main()
