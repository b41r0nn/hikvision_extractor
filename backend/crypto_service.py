"""
crypto_service.py
Encriptación simétrica de valores sensibles en reposo con Fernet.
La clave se lee de la variable de entorno FERNET_KEY. Si falta,
el proceso falla al importar el módulo (fail-loud).
"""
import os
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()

_FERNET_KEY = os.getenv("FERNET_KEY")
if not _FERNET_KEY:
    raise RuntimeError(
        "FERNET_KEY no está configurada. Revisá el .env — "
        "se requiere para encriptar la configuración de correo."
    )

_fernet = Fernet(_FERNET_KEY.encode())


def encriptar(valor: str) -> str:
    """Encripta un string y devuelve el token como string ASCII."""
    if not isinstance(valor, str):
        raise TypeError("El valor a encriptar debe ser str")
    return _fernet.encrypt(valor.encode("utf-8")).decode("ascii")


def desencriptar(valor: str) -> str:
    """Desencripta un token Fernet y devuelve el string original."""
    if not isinstance(valor, str):
        raise TypeError("El valor a desencriptar debe ser str")
    return _fernet.decrypt(valor.encode("ascii")).decode("utf-8")
