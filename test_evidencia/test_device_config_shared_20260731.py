"""
Test de centralización de DEVICE_IP.

Fase 1.1: extractor_hikvision.py y backend/sync_empleados.py deben leer
la configuración del biométrico desde un único lugar (backend.device_config).

Este test verifica:
  1. Ambos módulos comparten el mismo DEVICE_IP (default y custom).
  2. Las URLs construidas apuntan al mismo host.
  3. No queda doble lectura de os.getenv("DEVICE_IP") en los módulos.
"""
import os
import sys
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LOG_PATH = os.path.join(ROOT, "test_evidencia", "logs", "test_device_config_shared_20260731.txt")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)


def log(msg):
    ts = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def leer_fuente(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_default():
    """Sin DEVICE_IP en env, ambos módulos usan el default compartido."""
    env_backup = os.environ.pop("DEVICE_IP", None)
    try:
        import importlib
        from backend import device_config as dc
        import extractor_hikvision as ext
        import backend.sync_empleados as sync

        # Recargar para que tomen el valor actual de env
        importlib.reload(dc)
        importlib.reload(ext)
        importlib.reload(sync)

        log(f"device_config.DEVICE_IP = {dc.DEVICE_IP}")
        log(f"extractor_hikvision.IP  = {ext.IP}")
        log(f"sync_empleados.IP       = {sync.IP}")

        assert dc.DEVICE_IP == ext.IP == sync.IP, "IPs no coinciden"
        assert dc.DEVICE_IP == "192.168.1.127", f"Default inesperado: {dc.DEVICE_IP}"
        assert "192.168.1.127" in ext.URL, f"URL extractor mal: {ext.URL}"
        assert "192.168.1.127" in sync.URL, f"URL sync mal: {sync.URL}"
        log("[OK] Default compartido verificado")
    finally:
        if env_backup is not None:
            os.environ["DEVICE_IP"] = env_backup


def test_custom_ip():
    """Con DEVICE_IP custom, ambos módulos reflejan el mismo valor."""
    env_backup = os.environ.get("DEVICE_IP")
    os.environ["DEVICE_IP"] = "10.20.30.40"
    try:
        import importlib
        from backend import device_config as dc
        import extractor_hikvision as ext
        import backend.sync_empleados as sync

        importlib.reload(dc)
        importlib.reload(ext)
        importlib.reload(sync)

        log(f"device_config.DEVICE_IP = {dc.DEVICE_IP}")
        log(f"extractor_hikvision.IP  = {ext.IP}")
        log(f"sync_empleados.IP       = {sync.IP}")

        assert dc.DEVICE_IP == "10.20.30.40"
        assert ext.IP == "10.20.30.40"
        assert sync.IP == "10.20.30.40"
        assert "10.20.30.40" in ext.URL
        assert "10.20.30.40" in sync.URL
        log("[OK] IP custom compartida verificada")
    finally:
        if env_backup is not None:
            os.environ["DEVICE_IP"] = env_backup
        else:
            os.environ.pop("DEVICE_IP", None)


def test_no_double_read():
    """Ya no debe haber os.getenv('DEVICE_IP') duplicado en los módulos."""
    ext_src = leer_fuente(os.path.join(ROOT, "extractor_hikvision.py"))
    sync_src = leer_fuente(os.path.join(ROOT, "backend", "sync_empleados.py"))

    ext_matches = len(re.findall(r'os\.getenv\(["\']DEVICE_IP["\']', ext_src))
    sync_matches = len(re.findall(r'os\.getenv\(["\']DEVICE_IP["\']', sync_src))

    log(f"os.getenv('DEVICE_IP') en extractor_hikvision.py: {ext_matches}")
    log(f"os.getenv('DEVICE_IP') en sync_empleados.py: {sync_matches}")

    assert ext_matches == 0, "extractor_hikvision.py aún lee DEVICE_IP directamente"
    assert sync_matches == 0, "sync_empleados.py aún lee DEVICE_IP directamente"
    log("[OK] No hay doble lectura de DEVICE_IP")


def main():
    if os.path.exists(LOG_PATH):
        os.remove(LOG_PATH)
    log("=" * 60)
    log("Test centralización DEVICE_IP (Fase 1.1)")
    log("=" * 60)

    try:
        test_default()
        test_custom_ip()
        test_no_double_read()
    except Exception as e:
        log(f"[RESULTADO] FAIL: {e}")
        return 1

    log("\n[RESULTADO] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
