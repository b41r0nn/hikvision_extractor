from sqlalchemy import (
    Column, Integer, String, Date, Time, Boolean, ForeignKey
)
from sqlalchemy.orm import relationship
from .database import Base


class Turno(Base):
    __tablename__ = "turnos"

    id                  = Column(Integer, primary_key=True, index=True)
    nombre              = Column(String, nullable=False)          # ej. "Turno A", "Administrativo"
    hora_entrada        = Column(Time, nullable=False)            # ej. 07:30
    hora_salida         = Column(Time, nullable=True)             # ej. 17:00 (referencia, no obligatoria)
    tolerancia_minutos  = Column(Integer, default=10, nullable=False)

    empleados = relationship("Empleado", back_populates="turno")


class Empleado(Base):
    __tablename__ = "empleados"

    id                  = Column(Integer, primary_key=True, index=True)
    employee_id         = Column(String, unique=True, index=True)   # código del biométrico
    nombre              = Column(String, nullable=False)
    departamento        = Column(String, nullable=True)
    turno_id            = Column(Integer, ForeignKey("turnos.id"), nullable=True)  # legacy
    activo              = Column(Boolean, default=True, nullable=False)
    hora_entrada        = Column(Time, nullable=True)          # turno individual (HH:MM)
    tolerancia_minutos  = Column(Integer, nullable=True)       # tolerancia individual

    turno      = relationship("Turno", back_populates="empleados")
    registros  = relationship("RegistroAsistencia", back_populates="empleado",
                              primaryjoin="Empleado.employee_id == foreign(RegistroAsistencia.empleado_id)")


class Festivo(Base):
    __tablename__ = "festivos"

    id          = Column(Integer, primary_key=True, index=True)
    fecha       = Column(Date, unique=True, nullable=False, index=True)
    descripcion = Column(String, nullable=False)
    fuente      = Column(String, default="holidays")   # 'holidays' o 'manual'


class RegistroAsistencia(Base):
    __tablename__ = "registros_asistencia"

    id              = Column(Integer, primary_key=True, index=True)
    empleado_id     = Column(String, index=True)        # employeeNoString del biométrico
    nombre_empleado = Column(String)
    fecha           = Column(Date, index=True)
    hora            = Column(Time)
    tipo_evento     = Column(String)
    evento_raw      = Column(String)                    # timestamp ISO raw del biométrico

    empleado = relationship(
        "Empleado",
        primaryjoin="foreign(RegistroAsistencia.empleado_id) == Empleado.employee_id",
        back_populates="registros",
        uselist=False,
        viewonly=True,
    )


class Configuracion(Base):
    __tablename__ = "configuracion"

    id    = Column(Integer, primary_key=True, index=True)
    clave = Column(String, unique=True, nullable=False, index=True)
    valor = Column(String, nullable=False)


# ═══════════════════════════════════════════════════════════════════════════════
#  RBAC (Roles y Permisos)
# ═══════════════════════════════════════════════════════════════════════════════
class Permiso(Base):
    __tablename__ = "permisos"

    id          = Column(Integer, primary_key=True, index=True)
    nombre      = Column(String, unique=True, nullable=False, index=True)
    descripcion = Column(String, nullable=True)

    roles = relationship("Rol", secondary="rol_permiso", back_populates="permisos")


class Rol(Base):
    __tablename__ = "roles"

    id     = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, unique=True, nullable=False)

    permisos = relationship("Permiso", secondary="rol_permiso", back_populates="roles")
    usuarios = relationship("Usuario", back_populates="rol")


class RolPermiso(Base):
    __tablename__ = "rol_permiso"

    rol_id     = Column(Integer, ForeignKey("roles.id"), primary_key=True)
    permiso_id = Column(Integer, ForeignKey("permisos.id"), primary_key=True)


class Usuario(Base):
    __tablename__ = "usuarios"

    id           = Column(Integer, primary_key=True, index=True)
    username     = Column(String, unique=True, nullable=False, index=True)
    password_hash             = Column(String, nullable=False)
    rol_id                    = Column(Integer, ForeignKey("roles.id"), nullable=False)
    activo                    = Column(Boolean, default=True, nullable=False)
    requiere_cambio_password  = Column(Boolean, default=False, nullable=False)

    rol = relationship("Rol", back_populates="usuarios")
