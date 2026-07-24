"""
backend/main.py
API principal del Sistema de Asistencia Biométrica REDIHOS.
"""
import io
import os
from contextlib import asynccontextmanager
from datetime import date, time, timedelta
from typing import List, Optional
import threading

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import models
from .database import engine, get_db, SessionLocal
from .scheduler import start_scheduler
from .report_service import generar_reporte, calcular_tardanzas_dia, get_festivos, es_dia_laboral, init_festivos
from .email_service import enviar_correo_prueba
from .sync_empleados import sync_empleados
from .auth import (
    get_current_user, require_perm, get_password_hash, verify_password,
    create_access_token, init_rbac, PERMISOS,
)
from . import config_service
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
                        except Exception as e:
                            print(f"[BACKFILL ERROR] {e}")

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
        extractor_hikvision.main(start_str=start_date, end_str=end_date,
                                  progress_callback=progress_callback)
        extraction_state["progress"] = "Extracción completada."
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

class TurnoCreate(BaseModel):
    nombre:             str
    hora_entrada:       str      # "HH:MM"
    hora_salida:        Optional[str] = None
    tolerancia_minutos: int = 10

class EmpleadoUpdate(BaseModel):
    departamento:       Optional[str] = None
    hora_entrada:       Optional[str] = None      # "HH:MM"
    tolerancia_minutos: Optional[int] = None
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
    return db.query(models.Empleado).order_by(models.Empleado.nombre).all()

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

    obj.departamento       = emp.departamento
    obj.activo             = emp.activo
    obj.tolerancia_minutos = emp.tolerancia_minutos

    if emp.hora_entrada:
        try:
            h, m = emp.hora_entrada.split(":")
            obj.hora_entrada = time(int(h), int(m))
        except ValueError:
            raise HTTPException(status_code=400, detail="hora_entrada debe tener formato HH:MM.")
    else:
        obj.hora_entrada = None

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
#  TURNOS (legacy: ya no se usan en la UI, protegidos por admin_empleados)
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/api/turnos")
def get_turnos(
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_empleados")),
):
    return db.query(models.Turno).all()

@app.post("/api/turnos", status_code=201)
def create_turno(
    t: TurnoCreate,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_empleados")),
):
    h_entrada = time(*[int(x) for x in t.hora_entrada.split(":")])
    h_salida  = time(*[int(x) for x in t.hora_salida.split(":")]) if t.hora_salida else None
    nuevo = models.Turno(
        nombre=t.nombre,
        hora_entrada=h_entrada,
        hora_salida=h_salida,
        tolerancia_minutos=t.tolerancia_minutos
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo

@app.put("/api/turnos/{turno_id}")
def update_turno(
    turno_id: int,
    t: TurnoCreate,
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_empleados")),
):
    obj = db.query(models.Turno).filter(models.Turno.id == turno_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Turno no encontrado.")
    obj.nombre             = t.nombre
    obj.hora_entrada       = time(*[int(x) for x in t.hora_entrada.split(":")])
    obj.hora_salida        = time(*[int(x) for x in t.hora_salida.split(":")]) if t.hora_salida else None
    obj.tolerancia_minutos = t.tolerancia_minutos
    db.commit()
    db.refresh(obj)
    return obj

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
@app.get("/api/configuracion/correo")
def get_config_correo(
    db: Session = Depends(get_db),
    user: models.Usuario = Depends(require_perm("admin_correo")),
):
    """Retorna la configuración de correo actual (destinatarios y periodicidad)."""
    return {
        "smtp_host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "smtp_port": int(os.getenv("SMTP_PORT", "587")),
        "smtp_user": os.getenv("SMTP_USER", ""),
        "destinatarios": config_service.get_recipients(db),
        "periodicidad":  config_service.get_periodicidad(db),
        "configurado":   bool(os.getenv("SMTP_APP_PASSWORD")),
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
def test_correo(
    user: models.Usuario = Depends(require_perm("admin_correo")),
):
    """Envía un correo de prueba para verificar la configuración SMTP."""
    try:
        enviar_correo_prueba()
        return {"message": "Correo de prueba enviado. Revisa la bandeja de entrada de los destinatarios."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
