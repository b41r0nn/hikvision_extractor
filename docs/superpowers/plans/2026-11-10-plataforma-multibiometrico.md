# Plan de implementación — Plataforma multi-biométrico

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Despegar el extractor de asistencia de un único biométrico Hikvision fijado en el código, para que acepte varios aparatos de varias marcas, dados de alta desde Administración, en una o varias sedes.

**Architecture:** Núcleo intacto (turnos, tardanzas, fusión, informes, correo) detrás de un contrato de adaptador serializable, con un adaptador por marca. La configuración del aparato pasa de constantes de módulo a filas cifradas en base de datos. La identidad de la persona deja de resolverse por igualdad de cadenas y pasa a credenciales por dispositivo.

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy · Alembic · PostgreSQL · pytest · Docker Compose · HTML/JS con Tailwind por CDN.

**Spec:** `docs/superpowers/specs/2026-11-10-plataforma-multibiometrico-design.md`

**Base:** `hikvision_extractor` en el tag `v1.6.3-docs` (commit `6bc67a7`).

---

## Alcance de este plan

El diseño describe **varios subsistemas independientes**. Escribirlos todos al nivel de tarea produciría un documento más largo que el código que describe, y las decisiones de los subsistemas tardíos dependen de respuestas que aún no existen (alojamiento, presupuesto, fecha del préstamo de equipos).

Por eso este documento tiene **dos niveles**:

- **Hito 1 — «REDIHOS sobre el producto nuevo, en modo local»** (fases 0 a 4 del diseño): detallado hasta el paso, con TDD. Es lo que se construye ahora.
- **Hitos 2 a 4** (fases 5 a 11): detallados a nivel de fase con objetivo, alcance, tareas, entregables, criterios de aceptación y riesgos — que es lo que se pidió — y cada uno recibirá su propio plan de tareas cuando le toque.

**Por qué este orden.** El Hikvision de REDIHOS es el único biométrico real disponible para verificar. El modo local es un modo de producto soportado y es donde REDIHOS ya está. Ordenando así, cada fase deja un sistema que funciona de verdad contra hardware real, en vez de piezas a medias esperando a que exista la nube.

---

## Orquestación: qué modelo ejecuta cada tarea

Ejecución **por subagentes**, con el modelo elegido según la complejidad de la tarea. Política fijada por el usuario.

| Nivel | Modelo y esfuerzo | Cuándo |
| --- | --- | --- |
| **Alta** | `fable` · medium | Diseño de arquitectura, refactor amplio, migración de datos irreversible, depuración no trivial, razonamiento de varios pasos |
| **Media** | `sonnet` · medium–high | Trabajo que sigue un patrón ya existente en el código, pero con riesgo si se hace mal |
| **Básica** | `haiku` · low | Búsquedas, lecturas, renombrados, formateo, andamiaje mecánico |

El **revisor de cada tarea va al mismo nivel que la tarea**: una revisión de la Tarea 7 con un modelo barato no detectaría un fallo sutil en el cálculo de tardanzas, que es justo lo que esa revisión existe para encontrar.

### Clasificación de las 17 tareas

| # | Tarea | Nivel | Modelo | Por qué |
| --- | --- | --- | --- | --- |
| 1 | Repositorio nuevo | Básica | `haiku` low | Comandos git mecánicos, cero criterio |
| 2 | Caracterización | **Alta** | `fable` medium | Decidir *qué* fijar es criterio puro. Mal elegido, el refactor pasa con pruebas que no protegen nada |
| 3 | Sede y Catálogo | Media | `sonnet` medium | Modelos declarativos siguiendo el patrón de `models.py` |
| 4 | Dispositivo cifrado | Media | `sonnet` high | Toca secretos; la prueba de no filtración es sutil |
| 5 | `dispositivo_id` + migración | **Alta** | `fable` medium | Paso de datos sobre base real; un error no se deshace |
| 6 | `EmpleadoCredencial` | **Alta** | `fable` medium | Migración de identidad; el histórico depende de ella |
| 7 | Resolución en el núcleo | **Alta** | `fable` medium | El cambio más delicado del plan: `report_service` y tardanzas |
| 8 | Unicidad por serie | **Alta** | `fable` medium | Varios pasos sobre restricciones y `nulls_not_distinct` |
| 9 | `sync_empleados` y reconciliación | Media | `sonnet` high | Reutiliza una pantalla existente |
| 10 | Contrato de adaptador | **Alta** | `fable` medium | Arquitectura. Si falla, se rehace el hito entero |
| 11 | Adaptador Hikvision | **Alta** | `fable` medium | Refactor amplio, con la caracterización como única red |
| 12 | API de sedes y dispositivos | Media | `sonnet` medium | CRUD siguiendo el patrón de `main.py` |
| 13 | Prueba de conexión | Media | `sonnet` high | Riesgo de filtrar la credencial en el diagnóstico |
| 14 | Pantallas de Administración | Media | `sonnet` medium | Sigue el patrón de pestañas ya existente |
| 15 | Orquestación multi-dispositivo | **Alta** | `fable` medium | Aislamiento de fallos, varios caminos de error |
| 16 | Fusión por dispositivo | **Alta** | `fable` medium | Regla sutil: equivocarse **destruye marcas de salida** |
| 17 | Zona horaria y reloj | **Alta** | `fable` medium | Razonamiento temporal, históricamente propenso a error |

**Reparto real: 10 altas, 6 medias, 1 básica.** Este plan es casi todo núcleo; el nivel barato apenas interviene. Forzar tareas de núcleo al nivel barato para ahorrar sería ahorro falso: el coste de un informe de asistencia equivocado con datos reales de nómina supera con mucho la diferencia.

## Global Constraints

Requisitos del proyecto entero. Los de cada tarea los incluyen implícitamente.

- **Español** en código, comentarios, interfaz y mensajes de commit.
- **Sin atribución a Claude ni Anthropic** en commits ni en pull requests.
- **Los 56 tests heredados pasan siempre.** Ninguna tarea se da por cerrada con la suite roja.
- **Nunca se almacenan plantillas biométricas.** Solo marcaciones: código del empleado, instante y tipo.
- **Los adaptadores son de solo lectura frente al aparato.** No enrolan, no modifican, no borran. Única excepción: responder a `/iclock/getrequest` en ZKTeco.
- **Las credenciales de dispositivo nunca aparecen** en claro en base de datos, logs, informes de diagnóstico, respuestas de API ni `.env`.
- Pila existente: Python 3.12, FastAPI, SQLAlchemy, Alembic, PostgreSQL. **Sin reescritura.**
- Migraciones **siempre con paso de datos**: ninguna instalación existente pierde registros.

## Review Focus

Cinco modos de fallo que el diseño implica y que un usuario encontrará. Cada uno tiene su prueba en la tarea que posee el código.

1. **Reloj del aparato desajustado** — una marca con hora desviada cae en el día equivocado sin que nada falle. Esperado: se registra y se avisa, no se calcula en silencio. → Tarea 17.
2. **Código de empleado desconocido** — un aparato informa un código sin credencial asociada. Esperado: la marcación **se guarda igual**, sin empleado, visible para reconciliar. Nunca se descarta. → Tarea 7.
3. **Dispositivo borrado y vuelto a crear** — la reextracción no debe duplicar el histórico. Esperado: la unicidad aguanta porque se ancla al número de serie. → Tarea 8.
4. **Un aparato caído dentro de un lote** — con N dispositivos, uno apagado. Esperado: los demás se extraen, el fallo se reporta, el lote termina. → Tarea 15.
5. **Contraseña del dispositivo filtrada** — por serialización del modelo, por el informe de diagnóstico o por un log. Esperado: no aparece nunca. → Tareas 4 y 13.

---

# HITO 1 — REDIHOS sobre el producto nuevo, en modo local

## Estructura de archivos

| Archivo | Responsabilidad |
| --- | --- |
| `backend/models.py` | *(modificar)* `Sede`, `Dispositivo`, `EmpleadoCredencial`, `CatalogoModelo`; `dispositivo_id` en `RegistroAsistencia` |
| `backend/adaptadores/__init__.py` | *(crear)* Registro de adaptadores por tipo |
| `backend/adaptadores/base.py` | *(crear)* Contrato: `Marcacion`, `Capacidades`, `ResultadoPrueba`, `AdaptadorBase` |
| `backend/adaptadores/hikvision.py` | *(crear)* Adaptador ISAPI, movido desde `extractor_hikvision.py` |
| `backend/dispositivo_service.py` | *(crear)* Alta, edición, baja y prueba de conexión |
| `backend/identidad_service.py` | *(crear)* Resolución de credencial a empleado |
| `backend/device_config.py` | *(borrar)* Constantes de módulo que fijan un solo aparato |
| `backend/main.py` | *(modificar)* Endpoints de sedes y dispositivos |
| `frontend/index.html` | *(modificar)* Pestañas de Sedes y Dispositivos en Administración |
| `frontend/app.js` | *(modificar)* Lógica de esas pantallas |
| `alembic/versions/` | *(crear)* Tres migraciones con paso de datos |

---

## Fase 0 — Repositorio nuevo y red de seguridad

**Objetivo:** Tener el proyecto separado y una red que avise si el refactor rompe el comportamiento actual.
**Alcance:** No cambia ninguna funcionalidad. Solo copia el proyecto y fija lo que hoy hace.
**Dependencias:** Ninguna.
**Riesgos:** El nombre del producto está sin decidir (pregunta abierta 1). Se usa un nombre provisional y se renombra el repositorio después, que en GitHub es barato.

### Tarea 1: Repositorio nuevo con la suite heredada en verde

**Files:**
- Create: repositorio nuevo desde `v1.6.3-docs`
- Modify: `README.md` (título y versión de partida)

**Interfaces:**
- Produces: un árbol idéntico al de `v1.6.3-docs` con historia propia.

- [ ] **Step 1: Crear el repositorio desde el tag**

```bash
git clone --branch v1.6.3-docs <origen> plataforma-asistencia
cd plataforma-asistencia && rm -rf .git && git init && git add -A
```

- [ ] **Step 2: Ejecutar la suite heredada**

Run: `python -m pytest tests/ -q`
Expected: `56 passed`

- [ ] **Step 3: Commit inicial**

```bash
git commit -m "chore: punto de partida desde hikvision_extractor v1.6.3-docs"
```

### Tarea 2: Pruebas de caracterización del extractor Hikvision

Fijan lo que el extractor hace **hoy**, para que el refactor de la Tarea 13 no pueda cambiarlo sin que se note.

**Files:**
- Create: `tests/test_caracterizacion_hikvision.py`
- Create: `tests/fixtures/isapi_respuesta.json` (respuesta ISAPI real, anonimizada)

**Interfaces:**
- Consumes: `extractor_hikvision.normalize(e)`, `parse_events(raw_data, day)`, `save_to_db(db, new_events, include_all=False)`.
- Produces: pruebas que las tareas 13 y 18 deben seguir pasando **sin modificarlas**.

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_normalize_conserva_mapeo_de_eventos(respuesta_isapi):
    # AUTH_MINORS = {38, 75, 104} y EVENT_MAP tal como están hoy
    assert normalize(evento_minor_38)["tipo_evento"] == <valor actual>

def test_parse_events_filtra_eventos_de_sistema(respuesta_isapi): ...
def test_save_to_db_descarta_sin_nombre_salvo_include_all(db): ...
def test_save_to_db_ignora_duplicados_por_restriccion(db): ...
```

- [ ] **Step 2: Ejecutar y comprobar que fallan**

Run: `python -m pytest tests/test_caracterizacion_hikvision.py -v`
Expected: FAIL — falta el fixture

- [ ] **Step 3: Grabar el fixture desde el Hikvision real de REDIHOS**

Capturar una respuesta de `ACS_EVENT_URL`, sustituir nombres y documentos por valores inventados, conservar la forma exacta.

- [ ] **Step 4: Ejecutar y comprobar que pasan**

Run: `python -m pytest tests/test_caracterizacion_hikvision.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_caracterizacion_hikvision.py tests/fixtures/isapi_respuesta.json
git commit -m "test: caracterizar el comportamiento actual del extractor Hikvision"
```

**Aceptación de la Fase 0:** 56 tests heredados + las de caracterización pasan en el repositorio nuevo. REDIHOS sigue intacto y sin tocar.

---

## Fase 1 — Sedes y dispositivos

**Objetivo:** Que la configuración del aparato viva en base de datos, cifrada, en vez de en constantes de módulo.
**Alcance:** Solo estructura. **No se toca la identidad del empleado** — eso es la Fase 1b.
**Dependencias:** Fase 0.
**Riesgos:** Ninguno relevante; es aditivo.

### Tarea 3: Modelos `Sede` y `CatalogoModelo`

**Files:**
- Modify: `backend/models.py`
- Create: `alembic/versions/<hash>_agregar_sede_y_catalogo.py`
- Test: `tests/test_modelos_dispositivo.py`

**Interfaces:**
- Produces: `Sede(id, nombre, direccion, zona_horaria)` con `zona_horaria` por defecto `"America/Bogota"`; `CatalogoModelo(id, marca, modelo, firmware, estado)` con `estado` en `{"verificado", "en_pruebas", "sin_verificar"}`.

- [ ] **Step 1: Escribir la prueba que falla**

```python
def test_sede_por_defecto_usa_zona_bogota(db):
    s = Sede(nombre="Principal"); db.add(s); db.commit()
    assert s.zona_horaria == "America/Bogota"

def test_catalogo_solo_admite_estados_conocidos(db): ...
```

- [ ] **Step 2: Ejecutar y comprobar el fallo** — Run: `python -m pytest tests/test_modelos_dispositivo.py -v` · Expected: FAIL, no existe `Sede`
- [ ] **Step 3: Implementar `Sede` y `CatalogoModelo` en `backend/models.py`**
- [ ] **Step 4: Generar la migración** — Run: `alembic revision --autogenerate -m "agregar sede y catalogo"`, revisar el archivo generado a mano
- [ ] **Step 5: Ejecutar y comprobar que pasa** — Expected: PASS
- [ ] **Step 6: Commit** — `feat(modelo): agregar Sede y CatalogoModelo`

### Tarea 4: Modelo `Dispositivo` con contraseña cifrada

**Files:**
- Modify: `backend/models.py`
- Create: `alembic/versions/<hash>_agregar_dispositivo.py`
- Test: `tests/test_modelos_dispositivo.py`

**Interfaces:**
- Consumes: `backend.crypto_service.encriptar(valor: str) -> str` y `desencriptar(valor: str) -> str`.
- Produces: `Dispositivo(id, sede_id, tipo, direccion, puerto, usuario, password_cifrada, numero_serie, estado_compatibilidad, ultima_marcacion, ultima_prueba)`. `numero_serie` único. Propiedad `password` que cifra al asignar y descifra al leer.

- [ ] **Step 1: Escribir la prueba que falla** — *cubre el Review Focus 5*

```python
def test_password_no_se_guarda_en_claro(db, sede):
    d = Dispositivo(sede_id=sede.id, tipo="hikvision", direccion="10.0.0.1", usuario="admin")
    d.password = "secreta123"
    db.add(d); db.commit()
    assert d.password_cifrada != "secreta123"
    assert "secreta123" not in str(d.password_cifrada)
    assert d.password == "secreta123"

def test_serializar_dispositivo_nunca_expone_password(db, sede): ...
def test_numero_serie_es_unico(db, sede): ...
```

- [ ] **Step 2: Ejecutar y comprobar el fallo**
- [ ] **Step 3: Implementar `Dispositivo` con la propiedad `password` sobre `crypto_service`**
- [ ] **Step 4: Generar y revisar la migración**
- [ ] **Step 5: Ejecutar y comprobar que pasa**
- [ ] **Step 6: Commit** — `feat(modelo): agregar Dispositivo con credenciales cifradas`

### Tarea 5: `dispositivo_id` en los registros, con migración de datos

**Files:**
- Modify: `backend/models.py`
- Create: `alembic/versions/<hash>_registros_dispositivo.py`
- Test: `tests/test_migracion_dispositivo.py`

**Interfaces:**
- Produces: `RegistroAsistencia.dispositivo_id`, clave ajena a `dispositivos.id`.

- [ ] **Step 1: Escribir la prueba que falla**

```python
def test_migracion_asigna_todo_a_sede_y_dispositivo_por_defecto(db_esquema_viejo):
    # 3 registros previos, ninguna sede ni dispositivo
    aplicar_migracion()
    assert db.query(Sede).count() == 1
    assert db.query(Dispositivo).count() == 1
    assert db.query(RegistroAsistencia).filter_by(dispositivo_id=None).count() == 0
    assert db.query(RegistroAsistencia).count() == 3   # no se pierde ninguno
```

- [ ] **Step 2: Ejecutar y comprobar el fallo**
- [ ] **Step 3: Escribir la migración con su paso de datos** — crea la sede «Principal» y el dispositivo por defecto a partir de los valores que hoy están en `.env`, y asigna todos los registros existentes
- [ ] **Step 4: Ejecutar y comprobar que pasa**
- [ ] **Step 5: Commit** — `feat(modelo): vincular registros de asistencia a su dispositivo`

**Aceptación de la Fase 1:** Una base con el esquema viejo migra sin perder registros y queda con una sede y un dispositivo por defecto. La contraseña no aparece en claro ni en la base ni al serializar. Las pruebas de caracterización siguen pasando sin tocarse.

---

## Fase 1b — Identidad del empleado por credencial

**Objetivo:** Que una persona sea un solo empleado aunque marque en varios aparatos.
**Alcance:** **Esta fase sí toca el núcleo.** Es la única autorizada a modificar las pruebas de caracterización, y solo con justificación escrita.
**Dependencias:** Fase 1.
**Riesgos:** Es el cambio de mayor alcance del hito. Hoy la identidad se resuelve por igualdad de cadenas en `backend/models.py:47` y `:78`, y de ello dependen `generar_reporte` y `calcular_tardanzas_dia`.

### Tarea 6: Tabla `EmpleadoCredencial` y migración de datos

**Files:**
- Modify: `backend/models.py`
- Create: `alembic/versions/<hash>_empleado_credencial.py`
- Test: `tests/test_identidad.py`

**Interfaces:**
- Produces: `EmpleadoCredencial(id, empleado_id, dispositivo_id, codigo_en_equipo)`, único por `(dispositivo_id, codigo_en_equipo)`.

- [ ] **Step 1: Escribir la prueba que falla**

```python
def test_migracion_crea_una_credencial_por_empleado(db_con_empleados):
    aplicar_migracion()
    for e in db.query(Empleado):
        cred = db.query(EmpleadoCredencial).filter_by(empleado_id=e.id).one()
        assert cred.codigo_en_equipo == e.employee_id   # el valor viejo se conserva

def test_mismo_codigo_en_dos_dispositivos_son_credenciales_distintas(db): ...
```

- [ ] **Step 2: Ejecutar y comprobar el fallo**
- [ ] **Step 3: Implementar el modelo y la migración con paso de datos**
- [ ] **Step 4: Ejecutar y comprobar que pasa**
- [ ] **Step 5: Commit** — `feat(modelo): credenciales de empleado por dispositivo`

### Tarea 7: Resolución de identidad en el núcleo

**Files:**
- Create: `backend/identidad_service.py`
- Modify: `backend/report_service.py` (`generar_reporte`, `calcular_tardanzas_dia`)
- Test: `tests/test_identidad.py`

**Interfaces:**
- Produces: `resolver_empleado(db, dispositivo_id: int, codigo: str) -> Empleado | None`.
- Consumes: `EmpleadoCredencial` de la Tarea 6.

- [ ] **Step 1: Escribir las pruebas que fallan** — *cubre el Review Focus 2*

```python
def test_una_persona_con_dos_credenciales_es_un_solo_empleado_en_el_informe(db):
    # credenciales en dispositivo A y B, marcas el mismo día en ambos
    informe = generar_reporte(db, fecha, fecha)
    assert len(filas_de(informe, "Pérez, Ana")) == 1

def test_codigo_desconocido_guarda_la_marcacion_sin_empleado(db):
    assert resolver_empleado(db, disp.id, "9999") is None
    # y la marcación existe, no se descarta
    assert db.query(RegistroAsistencia).filter_by(empleado_id=None).count() == 1
```

- [ ] **Step 2: Ejecutar y comprobar el fallo**
- [ ] **Step 3: Implementar `resolver_empleado` y sustituir la resolución por cadenas en `report_service`**
- [ ] **Step 4: Ejecutar la suite completa** — Run: `python -m pytest tests/ -q` · Expected: todo verde; si alguna prueba de caracterización falla, **anotar en el commit por qué el cambio es correcto**
- [ ] **Step 5: Commit** — `feat(nucleo): resolver identidad por credencial de dispositivo`

### Tarea 8: Unicidad anclada al número de serie

**Files:**
- Create: `alembic/versions/<hash>_unicidad_por_serie.py`
- Test: `tests/test_identidad.py`

- [ ] **Step 1: Escribir la prueba que falla** — *cubre el Review Focus 3*

```python
def test_borrar_y_recrear_dispositivo_no_duplica_historico(db):
    # extraer, borrar el dispositivo, recrearlo con el MISMO numero_serie, reextraer
    assert db.query(RegistroAsistencia).count() == n_original
```

- [ ] **Step 2: Ejecutar y comprobar el fallo**
- [ ] **Step 3: Implementar la reutilización por número de serie**

Una restricción de unicidad no puede abarcar dos tablas, y `numero_serie` vive en `Dispositivo`, no en `RegistroAsistencia`. Por tanto el anclaje se consigue así, y no metiendo la serie en cada registro:

1. La restricción de registros pasa a `(dispositivo_id, empleado_id, fecha, hora)`, **conservando `postgresql_nulls_not_distinct=True`** como en `b7c4e19a2f30`.
2. **Dar de alta un dispositivo cuyo `numero_serie` ya existe reutiliza la fila existente** en lugar de crear una nueva, de modo que `dispositivo_id` es estable aunque el usuario lo borre y lo vuelva a crear.
3. El borrado de un dispositivo es lógico (`activo = False`), nunca físico, porque sus registros lo referencian.
- [ ] **Step 4: Ejecutar y comprobar que pasa**
- [ ] **Step 5: Commit** — `fix(modelo): anclar unicidad de registros al numero de serie`

### Tarea 9: `sync_empleados` y reconciliación

**Files:**
- Modify: `backend/sync_empleados.py`, `frontend/index.html`, `frontend/app.js`
- Test: `tests/test_identidad.py`

**Interfaces:**
- Produces: endpoint para asociar un código suelto a un empleado existente o crear uno nuevo.

- [ ] **Step 1: Escribir la prueba que falla**

```python
def test_asociar_codigo_suelto_incorpora_sus_marcas_al_calculo(db): ...
```

- [ ] **Step 2: Ejecutar y comprobar el fallo**
- [ ] **Step 3: Adaptar `sync_empleados` para crear credenciales, y extender la pantalla «Marcas sin Empleado Asociado» que ya existe**
- [ ] **Step 4: Ejecutar y comprobar que pasa**
- [ ] **Step 5: Commit** — `feat(admin): reconciliar credenciales desconocidas`

**Aceptación de la Fase 1b:** Una persona con credenciales en dos dispositivos produce un solo empleado en los informes. Un código desconocido genera marcación sin empleado, visible, y asociarla la incorpora al cálculo. Borrar y recrear un dispositivo no duplica su histórico.

---

## Fase 2 — Capa de adaptadores

**Objetivo:** Que el núcleo deje de saber de marcas, y que el mismo adaptador pueda correr dentro del servidor o dentro del agente.
**Alcance:** Refactor **sin cambio funcional**. Las pruebas de caracterización pasan sin modificarse.
**Dependencias:** Fase 1b.
**Riesgos:** Si el contrato no es serializable desde aquí, el agente del Hito 3 obliga a rehacer las fases 2, 3 y 4.

### Tarea 10: Contrato de adaptador y taxonomía

**Files:**
- Create: `backend/adaptadores/base.py`, `backend/adaptadores/__init__.py`
- Test: `tests/test_adaptadores.py`

**Interfaces:**
- Produces:
  - `Marcacion(codigo_en_equipo: str, instante: datetime, tipo: TipoMarcacion, crudo: str)` — `instante` **siempre con zona**.
  - `TipoMarcacion` cerrado: `AUTENTICACION_VALIDA`, `AUTENTICACION_FALLIDA`, `EVENTO_SISTEMA`.
  - `Capacidades(probar_conexion: bool, listar_empleados: bool, traer_marcaciones: bool, recibir_empuje: bool)`.
  - `ResultadoPrueba(ok: bool, mensaje: str, detalles: dict)`.
  - `AdaptadorBase` con `capacidades()`, `probar_conexion()`, `listar_empleados()`, `traer_marcaciones(desde, hasta)`.
  - `registrar(tipo: str, clase)` y `obtener(tipo: str) -> type[AdaptadorBase]`.

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_marcacion_viaja_serializada_sin_perdida():
    m = Marcacion(...)
    assert Marcacion.desde_dict(m.a_dict()) == m

def test_adaptador_de_empuje_declara_que_no_sabe_listar_empleados(): ...
def test_tipo_de_marcacion_no_admite_valores_fuera_de_la_taxonomia(): ...
```

- [ ] **Step 2: Ejecutar y comprobar el fallo**
- [ ] **Step 3: Implementar el contrato** — `a_dict()`/`desde_dict()` con tipos primitivos, para que el mismo objeto cruce la red hacia el agente
- [ ] **Step 4: Ejecutar y comprobar que pasa**
- [ ] **Step 5: Commit** — `feat(adaptadores): contrato serializable y taxonomia de marcacion`

### Tarea 11: Adaptador Hikvision y borrado de `device_config.py`

**Files:**
- Create: `backend/adaptadores/hikvision.py`
- Modify: `extractor_hikvision.py`
- Delete: `backend/device_config.py`
- Modify: `.env.example` (quitar `DEVICE_IP`, `DEVICE_USER`, `DEVICE_PASS`)

**Interfaces:**
- Consumes: `AdaptadorBase` de la Tarea 10, `Dispositivo` de la Tarea 4.
- Produces: `AdaptadorHikvision(dispositivo: Dispositivo)` registrado bajo el tipo `"hikvision"`.

- [ ] **Step 1: Escribir la prueba que falla**

```python
def test_adaptador_hikvision_traduce_minor_38_a_autenticacion_valida(respuesta_isapi): ...
def test_no_queda_ninguna_referencia_a_DEVICE_IP():
    # grep sobre el árbol del proyecto, incluido .env.example
    assert buscar_en_proyecto("DEVICE_IP") == []
```

- [ ] **Step 2: Ejecutar y comprobar el fallo**
- [ ] **Step 3: Mover el código ISAPI detrás del contrato** — `EVENT_MAP` y `AUTH_MINORS` se traducen a `TipoMarcacion` **dentro del adaptador**; el núcleo nunca mira `crudo`
- [ ] **Step 4: Borrar `backend/device_config.py` y limpiar `.env.example`**
- [ ] **Step 5: Ejecutar la suite completa** — Expected: **las pruebas de caracterización pasan sin haberse modificado**
- [ ] **Step 6: Verificar contra el Hikvision real de REDIHOS** — extracción de un día leyendo la configuración desde la base de datos
- [ ] **Step 7: Commit** — `refactor(extractor): mover Hikvision detras del contrato de adaptador`

**Aceptación de la Fase 2:** Caracterización en verde sin tocarse. Cero referencias a `DEVICE_IP`/`DEVICE_USER`/`DEVICE_PASS`. Extracción real contra el Hikvision leyendo de base de datos. El contrato se serializa y deserializa sin pérdida.

---

## Fase 3 — Administración: alta de dispositivos

**Objetivo:** Dar de alta un biométrico y probarlo desde la interfaz, sin tocar archivos ni reiniciar. **Es lo que se pidió originalmente.**
**Alcance:** Sedes y dispositivos, con permisos por rol y prueba de conexión.
**Dependencias:** Fase 2.
**Riesgos:** El diagnóstico es el sitio más fácil por donde se escapa una contraseña.

### Tarea 12: Servicio y endpoints de sedes y dispositivos

**Files:**
- Create: `backend/dispositivo_service.py`
- Modify: `backend/main.py`, `backend/auth.py` (permiso `gestionar_dispositivos`)
- Test: `tests/test_api_dispositivos.py`

**Interfaces:**
- Produces: `GET/POST/PUT/DELETE /api/sedes` y `/api/dispositivos`; `GET /api/tipos-biometrico` devolviendo tipo, capacidades y estado de compatibilidad del catálogo.

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_usuario_sin_permiso_no_puede_listar_dispositivos(client): assert r.status_code == 403
def test_respuesta_de_dispositivo_no_incluye_password(client): assert "password" not in r.json()
def test_tipos_biometrico_devuelve_estado_de_compatibilidad(client): ...
```

- [ ] **Step 2: Ejecutar y comprobar el fallo**
- [ ] **Step 3: Implementar el servicio, los endpoints y el permiso nuevo**
- [ ] **Step 4: Ejecutar y comprobar que pasa**
- [ ] **Step 5: Commit** — `feat(admin): API de sedes y dispositivos`

### Tarea 13: Prueba de conexión con diagnóstico

**Files:**
- Modify: `backend/dispositivo_service.py`, `backend/main.py`
- Test: `tests/test_api_dispositivos.py`

**Interfaces:**
- Produces: `POST /api/dispositivos/{id}/probar` → `ResultadoPrueba`, y `GET /api/dispositivos/{id}/diagnostico` descargable.

- [ ] **Step 1: Escribir la prueba que falla** — *cubre el Review Focus 5*

```python
def test_diagnostico_nunca_contiene_la_password(db, client):
    d.password = "secretísima"
    texto = client.get(f"/api/dispositivos/{d.id}/diagnostico").text
    assert "secretísima" not in texto
```

- [ ] **Step 2: Ejecutar y comprobar el fallo**
- [ ] **Step 3: Implementar la prueba de conexión; el diagnóstico lleva tipo, dirección, firmware, latencia y error, **nunca credenciales**
- [ ] **Step 4: Ejecutar y comprobar que pasa**
- [ ] **Step 5: Commit** — `feat(admin): prueba de conexion con diagnostico descargable`

### Tarea 14: Pantallas de Sedes y Dispositivos

**Files:**
- Modify: `frontend/index.html`, `frontend/app.js`

**Interfaces:**
- Consumes: los endpoints de las tareas 12 y 13.

- [ ] **Step 1: Añadir las pestañas en Administración** — con la estética existente (`.puzzle-tabs`, `.data-table`, `.form-input`), siguiendo el patrón de la pestaña de Turnos
- [ ] **Step 2: Ocultar los botones que el adaptador no declara** — un dispositivo de solo empuje no muestra «listar empleados» ni «probar conexión»
- [ ] **Step 3: Verificar en el navegador** — alta de un dispositivo, prueba de conexión y extracción, sin reiniciar nada
- [ ] **Step 4: Commit** — `feat(admin): pantallas de sedes y dispositivos`

**Aceptación de la Fase 3:** Un administrador da de alta un biométrico, prueba la conexión y extrae marcaciones sin tocar archivos. Un usuario sin el permiso no ve ni puede invocar nada de esto. El diagnóstico no contiene la contraseña.

---

## Fase 4 — Extracción e informes multi-dispositivo

**Objetivo:** Que N aparatos funcionen a la vez y que un fallo no tumbe el lote.
**Alcance:** Orquestación, fusión por dispositivo, filtro de sede, zona horaria.
**Dependencias:** Fase 3.
**Riesgos:** Fusionar entre dispositivos haría desaparecer salidas; es el error más caro de esta fase y por eso tiene prueba propia.

### Tarea 15: Orquestación con aislamiento de fallos

**Files:**
- Modify: `extractor_hikvision.py` (`main`), `backend/scheduler.py`
- Test: `tests/test_extraccion_multidispositivo.py`

**Interfaces:**
- Produces: `extraer_todos(db, desde, hasta) -> ResumenExtraccion` con marcaciones guardadas y fallos por dispositivo.

- [ ] **Step 1: Escribir la prueba que falla** — *cubre el Review Focus 4*

```python
def test_un_dispositivo_caido_no_tumba_el_lote(db):
    resumen = extraer_todos(db, hoy, hoy)   # 3 dispositivos, el 2 apagado
    assert resumen.fallidos == [disp2.id]
    assert resumen.guardadas > 0
```

- [ ] **Step 2: Ejecutar y comprobar el fallo**
- [ ] **Step 3: Implementar `extraer_todos` recorriendo dispositivos activos, capturando el fallo de cada uno**
- [ ] **Step 4: Ejecutar y comprobar que pasa**
- [ ] **Step 5: Commit** — `feat(extraccion): orquestar varios dispositivos aislando fallos`

### Tarea 16: Fusión por dispositivo y filtro de sede

**Files:**
- Modify: `backend/report_service.py` (`_fusionar_marcas_por_empleado_dia`, `generar_reporte`)
- Test: `tests/test_report_service.py`

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_marcas_de_dispositivos_distintos_no_se_fusionan(db):
    # lector de entrada y lector de salida, a 30 segundos
    assert len(marcas_resultantes) == 2    # la salida NO desaparece

def test_filtro_de_sede_usa_la_sede_del_dispositivo(db): ...
```

- [ ] **Step 2: Ejecutar y comprobar el fallo**
- [ ] **Step 3: Cambiar la agrupación de `(nombre, fecha)` a `(dispositivo, credencial, fecha)` y añadir el filtro de sede**
- [ ] **Step 4: Ejecutar y comprobar que pasa**
- [ ] **Step 5: Commit** — `fix(reportes): fusionar marcas por dispositivo, nunca entre dispositivos`

### Tarea 17: Zona horaria y reloj desajustado

**Files:**
- Modify: `backend/adaptadores/base.py`, `backend/timezone.py`
- Test: `tests/test_adaptadores.py`

- [ ] **Step 1: Escribir la prueba que falla** — *cubre el Review Focus 1*

```python
def test_aparato_sin_zona_hereda_la_de_su_sede(db): ...
def test_reloj_desviado_genera_alerta_visible(db):
    # aparato 20 minutos adelantado
    assert alertas_de(disp) != []
```

- [ ] **Step 2: Ejecutar y comprobar el fallo**
- [ ] **Step 3: Completar la zona desde la sede cuando el aparato no la reporte, y registrar alerta si la desviación supera 5 minutos**
- [ ] **Step 4: Ejecutar y comprobar que pasa**
- [ ] **Step 5: Commit** — `feat(adaptadores): zona horaria por sede y alerta de reloj desajustado`

**Aceptación de la Fase 4:** Con tres dispositivos y uno apagado, la extracción termina, reporta el fallo y guarda lo de los otros dos. Un empleado que marca en dos sedes aparece bien y sin duplicar. Dos lectores en la misma puerta no se fusionan.

### 🏁 Fin del Hito 1

**REDIHOS puede correr sobre el producto nuevo, en modo local, con su Hikvision dado de alta desde la interfaz y su histórico íntegro.** El producto ya no está atado a una marca ni a un aparato.

---

# HITOS 2 a 4 — nivel de fase

> Cada uno recibirá su plan de tareas cuando le toque. Las decisiones de detalle dependen de respuestas que aún no existen.

## Hito 2 — Más marcas (fases 5, 6, 8 y 9 del diseño)

**Objetivo:** Ampliar la cobertura de mercado.
**Dependencias:** Hito 1 cerrado, **y la ventana de préstamo de equipos**.
**Riesgo dominante:** la ventana no tiene fecha. Las tres fases que necesitan hardware se agrupan en **una sola campaña de pruebas**, y todo lo que no requiera el aparato se construye antes contra documentación y cargas grabadas.

| Fase | Alcance | Aceptación | Riesgo |
| --- | --- | --- | --- |
| 5 · ZKTeco empuje | Endpoint `/iclock/cdata` y `/iclock/getrequest`, ambas variantes de ruta; traducción de `ATTLOG` | Un ZKTeco prestado entrega marcas sin agente ni puertos abiertos; serie no registrada se rechaza | Variantes de firmware; HTTP en claro |
| 6 · ZKTeco consulta + ESSL | Adaptador sobre puerto 4370 con `pyzk` | Extracción real; cada modelo probado queda en la matriz con su firmware | `pyzk` no es oficial; compatibilidad variable |
| 8 · Dahua | API CGI | Extracción real **o informe de abandono razonado**; ambos son resultado válido | Documentación pobre; plazo de 2 días |
| 9 · Suprema y Anviz | Suprema vía BioStar 2; Anviz según registro de partner | Suprema aparece con su requisito escrito para que nadie la compre por error | Dependen de terceros |

## Hito 3 — La nube (fases 7 y 5-pasarela del diseño)

**Objetivo:** Poder vender a clientes que no quieren servidor propio.
**Dependencias:** Hito 1. El contrato serializable de la Tarea 10 es el cimiento.
**Riesgo dominante:** si el contrato no aguanta viajar, esta fase obliga a rehacer el Hito 1.

- **Agente local** — Python, servicio de Windows, cola en disco, reintento. Acepta cuando el **mismo** adaptador Hikvision corre sin cambios dentro del agente y dentro del servidor.
- **Pasarela de ingesta** — compartida, sin persistencia, pre-registro por serie, secreto por dispositivo, límite de caudal. Acepta cuando una serie no registrada se rechaza y no alcanza ninguna instancia, y una prueba demuestra que la pasarela no guarda nada.

## Hito 4 — Distribución (fases 10 y 11 del diseño)

**Objetivo:** Que dar de alta un cliente no sea trabajo manual.
**Dependencias:** Hito 3.
**Riesgo dominante:** **dos modos de despliegue doblan esta fase**; y el modelo de cobro sigue sin decidir, lo que en modo local es más peliagudo porque el software corre en una máquina ajena.

- Dos plantillas de despliegue, nube y local. Alta en nube en **un comando**.
- Custodia de la `FERNET_KEY` por instancia. **La restauración debe demostrar que tras restaurar se extraen marcaciones sin volver a teclear ninguna contraseña.**
- Matriz de compatibilidad pública, alimentada por diagnósticos con consentimiento revocable. Prueba de que el envío nunca incluye marcaciones, empleados, credenciales ni nombre del cliente.

---

## Decisiones pendientes que afectan al plan

| # | Pendiente | A qué afecta |
| --- | --- | --- |
| 1 | Nombre del producto y visibilidad del repositorio | Tarea 1. Se usa nombre provisional |
| 2 | Alojamiento de la nube y presupuesto | Hito 3 y 4. No bloquea el Hito 1 |
| 3 | Modelo de cobro y control de licencia | Hito 4 |
| 4 | Fecha del préstamo de equipos | Hito 2 entero |

**Ninguna de las cuatro bloquea el Hito 1**, que es precisamente lo que resuelve el encargo original: sacar las credenciales del código y poder dar de alta biométricos desde Administración.
