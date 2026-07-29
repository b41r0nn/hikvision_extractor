"""
email_service.py
Envío de reportes de asistencia por correo SMTP.
La configuración SMTP se lee desde la tabla configuracion_correo (encriptada).
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from datetime import date, timedelta
from sqlalchemy.orm import Session

from .database import SessionLocal
from .report_service import generar_reporte
from .config_service import get_recipients
from .config_correo_service import get_config_desencriptada
from .timezone import hoy_bogota


class CorreoNoConfiguradoError(Exception):
    """Se lanza cuando no hay configuración de correo en la base de datos."""


def _get_config_o_error(db: Session):
    cfg = get_config_desencriptada(db)
    if not cfg:
        raise CorreoNoConfiguradoError(
            "Correo no configurado. Configurá el SMTP desde el panel Admin."
        )
    return cfg


def _enviar_correo_raw(
    cfg: dict,
    asunto: str,
    cuerpo: str,
    adjunto_bytes: bytes,
    nombre_adjunto: str,
    destinatarios: list,
):
    """Envía un correo usando la configuración desencriptada."""
    remitente_nombre = cfg.get("remitente_nombre") or cfg["usuario"]
    remitente = cfg["usuario"]

    msg = MIMEMultipart()
    msg["From"]    = f"{remitente_nombre} <{remitente}>"
    msg["To"]      = ", ".join(destinatarios)
    msg["Subject"] = asunto
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))

    if adjunto_bytes:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(adjunto_bytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{nombre_adjunto}"')
        msg.attach(part)

    seguridad = cfg.get("seguridad", "starttls")

    if seguridad == "ssl":
        with smtplib.SMTP_SSL(cfg["host"], cfg["puerto"], timeout=30) as server:
            server.login(cfg["usuario"], cfg["password"])
            server.sendmail(remitente, destinatarios, msg.as_bytes())
    else:
        with smtplib.SMTP(cfg["host"], cfg["puerto"], timeout=30) as server:
            if seguridad == "starttls":
                server.ehlo()
                server.starttls()
                server.ehlo()
            server.login(cfg["usuario"], cfg["password"])
            server.sendmail(remitente, destinatarios, msg.as_bytes())


def _enviar_correo(asunto: str, cuerpo: str, adjunto_bytes: bytes, nombre_adjunto: str):
    """Envía un correo con un archivo Excel adjunto a los destinatarios configurados."""
    db = SessionLocal()
    try:
        cfg = _get_config_o_error(db)
        recipients = get_recipients(db)
        if not recipients:
            print("[EMAIL] Sin destinatarios configurados.")
            return
        _enviar_correo_raw(cfg, asunto, cuerpo, adjunto_bytes, nombre_adjunto, recipients)
        print(f"[EMAIL] Correo enviado exitosamente a: {', '.join(recipients)}")
    except CorreoNoConfiguradoError as e:
        print(f"[EMAIL ERROR] {e}")
    except smtplib.SMTPException as e:
        print(f"[EMAIL ERROR] Error SMTP: {e}")
    except Exception as e:
        print(f"[EMAIL ERROR] No se pudo enviar el correo: {e}")
    finally:
        db.close()


def enviar_reporte_semanal():
    """Genera y envía el reporte de la semana laboral pasada (L-V)."""
    hoy   = hoy_bogota()
    lunes_pasado = hoy - timedelta(days=hoy.weekday() + 7)
    viernes_pasado = lunes_pasado + timedelta(days=4)

    db: Session = SessionLocal()
    try:
        cfg = _get_config_o_error(db)
        recipients = get_recipients(db)
        if not recipients:
            print("[EMAIL] Sin destinatarios configurados.")
            return
        excel_bytes = generar_reporte(db, lunes_pasado, viernes_pasado)
        nombre = f"Asistencia_Semanal_{lunes_pasado.strftime('%Y%m%d')}_{viernes_pasado.strftime('%Y%m%d')}.xlsx"
        asunto = f"Informe Semanal de Asistencia — {lunes_pasado.strftime('%d/%m')} al {viernes_pasado.strftime('%d/%m/%Y')}"
        cuerpo = (
            f"Adjunto encontrará el informe semanal de asistencia de REDIHOS S.A.S.\n\n"
            f"Período: {lunes_pasado.strftime('%d/%m/%Y')} al {viernes_pasado.strftime('%d/%m/%Y')}\n\n"
            f"Este correo fue generado automáticamente por el Sistema de Asistencia Biométrica."
        )
        _enviar_correo_raw(cfg, asunto, cuerpo, excel_bytes, nombre, recipients)
        print(f"[EMAIL] Correo semanal enviado exitosamente a: {', '.join(recipients)}")
    except CorreoNoConfiguradoError as e:
        print(f"[EMAIL ERROR] {e}")
    except Exception as e:
        print(f"[EMAIL] Error generando/enviando reporte semanal: {e}")
    finally:
        db.close()


def enviar_reporte_mensual():
    """Genera y envía el reporte del mes anterior completo."""
    hoy = hoy_bogota()
    primer_dia_mes_actual = hoy.replace(day=1)
    ultimo_dia_mes_ant    = primer_dia_mes_actual - timedelta(days=1)
    primer_dia_mes_ant    = ultimo_dia_mes_ant.replace(day=1)

    db: Session = SessionLocal()
    try:
        cfg = _get_config_o_error(db)
        recipients = get_recipients(db)
        if not recipients:
            print("[EMAIL] Sin destinatarios configurados.")
            return
        excel_bytes = generar_reporte(db, primer_dia_mes_ant, ultimo_dia_mes_ant)
        nombre = f"Asistencia_Mensual_{primer_dia_mes_ant.strftime('%Y%m')}.xlsx"
        asunto = f"Informe Mensual de Asistencia — {primer_dia_mes_ant.strftime('%B %Y').upper()}"
        cuerpo = (
            f"Adjunto encontrará el informe mensual de asistencia de REDIHOS S.A.S.\n\n"
            f"Período: {primer_dia_mes_ant.strftime('%d/%m/%Y')} al {ultimo_dia_mes_ant.strftime('%d/%m/%Y')}\n\n"
            f"Este correo fue generado automáticamente por el Sistema de Asistencia Biométrica."
        )
        _enviar_correo_raw(cfg, asunto, cuerpo, excel_bytes, nombre, recipients)
        print(f"[EMAIL] Correo mensual enviado exitosamente a: {', '.join(recipients)}")
    except CorreoNoConfiguradoError as e:
        print(f"[EMAIL ERROR] {e}")
    except Exception as e:
        print(f"[EMAIL] Error generando/enviando reporte mensual: {e}")
    finally:
        db.close()


def enviar_alerta_llegadas_tarde():
    """Mantener compatibilidad — por ahora no hace nada."""
    pass


def enviar_correo_prueba_a(destinatario: str):
    """Envía un correo de prueba a una dirección específica."""
    db = SessionLocal()
    try:
        cfg = _get_config_o_error(db)
        asunto = "Prueba de configuración — Sistema REDIHOS"
        cuerpo = (
            "Este es un correo de prueba del Sistema de Asistencia Biométrica REDIHOS.\n"
            "Si ves este mensaje, la configuración SMTP es correcta."
        )
        _enviar_correo_raw(cfg, asunto, cuerpo, b"", "prueba.txt", [destinatario])
    finally:
        db.close()


def enviar_correo_prueba():
    """Envía un correo de prueba a los destinatarios configurados (legacy)."""
    db = SessionLocal()
    try:
        cfg = _get_config_o_error(db)
        recipients = get_recipients(db)
        if not recipients:
            raise CorreoNoConfiguradoError("No hay destinatarios configurados para el correo de prueba.")
        enviar_correo_prueba_a(recipients[0])
    finally:
        db.close()
