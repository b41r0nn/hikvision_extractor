"""
sync_empleados.py
Sincroniza la tabla Empleado con las personas enroladas en el biométrico
Hikvision vía ISAPI /ISAPI/AccessControl/UserInfo/Search.
Nunca elimina empleados existentes; solo crea o actualiza nombres.
"""
from datetime import datetime
from typing import Callable, List, Optional

import requests
from requests.auth import HTTPDigestAuth
from sqlalchemy.orm import Session

from .models import Empleado
from .device_lock import device_lock
from .device_config import (
    DEVICE_IP as IP,
    DEVICE_USER as USER,
    DEVICE_PASS as PASS,
    USER_INFO_URL as URL,
)

BATCH_SIZE = 1000


def _fetch_user_info_page(
    session: requests.Session,
    position: int,
    max_results: int,
) -> tuple:
    """Consulta una página del endpoint UserInfo."""
    payload = {
        "UserInfoSearchCond": {
            "searchID": "1",
            "searchResultPosition": position,
            "maxResults": max_results,
        }
    }
    try:
        with device_lock:
            r = session.post(
                URL,
                json=payload,
                auth=HTTPDigestAuth(USER, PASS),
                timeout=15,
            )
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Error consultando {URL}: {e}")

    search = data.get("UserInfoSearch", {})
    users  = search.get("UserInfo", []) or []
    total  = int(search.get("totalMatches", 0) or 0)
    num    = int(search.get("numOfMatches", len(users)) or len(users))
    return users, total, num


def fetch_all_user_info(
    progress_callback: Optional[Callable[[str], None]] = None,
) -> List[dict]:
    """Descarga todas las personas enroladas en el dispositivo."""
    session = requests.Session()
    all_users: List[dict] = []
    position = 0
    total = None

    while True:
        users, total_reported, _ = _fetch_user_info_page(
            session, position, BATCH_SIZE
        )
        if total is None:
            total = total_reported

        all_users.extend(users)

        if progress_callback:
            progress_callback(
                f"Descargando empleados del dispositivo: {len(all_users)}/{total}"
            )

        if not users:
            break
        position += len(users)

    return all_users


def sync_empleados(
    db: Session,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    Sincroniza empleados desde el biométrico.
    - Si el employee_id ya existe, actualiza el nombre.
    - Si no existe, lo crea como activo=True, sin turno ni departamento.
    - NUNCA elimina empleados.
    """
    users = fetch_all_user_info(progress_callback)
    creados = 0
    actualizados = 0

    for u in users:
        emp_no = str(u.get("employeeNo", "")).strip()
        nombre = str(u.get("name", "")).strip()

        if not emp_no or not nombre:
            continue

        existing = (
            db.query(Empleado)
            .filter(Empleado.employee_id == emp_no)
            .first()
        )

        if existing:
            if existing.nombre != nombre:
                existing.nombre = nombre
                actualizados += 1
        else:
            db.add(
                Empleado(
                    employee_id=emp_no,
                    nombre=nombre,
                    departamento=None,
                    turno_id=None,
                    activo=True,
                )
            )
            creados += 1

    db.commit()
    return {
        "total_en_dispositivo": len(users),
        "creados": creados,
        "actualizados": actualizados,
    }
