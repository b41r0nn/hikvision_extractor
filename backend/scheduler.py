from apscheduler.schedulers.background import BackgroundScheduler
import extractor_hikvision
from .database import SessionLocal
from .sync_empleados import sync_empleados
from .email_service import enviar_reporte_semanal, enviar_reporte_mensual
from .config_service import get_periodicidad, set_ultima_extraccion

scheduler = BackgroundScheduler()


def tarea_extraccion_diaria():
    """Extrae eventos del día actual a las 8:00 PM."""
    print("[SCHEDULER] Ejecutando extracción diaria programada...")
    try:
        print("[EXTRACCION] Disparador: scheduler (cron hour=20, minute=0)")
        extractor_hikvision.main()
        # Solo si la extracción fue exitosa, registramos el timestamp
        db = SessionLocal()
        try:
            set_ultima_extraccion(db)
        finally:
            db.close()
        print("[SCHEDULER] Extracción diaria completada y registrada.")
    except Exception as e:
        print(f"[SCHEDULER ERROR] Extracción diaria: {e}")


def tarea_sync_empleados_diaria():
    """Sincroniza empleados enrolados en el biométrico a las 7:00 AM."""
    print("[SCHEDULER] Sincronizando empleados desde el biométrico...")
    db = SessionLocal()
    try:
        result = sync_empleados(db)
        print(f"[SCHEDULER] Empleados sincronizados: {result}")
    except Exception as e:
        print(f"[SCHEDULER ERROR] Sincronización empleados: {e}")
    finally:
        db.close()


def tarea_reporte_semanal():
    """Genera y envía el reporte semanal según la configuración."""
    print("[SCHEDULER] Generando y enviando reporte semanal...")
    enviar_reporte_semanal()


def tarea_reporte_mensual():
    """Genera y envía el reporte mensual según la configuración."""
    print("[SCHEDULER] Generando y enviando reporte mensual...")
    enviar_reporte_mensual()


def schedule_reporte_semanal():
    """Lee la periodicidad de la BD y programa el job semanal."""
    db = SessionLocal()
    try:
        cfg = get_periodicidad(db)["semanal"]
    finally:
        db.close()

    scheduler.add_job(
        tarea_reporte_semanal,
        "cron",
        day_of_week=str(cfg["dia"]),
        hour=cfg["hora"],
        minute=cfg["minuto"],
        id="reporte_semanal",
        misfire_grace_time=60,
        coalesce=True,
        replace_existing=True,
    )


def schedule_reporte_mensual():
    """Lee la periodicidad de la BD y programa el job mensual."""
    db = SessionLocal()
    try:
        cfg = get_periodicidad(db)["mensual"]
    finally:
        db.close()

    scheduler.add_job(
        tarea_reporte_mensual,
        "cron",
        day=cfg["dia"],
        hour=cfg["hora"],
        minute=cfg["minuto"],
        id="reporte_mensual",
        misfire_grace_time=60,
        coalesce=True,
        replace_existing=True,
    )


def reschedule_report_jobs():
    """Reprograma en caliente los jobs de reportes semanal/mensual."""
    schedule_reporte_semanal()
    schedule_reporte_mensual()
    print("[SCHEDULER] Jobs de reportes reprogramados.")


def start_scheduler():
    # Configuración común a todos los jobs:
    # - misfire_grace_time=60: si el contenedor estuvo caído a la hora
    #   programada, el run "missed" SOLO se ejecuta al rearrancar si el
    #   retraso es menor o igual a 60 segundos. Si el retraso supera los
    #   60s, APScheduler descarta ese run y espera la próxima ocurrencia.
    #   Esto evita la "extracción misteriosa" al levantar el backend
    #   horas después de la hora del job.
    # - coalesce=True: si acumuló varios runs missed, los colapsa en uno
    #   solo (relevante principalmente durante el grace time).
    common = dict(misfire_grace_time=60, coalesce=True, replace_existing=True)

    # Sincronización de empleados a las 7:00 AM (antes del reporte semanal)
    scheduler.add_job(tarea_sync_empleados_diaria, "cron", hour=7, minute=0,
                      id="sync_empleados_diaria", **common)
    # Extracción diaria a las 8:00 PM (L-D para no perder ningún día)
    scheduler.add_job(tarea_extraccion_diaria, "cron", hour=20, minute=0,
                      id="extraccion_diaria", **common)
    # Reportes: leen periodicidad de la BD
    schedule_reporte_semanal()
    schedule_reporte_mensual()
    if not scheduler.running:
        scheduler.start()
    print("[SCHEDULER] Scheduler iniciado. Jobs: sync_empleados_diaria, extraccion_diaria, reporte_semanal, reporte_mensual.")
