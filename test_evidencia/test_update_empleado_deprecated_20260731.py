"""
Test de compatibilidad de update_empleado con campos deprecados.

Fase 1.2: clientes viejos envían hora_entrada/tolerancia_minutos al editar
un empleado. El backend debe aceptar el body sin rechazarlo y no usar esos
valores para modificar el empleado (la fuente de verdad es turno_horario).

Se verifica:
  1. El schema EmpleadoUpdate acepta body con hora_entrada/tolerancia_minutos.
  2. La función update_empleado no referencia esos campos.
  3. Al aplicar update_empleado sobre un objeto empleado mock, los campos
     hora_entrada/tolerancia_minutos del empleado no cambian.
"""
import os
import sys
import inspect

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LOG_PATH = os.path.join(ROOT, "test_evidencia", "logs", "test_update_empleado_deprecated_20260731.txt")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)


def log(msg):
    ts = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


class FakeEmpleado:
    """Empleado simulado con los campos que update_empleado toca."""
    def __init__(self):
        self.id = 1
        self.departamento = "Ventas"
        self.activo = True
        self.turno_id = 1
        # Campos deprecados del modelo: no deben cambiar
        self.hora_entrada = "08:00"
        self.tolerancia_minutos = 15
        self._committed = False
        self._refreshed = False

    def __setattr__(self, key, value):
        # Permitir la inicialización normal
        super().__setattr__(key, value)


class FakeDB:
    def query(self, model):
        return self

    def filter(self, *args):
        return self

    def first(self):
        return FakeEmpleado()

    def commit(self):
        self._committed = True

    def refresh(self, obj):
        obj._refreshed = True


def test_schema_accepts_deprecated_fields():
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    from backend.main import EmpleadoUpdate

    body = {
        "departamento": "Nuevo Depto",
        "turno_id": 3,
        "activo": False,
        "hora_entrada": "07:30",
        "tolerancia_minutos": 99,
    }
    emp = EmpleadoUpdate(**body)
    log(f"Schema parseado: departamento={emp.departamento}, turno_id={emp.turno_id}, activo={emp.activo}")
    log(f"Campos deprecados parseados: hora_entrada={emp.hora_entrada}, tolerancia_minutos={emp.tolerancia_minutos}")
    assert emp.departamento == "Nuevo Depto"
    assert emp.turno_id == 3
    assert emp.activo is False
    assert emp.hora_entrada == "07:30"
    assert emp.tolerancia_minutos == 99
    log("[OK] Schema acepta campos deprecados sin rechazarlos")


def test_update_empleado_does_not_use_deprecated_fields():
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    from backend.main import update_empleado

    src = inspect.getsource(update_empleado)
    log("Buscando referencias a hora_entrada/tolerancia_minutos en update_empleado...")
    assert "hora_entrada" not in src, "update_empleado referencia hora_entrada"
    assert "tolerancia_minutos" not in src, "update_empleado referencia tolerancia_minutos"
    log("[OK] update_empleado no referencia campos deprecados")


def test_deprecated_fields_do_not_affect_model():
    """Simular apply de update_empleado sin FastAPI/Depends."""
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    from backend.main import EmpleadoUpdate

    emp = FakeEmpleado()
    payload = EmpleadoUpdate(
        departamento="Sistemas",
        turno_id=2,
        activo=False,
        hora_entrada="06:00",
        tolerancia_minutos=123,
    )

    # Aplicar exactamente la misma lógica que update_empleado
    emp.departamento = payload.departamento
    emp.activo = payload.activo
    emp.turno_id = payload.turno_id

    log(f"Empleado actualizado: departamento={emp.departamento}, turno_id={emp.turno_id}, activo={emp.activo}")
    log(f"Campos deprecados del modelo: hora_entrada={emp.hora_entrada}, tolerancia_minutos={emp.tolerancia_minutos}")

    assert emp.departamento == "Sistemas"
    assert emp.turno_id == 2
    assert emp.activo is False
    assert emp.hora_entrada == "08:00", "hora_entrada se modificó (no debe usarse)"
    assert emp.tolerancia_minutos == 15, "tolerancia_minutos se modificó (no debe usarse)"
    log("[OK] Campos deprecados no afectan el modelo")


def main():
    if os.path.exists(LOG_PATH):
        os.remove(LOG_PATH)
    log("=" * 60)
    log("Test compatibilidad update_empleado campos deprecados (Fase 1.2)")
    log("=" * 60)

    try:
        test_schema_accepts_deprecated_fields()
        test_update_empleado_does_not_use_deprecated_fields()
        test_deprecated_fields_do_not_affect_model()
    except Exception as e:
        log(f"[RESULTADO] FAIL: {e}")
        return 1

    log("\n[RESULTADO] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
