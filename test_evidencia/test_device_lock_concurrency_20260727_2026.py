"""
test_evidencia/test_device_lock_concurrency_20260727_2026.py
Prueba de que device_lock (backend/device_lock.py) serializa 2 llamadas
simultaneas a fetch_range().

Mock: reemplaza requests.post para que el POST al dispositivo tarde 2s
artificialmente. Si el lock funciona, los 2 threads nunca deben estar
dentro del POST al mismo tiempo (se ven entrelazados).

Evidencia: log con timestamp + thread id por linea.
"""
import os
import sys
import time
import json
import threading
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LOG_DIR = os.path.abspath(os.path.join(ROOT, "test_evidencia", "logs"))
TS = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_PATH = os.path.join(LOG_DIR, f"test_device_lock_concurrency_{TS}.log")

os.makedirs(LOG_DIR, exist_ok=True)

# Evitar que extractor_hikvision intente conectar a la BD real al importar
os.environ.setdefault(
    "DATABASE_URL",
    "sqlite:///" + os.path.abspath(os.path.join(ROOT, "test_evidencia", "evidencia.db")),
)


def log(msg):
    ts = datetime.datetime.now().isoformat()
    tid = threading.current_thread().ident
    line = f"[{ts}] [thread={tid}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


# Importar despues de setear DATABASE_URL
import extractor_hikvision
from backend.device_lock import device_lock

# Mock de requests.post: simula llamada al dispositivo que tarda 2s
original_post = extractor_hikvision.requests.post


class MockResponse:
    def json(self):
        return {"AcsEvent": {"InfoList": [], "totalMatches": 0}}

    def raise_for_status(self):
        pass


def mock_post(url, json=None, auth=None, timeout=None):
    tid = threading.current_thread().ident
    log(f"[DEVICE_CALL ENTER] {url}")
    time.sleep(2)  # simulacion de latencia del dispositivo
    log(f"[DEVICE_CALL EXIT]  {url}")
    return MockResponse()


extractor_hikvision.requests.post = mock_post


def worker(name):
    log(f"[{name}] START fetch_range")
    try:
        events, total = extractor_hikvision.fetch_range(
            "2026-07-27T00:00:00", "2026-07-27T23:59:59"
        )
        log(f"[{name}] DONE fetch_range -> events={len(events)}, total={total}")
    except Exception as e:
        log(f"[{name}] ERROR fetch_range -> {e}")


def main():
    log("=== test_device_lock_concurrency iniciado ===")
    log(f"log_path = {LOG_PATH}")
    log(f"device_lock = {device_lock}")
    log(f"Simulacion: 2 threads llaman fetch_range() casi simultaneamente")
    log(f"Esperado: thread A entra al POST, duerme 2s, sale; RECIEN thread B entra")
    log(f"Si se solapan los DEVICE_CALL ENTER/EXIT -> el lock falla")

    start = time.time()

    t1 = threading.Thread(target=worker, args=("A",), name="worker-A")
    t2 = threading.Thread(target=worker, args=("B",), name="worker-B")

    t1.start()
    t2.start()

    t1.join()
    t2.join()

    elapsed = time.time() - start
    log(f"Tiempo total: {elapsed:.2f}s (esperado ~4s si el lock serializa)")

    # Verificacion automatica: leer el log y detectar solapamiento
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    inside = 0
    overlap = False
    for line in lines:
        if "[DEVICE_CALL ENTER]" in line:
            inside += 1
            if inside > 1:
                overlap = True
                log(f"[DETECCION] Solapamiento detectado: {line.strip()}")
        elif "[DEVICE_CALL EXIT]" in line:
            inside -= 1

    if overlap:
        log("[RESULTADO] FAIL: se detecto solapamiento en el lock")
    else:
        log("[RESULTADO] PASS: no se detecto solapamiento; lock serializo las llamadas")

    log("=== test_device_lock_concurrency finalizado ===")


if __name__ == "__main__":
    main()
