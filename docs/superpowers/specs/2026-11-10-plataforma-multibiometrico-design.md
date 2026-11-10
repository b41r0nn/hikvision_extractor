# Diseño — Plataforma multi-biométrico de control de asistencia

**Fecha:** 2026-11-10
**Autor del diseño:** Bairon Calle Rivera
**Base de partida:** `hikvision_extractor`, tag `v1.6.3-docs` (commit `6bc67a7`)
**Estado:** propuesta, pendiente de aprobación

---

## 1. Intención y porqué

`hikvision_extractor` funciona bien para lo que se construyó: extraer marcaciones de **un** biométrico Hikvision de REDIHOS y convertirlas en informes de asistencia. El producto que se quiere ahora es otro: **una plataforma que cualquier PyME pueda contratar, conectando los biométricos que ya tenga, de la marca que sean, en una o varias sedes.**

Tres cosas lo impiden hoy:

1. **El dispositivo está fijado en el código.** `backend/device_config.py` lee `DEVICE_IP`, `DEVICE_USER` y `DEVICE_PASS` del entorno **como constantes de módulo, en el momento de importar**, con valores por defecto incrustados (`192.168.1.127`, `admin`). No hay forma de tener dos aparatos, ni de cambiar uno sin reiniciar el proceso.
2. **El protocolo está fijado en el código.** Las URL de ISAPI de Hikvision se construyen en ese mismo módulo. No existe la noción de «tipo de dispositivo».
3. **El modelo de datos no conoce el mundo real.** En `backend/models.py` no hay tabla de sede ni de dispositivo, y `RegistroAsistencia` no registra de qué equipo vino cada marcación. Con dos aparatos, dos empleados con el mismo identificador en equipos distintos se mezclarían sin aviso.

El porqué de fondo: el trabajo de integración ya está pagado una vez. Extraer marcaciones, calcular tardanzas con turnos versionados, fusionar marcas duplicadas, generar el Excel y mandarlo por correo es la parte difícil, y está hecha y probada. Lo que falta es despegarla de un único aparato de una única marca.

---

## 2. Objetivos

- Dar de alta un dispositivo desde **Administración**: tipo de biométrico, dirección, puerto, credenciales y sede a la que pertenece. Sin tocar archivos ni reiniciar.
- **Multi-dispositivo y multi-sede**: varias sedes, varios equipos por sede, e informes filtrables por sede.
- **Credenciales cifradas en base de datos**, nunca en `.env`, nunca en el código, nunca en logs ni en informes.
- **Un adaptador por marca**, aislado, de modo que añadir una marca sea añadir un módulo y no tocar el núcleo.
- **Estado de compatibilidad visible** por modelo: verificado, en pruebas, sin verificar.
- **Prueba de conexión** que el propio cliente ejecuta contra su equipo y que produce un informe de diagnóstico.
- **Alta de un cliente nuevo automatizada**, sin trabajo manual del autor.
- Conservar la interfaz existente (estética oscura Puzzle, `frontend/index.html`).

## 3. No objetivos

- **No se almacenan plantillas biométricas.** Solo marcaciones: identificador de empleado, fecha y hora. Las huellas y los rostros no salen del aparato.
- **No se hace control de acceso.** No se abren puertas ni se gestionan permisos de paso; solo se leen los eventos de asistencia.
- **No sustituye al software del fabricante** para enrolar empleados en el aparato. El enrolamiento sigue haciéndose donde se hace hoy.
- **No se hace nómina.** El producto entrega tardanzas e informes; el cálculo de salarios queda fuera.
- **No se soportan marcas que no se puedan probar**, más allá de dejarlas marcadas como «sin verificar».

## 4. Anti-objetivos

Cosas que harían fracasar el proyecto aunque todo el código funcionara:

- **Prometer marcas no verificadas como si lo estuvieran.** Un cliente que compra por una compatibilidad declarada y descubre que su modelo no funciona es una devolución y una reputación quemada.
- **Que añadir una marca obligue a tocar el núcleo.** Si el quinto adaptador exige modificar el cálculo de tardanzas, la arquitectura falló.
- **Que dar de alta un cliente requiera trabajo manual del autor.** Con una instancia por empresa, el alta manual convierte cada venta en una carga permanente.
- **Que una credencial de biométrico aparezca en un log, un informe o un volcado.**
- **Romper lo que ya funciona en REDIHOS.** La instalación en producción debe poder migrar sin perder un solo registro histórico.

---

## 5. Restricciones

| # | Restricción | Consecuencia |
| --- | --- | --- |
| R1 | **Solo hay un Hikvision para probar.** El resto de equipos llegan prestados por un integrador, en una ventana corta de tiempo. | Las pruebas de todas las marcas se agrupan en una única fase intensiva. Fuera de esa ventana, los adaptadores se desarrollan contra documentación, librerías abiertas y cargas grabadas. |
| R2 | **Suprema expone su API en el servidor BioStar 2, no en el aparato.** | Solo se soporta si el cliente ya tiene BioStar 2 instalado y licenciado. No se vende como compatibilidad general. |
| R3 | **Anviz exige registro de partner para obtener el SDK.** | Queda condicionada a un trámite comercial que no controla el equipo técnico. |
| R4 | **La documentación pública de Dahua es pobre.** Hace falta el PDF oficial `DAHUA_HTTP_API` de la versión de firmware concreta. | Es trabajo, no bloqueo. Se asume mayor esfuerzo de investigación. |
| R5 | **Los biométricos viven en la red local del cliente.** | Las marcas que solo responden cuando se las consulta necesitan un agente dentro de esa red. Las que empujan, no. |
| R6 | **Base técnica existente.** Python 3.12, FastAPI, SQLAlchemy, Alembic, PostgreSQL, Docker Compose, frontend HTML/JS con Tailwind por CDN. | Se construye sobre ello. No hay reescritura de lenguaje ni de framework. |
| R7 | **Los 56 tests actuales deben seguir en verde** en todo momento. | Cada fase incluye la suite completa como criterio de aceptación. |
| R8 | **Una instancia por empresa.** | El aislamiento es por despliegue, no por columna `empresa_id`. El modelo de datos no se multi-tenantiza. **Única excepción documentada:** la pasarela de ingesta de §7.9, que es compartida pero no guarda ni interpreta datos. |
| R10 | **Dos modos de despliegue: nube e instalación local.** | Todo lo que se construya tiene que funcionar en ambos. La Fase 10 se dobla: dos plantillas, dos procedimientos de actualización y dos de respaldo. En modo local no hay pasarela ni agente: el servidor ya está en la red del aparato. |
| R9 | **Los adaptadores son de solo lectura frente al aparato.** Consecuencia directa de no almacenar plantillas biométricas. | Ningún adaptador enrola, modifica ni borra usuarios, plantillas o configuración en el biométrico. La única excepción admitida es responder a `/iclock/getrequest` en ZKTeco con lo mínimo para que el equipo siga entregando marcaciones. Esto reduce la superficie de cada adaptador y elimina el riesgo de dejar inservible el aparato de un cliente. |

---

## 6. Decisiones ya tomadas

| Decisión | Quién la tomó |
| --- | --- |
| Alojamiento en la nube, con agente local para las marcas que haya que consultar | Usuario |
| **Dos modos de despliegue: nube e instalación local** en el servidor del cliente (R10) | Usuario |
| Los diagnósticos de campo se envían **automáticamente, previo consentimiento** revocable (§7.10) | Usuario |
| **Una instalación (y una base de datos) por empresa cliente** | Usuario |
| Público objetivo: PyMEs colombianas con una o varias sedes, perfil REDIHOS | Usuario |
| Se parte del diseño visual ya existente en el repositorio (estética oscura Puzzle) | Usuario |
| Soportar el máximo de marcas posible; abandonar las que resulten inviables | Usuario |
| Los equipos de prueba se consiguen prestados de un integrador | Usuario |
| Tres causas de abandono de una marca: puerta comercial ajena, obligar al cliente a comprar otro software, o prueba fallida tras 2 días | Claude |
| Orden de ataque: Hikvision → ZKTeco push → ZKTeco pull → ESSL → Dahua → Suprema → Anviz | Claude |
| Estado de compatibilidad visible por modelo + prueba de conexión con diagnóstico | Claude |
| Se conserva Python/FastAPI/PostgreSQL; sin reescritura de pila | Claude |
| El agente local se escribe en Python y se entrega como servicio de Windows | Claude |
| **No se almacenan plantillas biométricas en ningún caso.** Solo marcaciones. Las huellas y los rostros no salen del aparato | Usuario |
| Una persona es **una** fila de `Empleado` con una credencial por dispositivo (§8.2) | Claude |
| La reconciliación de credenciales desconocidas es **un acto humano**, por la pantalla «Marcas sin Empleado Asociado» que ya existe | Claude |
| La interfaz de adaptador es **serializable y remota desde la Fase 2**, para que el agente reutilice el mismo código | Claude |
| Cada adaptador **declara sus capacidades**; la interfaz de Administración dibuja solo lo que el aparato sabe hacer | Claude |
| Taxonomía canónica de marcación cerrada, con el código del fabricante conservado aparte (§7.4) | Claude |
| El adaptador entrega un **instante con zona horaria**; la de `Sede` entra en el cálculo (§7.5) | Claude |
| La ventana de fusión de 2 minutos se aplica **por dispositivo, nunca entre dispositivos** (§7.6) | Claude |
| La unicidad se ancla al **número de serie** del aparato, no a su identificador interno | Claude |
| **Pasarela de ingesta compartida que solo reenvía** para el camino de empuje (§7.9) | Claude, por delegación expresa del usuario |
| REDIHOS pasa al producto nuevo **en modo local**, que es donde ya está (Fase 11) | Claude |

---

## 7. Arquitectura

### 7.1 Núcleo y adaptadores

```
┌─────────────────────────────────────────────────────────┐
│  NÚCLEO (lo que ya existe y no se toca)                 │
│  turnos versionados · tardanzas · fusión de marcas      │
│  festivos · informes Excel · correo · roles y permisos  │
└───────────────────────┬─────────────────────────────────┘
                        │  interfaz única de marcación
        ┌───────────────┴───────────────┐
        │                               │
┌───────▼────────┐            ┌─────────▼─────────┐
│ ADAPTADORES    │            │ ADAPTADORES       │
│ DE TIRAR       │            │ DE EMPUJAR        │
│ (pull)         │            │ (push)            │
│                │            │                   │
│ Hikvision ISAPI│            │ ZKTeco ADMS       │
│ Dahua CGI      │            │                   │
│ ZKTeco :4370   │            │                   │
│ Suprema REST   │            │                   │
└───────┬────────┘            └─────────▲─────────┘
        │ requiere agente               │ el equipo inicia
        │ en la red del cliente         │ la conexión
```

**Interfaz única.** Todo adaptador entrega la misma estructura de marcación y el núcleo no sabe de marcas. Tres propiedades que no son negociables:

1. **Serializable y remota desde el primer día.** La interfaz no es una clase abstracta que se llama en proceso: es un contrato que tiene que poder viajar. El mismo adaptador debe poder ejecutarse dentro del servidor (cuando está en la misma red que el aparato) o dentro del agente (cuando no lo está), sin reescribirse. Entradas, salidas, errores y diagnóstico se definen como datos serializables, y toda operación es idempotente y tiene plazo máximo. **Descubrir esto en la Fase 7 obligaría a rehacer las fases 2, 3, 4, 6 y 8.**
2. **Capacidades declaradas.** No todos los aparatos saben hacer lo mismo. Un ZKTeco por empuje no se puede consultar: manda lo que quiere cuando quiere, así que **no puede listar empleados ni probar conexión bajo demanda**. Cada adaptador declara qué sabe hacer (`probar_conexion`, `listar_empleados`, `traer_marcaciones`, `recibir_empuje`) y la interfaz de Administración dibuja solo lo que aplica. En un dispositivo de solo empuje, los empleados se dan de alta por reconciliación (§8.3), no por descarga.
3. **Taxonomía canónica, con el crudo al lado.** Ver §7.4.

### 7.2 Los dos caminos de entrada

**Empujar (ZKTeco con ADMS).** El propio equipo hace `POST` a `/iclock/cdata` contra una URL configurada en su menú, y consulta `/iclock/getrequest` para recibir órdenes. Como el aparato inicia la conexión, **no hace falta IP fija ni abrir puertos** en la red del cliente, y **no hace falta agente**. Hay variantes de ruta según firmware (`/iclock/cdata.aspx` en algunos modelos): el servidor debe aceptar ambas.

**Tirar (Hikvision, Dahua, ZKTeco por 4370, Suprema).** El equipo solo responde si se le pregunta, y vive en una red privada. Requiere el **agente local**.

### 7.3 El agente local

Un proceso pequeño que el cliente instala en un PC de su red. No expone puertos: abre él la conexión hacia la nube, pide qué dispositivos le tocan, los consulta, y sube las marcaciones. Guarda en disco lo que no pudo enviar y reintenta.

**Las credenciales de los biométricos viven cifradas en la nube** y se entregan al agente solo durante la sesión; no se escriben en disco en el equipo del cliente.

### 7.4 Qué es una marcación

Hoy el criterio de «esto es asistencia y esto es ruido» vive dentro del código Hikvision y habla vocabulario Hikvision: `EVENT_MAP` con pares `(major, minor)` y el conjunto `AUTH_MINORS = {38, 75, 104}` en `extractor_hikvision.py`. Si cada adaptador inventa su propio criterio, el núcleo acaba con condicionales por marca, que es justo el anti-objetivo declarado.

La marcación canónica que todo adaptador entrega:

| Campo | Contenido |
| --- | --- |
| `codigo_en_equipo` | Identificador tal como lo reporta el aparato |
| `instante` | **Momento con zona horaria explícita**, no fecha y hora sueltas |
| `tipo` | Taxonomía canónica cerrada: `autenticacion_valida`, `autenticacion_fallida`, `evento_sistema` |
| `crudo` | Código original del fabricante, conservado como ya hace hoy `evento_raw` |

**Solo las de tipo `autenticacion_valida` entran en el cálculo.** El resto se guarda para diagnóstico y no se cuenta. **Traducir el vocabulario del fabricante a esta taxonomía es responsabilidad del adaptador, siempre.** El núcleo nunca mira el campo `crudo` para decidir nada.

Se conserva el comportamiento actual de inferir entrada y salida por orden cronológico y no por el tipo de evento, para que el modo `entrada_salida` del informe no cambie de significado según la marca del aparato.

### 7.5 Hora y zona horaria

El adaptador entrega un **instante con zona**. Si el aparato no la reporta —el `ATTLOG` de ZKTeco da la hora del reloj del equipo, a secas— el adaptador la completa con la zona horaria de la **sede** a la que pertenece el dispositivo. El núcleo convierte y sigue usando `hoy_bogota()` para el corte de día mientras el producto sea colombiano.

Esto hace que la zona horaria de `Sede` **no sea decorativa**: entra en el cálculo. Y obliga a una salvaguarda: si la hora que reporta un aparato se desvía más de unos minutos de la del servidor, se registra una alerta visible, porque un reloj desajustado mete marcas en el día equivocado sin que nada falle.

### 7.6 Fusión y deduplicación con varios equipos

- **La ventana de fusión de 2 minutos se aplica por dispositivo, nunca entre dispositivos.** Dos lectores en la misma puerta —uno de entrada, otro de salida— producen marcas a segundos de distancia que, fusionadas, harían desaparecer la salida.
- La agrupación de `_fusionar_marcas_por_empleado_dia` pasa de `(nombre, fecha)` a `(dispositivo, credencial, fecha)`.
- El filtro por sede de los informes usa **la sede del dispositivo donde cayó la marca**, no una sede del empleado, que ya no existe como atributo.

### 7.7 Custodia de la clave de cifrado

`crypto_service` lee `FERNET_KEY` del entorno y falla al importar si falta. Con una instancia por empresa hay una clave por cliente, y de ella dependen todas las contraseñas de sus biométricos.

- La clave **se genera en el alta** de la instancia y se guarda fuera de la base de datos.
- **Una copia de la base de datos sin su clave es inservible** para recuperar credenciales: el procedimiento de respaldo de la Fase 10 debe incluir la clave, y la prueba de restauración debe demostrar que tras restaurar se extraen marcaciones sin volver a teclear ninguna contraseña.
- El agente recibe credenciales descifradas solo en memoria y durante la sesión.

### 7.8 Una instancia por empresa

Cada cliente recibe su propio despliegue (aplicación + base de datos), aislado del resto. Se sostiene porque el alta es automática: una plantilla de `docker-compose`, un script de aprovisionamiento y un subdominio por cliente. **No se introduce `empresa_id` en el modelo de datos**: el aislamiento es por despliegue.

**Dos modos, el mismo producto.**

| | Nube | Local |
| --- | --- | --- |
| Dónde corre | Infraestructura del autor | Servidor del cliente |
| Aparatos de tirar | Vía agente | Directo: ya está en la misma red |
| Aparatos de empuje | Vía pasarela (§7.9) | Apuntan al propio servidor |
| Actualizaciones | El autor, a todas las instancias | El cliente, o el autor con acceso |
| Respaldos | El autor | El cliente |
| Para quién | La mayoría | Quien no quiera que sus datos salgan |

El mismo artefacto sirve para ambos: lo que cambia es el aprovisionamiento y quién opera. **El modo local es un argumento de venta real en PyMEs recelosas con los datos de su personal**, y es además donde REDIHOS está hoy, así que se puede validar desde el primer día sin migrar nada.

### 7.9 Pasarela de ingesta para el camino de empuje

*Decisión tomada por Claude, a petición del usuario, con criterio de seguridad y eficiencia.*

Un **único punto de entrada compartido que solo reenvía**: recibe de todos los aparatos de empuje, mira el número de serie y entrega a la instancia que corresponda. No guarda nada, no interpreta las marcaciones y no tiene base de datos.

**Por qué esta y no las otras dos:**

- *Frente a un endpoint por instancia:* muchos firmwares ZKTeco son quisquillosos con nombres de servidor y no manejan bien SNI. Una URL única e idéntica para todos los clientes elimina la clase de fallo más probable en una instalación, y evita tener que configurar certificados y DNS por cliente en aparatos que puede que no los acepten.
- *Frente a una pasarela que almacene:* al no guardar ni descifrar nada, el aislamiento de datos que pediste se mantiene intacto. Lo compartido es el buzón, no el contenido.
- *Sobre el HTTP en claro:* es un hecho de los firmwares, no una elección. La pasarela es justamente el sitio donde conviene aceptarlo, porque confina el tráfico sin cifrar a **un solo salto que tú controlas y parcheas una vez**, y lo reenvía ya cifrado hacia la instancia del cliente. Repartirlo por los subdominios de cada cliente sería peor.

**El número de serie no basta como autenticación**, menos aún sobre HTTP en claro, donde viaja visible y cualquiera podría suplantarlo para inyectar marcas falsas. Por tanto:

- El aparato se **pre-registra** antes de poder enviar nada: una serie desconocida se rechaza en la pasarela y no llega a ninguna instancia.
- Además de la serie, cada dispositivo lleva un **secreto propio** asignado en el alta.
- Límite de caudal por serie, y alerta cuando una serie emite desde un origen inesperado.
- Las marcaciones recibidas por transporte sin cifrar se marcan como tales, de modo que el cliente pueda verlo.
- A quien le importe de verdad, se le ofrece red privada o lista de IP permitidas; es una recomendación, no un requisito.

### 7.10 Diagnósticos de campo

La instancia del cliente envía al autor marca, modelo, firmware y resultado de las pruebas de conexión, **previo consentimiento otorgado en el alta**, para alimentar la matriz de compatibilidad.

Qué se envía está cerrado y escrito: identificación del aparato, versión de firmware, resultado de la prueba y error si lo hubo. **Nunca marcaciones, ni empleados, ni credenciales, ni nombre del cliente.** El consentimiento es revocable desde la propia aplicación, y existe una vista donde el cliente ve exactamente qué se ha enviado.

---

## 8. Modelo de datos

Añadidos sobre el esquema actual:

### 8.1 Tablas

- **`Sede`** — nombre, dirección, zona horaria. Toda empresa tiene al menos una.
- **`Dispositivo`** — sede a la que pertenece, tipo (marca y variante de protocolo), dirección y puerto, usuario, **contraseña cifrada con el `crypto_service` que ya existe**, **número de serie**, estado de compatibilidad observado, fecha de la última marcación recibida y resultado de la última prueba de conexión.
- **`EmpleadoCredencial`** *(tabla nueva)* — `empleado_id`, `dispositivo_id`, `codigo_en_equipo`. Único por `(dispositivo_id, codigo_en_equipo)`.
- **`RegistroAsistencia`** gana `dispositivo_id`.
- **`CatalogoModelo`** — marca, modelo, firmware, estado de compatibilidad. Sembrado con el producto; es distinto del estado observado en `Dispositivo`.

### 8.2 Identidad de la persona

**Una persona es una fila de `Empleado`, y puede tener una credencial distinta en cada aparato.** Es la única lectura compatible con el requisito de que alguien que marca en dos sedes aparezca una sola vez. Lo contrario —un empleado por dispositivo— convertiría a esa persona en dos empleados y haría imposible la Fase 4.

El identificador del equipo, por tanto, **no vive en `Empleado`**: vive en `EmpleadoCredencial`, y es único por dispositivo, no global. `Empleado` conserva su identidad propia (nombre, documento) y **no** gana una sede única: la sede de una marcación es la del dispositivo donde ocurrió, no un atributo de la persona.

**Consecuencia sobre el núcleo, que hay que asumir de frente:** hoy la identidad se resuelve por igualdad de cadenas entre `RegistroAsistencia.empleado_id` y `Empleado.employee_id` (`backend/models.py:47` y `:78`), mediante un `primaryjoin` sin clave ajena, y de eso dependen `generar_reporte` y `calcular_tardanzas_dia`. Pasar a credenciales por dispositivo convierte esa resolución en una búsqueda de dos columnas. **Esto sí toca el núcleo**, y por eso tiene fase propia (Fase 1b) en lugar de esconderse dentro del refactor de adaptadores.

### 8.3 Reconciliación de credenciales

Cuando un aparato informa un código que no corresponde a ninguna credencial conocida, la marcación **se guarda igualmente**, sin empleado asociado, y aparece en la pantalla que ya existe hoy en Administración: **«Marcas sin Empleado Asociado»**. Desde ahí un administrador asocia el código a un empleado existente o crea uno nuevo. No se intenta adivinar por nombre entre dispositivos: la fusión es siempre un acto humano explícito. Esto reutiliza una pantalla y un flujo que ya están construidos y probados.

### 8.4 Unicidad y migración

La restricción de unicidad pasa de `(empleado_id, fecha, hora)` a **`(dispositivo_id, codigo_en_equipo, fecha, hora)`**, anclada al **número de serie del aparato y no a su identificador interno**, para que borrar y volver a crear un dispositivo no duplique todo su histórico en la siguiente extracción. Hay que conservar la semántica de `postgresql_nulls_not_distinct=True` de la migración `b7c4e19a2f30`, que existe porque `empleado_id` puede ser nulo en el camino de respaldo por nombre.

Migraciones Alembic con paso de datos: todo lo existente se asigna a una sede y un dispositivo por defecto, y por cada `Empleado.employee_id` actual se crea su `EmpleadoCredencial` contra ese dispositivo. La instalación de REDIHOS migra sin perder un solo registro.

---

## 9. Fases

> Cada fase termina con la suite completa en verde. Ninguna fase se da por cerrada con pruebas rojas o sin ejecutar.

### Fase 0 — Separación del proyecto y red de seguridad

| | |
| --- | --- |
| **Tareas** | Crear el repositorio nuevo a partir de `v1.6.3-docs`. Decidir y fijar el nombre del producto. Cubrir con pruebas de caracterización el comportamiento actual del extractor Hikvision, para poder refactorizar sin romperlo. Dejar el pipeline de pruebas corriendo. |
| **Entregables** | Repositorio nuevo con historia propia. Suite heredada en verde. Pruebas de caracterización del extractor. |
| **Aceptación** | Los 56 tests heredados pasan en el repositorio nuevo. Existen pruebas que fijan la salida actual del extractor Hikvision ante una respuesta ISAPI grabada. REDIHOS sigue intacto y sin tocar. |

### Fase 1 — Sedes y dispositivos en el modelo de datos

| | |
| --- | --- |
| **Tareas** | Modelos `Sede`, `Dispositivo` y `CatalogoModelo`. Cifrado de la contraseña del dispositivo reutilizando `crypto_service`. `dispositivo_id` en `RegistroAsistencia`. Migración Alembic con paso de datos que crea la sede y el dispositivo por defecto. **Sin tocar todavía la identidad del empleado.** |
| **Entregables** | Migraciones. Modelos con sus pruebas. Catálogo de modelos sembrado. |
| **Aceptación** | Una base de datos con el esquema viejo migra sin perder registros y queda con una sede y un dispositivo por defecto. La contraseña del dispositivo **no aparece en claro** en la base de datos ni al serializar el modelo, y hay una prueba que lo verifica explícitamente. Las pruebas de caracterización de la Fase 0 siguen pasando sin modificarse. |

### Fase 1b — Identidad del empleado por credencial

> Fase propia porque **sí toca el núcleo**, al contrario que la 1 y la 2. Separarla permite que el refactor de adaptadores siga siendo un cambio sin efectos funcionales.

| | |
| --- | --- |
| **Tareas** | Tabla `EmpleadoCredencial`. Sustituir la resolución por igualdad de cadenas (`primaryjoin` de `backend/models.py:47` y `:78`) por una búsqueda de dos columnas. Adaptar `generar_reporte` y `calcular_tardanzas_dia`. Nueva restricción de unicidad anclada al número de serie del aparato. Adaptar `sync_empleados`, que es el segundo consumidor de ISAPI y hoy no aparece en ninguna fase. Reconciliación por la pantalla «Marcas sin Empleado Asociado» que ya existe. |
| **Entregables** | Migración con paso de datos. Núcleo adaptado. Flujo de reconciliación. |
| **Aceptación** | Una persona con credenciales en dos dispositivos produce **un solo empleado** en los informes. Un código desconocido genera una marcación sin empleado, visible en «Marcas sin Empleado Asociado», y asociarla desde ahí la incorpora al cálculo. Borrar y volver a crear un dispositivo **no duplica** su histórico al reextraer. Las pruebas de caracterización se actualizan **de forma explícita y justificada**: es la única fase autorizada a cambiarlas. |

### Fase 2 — Capa de adaptadores, con Hikvision como primero

| | |
| --- | --- |
| **Tareas** | Definir la interfaz de adaptador: **serializable y remota desde el principio** (§7.1), con capacidades declaradas y la taxonomía canónica de marcación (§7.4). Mover el código Hikvision actual detrás de ella, incluida la traducción de `EVENT_MAP` y `AUTH_MINORS` a la taxonomía. Eliminar `device_config.py` y sus constantes de módulo: la configuración se resuelve por dispositivo, en tiempo de ejecución. Registro de adaptadores por tipo. |
| **Entregables** | Interfaz de adaptador. Adaptador Hikvision. `device_config.py` borrado. |
| **Aceptación** | **Refactor sin cambio funcional**: las pruebas de caracterización pasan sin modificarse. No queda ninguna referencia a `DEVICE_IP`, `DEVICE_USER` ni `DEVICE_PASS` en el código ni en `.env.example`. La extracción funciona contra el Hikvision real de REDIHOS leyendo la configuración desde la base de datos. **El contrato del adaptador se serializa y se deserializa sin pérdida en una prueba**, aunque todavía no viaje a ningún sitio: es lo que permite que el agente de la Fase 7 reutilice el mismo código. |

### Fase 3 — Administración: alta de dispositivos y prueba de conexión

| | |
| --- | --- |
| **Tareas** | Pantallas de Sedes y Dispositivos en el módulo de Administración, con la estética existente. Alta, edición y baja. Selector de tipo de biométrico que muestra su estado de compatibilidad. Botón de prueba de conexión con informe de diagnóstico descargable. Permisos por rol para la gestión de dispositivos. |
| **Entregables** | Pantallas nuevas. Endpoints. Prueba de conexión con diagnóstico. |
| **Aceptación** | Un administrador da de alta un biométrico, prueba la conexión y extrae marcaciones **sin tocar ningún archivo ni reiniciar nada**. Un usuario sin el permiso correspondiente no ve ni puede invocar la gestión de dispositivos. El informe de diagnóstico **no contiene la contraseña**. |

### Fase 4 — Extracción e informes multi-dispositivo

| | |
| --- | --- |
| **Tareas** | Orquestar la extracción sobre N dispositivos. Aislar el fallo de un equipo para que no tumbe el lote. Filtro por sede en los informes. Revisar la fusión de marcas y la deduplicación cuando hay varios equipos. Programación de extracciones por dispositivo. |
| **Entregables** | Extracción multi-dispositivo. Informes con filtro de sede. |
| **Aceptación** | Con tres dispositivos configurados y uno apagado, la extracción termina, reporta el fallo del apagado y guarda las marcaciones de los otros dos. Un empleado que marca en dos sedes el mismo día aparece correctamente y sin duplicar. |

### Fase 5 — ZKTeco por empuje (ADMS)

| | |
| --- | --- |
| **Tareas** | Servidor que atiende `/iclock/cdata` y `/iclock/getrequest`, aceptando las variantes de ruta por firmware. Traducción del formato `ATTLOG` a la taxonomía canónica (§7.4), completando la zona horaria desde la sede. **Pasarela de ingesta** (§7.9): pre-registro por número de serie, secreto por dispositivo, límite de caudal, reenvío cifrado a la instancia. En modo local, el mismo endpoint lo sirve el propio servidor del cliente, sin pasarela. Instrucciones de configuración del aparato. |
| **Entregables** | Adaptador ZKTeco push. Pasarela de ingesta. Documentación de puesta en marcha. |
| **Aceptación** | Un equipo ZKTeco prestado, apuntado a la plataforma, entrega marcaciones que aparecen en el panel **sin agente y sin abrir puertos en la red del cliente**. Se prueba con al menos dos variantes de ruta. **Una serie no pre-registrada se rechaza en la pasarela y no alcanza ninguna instancia.** Una serie válida con secreto incorrecto también se rechaza. La pasarela **no persiste** ninguna marcación: hay una prueba que lo verifica. El mismo equipo funciona en modo local apuntando directamente al servidor del cliente. |

### Fase 6 — ZKTeco por consulta y ESSL

| | |
| --- | --- |
| **Tareas** | Adaptador sobre el puerto 4370 apoyado en `pyzk`. Comprobar qué modelos ESSL responden al mismo protocolo. Documentar modelos y firmwares probados. |
| **Entregables** | Adaptador ZKTeco pull. Nota de compatibilidad ESSL. |
| **Aceptación** | Se extraen marcaciones de un ZKTeco prestado por el puerto 4370. Cada modelo probado queda registrado en la matriz con su firmware. Los que fallan quedan documentados con el motivo. |

### Fase 7 — Agente local

| | |
| --- | --- |
> **Solo aplica al modo nube.** En modo local el servidor ya está en la red del aparato y consulta directamente, sin agente. El agente ejecuta **el mismo código de adaptador** que el servidor, gracias al contrato serializable fijado en la Fase 2.

| | |
| --- | --- |
| **Tareas** | Agente en Python: se registra contra la nube, recibe su lista de dispositivos, consulta, sube. Cola en disco y reintento. Instalador para Windows y servicio que arranca con el equipo. Actualización del propio agente. |
| **Entregables** | Agente. Instalador Windows firmado. Guía de instalación. |
| **Aceptación** | El agente se instala en un Windows limpio con el instalador, sin configuración manual más allá de un código de vinculación. Cortada la conexión 30 minutos, al restablecerse sube lo acumulado sin duplicar. **No escribe credenciales en disco.** **El adaptador Hikvision corre sin cambios dentro del agente y dentro del servidor**: si hubo que modificarlo para que funcione en los dos sitios, el contrato de la Fase 2 estaba mal y se corrige allí. |

### Fase 8 — Dahua

| | |
| --- | --- |
| **Tareas** | Obtener el `DAHUA_HTTP_API` de la versión de firmware. Adaptador CGI. Pruebas contra equipo prestado. |
| **Entregables** | Adaptador Dahua, o informe de abandono. |
| **Aceptación** | Se extraen marcaciones de un Dahua prestado. Si tras 2 días de trabajo no se consigue, se documenta lo aprendido y la marca se marca como no soportada. **Ambos desenlaces son resultados válidos de la fase.** |

### Fase 9 — Marcas condicionadas: Suprema y Anviz

| | |
| --- | --- |
| **Tareas** | Suprema: adaptador contra `POST /api/events/search` de BioStar 2, con paginación. Anviz: iniciar el registro de partner y evaluar según resultado. |
| **Entregables** | Adaptador Suprema, documentado como «requiere BioStar 2 del cliente». Decisión sobre Anviz. |
| **Aceptación** | Suprema aparece en la interfaz con su requisito escrito, de modo que nadie lo compre por error. Anviz se incluye solo si el SDK se obtuvo; si no, queda explícitamente fuera. |

### Fase 10 — Aprovisionamiento de clientes

| | |
| --- | --- |
| **Tareas** | **Dos plantillas de despliegue: nube y local (R10).** Script de alta en nube que crea instancia, base de datos, subdominio, certificado, clave de cifrado y administrador inicial. Instalador para el modo local. Generación y custodia de la `FERNET_KEY` por instancia (§7.7). Respaldos y procedimiento de actualización **para cada modo**. |
| **Entregables** | Automatización del alta en nube. Instalador del modo local. Procedimientos de actualización y respaldo, uno por modo. |
| **Aceptación** | Dar de alta un cliente en nube es **un comando** y termina con un entorno accesible y funcional. El modo local se instala en un servidor limpio siguiendo su guía, sin pasos manuales no documentados. Actualizar todas las instancias de nube es un procedimiento ensayado sobre al menos dos. **La restauración desde copia incluye la clave de cifrado y demuestra que tras restaurar se extraen marcaciones sin volver a teclear ninguna contraseña de dispositivo.** |

### Fase 11 — Compatibilidad pública y distribución

| | |
| --- | --- |
| **Tareas** | Matriz de compatibilidad pública por marca, modelo y firmware. **Envío automático de diagnósticos con consentimiento** (§7.10): consentimiento en el alta, revocable, con vista de lo enviado. Material de instalación para el cliente. Paso de REDIHOS al producto nuevo **en modo local**, que es donde ya está. |
| **Entregables** | Matriz publicada. Canal de diagnósticos con su consentimiento. Documentación de cliente. REDIHOS sobre el producto nuevo. |
| **Aceptación** | La matriz distingue verificado, en pruebas y sin verificar, y **ningún modelo figura como verificado sin una prueba real que lo respalde**. El envío de diagnósticos no sale sin consentimiento, y una prueba verifica que **nunca incluye marcaciones, empleados, credenciales ni el nombre del cliente**. Revocar el consentimiento detiene el envío. REDIHOS opera sobre el producto nuevo con su histórico íntegro. |

---

## 10. Lo que queda a criterio de quien construya

- Organización interna de los módulos de adaptadores.
- Mecanismo concreto de la cola en disco del agente.
- Herramienta de empaquetado del instalador de Windows.
- Formato del informe de diagnóstico.
- Si la programación de extracciones sigue con APScheduler o cambia.

## 11. Preguntas abiertas

1. **Nombre del producto** y si el repositorio nuevo es público o privado.
2. **Quién aloja la nube** y con qué presupuesto mensual. Condiciona la Fase 10.
3. **Modelo de cobro**, si lo hay, y si el producto debe llevar control de licencia. Con dos modos de despliegue la pregunta se agranda: en modo local el software corre en una máquina que no controlas.
4. **Cuándo llega el préstamo de equipos** del integrador: las fases 5, 6 y 8 dependen de esa ventana y probablemente haya que agruparlas en una sola campaña.

> Resueltas en la revisión del 10-nov: identidad del empleado por credencial (§8.2), dónde corre el adaptador (§7.1), taxonomía de marcación (§7.4), zona horaria (§7.5), fusión entre equipos (§7.6), custodia de la clave (§7.7), dos modos de despliegue (R10), pasarela de ingesta (§7.9), diagnósticos con consentimiento (§7.10) y destino de REDIHOS (Fase 11, modo local).

---

## 12. Fuentes de la investigación de protocolos

- ZKTeco ADMS / Push: [implementación de referencia](https://packagist.org/packages/dewanlab/laravel-zkteco-adms-core), [sentido del tráfico y configuración del equipo](https://get.clockit.io/en/zkteco/zkteco-iclock-680), [variante de ruta por firmware](https://kiwix.lema.org/stackoverflow.com_en_all_2023-11/questions/49049235/nodejs-express-receive-data-from-zkteco-device)
- ZKTeco por consulta: [pyzk](https://pyzk.readthedocs.io/)
- Suprema BioStar 2: [API de búsqueda de eventos](https://support.supremainc.com/en/support/solutions/articles/24000054050--biostar-2-api-how-to-retrieve-the-event-logs-through-biostar-2-new-local-api)
- Anviz: [Local Web API, con descarga tras registro de partner](https://community.anviz.com/t/anviz-local-web-api/2761)
- ESSL: [integración de terceros vía base de datos](https://apps.odoo.com/apps/modules/19.0/aspl_biometric_attendance)
