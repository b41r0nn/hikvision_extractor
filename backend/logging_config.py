"""
backend/logging_config.py
Configura el sistema de logging para la aplicación.

- stdout: comportamiento existente de print() no cambia.
- archivo rotativo: captura los mensajes enviados via logging.xxx()
  (incluyendo los logs internos de uvicorn y SQLAlchemy).
- Rotación a 10 MB, conserva los últimos 5 archivos.
"""
import logging
import os
from logging.handlers import RotatingFileHandler

_configured = False


def setup_logging() -> None:
    """Configura el root logger y el logger de uvicorn con un handler rotativo.

    Escribe a LOG_DIR/app.log (por defecto /app/logs/ en Docker,
    ./logs/ si la ruta no existe con permisos de escritura).
    Inocuo si se llama más de una vez.
    """
    global _configured
    if _configured:
        return
    _configured = True

    log_dir = os.getenv("LOG_DIR", "/app/logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "app.log")
        # Prueba de escritura rápida
        open(log_path, "a").close()
    except OSError:
        # Fallback al directorio local si /app/logs no tiene permisos
        log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "app.log")

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.INFO)

    # Configurar root logger — captura uvicorn, sqlalchemy, apscheduler, etc.
    root = logging.getLogger()
    if not root.handlers:
        # Si no hay handlers (ejecución directa), agregar también stdout
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)
        root.addHandler(console_handler)
    root.addHandler(file_handler)
    root.setLevel(logging.INFO)

    # Reducir verbosidad de libs ruidosas en el archivo
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("passlib").setLevel(logging.WARNING)

    print(f"[LOGGING] Archivo rotativo configurado en: {log_path}")
