# Script de backup automático de Hikvision Asistencia
# Siempre sobrescribe el mismo archivo para mantener solo la última copia.
# Ruta secundaria fija fuera de OneDrive. Se hace hardcode a propósito;
# cuando el deploy real a Ubuntu defina el backup permanente, se hará configurable.

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackupDir = Join-Path $ProjectDir "backups"
$ExternalBackupDir = "C:\BackupsRedihos"

$DbBackup = Join-Path $BackupDir "hikvision_latest.sql"
$EnvBackup = Join-Path $BackupDir ".env.backup"
$LogFile = Join-Path $BackupDir "backup.log"

$ExternalDbBackup = Join-Path $ExternalBackupDir "hikvision_latest.sql"
$ExternalEnvBackup = Join-Path $ExternalBackupDir ".env.backup"
$ExternalLogFile = Join-Path $ExternalBackupDir "backup.log"

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
New-Item -ItemType Directory -Force -Path $ExternalBackupDir | Out-Null

function Log($message) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $message"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

Set-Location -LiteralPath $ProjectDir

Log "Iniciando backup..."

try {
    docker compose exec -T db pg_dump -U admin -d hikvision > $DbBackup
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Log "ERROR: pg_dump fallo con codigo $exitCode. Verifique que el contenedor 'db' este corriendo."
        exit 1
    }
    if ((Get-Item $DbBackup).Length -eq 0) {
        Log "ERROR: el backup de base de datos esta vacio."
        exit 1
    }
    Log "OK: backup de base de datos guardado en $DbBackup"
} catch {
    Log "ERROR: fallo pg_dump. Verifique que el contenedor 'db' este corriendo."
    exit 1
}

if (Test-Path "$ProjectDir\.env") {
    Copy-Item "$ProjectDir\.env" $EnvBackup -Force
    Log "OK: backup de .env guardado en $EnvBackup"
} else {
    Log "ADVERTENCIA: no se encontro $ProjectDir\.env"
}

# Copia secundaria fuera de OneDrive
try {
    Copy-Item $DbBackup $ExternalDbBackup -Force
    Log "OK: copia externa de base de datos guardada en $ExternalDbBackup"
} catch {
    Log "ERROR: no se pudo copiar la base de datos a $ExternalDbBackup"
}

if (Test-Path $EnvBackup) {
    Copy-Item $EnvBackup $ExternalEnvBackup -Force
    Log "OK: copia externa de .env guardada en $ExternalEnvBackup"
} else {
    Log "ADVERTENCIA: no se encontro $EnvBackup para copia externa"
}

# También copiamos el log local acumulado al finalizar
if (Test-Path $LogFile) {
    Copy-Item $LogFile $ExternalLogFile -Force
    Log "OK: copia externa del log guardada en $ExternalLogFile"
}

Log "Backup completado."
