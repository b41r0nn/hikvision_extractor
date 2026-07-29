"""
backend/main.py
API principal del Sistema de Asistencia Biométrica REDIHOS.
"""
import io
import os
import time as _time
from contextlib import asynccontextmanager
from datetime import date, time, timedelta
from typing import List, Optional
import threading

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import models
from .database import engine, get_db, SessionLocal
from .scheduler import start_scheduler
from .report_service import generar_reporte, calcular_tardanzas_dia, get_festivos, es_dia_laboral, init_festivos, obtener_horario_vigente, HorarioNoConfiguradoError
from .email_service import enviar_correo_prueba_a, CorreoNoConfiguradoError
from .sync_empleados import sync_empleados
from .auth import (
    get_current_user, require_perm, get_password_hash, verify_password,
    create_access_token, init_rbac, PERMISOS,
)
from . import config_service
from . import config_correo_service
from .scheduler import reschedule_report_jobs, scheduler as app_scheduler
from .timezone import hoy_bogota, ahora_bogota
import extractor_hikvision


@asynccontextmanager
async def lifespan(app: FastAPI):
    # La migración de esquema es CRÍTICA: si falla, la app NO debe arrancar
    # con la BD desincronizada. Cualquier excepción aquí detiene el lifespan
    # y el contenedor se reiniciará (docker restart policy).
    print("Aplicando migraciones de Alembic...")
    from alembic import command
    from alembic.config import Config
    alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
    print("[MIGRACIONES] Alembic upgrade head aplicado correctamente.")

    print("Iniciando inicialización de datos...")
    # Cada bloque de inicialización es independiente: un fallo en uno
    # NO debe abortar los demás.
    db = next(get_db())
    try:
        # 1. Festivos colombianos
        try:
            n = init_festivos(db)
            print(f"[FESTIVOS] {n} festivos poblados desde la librería holidays.")
        except Exception as e:
            db.rollback()
            print(f"[FESTIVOS ERROR] No se pudieron poblar festivos: {e}")

        # 2. Roles, permisos y usuario admin
        try:
            init_rbac(db)
            print("[RBAC] Roles y permisos inicializados.")
        except Exception as e:
            db.rollback()
            print(f"[RBAC ERROR] No se pudieron inicializar roles/permisos: {e}")

        # 3. Configuración por defecto (correo y periodicidad)
        try:
            config_service.init_defaults(db)
            print("[CONFIG] Configuración por defecto inicializada.")
        except Exception as e:
            db.rollback()
            print(f"[CONFIG ERROR] No se pudo inicializar configuración: {e}")
    finally:
        db.close()

    # 4. Backfill automático al arrancar: si el contenedor estuvo apagado,
    #    recuperamos los días entre la última extracción exitosa y hoy.
    #    Se ejecuta en background para no retrasar el arranque de la API.
    try:
        db = SessionLocal()
        try:
            ultima_iso = config_service.get_ultima_extraccion(db)
            if ultima_iso:
                ultima_date = date.fromisoformat(ultima_iso[:10])
                hoy = hoy_bogota()
                if ultima_date < hoy:
                    start_backfill = ultima_date + timedelta(days=1)
                    end_backfill = hoy
                    print(f"[BACKFILL] Rellenando desde {start_backfill} hasta {end_backfill}...")

                    def _backfill():
                        try:
                            print(f"[EXTRACCION] Disparador: backfill "
                                  f"(rango {start_backfill} -> {end_backfill})")
                            extractor_hikvision.main(
                                start_str=start_backfill.isoformat(),
                                end_str=end_backfill.isoformat(),
                                progress_callback=lambda msg: print(f"[BACKFILL] {msg}"),
                            )
                            db2 = SessionLocal()
                            try:
                                config_service.set_ultima_extraccion(db2)
                                print(f"[BACKFILL] Exito. Rango {start_backfill} -> {end_backfill} completado.")
                            finally:
                                db2.close()
                        except extractor_hikvision.DeviceUnavailableError as e:
                            print(f"[BACKFILL ABORTADO] {e}")
                            print(f"[BACKFILL] ultima_extraccion_exitosa NO se actualiza; "
                                  f"se reintentara en el proximo arranque.")
                        except Exception as e:
                            print(f"[BACKFILL ERROR] {e}")

                    # Techo duro: si el backfill supera BACKFILL_TIMEOUT_SEC,
                    # el watchdog mata el proceso. La política restart: always
                    # de docker-compose levantará el contenedor de nuevo, y
                    # el siguiente arranque reintentará desde donde quedó.
                    timeout_sec = int(os.getenv("BACKFILL_TIMEOUT_SEC", "600"))

                    def _watchdog(start_ts: float):
                        if timeout_sec <= 0:
                            return
                        restante = timeout_sec - (_time.time() - start_ts)
                        if restante <= 0:
                            print(f"[BACKFILL WATCHDOG] Timeout duro alcanzado "
                                  f"({timeout_sec}s); terminando proceso para "
                                  f"forzar reinicio. Loguear este caso y revisar "
                                  f"estado del biometrico.")
                            os._exit(1)
                        timer = threading.Timer(
                            restante, _watchdog, args=(_time.time(),)
                        )
                        timer.daemon = True
                        timer.start()

                    watchdog = threading.Timer(
                        timeout_sec, _watchdog, args=(_time.time(),)
                    )
                    watchdog.daemon = True
                    watchdog.start()

                    threading.Thread(
                        target=_backfill,
                        name="backfill-extraccion",
                        daemon=True,
                    ).start()
                else:
                    print("[BACKFILL] Ultima extraccion es hoy; no se requiere relleno.")
            else:
                print("[BACKFILL] No hay ultima extraccion registrada; se omite backfill.")
        finally:
            db.close()
    except Exception as e:
        print(f"[BACKFILL ERROR] No se pudo evaluar backfill: {e}")

    print("Iniciando scheduler de tareas en segundo plano...")
    start_scheduler()
    yield
    print("Apagando API...")
    if app_scheduler.running:
        app_scheduler.shutdown(wait=False)

app = FastAPI(title="API Asistencia Biométrica — REDIHOS", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Estado global de extracción ───────────────────────────────────────────────
extraction_state = {"is_running": False, "progress": "Inactivo"}

def progress_callback(msg: str):
    print(f"[EXTRACCION] {msg}")
    extraction_state["progress"] = msg

def ejecutar_extraccion(start_date: str, end_date: str):
    if extraction_state["is_running"]:
        return
    try:
        extraction_state["is_running"] = True
        extraction_state["progress"]   = f"Iniciando ({start_date} → {end_date})..."
        print(f"[EXTRACCION] Disparador: manual "
              f"(rango {start_date} -> {end_date})")
        extractor_hikvision.main(start_str=start_date, end_str=end_date,
                                  progress_callback=progress_callback)
        # Solo actualizamos ultima_extraccion si el bucle completo terminó
        # sin DeviceUnavailableError. main() ya hace rollback en ese caso
        # y re-lanza la excepción, por lo que nunca llegamos a este punto
        # si la conectividad falló a mitad de un rango.
        db = SessionLocal()
        try:
            config_service.set_ultima_extraccion(db)
        finally:
            db.close()
        extraction_state["progress"] = "Extracción completada."
    except extractor_hikvision.DeviceUnavailableError as e:
        extraction_state["progress"] = f"Dispositivo no disponible: {e}"
        print(f"[EXTRACCION ABORTADA] {e}")
    except Exception as e:
        extraction_state["progress"] = f"Error: {e}"
        print(f"[EXTRACCION ERROR] {e}")
    finally:
        extraction_state["is_running"] = False


# ── Estado global de sincronización de empleados ──────────────────────────────
sync_state = {"is_running": False, "progress": "Inactivo", "last_result": None}


def ejecutar_sync():
    if sync_state["is_running"]:
        return
    db = SessionLocal()
    try:
        sync_state["is_running"] = True
        sync_state["progress"] = "Conectando con el dispositivo..."

        def cb(msg: str):
            print(f"[SYNC EMPLEADOS] {msg}")
            sync_state["progress"] = msg

        result = sync_empleados(db, progress_callback=cb)
        sync_state["last_result"] = result
        sync_state["progress"] = (
            f"Sincronización completada: {result['creados']} creados, "
            f"{result['actualizados']} actualizados."
        )
    except Exception as e:
        sync_state["progress"] = f"Error: {e}"
        sync_state["last_result"] = {"error": str(e)}
        print(f"[SYNC EMPLEADOS ERROR] {e}")
    finally:
        sync_state["is_running"] = False
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
#  SCHEMAS (Pydantic)
# ══════════════════════════════════════════════════════════════════════════════
class ExtraerRequest(BaseModel):
    fecha_inicio: Optional[str] = None
    fecha_fin:    Optional[str] = None

class TurnoHorarioItem(BaseModel):
    dia_semana:         int       # 0=lunes, 1=martes, 2=miércoles, 3=jueves, 4=viernes
    hora_entrada:       str       # "HH:MM"
    tolerancia_minutos: int = 10


class TurnoCreate(BaseModel):
    nombre:             str
    hora_salida:        Optional[str] = None
    # Al crear un turno se deben proveer los 5 horarios iniciales (lunes a viernes).
    horarios:           List[TurnoHorarioItem]


class TurnoUpdate(BaseModel):
    nombre:             str
    hora_salida:        Optional[str] = None


class TurnoHorarioCreate(BaseModel):
    dia_semana:         int
    hora_entrada:       str       # "HH:MM"
    tolerancia_minutos: int
    vigente_desde:      Optional[str] = None  # "YYYY-MM-DD"; default hoy_bogota()


class EmpleadoUpdate(BaseModel):
    departamento:       Optional[str] = None
    turno_id:           Optional[int] = None
    # hora_entrada y tolerancia_minutos individuales quedan deprecados en Fase A.
    # La fuente de verdad es turno_horario a través del turno_id del empleado.
    activo:             bool = True


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    password_actual: str
    password_nuevo: str


class UsuarioCreate(BaseModel):
    username: str
    password: str
    rol_id:   int
    activo:   bool = True


class UsuarioUpdate(BaseModel):
    rol_id: Optional[int] = None
    activo: Optional[bool] = None


class RolCreate(BaseModel):
    nombre: str


class AsignarPermisoRequest(BaseModel):
    permiso_id: int


class ReporteRequest(BaseModel):
    fecha_inicio:  str
    fecha_fin:     str
    employee_ids:  Optional[List[str]] = None
    departamentos: Optional[List[str]] = None
    modo:          str = "entrada_salida"   # "entrada_salida" | "completo"

class ConfigCorreoUpdate(BaseModel):
    destinatarios: List[str]


class ConfigSMTPRequest(BaseModel):
    host: str
    puerto: int
    usuario: str
    password: Optional[str] = None
    remitente_nombre: Optional[str] = None
    seguridad: str = "starttls"


class ConfigSMTPTestRequest(BaseModel):
    destinatario: str


class RecipientCreate(BaseModel):
    email: str


class PeriodicidadRequest(BaseModel):
    semanal: dict
    mensual: dict


# ══════════════════════════════════════════════════════════════════════════════
#  ENDPOINTS GENERALES
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/")
def read_root():
    return {"message": "API de Asistencia Biométrica REDIHOS — en línea"}


@app.get("/health")
def health_check():
    """
    Endpoint de salud para healthchecks de Docker/orquestadores.
    No requiere autenticación ni RBAC. Verifica conectividad a PostgreSQL.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  AUTENTICACIÓN
# ══════════════════════════════════════════════════════════════════════════════
@app.post("/api/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.Usuario).filter(models.Usuario.username == req.username).first()
    if not user or not verify_password(req.password, user.password_hash) or not user.activo:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    token = create_access_token({"sub": user.username, "rol": user.rol.nombre})
    return {
        "access_token": token,
        "token_type":   "bearer",
        "username":     user.username,
        "rol":          user.rol.nombre,
        "permisos":     [p.nombre for p in user.rol.permisos],
        "requiere_cambio_password": user.requiere_cambio_password,
    }


@app.get("/api/auth/me")
def me(user: models.Usuario = Depends(get_current_user)):
    return {
        "username": user.username,
        "rol":      user.rol.nombre,
        "permisos": [p.nombre for p in user.rol.permisos],
        "requiere_cambio_password": user.requiere_cambio_password,
    }


@app.post("/api/auth/cambiar-password")
def cambiar_password(
    req: PasswordChangeRequest,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(get_current_user),
):
    """Permite a un usuario cambiar su propia contraseña."""
    if not verify_password(req.password_actual, user.password_hash):
        raise HTTPException(status_code=401, detail="Contraseña actual incorrecta")
    user.password_hash = get_password_hash(req.password_nuevo)
    user.requiere_cambio_password = False
    db.commit()
    return {"message": "Contraseña actualizada correctamente"}


# ══════════════════════════════════════════════════════════════════════════════
#  ROLES Y PERMISOS (administración RBAC)
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/api/permisos")
def list_permisos(
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_roles")),
):
    return db.query(models.Permiso).order_by(models.Permiso.nombre).all()


@app.get("/api/roles")
def list_roles(
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_roles")),
):
    roles = db.query(models.Rol).order_by(models.Rol.nombre).all()
    return [
        {
            "id":        r.id,
            "nombre":    r.nombre,
            "permisos":  [{"id": p.id, "nombre": p.nombre, "descripcion": p.descripcion} for p in r.permisos],
        }
        for r in roles
    ]


@app.post("/api/roles", status_code=201)
def create_rol(
    req: RolCreate,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_roles")),
):
    if db.query(models.Rol).filter(models.Rol.nombre == req.nombre).first():
        raise HTTPException(status_code=400, detail="Ya existe un rol con ese nombre")
    rol = models.Rol(nombre=req.nombre)
    db.add(rol)
    db.commit()
    db.refresh(rol)
    return {"id": rol.id, "nombre": rol.nombre, "permisos": []}


@app.post("/api/roles/{rol_id}/permisos")
def add_permiso_to_rol(
    rol_id: int,
    req: AsignarPermisoRequest,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_roles")),
):
    rol = db.query(models.Rol).filter(models.Rol.id == rol_id).first()
    perm = db.query(models.Permiso).filter(models.Permiso.id == req.permiso_id).first()
    if not rol or not perm:
        raise HTTPException(status_code=404, detail="Rol o permiso no encontrado")
    if perm not in rol.permisos:
        rol.permisos.append(perm)
        db.commit()
    return {"id": rol.id, "nombre": rol.nombre,
            "permisos": [{"id": p.id, "nombre": p.nombre} for p in rol.permisos]}


@app.delete("/api/roles/{rol_id}/permisos/{permiso_id}")
def remove_permiso_from_rol(
    rol_id: int,
    permiso_id: int,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_roles")),
):
    rol = db.query(models.Rol).filter(models.Rol.id == rol_id).first()
    perm = db.query(models.Permiso).filter(models.Permiso.id == permiso_id).first()
    if not rol or not perm:
        raise HTTPException(status_code=404, detail="Rol o permiso no encontrado")
    if perm in rol.permisos:
        rol.permisos.remove(perm)
        db.commit()
    return {"id": rol.id, "nombre": rol.nombre,
            "permisos": [{"id": p.id, "nombre": p.nombre} for p in rol.permisos]}


@app.delete("/api/roles/{rol_id}", status_code=204)
def delete_rol(
    rol_id: int,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_roles")),
):
    rol = db.query(models.Rol).filter(models.Rol.id == rol_id).first()
    if not rol:
        raise HTTPException(status_code=404, detail="Rol no encontrado")
    if db.query(models.Usuario).filter(models.Usuario.rol_id == rol_id).first():
        raise HTTPException(status_code=400, detail="No se puede eliminar un rol con usuarios asignados")
    db.delete(rol)
    db.commit()
    return


@app.get("/api/usuarios")
def list_usuarios(
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_roles")),
):
    usuarios = db.query(models.Usuario).order_by(models.Usuario.username).all()
    return [
        {
            "id":                       u.id,
            "username":                 u.username,
            "activo":                   u.activo,
            "rol_id":                   u.rol_id,
            "rol":                      u.rol.nombre,
            "requiere_cambio_password": u.requiere_cambio_password,
        }
        for u in usuarios
    ]


@app.post("/api/usuarios", status_code=201)
def create_usuario(
    req: UsuarioCreate,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_roles")),
):
    if db.query(models.Usuario).filter(models.Usuario.username == req.username).first():
        raise HTTPException(status_code=400, detail="Ya existe un usuario con ese nombre")
    rol = db.query(models.Rol).filter(models.Rol.id == req.rol_id).first()
    if not rol:
        raise HTTPException(status_code=400, detail="Rol no encontrado")
    nuevo = models.Usuario(
        username=req.username,
        password_hash=get_password_hash(req.password),
        rol_id=req.rol_id,
        activo=req.activo,
        requiere_cambio_password=True,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return {"id": nuevo.id, "username": nuevo.username, "activo": nuevo.activo, "rol_id": nuevo.rol_id, "rol": nuevo.rol.nombre}


@app.put("/api/usuarios/{usuario_id}")
def update_usuario(
    usuario_id: int,
    req: UsuarioUpdate,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_roles")),
):
    obj = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if req.rol_id is not None:
        rol = db.query(models.Rol).filter(models.Rol.id == req.rol_id).first()
        if not rol:
            raise HTTPException(status_code=400, detail="Rol no encontrado")
        obj.rol_id = req.rol_id
    if req.activo is not None:
        obj.activo = req.activo
    db.commit()
    db.refresh(obj)
    return {"id": obj.id, "username": obj.username, "activo": obj.activo, "rol_id": obj.rol_id, "rol": obj.rol.nombre}


@app.delete("/api/usuarios/{usuario_id}", status_code=204)
def delete_usuario(
    usuario_id: int,
    db: Session = Depends(get_db),
    current: models.Usuario = Depends(require_perm("admin_roles")),
):
    obj = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if obj.id == current.id:
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propio usuario")
    db.delete(obj)
    db.commit()
    return


@app.get("/api/status")
def get_status(
    user: models.Usuario = Depends(require_perm("ver_dashboard")),
    db: Session = Depends(get_db),
):
    from .config_service import get_ultima_extraccion, get_alertas_extraccion
    from datetime import datetime, timezone, timedelta

    ultima_iso = get_ultima_extraccion(db)
    alerta_retraso = False
    horas_desde_ultima = None
    if ultima_iso:
        try:
            ultima = datetime.fromisoformat(ultima_iso)
            if ultima.tzinfo is None:
                ultima = ultima.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - ultima
            horas_desde_ultima = round(delta.total_seconds() / 3600, 1)
            # 24h de ciclo + 2h de margen
            if horas_desde_ultima > 26:
                alerta_retraso = True
        except Exception:
            pass

    alertas_incompletas = get_alertas_extraccion(db)

    return {
        **extraction_state,
        "ultima_extraccion_exitosa": ultima_iso,
        "horas_desde_ultima_extraccion": horas_desde_ultima,
        "alerta_retraso_extraccion": alerta_retraso,
        "extraccion_incompleta": alertas_incompletas,
        "alerta_extraccion_incompleta": len(alertas_incompletas) > 0,
    }

@app.post("/api/extraer")
def forzar_extraccion(
    req: ExtraerRequest,
    background_tasks: BackgroundTasks,
    user: models.Usuario = Depends(require_perm("forzar_extraccion")),
):
    if extraction_state["is_running"]:
        return {"message": "Ya hay una extracción en curso."}
    inicio = req.fecha_inicio or hoy_bogota().isoformat()
    fin    = req.fecha_fin    or hoy_bogota().isoformat()
    background_tasks.add_task(ejecutar_extraccion, inicio, fin)
    return {"message": f"Extracción iniciada ({inicio} → {fin})."}


# ══════════════════════════════════════════════════════════════════════════════
#  SINCRONIZACIÓN DE EMPLEADOS
# ══════════════════════════════════════════════════════════════════════════════
@app.post("/api/empleados/sync")
def sincronizar_empleados(
    background_tasks: BackgroundTasks,
    user: models.Usuario = Depends(require_perm("sync_empleados")),
):
    if sync_state["is_running"]:
        return {"message": "Ya hay una sincronización en curso."}
    background_tasks.add_task(ejecutar_sync)
    return {"message": "Sincronización de empleados iniciada."}


@app.get("/api/empleados/sync/status")
def get_sync_status(user: models.Usuario = Depends(require_perm("sync_empleados"))):
    return sync_state


# ══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD / KPIs
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/api/kpis")
def get_kpis(
    fecha: Optional[date] = None,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("ver_dashboard")),
):
    dia = fecha or hoy_bogota()
    registros = db.query(models.RegistroAsistencia).filter(
        models.RegistroAsistencia.fecha == dia
    ).all()

    # Solo contar como "empleados con marca" a los registrados manualmente
    nombres_registrados = {
        e.nombre for e in db.query(models.Empleado).filter(models.Empleado.activo == True).all()
    }
    empleados_con_marca = len(
        set(r.nombre_empleado for r in registros if r.nombre_empleado in nombres_registrados)
    )
    # Marcas de personas no asociadas (útiles para el panel de admin)
    marcas_sin_asociar = len(
        set(r.nombre_empleado for r in registros if r.nombre_empleado not in nombres_registrados)
    )

    tardanzas = calcular_tardanzas_dia(db, dia)
    llegadas_tarde = len(tardanzas)
    minutos_perdidos = sum(t["tardanza_mins"] for t in tardanzas)
    asistencia_a_tiempo_pct = 100.0
    llegadas_tarde_pct = 0.0
    if empleados_con_marca > 0:
        llegadas_tarde_pct = round((llegadas_tarde / empleados_con_marca) * 100, 1)
        asistencia_a_tiempo_pct = round(((empleados_con_marca - llegadas_tarde) / empleados_con_marca) * 100, 1)

    return {
        "fecha":                    dia.isoformat(),
        "total_marcaciones":        len(registros),
        "empleados_con_marca":      empleados_con_marca,
        "marcas_sin_asociar":       marcas_sin_asociar,
        "llegadas_tarde":           llegadas_tarde,
        "asistencia_a_tiempo_pct":  asistencia_a_tiempo_pct,
        "llegadas_tarde_pct":       llegadas_tarde_pct,
        "minutos_perdidos_tardanza": minutos_perdidos,
    }

@app.get("/api/tardanzas")
def get_tardanzas(
    fecha: Optional[date] = None,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("ver_dashboard")),
):
    dia = fecha or hoy_bogota()
    return calcular_tardanzas_dia(db, dia)

@app.get("/api/registros")
def read_registros(
    fecha:  Optional[date]  = None,
    nombre: Optional[str]   = None,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("ver_dashboard")),
):
    query = db.query(models.RegistroAsistencia)
    if fecha:
        query = query.filter(models.RegistroAsistencia.fecha == fecha)
    if nombre:
        query = query.filter(models.RegistroAsistencia.nombre_empleado.ilike(f"%{nombre}%"))
    return query.order_by(
        models.RegistroAsistencia.fecha.desc(),
        models.RegistroAsistencia.hora.desc()
    ).limit(1000).all()

@app.get("/api/registros/sin-asociar")
def get_registros_sin_asociar(
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_empleados")),
):
    """Retorna los nombres de empleados en las marcas que no existen en la tabla Empleados"""
    nombres_empleados = db.query(models.Empleado.nombre).all()
    nombres_registrados = [n[0] for n in nombres_empleados]

    query = db.query(
        models.RegistroAsistencia.nombre_empleado,
        models.RegistroAsistencia.empleado_id
    ).filter(
        ~models.RegistroAsistencia.nombre_empleado.in_(nombres_registrados)
    ).distinct()
    
    resultados = query.all()
    return [{"nombre": r[0], "employee_id": r[1]} for r in resultados]



# ══════════════════════════════════════════════════════════════════════════════
#  EMPLEADOS
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/api/empleados")
def get_empleados(
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("ver_dashboard")),
):
    empleados = db.query(models.Empleado).order_by(models.Empleado.nombre).all()
    return [
        {
            "id": e.id,
            "employee_id": e.employee_id,
            "nombre": e.nombre,
            "departamento": e.departamento,
            "turno_id": e.turno_id,
            "activo": e.activo,
            # Columnas individuales deprecadas; se mantienen por compatibilidad.
            "hora_entrada": e.hora_entrada.strftime("%H:%M") if e.hora_entrada else None,
            "tolerancia_minutos": e.tolerancia_minutos,
        }
        for e in empleados
    ]

@app.get("/api/empleados/departamentos")
def get_departamentos(
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("ver_dashboard")),
):
    rows = db.query(models.Empleado.departamento).distinct().all()
    return [r.departamento for r in rows if r.departamento]

@app.put("/api/empleados/{emp_id}")
def update_empleado(
    emp_id: int,
    emp: EmpleadoUpdate,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_empleados")),
):
    obj = db.query(models.Empleado).filter(models.Empleado.id == emp_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Empleado no encontrado.")

    obj.departamento = emp.departamento
    obj.activo       = emp.activo
    if emp.turno_id is not None:
        turno = db.query(models.Turno).filter(models.Turno.id == emp.turno_id).first()
        if not turno:
            raise HTTPException(status_code=400, detail="Turno no encontrado.")
        obj.turno_id = emp.turno_id
    else:
        obj.turno_id = None

    db.commit()
    db.refresh(obj)
    return obj

@app.delete("/api/empleados/{emp_id}", status_code=204)
def delete_empleado(
    emp_id: int,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_empleados")),
):
    obj = db.query(models.Empleado).filter(models.Empleado.id == emp_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Empleado no encontrado.")
    db.delete(obj)
    db.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  TURNOS (versionado por día de semana desde Fase A)
# ══════════════════════════════════════════════════════════════════════════════

def _str_to_time(value: Optional[str]) -> Optional[time]:
    if not value:
        return None
    try:
        h, m = value.split(":")
        return time(int(h), int(m))
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de hora debe ser HH:MM")


def _horario_vigente_hoy_json(db: Session, turno_id: int) -> List[Optional[dict]]:
    """Devuelve los 5 horarios vigentes de hoy (lunes=0 ... viernes=4) para un turno."""
    hoy = hoy_bogota()
    result = []
    for dia in range(5):
        try:
            he, tol = obtener_horario_vigente(db, turno_id, dia, hoy)
            result.append({
                "hora_entrada": he.strftime("%H:%M"),
                "tolerancia_minutos": tol,
                "vigente_desde": None,
            })
        except HorarioNoConfiguradoError:
            result.append(None)
    return result


@app.get("/api/turnos")
def get_turnos(
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_empleados")),
):
    """Lista de turnos con el horario vigente de hoy para cada día de semana."""
    turnos = db.query(models.Turno).order_by(models.Turno.nombre).all()
    return [
        {
            "id": t.id,
            "nombre": t.nombre,
            "hora_salida": t.hora_salida.strftime("%H:%M") if t.hora_salida else None,
            "horarios_hoy": _horario_vigente_hoy_json(db, t.id),
        }
        for t in turnos
    ]


@app.post("/api/turnos", status_code=201)
def create_turno(
    t: TurnoCreate,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_empleados")),
):
    """Crea un turno y sus 5 horarios iniciales vigentes desde hoy."""
    if len(t.horarios) != 5:
        raise HTTPException(status_code=400, detail="Se requieren exactamente 5 horarios (lunes a viernes)")
    dias = {h.dia_semana for h in t.horarios}
    if dias != set(range(5)):
        raise HTTPException(status_code=400, detail="Los horarios deben cubrir los días 0 al 4 (lunes a viernes)")

    h_salida = _str_to_time(t.hora_salida)
    # Mantenemos las columnas deprecadas por compatibilidad (no se leen).
    hoy = hoy_bogota()
    horario_lunes = next((h for h in t.horarios if h.dia_semana == 0), None)
    nuevo = models.Turno(
        nombre=t.nombre,
        hora_salida=h_salida,
        hora_entrada=_str_to_time(horario_lunes.hora_entrada) if horario_lunes else None,
        tolerancia_minutos=horario_lunes.tolerancia_minutos if horario_lunes else 10,
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)

    for h in t.horarios:
        db.add(
            models.TurnoHorario(
                turno_id=nuevo.id,
                dia_semana=h.dia_semana,
                hora_entrada=_str_to_time(h.hora_entrada),
                tolerancia_minutos=h.tolerancia_minutos,
                vigente_desde=hoy,
            )
        )
    db.commit()
    db.refresh(nuevo)
    return {
        "id": nuevo.id,
        "nombre": nuevo.nombre,
        "hora_salida": nuevo.hora_salida.strftime("%H:%M") if nuevo.hora_salida else None,
        "horarios_hoy": _horario_vigente_hoy_json(db, nuevo.id),
    }


@app.get("/api/turnos/{turno_id}")
def get_turno(
    turno_id: int,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_empleados")),
):
    """Detalle de un turno con su historial de horarios."""
    obj = db.query(models.Turno).filter(models.Turno.id == turno_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Turno no encontrado.")
    horarios = (
        db.query(models.TurnoHorario)
        .filter(models.TurnoHorario.turno_id == turno_id)
        .order_by(models.TurnoHorario.dia_semana, models.TurnoHorario.vigente_desde.desc())
        .all()
    )
    return {
        "id": obj.id,
        "nombre": obj.nombre,
        "hora_salida": obj.hora_salida.strftime("%H:%M") if obj.hora_salida else None,
        "horarios_hoy": _horario_vigente_hoy_json(db, turno_id),
        "horarios": [
            {
                "id": h.id,
                "dia_semana": h.dia_semana,
                "hora_entrada": h.hora_entrada.strftime("%H:%M"),
                "tolerancia_minutos": h.tolerancia_minutos,
                "vigente_desde": h.vigente_desde.isoformat(),
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in horarios
        ],
    }


@app.put("/api/turnos/{turno_id}")
def update_turno(
    turno_id: int,
    t: TurnoUpdate,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_empleados")),
):
    """Actualiza nombre y hora de salida de un turno (no sus horarios)."""
    obj = db.query(models.Turno).filter(models.Turno.id == turno_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Turno no encontrado.")
    obj.nombre = t.nombre
    obj.hora_salida = _str_to_time(t.hora_salida)
    db.commit()
    db.refresh(obj)
    return {
        "id": obj.id,
        "nombre": obj.nombre,
        "hora_salida": obj.hora_salida.strftime("%H:%M") if obj.hora_salida else None,
        "horarios_hoy": _horario_vigente_hoy_json(db, turno_id),
    }


@app.post("/api/turnos/{turno_id}/horarios", status_code=201)
def add_turno_horario(
    turno_id: int,
    h: TurnoHorarioCreate,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_empleados")),
):
    """Inserta una nueva vigencia de horario para un día de la semana.

    Nunca actualiza una fila existente; siempre inserta una nueva vigencia.
    """
    turno = db.query(models.Turno).filter(models.Turno.id == turno_id).first()
    if not turno:
        raise HTTPException(status_code=404, detail="Turno no encontrado.")
    if not (0 <= h.dia_semana <= 4):
        raise HTTPException(status_code=400, detail="dia_semana debe estar entre 0 (lunes) y 4 (viernes)")

    vigente_desde = date.fromisoformat(h.vigente_desde) if h.vigente_desde else hoy_bogota()
    nuevo_horario = models.TurnoHorario(
        turno_id=turno_id,
        dia_semana=h.dia_semana,
        hora_entrada=_str_to_time(h.hora_entrada),
        tolerancia_minutos=h.tolerancia_minutos,
        vigente_desde=vigente_desde,
    )
    db.add(nuevo_horario)
    db.commit()
    db.refresh(nuevo_horario)
    return {
        "id": nuevo_horario.id,
        "turno_id": nuevo_horario.turno_id,
        "dia_semana": nuevo_horario.dia_semana,
        "hora_entrada": nuevo_horario.hora_entrada.strftime("%H:%M"),
        "tolerancia_minutos": nuevo_horario.tolerancia_minutos,
        "vigente_desde": nuevo_horario.vigente_desde.isoformat(),
    }


@app.delete("/api/turnos/{turno_id}", status_code=204)
def delete_turno(
    turno_id: int,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_empleados")),
):
    obj = db.query(models.Turno).filter(models.Turno.id == turno_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Turno no encontrado.")
    db.delete(obj)
    db.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  FESTIVOS (solo lectura)
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/api/festivos")
def get_festivos_list(
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_correo")),
):
    """Lista de festivos colombianos cargados automáticamente."""
    festivos = db.query(models.Festivo).order_by(models.Festivo.fecha).all()
    return festivos


# ══════════════════════════════════════════════════════════════════════════════
#  REPORTES
# ══════════════════════════════════════════════════════════════════════════════
@app.post("/api/reportes/generar")
def generar_reporte_excel(
    req: ReporteRequest,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("generar_reportes")),
):
    try:
        inicio = date.fromisoformat(req.fecha_inicio)
        fin    = date.fromisoformat(req.fecha_fin)
        excel_bytes = generar_reporte(
            db, inicio, fin,
            employee_ids=req.employee_ids,
            departamentos=req.departamentos,
            modo=req.modo
        )
        filename = f"Asistencia_{inicio.strftime('%Y%m%d')}_{fin.strftime('%Y%m%d')}.xlsx"
        return StreamingResponse(
            io.BytesIO(excel_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando reporte: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN DE CORREO
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/api/config/correo")
def get_config_correo(
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_correo")),
):
    """Retorna la configuración SMTP actual (sin password en claro)."""
    cfg = config_correo_service.get_config_segura(db)
    return cfg or {
        "host": None,
        "puerto": None,
        "usuario": None,
        "remitente_nombre": None,
        "seguridad": "starttls",
        "password_configurado": False,
        "updated_at": None,
        "updated_by": None,
    }


@app.put("/api/config/correo")
def update_config_correo(
    req: ConfigSMTPRequest,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_correo")),
):
    """Crea o actualiza la configuración SMTP. Si password es None o vacío,
    se conserva el password existente.
    """
    try:
        seguridad = config_correo_service.validar_seguridad(req.seguridad)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    password = req.password if req.password else None
    try:
        config_correo_service.upsert_config(
            db,
            host=req.host,
            puerto=req.puerto,
            usuario=req.usuario,
            password=password,
            remitente_nombre=req.remitente_nombre,
            seguridad=seguridad,
            updated_by_id=user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"message": "Configuración de correo actualizada."}


@app.post("/api/config/correo/test")
def test_config_correo(
    req: ConfigSMTPTestRequest,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_correo")),
):
    """Envía un correo de prueba usando la configuración SMTP guardada."""
    import smtplib
    try:
        enviar_correo_prueba_a(req.destinatario)
        return {"message": f"Correo de prueba enviado a {req.destinatario}."}
    except CorreoNoConfiguradoError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except smtplib.SMTPException as e:
        raise HTTPException(status_code=400, detail=f"Error SMTP: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/configuracion/correo")
def get_config_correo_legacy(
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_correo")),
):
    """Retorna la configuración de correo actual (destinatarios y periodicidad)."""
    cfg = config_correo_service.get_config_segura(db)
    return {
        "smtp_host": cfg["host"] if cfg else None,
        "smtp_port": cfg["puerto"] if cfg else None,
        "smtp_user": cfg["usuario"] if cfg else None,
        "destinatarios": config_service.get_recipients(db),
        "periodicidad":  config_service.get_periodicidad(db),
        "configurado":   cfg["password_configurado"] if cfg else False,
    }


@app.get("/api/configuracion/correo/destinatarios")
def get_destinatarios(
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_correo")),
):
    return config_service.get_recipients(db)


@app.post("/api/configuracion/correo/destinatarios")
def add_destinatario(
    req: RecipientCreate,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_correo")),
):
    recipients = config_service.add_recipient(db, req.email)
    return {"destinatarios": recipients}


@app.delete("/api/configuracion/correo/destinatarios/{email}")
def remove_destinatario(
    email: str,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_correo")),
):
    recipients = config_service.remove_recipient(db, email)
    return {"destinatarios": recipients}


@app.post("/api/configuracion/correo/periodicidad")
def set_periodicidad(
    req: PeriodicidadRequest,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_correo")),
):
    config_service.set_periodicidad(db, req.semanal, req.mensual)
    reschedule_report_jobs()
    return {"message": "Periodicidad actualizada y jobs reprogramados.", "periodicidad": config_service.get_periodicidad(db)}


@app.post("/api/configuracion/correo/prueba")
def test_correo_legacy(
    user: models.Usuario = Depends(require_perm("admin_correo")),
):
    """Envía un correo de prueba para verificar la configuración SMTP (legacy)."""
    import smtplib
    try:
        enviar_correo_prueba_a(None)
        return {"message": "Correo de prueba enviado. Revisa la bandeja de entrada de los destinatarios."}
    except CorreoNoConfiguradoError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except smtplib.SMTPException as e:
        raise HTTPException(status_code=400, detail=f"Error SMTP: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
