"""
extractor_hikvision.py
Extrae eventos de acceso del biométrico Hikvision vía ISAPI REST.
Adaptado para la Fase 2: Guarda los registros en la base de datos PostgreSQL/SQLite.
"""

import os
import uuid
import threading
import requests
import argparse
from datetime import date, timedelta, datetime
from requests.auth import HTTPDigestAuth
from dotenv import load_dotenv

# Cargar variables de entorno desde .env si existe
load_dotenv()

# Imports de la base de datos
from backend.database import SessionLocal
from backend.models import RegistroAsistencia
from backend.timezone import hoy_bogota
from backend import config_service

# ── Configuración ─────────────────────────────────────────────────────────────
IP     = os.getenv("DEVICE_IP", "192.168.1.127")
USER   = os.getenv("DEVICE_USER", "admin")
PASS   = os.getenv("DEVICE_PASS", "tu_password")
URL    = f"http://{IP}/ISAPI/AccessControl/AcsEvent?format=json"

BATCH_SIZE = 50

# Lock global para serializar TODAS las llamadas al biométrico.
# El hardware soporta 1-2 conexiones concurrentes como mucho; cualquier
# llamada paralela (job programado + manual + script de diagnóstico)
# puede corromper la paginación y hacer perder eventos.
_device_lock = threading.Lock()

EVENT_MAP = {
    (5, 38):   "Fingerprint Recognition Passed",
    (5, 75):   "Face Authentication Passed",
    (5, 104):  "Card Authentication Passed",
    (5, 21):   "Door Locked",
    (5, 22):   "Door Unlocked",
    (5, 39):   "Fingerprint Recognition Failed",
    (5, 76):   "Face Authentication Failed",
    (3, 112):  "NTP Auto Time Synchronization",
    (3, 1029): "Remote: Login",
    (3, 7):    "Remote: Arming",
    (3, 6):    "Remote: Disarming",
}

AUTH_MINORS = {38, 75, 104}

# ── API ───────────────────────────────────────────────────────────────────────
def fetch_range(start_iso, end_iso):
    events, position, total_reported = [], 0, 0
    # searchID único por sesión de búsqueda: reutilizar el mismo ID entre
    # llamadas (incluso entre paginaciones) hace que el dispositivo
    # pise resultados y se pierdan eventos. UUID v4 por llamada.
    search_id = str(uuid.uuid4())
    with _device_lock:
        while True:
            payload = {"AcsEventCond": {
                "searchID": search_id, "searchResultPosition": position,
                "maxResults": BATCH_SIZE, "major": 5, "minor": 0,
                "startTime": start_iso, "endTime": end_iso,
            }}
            try:
                r = requests.post(URL, json=payload,
                                  auth=HTTPDigestAuth(USER, PASS), timeout=15)
                r.raise_for_status()
                data = r.json()
            except requests.exceptions.ConnectionError:
                print(f"  [ERROR] Sin conexion a {IP}")
                break
            except requests.exceptions.HTTPError as e:
                print(f"  [ERROR] HTTP {e.response.status_code}")
                break
            except Exception as e:
                print(f"  [ERROR] {e}")
                break

            batch = data.get("AcsEvent", {}).get("InfoList", [])
            total = data.get("AcsEvent", {}).get("totalMatches", 0)
            if position == 0:
                total_reported = total
            if not batch:
                break
            events.extend(batch)
            if len(events) >= total:
                break
            position += len(batch)

    return events, total_reported


def fetch_day(day):
    ds = day.strftime("%Y-%m-%d")

    def dedup(lst):
        seen, out = set(), []
        for e in lst:
            k = (e.get("major"), e.get("minor"),
                 e.get("time", ""), e.get("employeeNoString", ""))
            if k not in seen:
                seen.add(k)
                out.append(e)
        return out

    full, total = fetch_range(f"{ds}T00:00:00", f"{ds}T23:59:59")
    if len(full) >= total:
        return full, total

    print(f"  [!] {day}: total={total} obtenidos={len(full)} -> dividiendo AM/PM")
    am, am_t = fetch_range(f"{ds}T00:00:00", f"{ds}T11:59:59")
    pm, pm_t = fetch_range(f"{ds}T12:00:00", f"{ds}T23:59:59")

    combined = []
    if len(am) < am_t:
        print(f"  [!] {day} AM truncado -> Q1/Q2")
        q1, _ = fetch_range(f"{ds}T00:00:00", f"{ds}T05:59:59")
        q2, _ = fetch_range(f"{ds}T06:00:00", f"{ds}T11:59:59")
        combined.extend(q1 + q2)
    else:
        combined.extend(am)

    if len(pm) < pm_t:
        print(f"  [!] {day} PM truncado -> Q3/Q4")
        q3, _ = fetch_range(f"{ds}T12:00:00", f"{ds}T17:59:59")
        q4, _ = fetch_range(f"{ds}T18:00:00", f"{ds}T23:59:59")
        combined.extend(q3 + q4)
    else:
        combined.extend(pm)

    return dedup(combined), total


def normalize(e):
    major, minor = int(e.get("major", 0)), int(e.get("minor", 0))
    raw_t = e.get("time", "")
    try:
        dt = datetime.fromisoformat(raw_t)
        event_date = dt.date()
        event_time = dt.time()
    except:
        event_date = None
        event_time = None
        
    return {
        "Event Type":          EVENT_MAP.get((major, minor), f"Event({major},{minor})"),
        "Card Holder":         e.get("name", "")             if minor in AUTH_MINORS else "",
        "Employee ID":         e.get("employeeNoString", "") if minor in AUTH_MINORS else "",
        "Event Date":          event_date,
        "Event Time":          event_time,
        "Raw Time":            raw_t
    }

# ── Base de Datos ─────────────────────────────────────────────────────────────
def save_to_db(db, new_events, include_all=False):
    added = 0
    try:
        for e in new_events:
            nombre = e.get("Card Holder", "").strip()
            # Omitimos eventos sin nombre de empleado si no son deseados
            if not include_all and not nombre:
                continue
                
            fecha = e.get("Event Date")
            hora = e.get("Event Time")
            
            # Chequear si ya existe para no duplicar (usando empleado, fecha, hora)
            existe = db.query(RegistroAsistencia).filter(
                RegistroAsistencia.nombre_empleado == nombre,
                RegistroAsistencia.fecha == fecha,
                RegistroAsistencia.hora == hora
            ).first()
            
            if not existe:
                registro = RegistroAsistencia(
                    empleado_id=e.get("Employee ID"),
                    nombre_empleado=nombre,
                    fecha=fecha,
                    hora=hora,
                    tipo_evento=e.get("Event Type"),
                    evento_raw=e.get("Raw Time")
                )
                db.add(registro)
                added += 1
                
        db.flush() # Guardamos en sesion pero commit final lo hace main()
    except Exception as ex:
        print(f"Error al guardar en BD: {ex}")
        raise ex
    return added

def parse_events(raw_data, day):
    return [normalize(e) for e in raw_data]

# ── Main ──────────────────────────────────────────────────────────────────────
def main(start_str=None, end_str=None, progress_callback=None):
    global IP, USER, PASS, URL
    p = argparse.ArgumentParser(description="Extractor Hikvision ISAPI -> Database")
    p.add_argument("--start",    default=hoy_bogota().strftime("%Y-%m-%d"))
    p.add_argument("--end",      default=hoy_bogota().strftime("%Y-%m-%d"))
    p.add_argument("--ip",       default=IP)
    p.add_argument("--user",     default=USER)
    p.add_argument("--password", default=PASS)
    p.add_argument("--all",      action="store_true",
                   help="Incluir eventos de sistema ademas de personas")
    
    # Parse args only if called from command line
    import sys
    args = p.parse_args() if __name__ == "__main__" else p.parse_args([])

    IP   = args.ip
    USER = args.user
    PASS = args.password
    URL  = f"http://{IP}/ISAPI/AccessControl/AcsEvent?format=json"

    start_date = start_str if start_str else args.start
    end_date = end_str if end_str else args.end

    start = date.fromisoformat(start_date)
    end   = date.fromisoformat(end_date)

    msg_init = f"Modo       : GUARDAR EN BASE DE DATOS\nDesde      : {start}\nHasta      : {end}"
    print(f"{'='*50}\n{msg_init}\n{'='*50}")
    
    if progress_callback:
        progress_callback(f"Conectando al dispositivo para extraer desde {start} hasta {end}...")

    total_eventos = 0
    current = start

    db = SessionLocal()
    try:
        while current <= end:
            msg_day = f"Procesando {current}..."
            print(f"\n{msg_day}")
            if progress_callback:
                progress_callback(msg_day)
                
            raw, total_esperado = fetch_day(current)
            evts  = parse_events(raw, current)
            guardados = save_to_db(db, evts, include_all=args.all)

            total_eventos += guardados
            msg_res = f"  -> {guardados} nuevos registros guardados."
            print(msg_res)
            if progress_callback:
                progress_callback(msg_day + msg_res)

            # Auto-verificación: si el total reportado por el dispositivo
            # es mayor que lo que pudimos descargar (incluso con fallback),
            # persistir una alerta para que el dashboard la muestre.
            if len(raw) < total_esperado:
                config_service.add_alerta_extraccion(
                    db, current, total_esperado, len(raw)
                )
                print(f"  [ALERTA] {current}: esperado={total_esperado}, "
                      f"obtenido={len(raw)} -> alerta guardada")
            else:
                # Si había una alerta previa y ahora se completó, limpiarla
                config_service.clear_alerta_extraccion(db, current)

            current += timedelta(days=1)
            
        db.commit()
    except Exception as e:
        print(f"Error procesando {current}: {e}")
        db.rollback()
        raise e
    finally:
        db.close()

    msg_fin = f"Extracción completada. {total_eventos} nuevos registros."
    print(f"\n{'='*50}\n{msg_fin}\n{'='*50}")
    if progress_callback:
        progress_callback(msg_fin)

if __name__ == "__main__":
    main()
