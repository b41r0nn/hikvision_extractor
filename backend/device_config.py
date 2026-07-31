"""
device_config.py
Configuración compartida del biométrico Hikvision.

Fase 1: centraliza la lectura de DEVICE_IP/USER/PASS para evitar duplicación
entre extractor_hikvision.py y backend/sync_empleados.py. Cualquier cambio
en variables de entorno afecta a ambos módulos por igual.
"""
import os
from dotenv import load_dotenv

# Cargar .env desde el directorio del proyecto (compatible con raíz y backend).
load_dotenv()

DEVICE_IP = os.getenv("DEVICE_IP", "192.168.1.127")
DEVICE_USER = os.getenv("DEVICE_USER", "admin")
DEVICE_PASS = os.getenv("DEVICE_PASS", "tu_password")

ACS_EVENT_URL = f"http://{DEVICE_IP}/ISAPI/AccessControl/AcsEvent?format=json"
USER_INFO_URL = f"http://{DEVICE_IP}/ISAPI/AccessControl/UserInfo/Search?format=json"
