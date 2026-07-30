# Script de backup automático de Hikvision Asistencia
# Siempre sobrescribe el mismo archivo para mantener solo la última copia.

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackupDir = Join-Path $ProjectDir "backups"
$DbBackup = Join-Path $BackupDir "hikvision_latest.sql"
$EnvBackup = Join-Path $BackupDir ".env.backup"
$LogFile = Join-Path $BackupDir "backup.log"

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

function Log($message) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $message"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

Set-Location -LiteralPath $ProjectDir

Log "Iniciando backup..."

try {
    docker compose exec -T db pg_dump -U admin -d hikvision > $DbBackup
    Log "OK: backup de base de datos guardado en $DbBackup"
} catch {
    Log "ERROR: fallo pg_dump. Verifique que el contenedor 'db' esté corriendo."
    exit 1
}

if (Test-Path "$ProjectDir\.env") {
    Copy-Item "$ProjectDir\.env" $EnvBackup -Force
    Log "OK: backup de .env guardado en $EnvBackup"
} else {
    Log "ADVERTENCIA: no se encontro $ProjectDir\.env"
}

Log "Backup completado."
