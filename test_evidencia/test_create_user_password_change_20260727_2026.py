"""
test_evidencia/test_create_user_password_change_20260727_2026.py
Verifica que create_usuario setee requiere_cambio_password=True.
Pasos:
  1. Arranca uvicorn en :18004 con evidencia.db.
  2. Login admin.
  3. POST /api/usuarios con rol Reportes.
  4. Query directa a BD para confirmar requiere_cambio_password=True.
Evidencia: log con timestamp unico.
"""
import os
import sys
import json
import time
import sqlite3
import datetime
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB_PATH = os.path.abspath(os.path.join(ROOT, "test_evidencia", "evidencia.db"))
LOG_DIR = os.path.abspath(os.path.join(ROOT, "test_evidencia", "logs"))
TS = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_PATH = os.path.join(LOG_DIR, f"test_create_user_password_change_{TS}.log")

os.makedirs(LOG_DIR, exist_ok=True)


def log(msg):
    ts = datetime.datetime.now().isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def launch_uvicorn():
    log("[CONTROL] Lanzando uvicorn en puerto 18004...")
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [".venv\\Scripts\\python.exe", "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", "18004", "--log-level", "info"],
        cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    return proc


def wait_for_port(port, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            import urllib.request
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def api_call(method, path, body=None, token=None):
    import urllib.request
    url = f"http://127.0.0.1:18004{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def get_user_from_db(username):
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT username, requiere_cambio_password FROM usuarios WHERE username = ?",
            (username,)
        ).fetchone()
        return row
    finally:
        conn.close()


def main():
    log("=== test_create_user_password_change iniciado ===")
    log(f"log_path = {LOG_PATH}")
    log(f"db_path = {DB_PATH}")

    proc = launch_uvicorn()
    log(f"[CONTROL] PID uvicorn = {proc.pid}")

    try:
        ready = wait_for_port(18004, timeout=30)
        log(f"[CONTROL] Puerto 18004 listo? {ready}")

        # Login admin
        login = api_call("POST", "/api/auth/login",
                         {"username": "admin", "password": "Ingreso2026*"})
        token = login["access_token"]
        log(f"[LOGIN] admin OK, token={token[:20]}...")

        # Buscar rol Reportes
        roles = api_call("GET", "/api/roles", token=token)
        rol_reportes = next((r for r in roles if r["nombre"] == "Reportes"), None)
        if not rol_reportes:
            raise RuntimeError("Rol Reportes no encontrado")
        log(f"[ROL] Reportes id={rol_reportes['id']}")

        # Crear usuario
        ts_user = datetime.datetime.now().strftime("%H%M%S")
        username = f"testuser_{ts_user}"
        nuevo = api_call("POST", "/api/usuarios",
                         {"username": username, "password": "TempPass123",
                          "rol_id": rol_reportes["id"], "activo": True},
                         token=token)
        log(f"[CREATE USER] response={json.dumps(nuevo)}")

        # Verificar en BD
        row = get_user_from_db(username)
        log(f"[BD] usuario={row[0]}, requiere_cambio_password={row[1]}")

        if row[1] == 1:
            log("[RESULTADO] PASS: requiere_cambio_password=True")
        else:
            log(f"[RESULTADO] FAIL: requiere_cambio_password={row[1]} (esperado 1)")

    finally:
        log("[CONTROL] Matando uvicorn...")
        proc.kill()
        proc.wait()
        # Drain output
        try:
            for line in proc.stdout:
                log(f"[UVICORN] {line.rstrip()}")
        except Exception:
            pass

    log("=== test_create_user_password_change finalizado ===")


if __name__ == "__main__":
    main()
