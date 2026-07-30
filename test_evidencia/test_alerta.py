"""
test_evidencia/test_alerta.py
Verifica el flujo completo de la alerta extraccion_incompleta_dias:
  1. Inserta una alerta simulada (esperado=132, obtenido=120) para 2026-07-23.
  2. Llama a /api/status con JWT de admin.
  3. Confirma que alerta_extraccion_incompleta=true y la lista trae la alerta.
  4. Verifica que el banner #extraccion-incompleta-alerta esta referenciado en
     el JS y existe en el HTML.
"""
import os
import json
import sys
from datetime import date, datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB_PATH = os.path.abspath(os.path.join(ROOT, "test_evidencia", "evidencia.db"))
API_URL = os.getenv("API_URL", "http://127.0.0.1:18002")

os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"

from backend.database import SessionLocal
from backend import config_service

# 1. Insertar alerta
db = SessionLocal()
try:
    config_service.add_alerta_extraccion(db, date(2026, 7, 23),
                                         esperado=132, obtenido=120)
    alertas = config_service.get_alertas_extraccion(db)
    print(f"[ALERTA INSERTADA] {json.dumps(alertas, ensure_ascii=False)}")
finally:
    db.close()

# 2. Login + /api/status via HTTP
import urllib.request
import urllib.error

req = urllib.request.Request(
    f"{API_URL}/api/auth/login",
    data=json.dumps({"username": "admin", "password": "Ingreso2026*"}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req) as r:
    login = json.loads(r.read())
token = login["access_token"]
print(f"[LOGIN] user={login['username']} rol={login['rol']} "
      f"permisos={len(login['permisos'])}")

req = urllib.request.Request(
    f"{API_URL}/api/status",
    headers={"Authorization": f"Bearer {token}"},
)
with urllib.request.urlopen(req) as r:
    status = json.loads(r.read())
print(f"[STATUS] {json.dumps(status, indent=2, ensure_ascii=False)}")

assert status["alerta_extraccion_incompleta"] is True, \
    "FALLO: alerta_extraccion_incompleta no es true"
assert isinstance(status["extraccion_incompleta"], list) and \
       len(status["extraccion_incompleta"]) >= 1, \
    "FALLO: extraccion_incompleta no contiene alertas"
a = status["extraccion_incompleta"][0]
assert a["fecha"] == "2026-07-23" and a["esperado"] == 132 and a["obtenido"] == 120, \
    f"FALLO: alerta no coincide: {a}"
print("[OK] /api/status expone la alerta correctamente")

# 3. Verificacion estatica del banner en frontend
html_path = os.path.join(ROOT, "frontend", "index.html")
js_path   = os.path.join(ROOT, "frontend", "app.js")
with open(html_path, encoding="utf-8") as f:
    html = f.read()
with open(js_path, encoding="utf-8") as f:
    js = f.read()
assert 'id="extraccion-incompleta-alerta"' in html, \
    "FALLO: <div id='extraccion-incompleta-alerta'> no esta en index.html"
assert "extraccion-incompleta-alerta" in js, \
    "FALLO: app.js no referencia el banner"
assert "alerta_extraccion_incompleta" in js, \
    "FALLO: app.js no consulta alerta_extraccion_incompleta"
print("[OK] Banner #extraccion-incompleta-alerta existe en HTML y JS")

print("\n[RESULTADO] test_alerta: PASS")
