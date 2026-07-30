"""
Test de concurrencia cross-endpoint para device_lock.
Verifica que el mismo lock global serializa llamadas entre:
  - extractor_hikvision.fetch_range (endpoint /ISAPI/AccessControl/AcsEvent)
  - backend.sync_empleados._fetch_user_info_page (endpoint /ISAPI/AccessControl/UserInfo/Search)

Esto simula el choque a las 7:00 AM entre sync_empleados_diaria y extraccion_periodica.
"""
import os
import sys
import time
import threading
from datetime import datetime
from unittest.mock import patch

# Fijar DATABASE_URL antes de importar cualquier módulo del backend
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# Asegurar que el backend pueda importar desde el raíz del proyecto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import extractor_hikvision
from backend.sync_empleados import _fetch_user_info_page
from backend.database import Base, engine

# Crear tablas mínimas para que SessionLocal funcione (aunque no se usan)
Base.metadata.create_all(bind=engine)

ACSEVENT_URL = extractor_hikvision.URL
USERINFO_URL = f"http://{extractor_hikvision.IP}/ISAPI/AccessControl/UserInfo/Search?format=json"

SLEEP_SECONDS = 2.0
results = {"A": None, "B": None}


def mock_post(url, **kwargs):
    """Mock de requests.post que duerme dentro de la llamada según URL."""
    t0 = datetime.now()
    label = "AcsEvent" if "AcsEvent" in url else "UserInfo"
    print(f"[{label}] POST iniciado a {t0.strftime('%H:%M:%S.%f')[:-3]} -> {url}")
    # Simular latencia de red dentro del lock
    time.sleep(SLEEP_SECONDS)
    t1 = datetime.now()
    print(f"[{label}] POST finalizado a {t1.strftime('%H:%M:%S.%f')[:-3]}")

    if "AcsEvent" in url:
        return MockResponse({
            "AcsEvent": {
                "InfoList": [],
                "totalMatches": 0,
            }
        })
    else:
        return MockResponse({
            "UserInfoSearch": {
                "UserInfo": [],
                "totalMatches": 0,
                "numOfMatches": 0,
            }
        })


class MockResponse:
    def __init__(self, data):
        self._data = data
        self.status_code = 200

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


def run_acsevent():
    try:
        extractor_hikvision.fetch_range("2026-07-30T00:00:00", "2026-07-30T23:59:59")
        results["A"] = "OK"
    except Exception as e:
        results["A"] = f"ERROR: {e}"


def run_userinfo():
    try:
        session = requests.Session()
        _fetch_user_info_page(session, 0, 1000)
        results["B"] = "OK"
    except Exception as e:
        results["B"] = f"ERROR: {e}"


def main():
    print("=" * 60)
    print("Test device_lock cross-endpoint")
    print(f"AcsEvent URL: {ACSEVENT_URL}")
    print(f"UserInfo URL: {USERINFO_URL}")
    print("=" * 60)

    with patch("requests.Session.post", side_effect=mock_post):
        tA = threading.Thread(target=run_acsevent)
        tB = threading.Thread(target=run_userinfo)

        start = time.perf_counter()
        tA.start()
        tB.start()
        tA.join()
        tB.join()
        elapsed = time.perf_counter() - start

    print("\n" + "=" * 60)
    print(f"Resultado A: {results['A']}")
    print(f"Resultado B: {results['B']}")
    print(f"Tiempo total: {elapsed:.3f}s")
    print("=" * 60)

    if results["A"] != "OK" or results["B"] != "OK":
        print("[RESULTADO] FAIL: alguno de los threads falló")
        return 1

    # Si los requests fueron simultáneos, el total sería ~SLEEP_SECONDS.
    # Si el lock serializa, el total sería ~2 * SLEEP_SECONDS.
    if elapsed < (1.5 * SLEEP_SECONDS):
        print("[RESULTADO] FAIL: las llamadas parecen haberse solapado (lock no serializó)")
        return 1

    print(f"[RESULTADO] PASS: llamadas serializadas (~{elapsed:.3f}s >= {1.5 * SLEEP_SECONDS:.1f}s esperados)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
