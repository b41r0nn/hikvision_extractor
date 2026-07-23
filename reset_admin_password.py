"""
reset_admin_password.py
Actualiza la contraseña del usuario admin en la base de datos.
Útil si el usuario ya existe y cambiar .env no basta.
"""
import os
from dotenv import load_dotenv

load_dotenv()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

from backend.database import SessionLocal
from backend import models
from backend.auth import get_password_hash

db = SessionLocal()
try:
    user = db.query(models.Usuario).filter(models.Usuario.username == ADMIN_USERNAME).first()
    if not user:
        print(f"Usuario '{ADMIN_USERNAME}' no encontrado en la BD.")
        exit(1)

    user.password_hash = get_password_hash(ADMIN_PASSWORD)
    # Obligar cambio en el siguiente login si se desea; poner False para dejarla fija.
    user.requiere_cambio_password = False
    db.commit()
    print(f"Contraseña de '{ADMIN_USERNAME}' actualizada correctamente.")
    print(f"Puedes iniciar sesión con: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")
finally:
    db.close()
