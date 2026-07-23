"""
email_service.py
Envío de reportes de asistencia por correo SMTP (Gmail con contraseña de aplicación).
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from datetime import date, timedelta
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from .database import SessionLocal
from .report_service import generar_reporte
from .config_service import get_recipients
from .timezone import hoy_bogota

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_APP_PASSWORD", "")


def _enviar_correo(asunto: str, cuerpo: str, adjunto_bytes: bytes, nombre_adjunto: str):
    """Envía un correo con un archivo Excel adjunto."""
    if not SMTP_USER or not SMTP_PASS:
        print("[EMAIL] Credenciales SMTP no configuradas en .env — correo NO enviado.")
        return

    db = SessionLocal()
    try:
        recipients = get_recipients(db)
    finally:
        db.close()

    if not recipients:
        print("[EMAIL] Sin destinatarios configurados.")
        return

    msg = MIMEMultipart()
    msg["From"]    = SMTP_USER
    msg["To"]      = ", ".join(recipients)
    msg["Subject"] = asunto

    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))

    if adjunto_bytes:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(adjunto_bytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{nombre_adjunto}"')
        msg.attach(part)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, recipients, msg.as_bytes())
        print(f"[EMAIL] Correo enviado exitosamente a: {', '.join(recipients)}")
    except Exception as e:
        print(f"[EMAIL ERROR] No se pudo enviar el correo: {e}")


def enviar_reporte_semanal():
    """Genera y envía el reporte de la semana laboral pasada (L-V)."""
    hoy   = hoy_bogota()
    # Buscar el lunes de la semana anterior
    lunes_pasado = hoy - timedelta(days=hoy.weekday() + 7)
    viernes_pasado = lunes_pasado + timedelta(days=4)

    db: Session = SessionLocal()
    try:
        excel_bytes = generar_reporte(db, lunes_pasado, viernes_pasado)
        nombre = f"Asistencia_Semanal_{lunes_pasado.strftime('%Y%m%d')}_{viernes_pasado.strftime('%Y%m%d')}.xlsx"
        asunto = f"Informe Semanal de Asistencia — {lunes_pasado.strftime('%d/%m')} al {viernes_pasado.strftime('%d/%m/%Y')}"
        cuerpo = (
            f"Adjunto encontrará el informe semanal de asistencia de REDIHOS S.A.S.\n\n"
            f"Período: {lunes_pasado.strftime('%d/%m/%Y')} al {viernes_pasado.strftime('%d/%m/%Y')}\n\n"
            f"Este correo fue generado automáticamente por el Sistema de Asistencia Biométrica."
        )
        _enviar_correo(asunto, cuerpo, excel_bytes, nombre)
    except Exception as e:
        print(f"[EMAIL] Error generando reporte semanal: {e}")
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
        excel_bytes = generar_reporte(db, primer_dia_mes_ant, ultimo_dia_mes_ant)
        nombre = f"Asistencia_Mensual_{primer_dia_mes_ant.strftime('%Y%m')}.xlsx"
        asunto = f"Informe Mensual de Asistencia — {primer_dia_mes_ant.strftime('%B %Y').upper()}"
        cuerpo = (
            f"Adjunto encontrará el informe mensual de asistencia de REDIHOS S.A.S.\n\n"
            f"Período: {primer_dia_mes_ant.strftime('%d/%m/%Y')} al {ultimo_dia_mes_ant.strftime('%d/%m/%Y')}\n\n"
            f"Este correo fue generado automáticamente por el Sistema de Asistencia Biométrica."
        )
        _enviar_correo(asunto, cuerpo, excel_bytes, nombre)
    except Exception as e:
        print(f"[EMAIL] Error generando reporte mensual: {e}")
    finally:
        db.close()


def enviar_alerta_llegadas_tarde():
    """Mantener compatibilidad — por ahora no hace nada."""
    pass


def enviar_correo_prueba():
    """Envía un correo de prueba para verificar configuración SMTP."""
    _enviar_correo(
        asunto="Prueba de configuración — Sistema REDIHOS",
        cuerpo="Este es un correo de prueba del Sistema de Asistencia Biométrica REDIHOS.\nSi ves este mensaje, la configuración SMTP es correcta.",
        adjunto_bytes=b"",
        nombre_adjunto="prueba.txt"
    )
