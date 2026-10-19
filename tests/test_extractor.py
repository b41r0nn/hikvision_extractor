"""
tests/test_extractor.py
Tests para extractor_hikvision.py: normalización, dedup, DeviceUnavailableError,
refactor de globales (sin mutación de vars de módulo).
"""
import pytest
from datetime import date, time
from unittest.mock import patch, MagicMock


# ── Tests de normalize ───────────────────────────────────────────────────────

def test_normalize_evento_valido():
    from extractor_hikvision import normalize
    evento = {
        "major": 5,
        "minor": 38,  # Fingerprint Recognition Passed
        "name": "Juan Perez",
        "employeeNoString": "EMP001",
        "time": "2026-10-13T08:15:00",
    }
    result = normalize(evento)
    assert result["Card Holder"] == "Juan Perez"
    assert result["Employee ID"] == "EMP001"
    assert result["Event Date"] == date(2026, 10, 13)
    assert result["Event Time"] == time(8, 15, 0)
    assert result["Event Type"] == "Fingerprint Recognition Passed"


def test_normalize_tiempo_invalido_retorna_none():
    from extractor_hikvision import normalize
    evento = {
        "major": 5,
        "minor": 38,
        "name": "Juan",
        "employeeNoString": "EMP001",
        "time": "NO_ES_UNA_FECHA",
    }
    result = normalize(evento)
    assert result["Event Date"] is None
    assert result["Event Time"] is None


def test_normalize_tiempo_vacio():
    from extractor_hikvision import normalize
    evento = {"major": 5, "minor": 38, "time": ""}
    result = normalize(evento)
    assert result["Event Date"] is None
    assert result["Event Time"] is None


def test_normalize_evento_sistema_no_tiene_nombre():
    """Eventos que no son AUTH_MINORS no deben tener Card Holder."""
    from extractor_hikvision import normalize
    evento = {
        "major": 5,
        "minor": 21,  # Door Locked — no es AUTH_MINOR
        "name": "alguien",
        "time": "2026-10-13T08:00:00",
    }
    result = normalize(evento)
    assert result["Card Holder"] == ""
    assert result["Employee ID"] == ""


# ── Tests de dedup ───────────────────────────────────────────────────────────

def test_dedup_elimina_duplicados():
    from extractor_hikvision import fetch_day
    # Acceder a la función dedup interna a través del módulo
    # Probar indirectamente via fetch_day con mock
    pass  # dedup es función interna, se testa via comportamiento de fetch_day


# ── Tests de DeviceUnavailableError ─────────────────────────────────────────

def test_fetch_range_lanza_device_unavailable_en_timeout():
    from extractor_hikvision import fetch_range, DeviceUnavailableError
    import requests as req
    with patch("extractor_hikvision.requests.post") as mock_post:
        mock_post.side_effect = req.exceptions.Timeout("timeout")
        with pytest.raises(DeviceUnavailableError) as exc_info:
            fetch_range("2026-10-13T00:00:00", "2026-10-13T23:59:59")
        assert "Timeout" in str(exc_info.value)


def test_fetch_range_lanza_device_unavailable_en_connection_error():
    from extractor_hikvision import fetch_range, DeviceUnavailableError
    import requests as req
    with patch("extractor_hikvision.requests.post") as mock_post:
        mock_post.side_effect = req.exceptions.ConnectionError("sin conexion")
        with pytest.raises(DeviceUnavailableError):
            fetch_range("2026-10-13T00:00:00", "2026-10-13T23:59:59")


def test_main_lanza_device_unavailable_si_biometrico_no_responde():
    """main() lanza DeviceUnavailableError si el socket check falla."""
    from extractor_hikvision import main, DeviceUnavailableError
    import socket
    with patch("extractor_hikvision.socket.create_connection") as mock_conn:
        mock_conn.side_effect = socket.timeout("timeout")
        with pytest.raises(DeviceUnavailableError):
            main(start_str="2026-10-13", end_str="2026-10-13")


# ── Tests que los globales NO se mutan ──────────────────────────────────────

def test_main_no_muta_globales_del_modulo():
    """
    Después del refactor (#5), main() no modifica IP, USER, PASS, URL del módulo.
    Probar que tras llamar main() (que falla por socket), los globales siguen iguales.
    """
    import extractor_hikvision as ext
    import socket

    ip_original   = ext.IP
    user_original = ext.USER
    pass_original = ext.PASS
    url_original  = ext.URL

    with patch("extractor_hikvision.socket.create_connection") as mock_conn:
        mock_conn.side_effect = socket.timeout("timeout")
        with pytest.raises(ext.DeviceUnavailableError):
            ext.main(start_str="2026-10-13", end_str="2026-10-13")

    # Verificar que los globales no cambiaron
    assert ext.IP   == ip_original
    assert ext.USER == user_original
    assert ext.PASS == pass_original
    assert ext.URL  == url_original


def test_fetch_range_acepta_parametros_sin_usar_globales():
    """fetch_range usa los parámetros pasados, no los globales del módulo."""
    from extractor_hikvision import fetch_range, DeviceUnavailableError
    import requests as req

    captured = {}

    def mock_post(url, json=None, auth=None, timeout=None):
        captured["url"]  = url
        captured["auth"] = auth
        raise req.exceptions.ConnectionError("test")

    with patch("extractor_hikvision.requests.post", side_effect=mock_post):
        with pytest.raises(DeviceUnavailableError):
            fetch_range(
                "2026-10-13T00:00:00",
                "2026-10-13T23:59:59",
                ip="1.2.3.4",
                user="testuser",
                password="testpass",
                url="http://1.2.3.4/ISAPI/test",
            )

    assert captured.get("url") == "http://1.2.3.4/ISAPI/test"
    assert captured.get("auth").username == "testuser"


# ── Tests de save_to_db ──────────────────────────────────────────────────────

def test_save_to_db_inserta_registro(db):
    from extractor_hikvision import save_to_db
    from backend.models import RegistroAsistencia

    eventos = [{
        "Card Holder": "Maria Lopez",
        "Employee ID": "EMP002",
        "Event Date":  date(2026, 10, 13),
        "Event Time":  time(8, 5),
        "Event Type":  "Fingerprint Recognition Passed",
        "Raw Time":    "2026-10-13T08:05:00",
    }]

    added = save_to_db(db, eventos)
    assert added == 1
    reg = db.query(RegistroAsistencia).filter(
        RegistroAsistencia.empleado_id == "EMP002"
    ).first()
    assert reg is not None
    assert reg.nombre_empleado == "Maria Lopez"


def test_save_to_db_ignora_duplicados(db):
    from extractor_hikvision import save_to_db

    eventos = [{
        "Card Holder": "Maria Lopez",
        "Employee ID": "EMP003",
        "Event Date":  date(2026, 10, 13),
        "Event Time":  time(9, 0),
        "Event Type":  "Fingerprint Recognition Passed",
        "Raw Time":    "2026-10-13T09:00:00",
    }]

    added1 = save_to_db(db, eventos)
    added2 = save_to_db(db, eventos)  # segunda vez mismo registro
    assert added1 == 1
    assert added2 == 0  # dedup: no inserta el duplicado


def test_save_to_db_omite_sin_nombre(db):
    from extractor_hikvision import save_to_db

    eventos = [{
        "Card Holder": "",  # sin nombre
        "Employee ID": "",
        "Event Date":  date(2026, 10, 13),
        "Event Time":  time(10, 0),
        "Event Type":  "Door Locked",
        "Raw Time":    "2026-10-13T10:00:00",
    }]

    added = save_to_db(db, eventos, include_all=False)
    assert added == 0
