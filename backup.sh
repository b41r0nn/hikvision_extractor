#!/usr/bin/env bash
set -euo pipefail

# Script de backup automático de Hikvision Asistencia
# Siempre sobrescribe el mismo archivo para mantener solo la última copia.
# Ruta secundaria fija fuera de OneDrive. Se hace hardcode a propósito;
# cuando el deploy real a Ubuntu defina el backup permanente, se hará configurable.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$PROJECT_DIR/backups"
EXTERNAL_BACKUP_DIR="$HOME/backups_redihos"

DB_BACKUP="$BACKUP_DIR/hikvision_latest.sql"
ENV_BACKUP="$BACKUP_DIR/.env.backup"
LOG_FILE="$BACKUP_DIR/backup.log"

EXTERNAL_DB_BACKUP="$EXTERNAL_BACKUP_DIR/hikvision_latest.sql"
EXTERNAL_ENV_BACKUP="$EXTERNAL_BACKUP_DIR/.env.backup"
EXTERNAL_LOG_FILE="$EXTERNAL_BACKUP_DIR/backup.log"

mkdir -p "$BACKUP_DIR"
mkdir -p "$EXTERNAL_BACKUP_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

cd "$PROJECT_DIR"

# Verificar que Docker esté disponible
if ! command -v docker >/dev/null 2>&1; then
    log "ERROR: docker no está instalado o no está en el PATH"
    exit 1
fi

log "Iniciando backup..."

if docker compose exec -T db pg_dump -U admin -d hikvision > "$DB_BACKUP"; then
    if [ ! -s "$DB_BACKUP" ]; then
        log "ERROR: el backup de base de datos está vacío"
        exit 1
    fi
    log "OK: backup de base de datos guardado en $DB_BACKUP"
else
    log "ERROR: falló pg_dump. Verifique que el contenedor 'db' esté corriendo."
    exit 1
fi

if [ -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env" "$ENV_BACKUP"
    log "OK: backup de .env guardado en $ENV_BACKUP"
else
    log "ADVERTENCIA: no se encontró $PROJECT_DIR/.env"
fi

# Copia secundaria fuera de OneDrive
if cp "$DB_BACKUP" "$EXTERNAL_DB_BACKUP"; then
    log "OK: copia externa de base de datos guardada en $EXTERNAL_DB_BACKUP"
else
    log "ERROR: no se pudo copiar la base de datos a $EXTERNAL_DB_BACKUP"
fi

if [ -f "$ENV_BACKUP" ]; then
    cp "$ENV_BACKUP" "$EXTERNAL_ENV_BACKUP"
    log "OK: copia externa de .env guardada en $EXTERNAL_ENV_BACKUP"
else
    log "ADVERTENCIA: no se encontró $ENV_BACKUP para copia externa"
fi

# También copiamos el log local acumulado al finalizar
if [ -f "$LOG_FILE" ]; then
    cp "$LOG_FILE" "$EXTERNAL_LOG_FILE"
    log "OK: copia externa del log guardada en $EXTERNAL_LOG_FILE"
fi

log "Backup completado."
