# Guía de migración a Ubuntu Server — hikvision_asistencia

Esta guía describe paso a paso cómo migrar el sistema de asistencia biométrica
desde el entorno de desarrollo en Windows hacia un servidor **Ubuntu Server**
usando Docker y Docker Compose en producción.

> **Versión del sistema:** `v1.5-ui-historico`
> **Origen del código:** Windows + Docker Desktop local
> **Destino:** Ubuntu Server (misma red local que el biométrico Hikvision)

---

## 1. Requisitos previos en Ubuntu

- Ubuntu Server 22.04 LTS o superior (recomendado).
- Usuario con privilegios `sudo`.
- Conexión a la misma red local donde se encuentra el biométrico Hikvision.
- IP fija asignada al servidor (por DHCP reservado o configuración estática).
- Acceso SSH desde la máquina de desarrollo Windows.
- Puertos libres: `80` (frontend Nginx) y `8000` (backend FastAPI).
- Al menos **4 GB de RAM** y **20 GB de disco** disponibles

---

## 2. Instalación de Docker

Conectarse por SSH al servidor Ubuntu y ejecutar:

```bash
# Actualizar paquetes
sudo apt-get update
sudo apt-get upgrade -y

# Instalar dependencias
sudo apt-get install -y ca-certificates curl gnupg lsb-release

# Agregar la clave oficial de Docker
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Agregar el repositorio
 echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Instalar Docker Engine y Docker Compose plugin
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Verificar instalación
sudo docker --version
sudo docker compose version
```

Opcional: agregar el usuario actual al grupo `docker` para no usar `sudo`:

```bash
sudo usermod -aG docker $USER
newgrp docker
```

---

## 3. Empaquetado del código en Windows

Desde la raíz del proyecto en Windows, generar un `.zip` que **no incluya**
archivos sensibles ni artefactos de desarrollo.

### Opción A: con 7-Zip (recomendada)

Abrir PowerShell en la carpeta del proyecto:

```powershell
7z a -xr'!.git' -xr'!.env' -xr'!__pycache__' -xr'!node_modules' -xr'!pgdata' -xr'!test_evidencia' hikvision_asistencia.zip .
```

### Opción B: con PowerShell nativo

```powershell
$project = "C:\ruta\al\proyecto\hikvision_extractor"
$zip     = "C:\Users\Sistemas\Desktop\hikvision_asistencia.zip"
$exclude = @('.git', '.env', '__pycache__', 'node_modules', 'pgdata', 'test_evidencia')

# Limpiar zip anterior si existe
if (Test-Path $zip) { Remove-Item $zip }

$items = Get-ChildItem -Path $project -Exclude $exclude | Where-Object {
    $_.Name -notin $exclude
}

Compress-Archive -Path $items.FullName -DestinationPath $zip

# Nota: esta opción no elimina carpetas __pycache__ anidadas.
# Se recomienda borrarlas previamente con:
# Get-ChildItem -Path $project -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
```

**Exclusiones obligatorias:**

| Patrón           | Motivo                                              |
| ---------------- | --------------------------------------------------- |
| `.git`           | No se necesita en producción.                       |
| `.env`           | Contiene secretos; se crea nuevo en el servidor.    |
| `__pycache__`    | Artefactos de compilación Python.                   |
| `node_modules`   | Dependencias frontend no necesarias en producción.  |
| `pgdata`         | Datos locales de PostgreSQL; se migran por pg_dump. |
| `test_evidencia` | Logs y scripts de prueba internos.                  |

---

## 4. Exportar base de datos con pg_dump

Si PostgreSQL corre en Docker local en Windows, abrir PowerShell en la carpeta
del proyecto y ejecutar:

```powershell
docker compose exec db pg_dump -U admin -d hikvision > backup_hikvision.sql
```

Si el contenedor se llama `hikvision_db`:

```powershell
docker exec hikvision_db pg_dump -U admin -d hikvision > backup_hikvision.sql
```

> **Importante:** si la tabla `configuracion_correo` contiene una contraseña
> SMTP encriptada, el `FERNET_KEY` de producción debe ser **idéntico** al de
> desarrollo. Si se genera una nueva clave, habrá que reconfigurar el SMTP
> desde el panel Admin después del deploy.

Verificar el tamaño del backup:

```powershell
Get-Item backup_hikvision.sql
```

---

## 5. Transferir con scp

Desde PowerShell en Windows, transferir el código y el backup al servidor
Ubuntu:

```powershell
$server = "usuario@192.168.X.X"
scp hikvision_asistencia.zip ${server}:/opt/
scp backup_hikvision.sql ${server}:/opt/
```

> Sustituir `usuario` e `192.168.X.X` por el usuario SSH y la IP fija del
> servidor Ubuntu.

---

## 6. Descomprimir en Ubuntu

Conectarse por SSH al servidor y descomprimir:

```bash
sudo mkdir -p /opt/hikvision_asistencia
sudo apt-get install -y unzip
sudo unzip -q /opt/hikvision_asistencia.zip -d /opt/hikvision_asistencia

# Verificar estructura
ls -la /opt/hikvision_asistencia
```

Asegurarse de que el propietario permita leer/escribir a Docker:

```bash
sudo chown -R $USER:$USER /opt/hikvision_asistencia
```

---

## 7. Crear `.env` de producción

Copiar el archivo de ejemplo y editarlo con los valores reales:

```bash
cd /opt/hikvision_asistencia
cp .env.example .env
nano .env
```

Variables que **deben** cambiarse obligatoriamente:

| Variable            | Descripción                                                                            |
| ------------------- | -------------------------------------------------------------------------------------- |
| `POSTGRES_PASSWORD` | Contraseña fuerte para PostgreSQL.                                                     |
| `DATABASE_URL`      | Debe usar el servicio `db`: `postgresql://admin:<POSTGRES_PASSWORD>@db:5432/hikvision` |
| `FERNET_KEY`        | **Ver paso obligatorio más abajo.** Clave Fernet para desencriptar la contraseña SMTP. |
| `SECRET_KEY`        | Clave para firmar JWT. Generar una nueva en producción.                                |
| `ADMIN_PASSWORD`    | Contraseña temporal del usuario admin inicial.                                         |
| `DEVICE_IP`         | IP que Ubuntu ve del biométrico Hikvision.                                             |
| `DEVICE_USER`       | Usuario del biométrico.                                                                |
| `DEVICE_PASS`       | Contraseña del biométrico.                                                             |

### Paso obligatorio: decidir `FERNET_KEY` antes de generar nada

La `FERNET_KEY` es la clave maestra que protege la contraseña SMTP guardada en
la tabla `configuracion_correo`. **No generar una nueva automáticamente sin leer
este paso.**

Antes de restaurar el backup, ejecutar en el servidor Ubuntu:

```bash
# Buscar si el backup contiene filas en configuracion_correo
grep -i "configuracion_correo" /opt/backup_hikvision.sql | head -5
```

**Si el backup tiene datos en `configuracion_correo`:**

1. **Obtener el `FERNET_KEY` del `.env` de desarrollo/original.** Es la única
   clave que puede desencriptar el `password_encriptado` migrado.
2. Copiar **exactamente ese valor** en el `.env` de producción.
3. **No regenerar `FERNET_KEY`.** Si se regenera, el password SMTP quedará
   indescifrable silenciosamente; el próximo envío de correo fallará sin un
   mensaje claro durante el deploy.
4. Después del restore, ejecutar obligatoriamente la verificación del paso
   **10.5 Verificar desencriptación de la configuración SMTP**.

**Si el backup NO tiene datos en `configuracion_correo` (tabla vacía o no existe):**

1. Generar una `FERNET_KEY` nueva en el paso 8.
2. Configurar el SMTP desde el panel Admin después del deploy.

> **Regla de oro:** la `FERNET_KEY` de producción debe ser **idéntica** a la
> que encriptó los datos en origen. Si hay duda, copiarla del `.env` original.
> Nunca inventar una nueva sobre datos migrados.

---

## 8. Generar claves

> **Nota obligatoria sobre el nombre del archivo:** `docker-compose.prod.yml`
> tiene `env_file: .env` hardcodeado en los servicios `db` y `backend`. Por
> diseño, **el archivo final debe llamarse exactamente `.env`** en la raíz del
> proyecto. No usar `.env.prod`, `.env.production` ni ningún otro nombre; el
> compose de producción no lo aceptará, incluso si se pasa `--env-file` en la
> CLI (ese flag solo sustituye variables `${...}` en el YAML, no cambia el
> `env_file` declarado en cada servicio).

### `SECRET_KEY` (siempre nuevo en producción)

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Pegar el resultado en `.env`:

```env
SECRET_KEY=<salida_de_secrets_token_urlsafe>
```

### `FERNET_KEY` (solo si el backup NO tiene `configuracion_correo`)

Si el backup tiene datos de correo migrados, **omitir este comando** y usar la
`FERNET_KEY` del `.env` original (paso 7).

Si el backup no tiene datos de correo o se va a configurar SMTP desde cero:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Pegar el resultado en `.env`:

```env
FERNET_KEY=<salida_de_Fernet_generate_key>
```

> La librería `cryptography` debe estar instalada. Si falta:
> `pip3 install cryptography` o usar el contenedor del backend.

---

## 9. Levantar base de datos

Usar siempre `docker-compose.prod.yml`, **nunca** `docker-compose.yml` (que está
preparado para desarrollo con bind mounts y `--reload`).

```bash
cd /opt/hikvision_asistencia
sudo docker compose -f docker-compose.prod.yml up -d db
```

Esperar a que el healthcheck marque `healthy`:

```bash
sudo docker compose -f docker-compose.prod.yml ps
```

---

## 10. Restaurar backup con psql

```bash
cd /opt/hikvision_asistencia
cat /opt/backup_hikvision.sql | sudo docker compose -f docker-compose.prod.yml exec -T db psql -U admin -d hikvision
```

Verificar que las tablas y datos existan:

```bash
sudo docker compose -f docker-compose.prod.yml exec db psql -U admin -d hikvision -c "\dt"
sudo docker compose -f docker-compose.prod.yml exec db psql -U admin -d hikvision -c "SELECT count(*) FROM empleados;"
```

---

## 10.5 Verificar desencriptación de la configuración SMTP (obligatorio si el backup tenía `configuracion_correo`)

Este paso detecta **en el deploy** si la `FERNET_KEY` del `.env` de producción
no coincide con la que encriptó el password SMTP del backup. Es mucho mejor
fallar ahora que descubrir el problema a las 6:00 AM cuando el cron intente
enviar el primer reporte.

### Verificación rápida: ¿hay filas en `configuracion_correo`?

```bash
sudo docker compose -f docker-compose.prod.yml exec db psql -U admin -d hikvision -c "SELECT id, host, puerto, usuario, seguridad, password_encriptado IS NOT NULL as tiene_password FROM configuracion_correo;"
```

**Si la tabla está vacía:** no hay nada que verificar. Continuar con el paso 11.

**Si la tabla tiene datos:** ejecutar el siguiente script de verificación.

### Script de verificación de `FERNET_KEY`

```bash
cd /opt/hikvision_asistencia
sudo docker compose -f docker-compose.prod.yml run --rm backend python - << 'PY'
import os
from backend.database import SessionLocal
from backend import models
from cryptography.fernet import Fernet, InvalidToken

FERNET_KEY = os.getenv("FERNET_KEY")
if not FERNET_KEY:
    print("[ERROR] FERNET_KEY no está definida en el .env.")
    raise SystemExit(1)

db = SessionLocal()
try:
    config = db.query(models.ConfiguracionCorreo).first()
    if not config or not config.password_encriptado:
        print("[OK] No hay configuracion_correo con password encriptado. Nada que verificar.")
        raise SystemExit(0)

    try:
        f = Fernet(FERNET_KEY.encode())
        password = f.decrypt(config.password_encriptado.encode()).decode()
        print(f"[OK] FERNET_KEY coincide. Password desencriptado correctamente para {config.usuario}.")
        print(f"[OK] Longitud del password: {len(password)} caracteres.")
    except InvalidToken:
        print("[ERROR CRITICO] FERNET_KEY no puede desencriptar el password migrado.")
        print("[ERROR CRITICO] Posibles causas:")
        print("  1. Se regeneró FERNET_KEY en lugar de copiar la del .env original.")
        print("  2. El backup se encriptó con otra FERNET_KEY.")
        print("[ERROR CRITICO] Solución: obtener la FERNET_KEY correcta del .env de desarrollo")
        print("                 o borrar la fila de configuracion_correo y reconfigurar SMTP.")
        raise SystemExit(1)
finally:
    db.close()
PY
```

Si el script devuelve `[ERROR CRITICO]`, **no continuar** con el deploy. Resolver
una de estas dos opciones:

1. **Opción recomendada:** obtener la `FERNET_KEY` correcta del `.env` original,
   actualizar el `.env` de producción y volver a ejecutar el script.
2. **Opción alternativa:** borrar la configuración SMTP migrada y reconfigurarla
   desde el panel Admin con la nueva `FERNET_KEY`:
   ```bash
   sudo docker compose -f docker-compose.prod.yml exec db psql -U admin -d hikvision -c "DELETE FROM configuracion_correo;"
   ```

---

## 11. Correr migraciones con alembic upgrade head

Aunque el backend ejecuta migraciones al arrancar, es recomendable correrlas
manualmente antes del primer inicio para detectar errores temprano:

```bash
cd /opt/hikvision_asistencia
sudo docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head
```

---

## 12. Crear/resetear usuario admin

Si el backup ya trae el usuario admin, resetear su contraseña. Si no existe,
crearlo con el rol `Admin`.

Reemplazar `NUEVA_PASSWORD_FUERTE` por la contraseña real:

```bash
cd /opt/hikvision_asistencia
sudo docker compose -f docker-compose.prod.yml run --rm backend python - << 'PY'
import os
os.environ["DATABASE_URL"] = os.getenv("DATABASE_URL")

from backend.database import SessionLocal
from backend.auth import get_password_hash
from backend.models import Usuario, Rol

NUEVA_PASSWORD = "NUEVA_PASSWORD_FUERTE"
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")

db = SessionLocal()
try:
    rol_admin = db.query(Rol).filter(Rol.nombre == "Admin").first()
    if not rol_admin:
        print("ERROR: No existe el rol Admin. Revisa las migraciones.")
        raise SystemExit(1)

    usuario = db.query(Usuario).filter(Usuario.username == ADMIN_USERNAME).first()
    if not usuario:
        usuario = Usuario(
            username=ADMIN_USERNAME,
            password_hash=get_password_hash(NUEVA_PASSWORD),
            rol_id=rol_admin.id,
            activo=True,
            requiere_cambio_password=True,
        )
        db.add(usuario)
        print(f"Usuario {ADMIN_USERNAME} creado.")
    else:
        usuario.password_hash = get_password_hash(NUEVA_PASSWORD)
        usuario.requiere_cambio_password = True
        usuario.activo = True
        print(f"Usuario {ADMIN_USERNAME} actualizado.")

    db.commit()
finally:
    db.close()
PY
```

> El usuario deberá cambiar la contraseña en el primer login.

---

## 13. Build y levantar todo con `docker-compose.prod.yml`

```bash
cd /opt/hikvision_asistencia
sudo docker compose -f docker-compose.prod.yml up -d --build
```

Verificar que los tres contenedores estén `Up` o `healthy`:

```bash
sudo docker compose -f docker-compose.prod.yml ps
sudo docker compose -f docker-compose.prod.yml logs -f backend
```

---

## 14. Verificar con curl y logs

Desde el mismo servidor Ubuntu:

```bash
# Estado general del backend
curl -s http://localhost:8000/api/status | python3 -m json.tool

# Frontend
curl -s -o /dev/null -w "%{http_code}" http://localhost:80
```

Esperar a que el backend termine el lifespan (migraciones, festivos, RBAC,
configuración inicial). Los logs deben mostrar algo similar a:

```text
[MIGRACIONES] Migraciones aplicadas.
[FESTIVOS] Festivos cargados.
[RBAC] Roles y permisos inicializados.
[CONFIG] Configuración por defecto creada.
[SCHEDULER] Scheduler iniciado.
```

---

## 15. Acceder al sistema y configurar SMTP y destinatarios

Abrir en navegador la IP del servidor:

```text
http://192.168.X.X
```

Login inicial:

- **Usuario:** `admin`
- **Contraseña:** la definida en `ADMIN_PASSWORD` / paso 12.

El sistema pedirá cambiar la contraseña en el primer login.

### Configurar SMTP

1. Ir a la pestaña **Admin → Correo**.
2. Completar:
   - Host SMTP (`smtp.gmail.com`, `smtp.office365.com`, servidor propio, etc.)
   - Puerto (`587`, `465`, etc.)
   - Usuario/remitente
   - Contraseña
   - Seguridad (`starttls`, `ssl`, `none`)
3. Guardar.
4. Enviar un correo de prueba.

### Configurar destinatarios

1. En la misma pestaña **Admin → Correo**, agregar destinatarios.
2. Configurar la periodicidad de reportes semanal/mensual.

> Si el `FERNET_KEY` de producción no coincide con el de desarrollo y se
> restauró un backup con `configuracion_correo`, el formulario SMTP mostrará
> valores corruptos. En ese caso, borrar la fila de `configuracion_correo` y
> volver a configurar el SMTP desde cero.

---

## 16. Configurar DNS

### Opción A: DNS interno (recomendado para red corporativa)

Crear un registro tipo A en el servidor DNS interno:

```text
asistencia.redihos.local → 192.168.X.X
```

### Opción B: Archivo hosts (solo pruebas locales)

En cada PC cliente agregar:

```text
192.168.X.X  asistencia.redihos.local
```

Acceso final:

```text
http://asistencia.redihos.local
```

---

## 17. Backup automático con cron

El repositorio incluye `backup.sh`, que genera siempre la misma copia en
`backups/hikvision_latest.sql` y también respalda `.env`. Se recomienda este
script para desarrollo o para mantener una única copia diaria. Si se prefiere
retención de varios días, usar la Opción B más abajo.

### Opción A: usar `backup.sh` del repositorio (misma copia sobrescrita)

Hacer ejecutable el script:

```bash
cd /opt/hikvision_asistencia
chmod +x backup.sh
```

Probar manualmente:

```bash
./backup.sh
ls -lh backups/
```

Configurar cron para ejecutar todos los días a las 2:00 AM:

```bash
sudo crontab -e
```

Agregar la línea:

```cron
0 2 * * * cd /opt/hikvision_asistencia && ./backup.sh >> /opt/hikvision_asistencia/backups/backup.log 2>&1
```

Restauración:

```bash
cd /opt/hikvision_asistencia
cat backups/hikvision_latest.sql | sudo docker compose -f docker-compose.prod.yml exec -T db psql -U admin -d hikvision
cp backups/.env.backup .env
```

### Opción B: script con retención de 30 días

Crear el script de backup:

```bash
sudo tee /opt/backup_hikvision.sh << 'EOF'
#!/bin/bash
set -e

PROJECT_DIR="/opt/hikvision_asistencia"
BACKUP_DIR="/opt/backups/hikvision"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

mkdir -p "$BACKUP_DIR"
cd "$PROJECT_DIR"

# Backup de la base de datos
sudo docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U admin -d hikvision | gzip > "$BACKUP_DIR/backup_hikvision_$TIMESTAMP.sql.gz"

# Backup del archivo .env (contiene secretos; guardar en lugar seguro)
if [ -f .env ]; then
    cp .env "$BACKUP_DIR/env_backup_$TIMESTAMP"
fi

# Rotar backups antiguos
find "$BACKUP_DIR" -name 'backup_hikvision_*.sql.gz' -mtime +$RETENTION_DAYS -delete
find "$BACKUP_DIR" -name 'env_backup_*' -mtime +$RETENTION_DAYS -delete

echo "[$TIMESTAMP] Backup completado: $BACKUP_DIR/backup_hikvision_$TIMESTAMP.sql.gz"
EOF

sudo chmod +x /opt/backup_hikvision.sh
```

Configurar cron:

```bash
sudo crontab -e
```

Agregar:

```cron
0 2 * * * /opt/backup_hikvision.sh >> /var/log/backup_hikvision.log 2>&1
```

Probar manualmente:

```bash
sudo /opt/backup_hikvision.sh
ls -lh /opt/backups/hikvision/
```

---

## 18. Actualizaciones futuras

### Flujo recomendado

1. En Windows, actualizar el código y probar localmente.
2. Generar un nuevo `.zip` siguiendo el paso 3.
3. Subir al servidor:
   ```powershell
   scp hikvision_asistencia.zip usuario@192.168.X.X:/opt/
   ```
4. En Ubuntu, desplegar sin perder datos:
   ```bash
   cd /opt/hikvision_asistencia
   sudo docker compose -f docker-compose.prod.yml down
   sudo rm -rf /opt/hikvision_asistencia
   sudo mkdir -p /opt/hikvision_asistencia
   sudo unzip -q /opt/hikvision_asistencia.zip -d /opt/hikvision_asistencia
   sudo chown -R $USER:$USER /opt/hikvision_asistencia
   cd /opt/hikvision_asistencia
   # Restaurar el .env anterior
   cp /opt/backups/hikvision/env_backup_ULTIMO .env
   sudo docker compose -f docker-compose.prod.yml up -d --build
   ```
5. Verificar logs y estado.

### Script de empaquetado automático en Windows (opcional)

Se puede dejar listo un script `build_deploy.ps1` en el repositorio para
automatizar la generación del `.zip`. No es obligatorio para esta migración,
pero facilita las actualizaciones futuras.

---

## 19. HTTPS con certbot (apartado preparado)

Para exponer el sistema con HTTPS se recomienda usar **Certbot** con Nginx.

### Requisitos

- Tener un dominio público o interno resoluble desde el servidor.
- Puerto `443` accesible.

### Pasos generales

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d asistencia.redihos.local
```

> Si el dominio es interno (`.local`), Certbot con validación HTTP no
> funcionará. En ese caso usar certificado interno de la empresa o una CA
> propia.

### Configuración manual de Nginx (ejemplo)

```nginx
server {
    listen 80;
    server_name asistencia.redihos.local;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl;
    server_name asistencia.redihos.local;

    ssl_certificate /etc/letsencrypt/live/asistencia.redihos.local/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/asistencia.redihos.local/privkey.pem;

    location / {
        proxy_pass http://localhost:80;
    }
}
```

Este apartado queda preparado; la activación depende de la política de red y
DNS de REDIHOS.

---

## 20. Troubleshooting

### El backend no levanta y los logs muestran un error de `DATABASE_URL`

- Verificar que el archivo `.env` exista en `/opt/hikvision_asistencia/.env`.
- Verificar que `DATABASE_URL` use `db` como host:
  `postgresql://admin:<PASSWORD>@db:5432/hikvision`.

### Error de Fernet al leer la configuración SMTP

- Significa que el `FERNET_KEY` actual no coincide con la usada para encriptar
  la contraseña. Borrar la fila de `configuracion_correo` y reconfigurar SMTP.

```bash
sudo docker compose -f docker-compose.prod.yml exec db psql -U admin -d hikvision -c "DELETE FROM configuracion_correo;"
```

### No se pueden enviar correos de prueba

- Revisar host, puerto, seguridad y credenciales.
- Para Gmail u Outlook, usar contraseña de aplicación, no la contraseña normal.
- Verificar que el servidor Ubuntu tenga salida a Internet en el puerto SMTP.

### El frontend muestra error de conexión con el backend

- Verificar que el backend esté healthy:
  `sudo docker compose -f docker-compose.prod.yml ps`
- Revisar logs: `sudo docker compose -f docker-compose.prod.yml logs backend`
- Asegurarse de que el frontend apunte a `http://localhost:8000` o a la URL
  correcta.

### El biométrico no responde desde Ubuntu

- Probar conectividad:
  `curl -v http://<DEVICE_IP>/ISAPI/AccessControl/AcsEvent?format=json`
- Verificar que Ubuntu y el biométrico estén en la misma red.
- Revisar firewall del servidor Ubuntu:
  `sudo ufw status`

### PostgreSQL no acepta conexiones

- En `docker-compose.prod.yml` PostgreSQL no expone el puerto `5432` al host.
- Para diagnosticar, ejecutar psql dentro del contenedor:
  `sudo docker compose -f docker-compose.prod.yml exec db psql -U admin -d hikvision`

### Los jobs programados no corren

- Verificar que el contenedor no haya estado caído en el horario del job
  (`misfire_grace_time=60`).
- Revisar logs del scheduler:
  `sudo docker compose -f docker-compose.prod.yml logs -f backend | grep SCHEDULER`

---

## 21. Checklist de seguridad

Antes de dar por finalizado el deploy, verificar:

- [] El archivo `.env` de desarrollo **no** se transfirió dentro del `.zip`.
- [] `SECRET_KEY` se generó nuevo en producción con `secrets.token_urlsafe(32)`.
- [] `FERNET_KEY` coincide con el backup (si aplica) o se generó nueva y se
      reconfiguró SMTP.
- [ ] `POSTGRES_PASSWORD` es una contraseña fuerte y no la de ejemplo.
- [ ] `ADMIN_PASSWORD` se cambió y se reseteó el usuario admin.
- [ ] PostgreSQL no expone el puerto `5432` al exterior (verificar
      `docker-compose.prod.yml`).
- [ ] No hay bind mounts que expongan código fuente al contenedor en producción.
- [ ] El backend no arranca con `--reload`.
- [ ] Backup automático configurado y probado.
- [ ] Logs revisados sin errores.
- [ ] Primer login con admin funciona y fuerza cambio de contraseña.
- [ ] Correo de prueba enviado exitosamente.
- [ ] DNS configurado y accesible desde las PCs de REDIHOS.
- [ ] Firewall del servidor Ubuntu restringe accesos innecesarios.

---

## Referencias

- `README.md` — documentación general del sistema.
- `handoff_hikvision_asistencia.md` — notas internas de handoff y decisiones de
  arquitectura.
- `.env.example` — variables de entorno documentadas.
