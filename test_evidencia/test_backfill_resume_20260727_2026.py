"""
test_evidencia/test_backfill_resume_20260727_2026.py
Controla la prueba de retomo de backfill tras kill a mitad de camino.
Pasos:
  1. Crea BD backfill_resume.db con ultima_extraccion_exitosa = hoy - 5 dias.
  2. Lanza mock_backfill_uvicorn.py (backfill de 5 dias, 10s/dia).
  3. Espera a que commitee 2 dias y mata el proceso.
  4. Reinicia el proceso.
  5. Confirma en logs + BD que retoma desde el dia 3, no desde el dia 1.
Evidencia: log con timestamp unico.
"""
import os
import sys
import time
import sqlite3
import datetime
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB_PATH = os.path.abspath(os.path.join(ROOT, "test_evidencia", "backfill_resume.db"))
LOG_DIR = os.path.abspath(os.path.join(ROOT, "test_evidencia", "logs"))
TS = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_PATH = os.path.join(LOG_DIR, f"test_backfill_resume_{TS}.log")
WRAPPER = os.path.abspath(os.path.join(ROOT, "test_evidencia", "mock_backfill_uvicorn.py"))

os.makedirs(LOG_DIR, exist_ok=True)


def log(msg):
    ts = datetime.datetime.now().isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def setup_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    log(f"Creando BD {DB_PATH}")

    # Crear esquema con Alembic e inicializar datos
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
    subprocess.run(
        [".venv\\Scripts\\python.exe", "-m", "alembic", "upgrade", "head"],
        cwd=ROOT, env=env, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    # Inicializar festivos, RBAC, config
    subprocess.run(
        [".venv\\Scripts\\python.exe", "-c",
         "import os; os.environ['DATABASE_URL']='sqlite:///'+os.path.abspath('test_evidencia/backfill_resume.db'); "
         "from backend.database import SessionLocal; from backend.report_service import init_festivos; "
         "from backend.auth import init_rbac; from backend import config_service; "
         "db=SessionLocal(); init_festivos(db); init_rbac(db); config_service.init_defaults(db); db.close()"],
        cwd=ROOT, env=env, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    # Setear ultima_extraccion_exitosa a hoy - 5 dias
    hace_5_dias = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=5)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("INSERT INTO configuracion (clave, valor) VALUES (?, ?)",
                     ("ultima_extraccion_exitosa", hace_5_dias))
        conn.commit()
    finally:
        conn.close()
    log(f"[SETUP] ultima_extraccion_exitosa = {hace_5_dias}")


def get_ultima():
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute("SELECT valor FROM configuracion WHERE clave = ?",
                           ("ultima_extraccion_exitosa",)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def count_registros():
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute("SELECT COUNT(*) FROM registros_asistencia").fetchone()
        return row[0]
    finally:
        conn.close()


def launch_uvicorn():
    log("[CONTROL] Lanzando uvicorn (mock backfill) en puerto 18003...")
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [".venv\\Scripts\\python.exe", WRAPPER],
        cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    return proc


def drain_output(proc):
    try:
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            log(f"[UVICORN] {line.rstrip()}")
    except Exception:
        pass


def wait_for_days_committed(target_days, timeout=60):
    start = time.time()
    while time.time() - start < timeout:
        cnt = count_registros()
        log(f"[CONTROL] registros commiteados = {cnt}")
        if cnt >= target_days:
            return True
        time.sleep(2)
    return False


def main():
    log("=== test_backfill_resume iniciado ===")
    log(f"log_path = {LOG_PATH}")
    log(f"db_path = {DB_PATH}")

    setup_db()
    log(f"[SETUP] BD lista. ultima={get_ultima()}, registros={count_registros()}")

    # Primer arranque
    proc1 = launch_uvicorn()
    log(f"[CONTROL] PID primer arranque = {proc1.pid}")

    # Esperar a que commitee 2 dias
    ok = wait_for_days_committed(target_days=2, timeout=90)
    log(f"[CONTROL] Llego a 2 dias commiteados? {ok}")
    log(f"[CONTROL] Antes del kill: ultima={get_ultima()}, registros={count_registros()}")

    log(f"[CONTROL] Matando proceso {proc1.pid} (simula watchdog / kill -9)...")
    proc1.kill()
    proc1.wait()
    drain_output(proc1)
    log(f"[CONTROL] Proceso muerto. ultima={get_ultima()}, registros={count_registros()}")

    # Esperar un poco y reiniciar
    time.sleep(3)

    # Segundo arranque
    proc2 = launch_uvicorn()
    log(f"[CONTROL] PID segundo arranque = {proc2.pid}")

    # Esperar a que termine el backfill (deberian quedar 3 dias mas)
    ok = wait_for_days_committed(target_days=5, timeout=120)
    log(f"[CONTROL] Llego a 5 dias commiteados? {ok}")
    log(f"[CONTROL] Despues del reinicio: ultima={get_ultima()}, registros={count_registros()}")

    # Dejar que termine completamente
    time.sleep(5)

    log("[CONTROL] Matando segundo proceso...")
    proc2.kill()
    proc2.wait()
    drain_output(proc2)

    # Verificacion final
    ultima = get_ultima()
    registros = count_registros()
    log(f"[VERIFICACION FINAL] ultima={ultima}, registros={registros}")

    if registros == 5:
        log("[RESULTADO] PASS: Se completaron los 5 dias")
    else:
        log(f"[RESULTADO] FAIL: Se esperaban 5 registros (1 por dia), hay {registros}")

    hoy = datetime.date.today().isoformat()
    if ultima and ultima.startswith(hoy):
        log("[RESULTADO] PASS: ultima_extraccion_exitosa quedo en hoy")
    else:
        log(f"[RESULTADO] FAIL: ultima no quedo en hoy: {ultima}")

    log("=== test_backfill_resume finalizado ===")


if __name__ == "__main__":
    main()
