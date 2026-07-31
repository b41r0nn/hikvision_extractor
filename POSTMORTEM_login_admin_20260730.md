# Post-mortem: Fallo de login del usuario admin

**Fecha:** 30 de julio de 2026
**Sistema:** hikvision_extractor — Sistema de Asistencia Biométrica REDIHOS
**Componente afectado:** Autenticación (`backend/auth.py`, tabla `usuarios` en PostgreSQL)
**Severidad:** Alta — acceso bloqueado al panel de administración
**Estado:** Resuelto

---

## 1. Resumen ejecutivo

El usuario `admin` no podía iniciar sesión en el frontend (`localhost:3000`). El backend respondía `401 Unauthorized` con el mensaje `"Usuario o contraseña incorrectos"` para todas las contraseñas probadas.

Tras investigar se determinó que el hash de contraseña almacenado en la tabla `usuarios` de PostgreSQL **no correspondía a ninguna contraseña conocida**, y el campo `requiere_cambio_password` estaba en `False`. El sistema fue recuperado reseteando la contraseña del admin directamente en la base de datos, dejando `requiere_cambio_password = True` para que el usuario la cambie al siguiente login.

---

## 2. Síntomas observados

- Frontend mostraba `"Usuario o contraseña incorrectos"` al intentar login.
- `curl` directo al endpoint `POST /api/auth/login` también devolvía `401 Unauthorized`.
- El backend Docker estaba corriendo y respondía correctamente (`server: uvicorn`).
- La conexión a PostgreSQL funcionaba; el usuario `admin` existía y estaba activo (`activo = True`).
- Ninguna de las contraseñas probadas coincidía con el hash almacenado:
  - `admin123`
  - `tu_password_real`
  - `DevPass2026!`
  - Contraseña anterior presunta del `.env`

---

## 3. Cronología del incidente

### 3.1. Antecedente inmediato (perdida del `.env`)

Durante el día 30 de julio de 2026 se perdió el archivo `.env` original del proyecto. Se regeneró uno temporal. Esto ocasionó:

- Pérdida de variables de configuración, incluyendo posiblemente `ADMIN_PASSWORD`.
- Confusión sobre cuál era la contraseña real del usuario administrador.
- Los datos de PostgreSQL (tabla `empleados`, 71 registros) no se perdieron, pero los turnos y horarios (`turnos`, `turno_horario`) quedaron en 0, lo que evidenció que la operación de regeneración del entorno afectó más que solo el `.env`.

### 3.2. Intentos de recuperación del login

Se intentó resetear la contraseña del admin ejecutando scripts de Python dentro del contenedor `backend`. En uno de los intentos el script reportó éxito (`OK: contraseña reseteada a admin123`), pero posteriormente:

- El login seguía fallando con `401`.
- El campo `requiere_cambio_password` del usuario `admin` quedó en `False`.
- El hash almacenado no verificaba correctamente contra `admin123` ni ninguna otra contraseña conocida.

Esto indica que **alguno de los intentos de reset no persistió realmente en la base de datos** o fue sobrescrito por otro proceso (ver sección 4.3).

### 3.3. Diagnóstico final

Se ejecutó un script de verificación dentro del contenedor `backend` con `PYTHONPATH=/app`:

```python
from backend.database import SessionLocal
from backend.auth import verify_password
from backend.models import Usuario

db = SessionLocal()
u = db.query(Usuario).filter(Usuario.username == 'admin').first()
print('activo:', u.activo)
print('requiere_cambio_password:', u.requiere_cambio_password)
print('verify admin123:', verify_password('admin123', u.password_hash))
print('verify tu_password_real:', verify_password('tu_password_real', u.password_hash))
print('verify DevPass2026!:', verify_password('DevPass2026!', u.password_hash))
db.close()
```

Resultado:

```text
username: admin
activo: True
requiere_cambio_password: False
password_hash: $argon2id$v=19$m=65536,t=3,p=4$odRai9F6T0kJIaRUSmn ...
verify admin123: False
verify tu_password_real: False
verify DevPass2026!: False
```

### 3.4. Resolución

Se ejecutó un reset definitivo dentro del contenedor `backend`:

```bash
docker compose exec backend bash -c "PYTHONPATH=/app python -c \"
from backend.database import SessionLocal
from backend.auth import get_password_hash
from backend.models import Usuario

db = SessionLocal()
u = db.query(Usuario).filter(Usuario.username == 'admin').first()
u.password_hash = get_password_hash('admin123')
u.requiere_cambio_password = True
db.commit()
print('OK: contrasena reseteada a admin123')
db.close()
\""
```

Verificación:

```text
requiere_cambio_password: True
verify admin123: True
```

Login exitoso:

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
```

```json
{
  "access_token": "...",
  "token_type": "bearer",
  "username": "admin",
  "rol": "Admin",
  "permisos": [...],
  "requiere_cambio_password": true
}
```

---

## 4. Análisis técnico

### 4.1. Cómo funciona el login

El endpoint `POST /api/auth/login` en `backend/main.py`:

```python
@app.post("/api/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.Usuario).filter(
        models.Usuario.username == req.username
    ).first()
    if not user or not verify_password(req.password, user.password_hash) or not user.activo:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    ...
```

La contraseña se almacena como hash Argon2id mediante `passlib`. No existe fallback, ni comparación en texto plano. Si el hash no coincide, la única respuesta posible es `401`.

### 4.2. Confusión entre `.env` y base de datos

La función `init_rbac()` en `backend/auth.py` crea el usuario admin **solo si no existe**:

```python
admin_user = db.query(models.Usuario).filter(
    models.Usuario.username == os.getenv("ADMIN_USERNAME", "admin")
).first()
if not admin_user:
    db.add(
        models.Usuario(
            username=os.getenv("ADMIN_USERNAME", "admin"),
            password_hash=get_password_hash(
                os.getenv("ADMIN_PASSWORD", "admin")
            ),
            ...
        )
    )
    db.commit()
```

Esto significa que **cambiar `ADMIN_PASSWORD` en el `.env` y reiniciar el backend no actualiza la contraseña de un usuario admin existente**. La contraseña real vive en la tabla `usuarios`, no en el `.env`.

### 4.3. Por qué persistía el problema

Se identificaron al menos dos factores que dificultaron el diagnóstico y la solución:

1. **Backend fantasma en el puerto 8000**: en el entorno había otro proceso `uvicorn` (o posiblemente otra instancia del backend) respondiendo en `localhost:8000`. Esto hizo que algunas pruebas de `curl` devolvieran `401` incluso cuando el backend Docker estaba detenido. Finalmente, después de reiniciar el equipo, se descartó este factor y se confirmó que el 401 venía del backend Docker correcto.

2. **Estado inconsistente del campo `requiere_cambio_password`**: el campo pasó de `True` a `False` sin un registro claro. Posibles causas:
   - El usuario inició sesión exitosamente en algún momento y cambió la contraseña, lo cual setea `requiere_cambio_password = False`.
   - Un reset parcial sobrescribió el campo sin actualizar correctamente el hash.
   - Al perderse el `.env` y regenerarse, el frontend o backend quedaron en un estado confuso que no permitió completar el flujo de cambio de contraseña.

### 4.4. Root cause

El hash de contraseña del usuario `admin` en PostgreSQL no correspondía a ninguna contraseña conocida por el equipo. La causa raíz más probable es:

> **El usuario `admin` fue creado originalmente con una contraseña (`ADMIN_PASSWORD`) que se perdió al perderse el `.env` original. Como `init_rbac` no actualiza usuarios existentes, cambiar el `.env` posteriormente no restauró el acceso. La contraseña real quedó irrecuperable en el hash Argon2id.**

---

## 5. Lecciones aprendidas

1. **La contraseña del admin no se recupera desde `.env` si el usuario ya existe.** Hay que resetearla directamente en la base de datos.
2. **Perder el `.env` es un incidente crítico.** Contiene `SECRET_KEY`, `FERNET_KEY`, `ADMIN_PASSWORD`, credenciales del biométrico y de PostgreSQL. El backup diario de `.env` (implementado el 30 de julio) es esencial.
3. **Un backend fantasma en el puerto 8000 puede desviar el diagnóstico.** Verificar siempre el proceso que realmente escucha en el puerto.
4. **El campo `requiere_cambio_password` es parte del estado del usuario.** No se puede asumir que un reset de contraseña también lo deja en `True`; hay que setearlo explícitamente.

---

## 6. Acciones correctivas

| Acción | Estado | Responsable |
|--------|--------|-------------|
| Resetear contraseña admin y forzar cambio en próximo login | ✅ Completado | Sistemas / OpenCode |
| Verificar que el backup diario de `.env` y BD funcione | ✅ Configurado | Sistemas |
| Documentar que cambiar `ADMIN_PASSWORD` en `.env` no resetea usuarios existentes | ✅ En este documento | OpenCode |
| Considerar agregar un endpoint admin para resetear contraseña de usuarios | ⏳ Pendiente | Arquitecto |
| Implementar alerta si `admin` no puede iniciar sesión o si hay backups fallidos | ⏳ Pendiente | Arquitecto |

---

## 7. Comandos de referencia para futuros incidentes

### Verificar estado del admin

```bash
docker compose exec backend bash -c "PYTHONPATH=/app python -c \"
from backend.database import SessionLocal
from backend.models import Usuario

db = SessionLocal()
u = db.query(Usuario).filter(Usuario.username == 'admin').first()
print('activo:', u.activo)
print('requiere_cambio_password:', u.requiere_cambio_password)
print('username:', u.username)
db.close()
\""
```

### Resetear contraseña del admin

```bash
docker compose exec backend bash -c "PYTHONPATH=/app python -c \"
from backend.database import SessionLocal
from backend.auth import get_password_hash
from backend.models import Usuario

db = SessionLocal()
u = db.query(Usuario).filter(Usuario.username == 'admin').first()
u.password_hash = get_password_hash('admin123')
u.requiere_cambio_password = True
db.commit()
print('OK')
db.close()
\""
```

### Verificar backend real en el puerto 8000

```bash
docker compose stop backend
curl -v http://localhost:8000/api/status
# Si responde, hay otro backend. Identificar y detener.
docker compose start backend
```

---

## 8. Conclusión

El incidente fue causado por la pérdida de la contraseña real del admin en la base de datos, combinada con la confusión habitual de que el `.env` controla el acceso. El `.env` solo crea el usuario la primera vez; después el acceso depende del hash en PostgreSQL. El sistema quedó recuperado con una contraseña temporal y forzado el cambio en el próximo login.

Se recomienda al usuario finalizar el flujo de cambio de contraseña desde el frontend y guardar la nueva contraseña de forma segura.
