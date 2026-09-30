"""
Lock global para serializar operaciones de extracción de marcaciones.

Scheduler, backfill de arranque y extracción manual comparten este lock
para evitar que dos procesos escriban simultáneamente a la base de datos
y generen duplicados o estados inconsistentes.
"""
import threading

_extraction_lock = threading.Lock()


def acquire_extraction_lock(blocking: bool = False) -> bool:
    """
    Intenta adquirir el lock de extracción.

    Args:
        blocking: Si es True, espera hasta que el lock esté libre.
                  Si es False, retorna inmediatamente con el resultado.

    Returns:
        True si se adquirió el lock, False si estaba ocupado y blocking=False.
    """
    return _extraction_lock.acquire(blocking=blocking)


def release_extraction_lock() -> None:
    """Libera el lock de extracción."""
    try:
        _extraction_lock.release()
    except RuntimeError:
        # El lock ya estaba libero; ignoramos para evitar crashes.
        pass


def is_extracting() -> bool:
    """Retorna True si hay una extracción en curso (lock ocupado)."""
    # locked() es True si algún thread lo tiene; no indica si el thread
    # actual lo posee, pero para este caso es suficiente.
    return _extraction_lock.locked()
