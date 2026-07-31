"""
Test de movimiento de artefactos legacy.

Fase 1.3: los archivos hikvision.db, eventos.csv, eventos_hikvision.csv e
Informe_Asistencia12.xlsx se mueven a legacy/ sin borrarlos. Se verifica que
ningún código de producción los referencia y que la documentación/scripts
apuntan a la nueva ubicación.
"""
import os
import sys
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LOG_PATH = os.path.join(ROOT, "test_evidencia", "logs", "test_legacy_artifacts_20260731.txt")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

LEGACY_FILES = [
    "hikvision.db",
    "eventos.csv",
    "eventos_hikvision.csv",
    "Informe_Asistencia12.xlsx",
]


def log(msg):
    ts = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def files_moved_to_legacy():
    for name in LEGACY_FILES:
        path = os.path.join(ROOT, "legacy", name)
        exists = os.path.exists(path)
        log(f"legacy/{name} existe: {exists}")
        assert exists, f"{name} no se encontró en legacy/"
    log("[OK] Todos los artefactos están en legacy/")


def no_files_in_root():
    for name in LEGACY_FILES:
        path = os.path.join(ROOT, name)
        exists = os.path.exists(path)
        log(f"{name} en raíz: {exists}")
        assert not exists, f"{name} sigue en la raíz"
    log("[OK] Ningún artefacto quedó en la raíz")


def no_code_references():
    pattern = re.compile(r"hikvision\.db|eventos\.csv|eventos_hikvision\.csv|Informe_Asistencia12\.xlsx")
    bad_refs = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        # Saltar directorios que no son código de producción
        rel = os.path.relpath(dirpath, ROOT)
        if rel.startswith(("legacy", ".venv", "test_evidencia", "__pycache__", ".git")):
            continue
        for fn in filenames:
            if not fn.endswith((".py", ".md", ".txt", ".sh", ".ps1", ".yml", ".yaml", ".json")):
                continue
            full = os.path.join(dirpath, fn)
            try:
                with open(full, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        if pattern.search(line):
                            # Las referencias que ya apuntan a legacy/ son esperadas
                            # (script de migración y documentación).
                            if "legacy/" not in line:
                                bad_refs.append(f"{os.path.relpath(full, ROOT)}:{i}: {line.strip()}")
            except Exception:
                pass

    log(f"Referencias encontradas fuera de legacy/.venv/test_evidencia: {len(bad_refs)}")
    for ref in bad_refs:
        log(f"  - {ref}")
    assert not bad_refs, "Hay referencias a artefactos legacy fuera de carpetas permitidas"
    log("[OK] Ningún código de producción referencia los artefactos legacy")


def migrate_csv_default_updated():
    path = os.path.join(ROOT, "migrate_csv.py")
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    assert 'legacy/eventos.csv' in src, "migrate_csv.py no apunta a legacy/eventos.csv por defecto"
    log("[OK] migrate_csv.py default apunta a legacy/eventos.csv")


def readme_updated():
    path = os.path.join(ROOT, "README.md")
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    assert "legacy/eventos.csv" in src, "README.md no refleja la ruta legacy/eventos.csv"
    log("[OK] README.md refleja la ruta legacy/eventos.csv")


def legacy_readme_exists():
    path = os.path.join(ROOT, "legacy", "README.md")
    assert os.path.exists(path), "Falta legacy/README.md"
    log("[OK] legacy/README.md existe")


def main():
    if os.path.exists(LOG_PATH):
        os.remove(LOG_PATH)
    log("=" * 60)
    log("Test artefactos legacy (Fase 1.3)")
    log("=" * 60)

    try:
        files_moved_to_legacy()
        no_files_in_root()
        no_code_references()
        migrate_csv_default_updated()
        readme_updated()
        legacy_readme_exists()
    except Exception as e:
        log(f"[RESULTADO] FAIL: {e}")
        return 1

    log("\n[RESULTADO] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
