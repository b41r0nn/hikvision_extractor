#!/usr/bin/env bash
set -euo pipefail

# Script de backup automático de Hikvision Asistencia
# Siempre sobrescribe el mismo archivo para mantener solo la última copia.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$PROJECT_DIR/backups"
DB_BACKUP="$BACKUP_DIR/hikvision_latest.sql"
ENV_BACKUP="$BACKUP_DIR/.env.backup"
LOG_FILE="$BACKUP_DIR/backup.log"

mkdir -p "$BACKUP_DIR"

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

log "Backup completado."
