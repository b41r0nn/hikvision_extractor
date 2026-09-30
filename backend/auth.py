"""
auth.py
Utilidades de autenticación y autorización basada en roles (RBAC).
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import models
from .database import get_db

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY no está configurada. Revisá el .env — "
        "se requiere una clave segura para firmar tokens JWT."
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# Lista canónica de permisos del sistema.
# Pueden crearse más vía admin, pero estos son los que el código valida.
PERMISOS = {
    "ver_dashboard":           "Ver dashboard, KPIs, tardanzas y marcas del día",
    "generar_reportes":        "Generar y descargar reportes Excel",
    "ver_historico_tardanzas": "Ver histórico de llegadas tarde (acumulado mensual/anual)",
    "forzar_extraccion":       "Ejecutar extracción manual de marcaciones",
    "sync_empleados":          "Sincronizar empleados desde el biométrico",
    "admin_empleados":         "Editar empleados (departamento, hora, tolerancia, activo)",
    "admin_correo":            "Configurar correo y probar envío",
    "admin_roles":             "Administrar usuarios, roles y permisos",
}


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.Usuario:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudo validar credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.Usuario).filter(models.Usuario.username == username).first()
    if user is None or not user.activo:
        raise credentials_exception
    return user


def require_perm(nombre_permiso: str):
    """Factory de dependencias: exige un permiso específico del rol del usuario."""
    def checker(user: models.Usuario = Depends(get_current_user)) -> models.Usuario:
        permisos = {p.nombre for p in user.rol.permisos}
        if nombre_permiso not in permisos:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para realizar esta acción",
            )
        return user
    return checker


def init_rbac(db: Session) -> None:
    """
    Crea permisos, roles iniciales y usuario admin por defecto si no existen.
    Idempotente: puede llamarse en cada arranque.
    """
    # Crear permisos
    permiso_objs = {}
    for nombre, desc in PERMISOS.items():
        p = db.query(models.Permiso).filter(models.Permiso.nombre == nombre).first()
        if not p:
            p = models.Permiso(nombre=nombre, descripcion=desc)
            db.add(p)
        permiso_objs[nombre] = p
    db.commit()

    # Rol Admin con TODOS los permisos existentes en la BD
    # (se asignan desde la BD para que el Admin siempre tenga acceso completo,
    #  aunque el dict PERMISOS del código no los conozca aún)
    admin_rol = db.query(models.Rol).filter(models.Rol.nombre == "Admin").first()
    if not admin_rol:
        admin_rol = models.Rol(nombre="Admin")
        db.add(admin_rol)
        db.commit()
        db.refresh(admin_rol)
    todos_los_permisos = db.query(models.Permiso).all()
    admin_rol.permisos = todos_los_permisos

    # Rol Reportes (dashboard + reportes)
    reportes_rol = db.query(models.Rol).filter(models.Rol.nombre == "Reportes").first()
    if not reportes_rol:
        reportes_rol = models.Rol(nombre="Reportes")
        db.add(reportes_rol)
        db.commit()
        db.refresh(reportes_rol)
    reportes_rol.permisos = [
        permiso_objs["ver_dashboard"],
        permiso_objs["generar_reportes"],
        permiso_objs["ver_historico_tardanzas"],
    ]

    db.commit()

    # Usuario admin por defecto
    admin_user = db.query(models.Usuario).filter(
        models.Usuario.username == os.getenv("ADMIN_USERNAME", "admin")
    ).first()
    if not admin_user:
        db.add(
            models.Usuario(
                username=os.getenv("ADMIN_USERNAME", "admin"),
                password_hash=get_password_hash(
                    os.getenv("ADMIN_PASSWORD", "admin")
                ),
                rol_id=admin_rol.id,
                activo=True,
                requiere_cambio_password=True,  # forzar cambio en primer login
            )
        )
        db.commit()

    # Usuario de solo reportes (opcional, para pruebas)
    if os.getenv("REPORTES_USERNAME"):
        reportes_user = db.query(models.Usuario).filter(
            models.Usuario.username == os.getenv("REPORTES_USERNAME")
        ).first()
        if not reportes_user:
            db.add(
                models.Usuario(
                    username=os.getenv("REPORTES_USERNAME"),
                    password_hash=get_password_hash(
                        os.getenv("REPORTES_PASSWORD", "reportes")
                    ),
                    rol_id=reportes_rol.id,
                    activo=True,
                    requiere_cambio_password=True,
                )
            )
            db.commit()
