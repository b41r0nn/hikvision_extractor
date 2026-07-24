"""
Wrapper de diagnostico: lanza uvicorn redirigiendo stdout/stderr a un
archivo con timestamp por linea. No es codigo de produccion, solo se
usa desde test_evidencia/ para generar evidencia de las pruebas.

Uso:
    python test_evidencia/run_with_timestamps.py <log_path> <python> -m uvicorn ...
"""
import os
import sys
import datetime
import subprocess


def ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def main():
    if len(sys.argv) < 3:
        print("uso: run_with_timestamps.py <log_path> <comando...>")
        sys.exit(2)

    log_path = sys.argv[1]
    cmd = sys.argv[2:]

    log_file = open(log_path, "w", encoding="utf-8", buffering=1)

    def emit(line: str) -> None:
        out = f"[{ts()}] {line}"
        sys.stdout.write(out)
        sys.stdout.flush()
        log_file.write(out)
        log_file.flush()

    # Banner de diagnóstico: confirma QUÉ variables de entorno vio el proceso
    # al arrancar. Si DEVICE_IP está mal seteada, lo vemos acá, no en el log
    # de uvicorn (que no la imprime).
    emit(f"[DIAG] === run_with_timestamps.py iniciando ===\n")
    emit(f"[DIAG] log_path = {log_path}\n")
    emit(f"[DIAG] cmd      = {' '.join(cmd)}\n")
    emit(f"[DIAG] cwd      = {os.getcwd()}\n")
    emit(f"[DIAG] env DEVICE_IP      = {os.environ.get('DEVICE_IP', '<no seteada>')}\n")
    emit(f"[DIAG] env DATABASE_URL   = {os.environ.get('DATABASE_URL', '<no seteada>')}\n")
    emit(f"[DIAG] env PYTHONUNBUFFERED = {os.environ.get('PYTHONUNBUFFERED', '<no seteada>')}\n")
    emit(f"[DIAG] === arrancando subproceso ===\n\n")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as e:
        emit(f"[DIAG] ERROR lanzando subproceso: {e}\n")
        log_file.close()
        sys.exit(1)

    assert proc.stdout is not None
    try:
        for raw in proc.stdout:
            emit(raw if raw.endswith("\n") else raw + "\n")
    except KeyboardInterrupt:
        emit(f"[DIAG] KeyboardInterrupt -> terminando subproceso {proc.pid}\n")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    rc = proc.wait()
    emit(f"\n[DIAG] === subproceso termino con codigo {rc} ===\n")
    log_file.close()
    sys.exit(rc)


if __name__ == "__main__":
    main()
