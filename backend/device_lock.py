"""
device_lock.py
Lock global para serializar TODAS las llamadas HTTP al biométrico Hikvision.
El hardware soporta muy pocas conexiones concurrentes; cualquier llamada
paralela (extracción de marcas, sincronización de empleados, diagnóstico)
puede corromper la paginación y hacer perder eventos.
"""
import threading

# Lock global para serializar TODAS las llamadas HTTP al biométrico.
# Usado por extractor_hikvision.py y sync_empleados.py.
device_lock = threading.Lock()
