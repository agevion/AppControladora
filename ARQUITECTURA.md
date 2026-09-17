# AppControladora — Arquitectura y plan

Control del PC desde el móvil mediante dos IAs: Claude Code (razonamiento, desarrollo)
e IA local (ejecución barata de acciones rutinarias), sobre una capa de herramientas común.

---

## 1. Objetivos

- Hablar desde el móvil con **dos chats**: Claude Code y la IA controladora local.
- Que la IA local **administre el PC entero** —cualquier cosa que haría una persona
  sentada delante: abrir programas, tocar ficheros, mirar procesos, lo que sea—
  **sin gastar tokens**. Barata no es lo mismo que limitada: ver §8.0.
- Funcionar **dentro y fuera** de la red de casa.
- Recibir **builds** (APK) en el móvil e instalarlos.
- **Ver y controlar** el PC por vídeo cuando haga falta.
- La IA local **no reside en memoria**: se carga bajo demanda y se descarga al dormir.
- **Sin apps de terceros en el móvil.** Solo la app propia.

Entornos a controlar: Android Studio, IntelliJ IDEA (mods Java), Unity.

---

## 2. Hardware verificado (2026-07-16)

| | |
|---|---|
| GPU | NVIDIA GTX 1080 Ti — **11 GB VRAM** (Windows reporta 4 GB por bug conocido de `AdapterRAM`; `nvidia-smi` dice 11264 MiB) |
| CPU | AMD Ryzen 7 5700X3D, 8 núcleos |
| RAM | 32 GB |
| OS | Windows 10 Pro 19045 |
| Ya instalado | Python 3.10, Git |
| Falta instalar | Ollama, Node (para Claude Code) |

### Rutas descubiertas (las necesita el registry de tools de la Fase 1)

El PATH **no tiene** java, adb, gradle ni node. Todo por ruta absoluta:

| | |
|---|---|
| SDK Android | `C:\Users\<usuario>\AppData\Local\Android\Sdk` |
| adb | `…\Sdk\platform-tools\adb.exe` |
| JDK (el de Android Studio) | `C:\Program Files\Android\Android Studio\jbr` — OpenJDK 21.0.10 |
| Android Studio | `C:\Program Files\Android\Android Studio\bin\studio64.exe` |
| JetBrains | `C:\Program Files\JetBrains` |
| Unity Hub | `C:\Program Files\Unity Hub\Unity Hub.exe` |
| Platforms | android-34, 35, 36, 36.1 · build-tools 36.0.0, 36.1.0, 37.0.0 |

**Stack de build de referencia** (copiado de `E:\PokeOverlay`, que ya compila aquí):
Gradle 9.4.1, AGP 9.2.1, Kotlin 2.2.10, Compose BOM 2026.02.01. AGP 9 lleva Kotlin
integrado, por eso no hace falta el plugin `kotlin-android`.

**Implicación:** un modelo 7-8B en Q4 ocupa ~5 GB de VRAM y carga en 3-5 s. El coste de
"despertar" es despreciable, así que se puede descargar agresivamente. Un 14B cabría, pero
para traducir intención → llamada a función un 7-8B sobra y va al doble de velocidad.

**Nota Pascal:** la 1080 Ti no tiene tensor cores modernos (ni BF16/FP8). GGUF por
llama.cpp/Ollama funciona perfectamente; no intentar cargar modelos en FP16 nativo.

---

## 3. Red — verificado

| | |
|---|---|
| IP pública | `203.0.113.10` (ejemplo — sustituye por la tuya) |
| IP local del PC | `192.168.1.X` (ejemplo — la real va en `config.json`) |
| Gateway | `192.168.1.1` |
| **CGNAT** | **NO.** El salto 2 del traceroute es pública y del mismo /24 que la IP pública del PC. IP pública real. |
| Interfaz a ignorar | Radmin VPN (rango `26.x.x.x`) — no tiene cliente Android, no se usa |

**Consecuencia importante:** al haber IP pública real, en la Fase 4 el WebRTC conecta
**directo (P2P)**. No hace falta TURN, ni VPS, ni relé de ningún tipo.

---

## 4. Decisiones tomadas

| Decisión | Elegido | Motivo |
|---|---|---|
| Conectividad | **Tailscale** (revisado en Fase 0) | Ver §4.1. Sustituye a port forward + DDNS. |
| App móvil | **Kotlin + Compose** | Ya hay Android Studio; instalar APKs, foreground service y WebRTC son limpios en nativo. |
| Permisos IA local | **Lista cerrada + shell con confirmación** | Tools fijas para lo rutinario; comando libre solo con Permitir/Denegar en el móvil. |
| Ampliación de tools | **Dos vías: la IA local congela comandos, Claude Code escribe código** | Ver §8. La IA local sigue sin escribir código que se ejecuta. |
| TLS | **Autofirmado + mTLS + pinning** | Sin CA, sin renovaciones. El puerto no responde a quien no tenga el cert de cliente. Se mantiene *por encima* de Tailscale (ver §4.1). |

### 4.1 Por qué Tailscale reemplazó a port forward + DDNS

Durante la Fase 0, montar port forward + firewall público resultó mucho más frágil de lo
esperado (ver §10, notas de depuración). El usuario ya tenía Tailscale instalado en el
móvil por otro proyecto (impresora 3D) — reutilizarlo es coste marginal cero, no una
app nueva.

**Cambia respecto al plan original:**
- Ya no hace falta port forward en el router, ni DDNS, ni exponer el 8443 a la
  internet pública. La app le habla al PC por su IP de Tailscale (`100.x.y.z`),
  una red privada que solo existe entre los dispositivos del propio tailnet.
- El problema de CGNAT/IP dinámica (§3, §11) deja de importar: Tailscale atraviesa
  NAT solo. Da igual que la IP pública cambie.
- El "no quiero apps de terceros" original se relaja aquí a propósito: la app ya
  estaba instalada, y a cambio se elimina toda la superficie de exposición pública
  además de la complejidad de router+DDNS+firewall-público. Balance neto: menos
  piezas moviéndose, no más.
- **mTLS se mantiene.** Tailscale ya cifra y autentica el transporte (WireGuard),
  pero mTLS+token es defensa en profundidad barata (ya estaba construida) y sigue
  siendo quien decide qué puede hablarle al servicio, no solo qué puede alcanzarlo.

**Persistencia necesaria en los dos lados** (para que sea "siempre disponible" sin
tocar nada a mano):
- **Móvil:** Ajustes → Red → VPN → Tailscale → **VPN siempre activa**. Ya estaba
  activada de la config previa de la impresora.
- **PC:** icono de la bandeja → Preferencias → **Ejecutar sin supervisión**
  (unattended mode). Desacopla la conexión de la sesión de escritorio interactiva,
  igual que "VPN siempre activa" en Android. **Pendiente de confirmar que quedó
  activado** — sin esto, un reinicio del PC puede dejar Tailscale en `NeedsLogin`
  hasta que alguien inicie sesión en el escritorio.
- `run.py` llama a `controladora/tailscale.py::ensure_up()` al arrancar como red de
  seguridad adicional: si Tailscale no está `Running`, intenta `tailscale up`. Nunca
  bloquea el arranque del servidor (en LAN funciona igual sin Tailscale). Ver §5.0:
  es parte del arranque de una sola pieza, junto con Ollama.

---

## 5. Arquitectura

### 5.0 Cómo se arranca

**Doble clic en `pc\arrancar.bat`** (o `python run.py` desde `pc/`). Eso es todo: no hay
que levantar nada a mano ni en ningún orden concreto.

`run.py` deja el sistema entero en pie:

| Paso | Qué hace | Si ya estaba |
|---|---|---|
| Job de Windows | mete **al propio proceso** en un job con `KILL_ON_JOB_CLOSE`, antes de lanzar nada | — |
| Tailscale | `tailscale up` si no está `Running` | lo detecta y sigue |
| Ollama | lanza `ollama serve` (hereda el job de arriba) y espera a que abra el puerto | lo detecta y sigue, y **no lo toca** al cerrar: no es suyo |
| Sensores | dispara la tarea `ControladoraSensores`, que abre LibreHardwareMonitor **elevado** (temperatura de CPU) | lo detecta y sigue, y **no lo toca** al cerrar: no es suyo |
| Registry | carga las tools y **avisa de las rotas antes** de que las pidas desde el gym | — |
| Servidor | uvicorn con mTLS | aborta con un mensaje claro (puerto ocupado = ya lo arrancaste) |

**Los preparativos avisan, no bloquean.** Solo se aborta si falta algo sin lo cual el
servicio no puede existir: los certificados, o el puerto ya ocupado. Que Ollama no esté
es un aviso, no un error: el chat de Claude Code funciona igual, y el de la IA local dará
un mensaje claro cuando lo uses.

**Sin rastro al cerrar.** Decisión explícita: si `arrancar.bat` no está abierto, no debe
quedar nada corriendo — ni Ollama, ni un `claude.exe` del Agent SDK a medio turno, ni un
`gradlew.bat` a medias. Esto **revierte** lo que se hizo al principio (Ollama desacoplado a
propósito para sobrevivir al reinicio del servidor): se prefirió explícitamente "sin rastro"
por encima de "reinicio rápido". El coste es que tras cada reinicio del `.bat`, la primera
pregunta a la IA local vuelve a tardar ~38 s (carga de los 5.2 GB en VRAM, ARQUITECTURA.md
§7) en vez de los ~0.5 s en caliente.

Cómo se consigue de verdad, y por qué no basta con `atexit` (`controladora/winjob.py`):
cerrar la ventana con la X, un `taskkill /F`, o un crash **no** dan ninguna garantía de que
se ejecute código de limpieza propio — de hecho `claude_agent_sdk` ya registra un `atexit`
para matar su `claude.exe`, y ese `atexit` **no dispara** en una terminación forzosa (solo
en salida limpia). La garantía real la da el kernel: `run.py` mete **su propio proceso** en
un [Job Object](https://learn.microsoft.com/windows/win32/procthread/job-objects) con
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` nada más arrancar. Windows hereda ese job en todo hijo
que se lance después (Ollama, un futuro `claude.exe`, cualquier tool con `subprocess`) salvo
que pida explícitamente escaparse, y en el instante en que el proceso padre termina — **sea
como sea** — el kernel mata a todo lo que esté dentro del job. No hace falta ser
administrador. Verificado de extremo a extremo: `arrancar.bat` → Ollama arriba → `Stop-Process
-Force` al servidor (el equivalente exacto de cerrar la ventana con la X sin margen de
gracia) → Ollama muerto en el mismo instante, sin código de limpieza propio de por medio.

**LibreHardwareMonitor es el único que el job NO puede matar, y hay que saberlo.**
LHM tiene que correr **elevado** (su driver lee la temperatura de la CPU y sin
privilegios no carga), y `run.py` corre como usuario normal. Quien crea de verdad
un proceso elevado es el Programador de tareas, no nosotros: **LHM nace fuera de
nuestro job** y el kernel no se lo lleva al cerrar. No es un olvido, es que no se
puede meter ahí. Se resuelve por el otro lado (`scripts/sensor_supervisor.py`): el
supervisor va elevado, abre LHM, y se queda mirando el PID de `run.py`; en cuanto
desaparece —da igual cómo— mata LHM. Cubre el caso real (cerrar la ventana), pero
es honesto decir que **no es la misma garantía**: si al supervisor lo matan a la
fuerza, LHM se queda. Y si LHM ya estaba abierto antes, no se toca al salir —mismo
criterio que con Ollama: sólo se cierra lo que hemos abierto nosotros.

Primera versión de esto (2026-07-17): una tarea que abría LHM **al iniciar sesión**.
Estaba mal y se corrigió — dejaba LHM corriendo con o sin servidor, que es
exactamente el rastro que esta sección dice que no debe quedar. Se borra sola al
pasar `pc\instalar_admin.bat`.

**Tailscale es la excepción, a propósito.** Es un servicio del sistema pensado para estar
siempre activo (§4.1) y lo usan otros proyectos además de este (la impresora 3D); apagarlo
al cerrar `arrancar.bat` tendría efectos fuera de esta app, así que `run.py` nunca lo toca al
salir. Verificado: tras matar el servidor a la fuerza, `tailscaled` sigue vivo.

**El `.bat` existe** porque el PATH de este PC no tiene python: hay que usar sí o sí el del
entorno virtual, por ruta absoluta (§2). Y no se cierra sin que leas el error si falla.

```
                MÓVIL — app Kotlin/Compose
        [Chat Claude] [Chat Local] [Terminal] [App] [Vídeo] [Builds] [Aprobaciones]
                          │
                          │  WSS :8443  ·  mTLS + token  ·  cert pinning
                          ▼
              Tailscale — IP 100.x.y.z del PC  (§4.1; ya no hay port forward)
                          ▼
              PC — servicio "Controladora" (Python 3.10 + FastAPI)
          │
          ├── Cerebro A: Claude Code    (Agent SDK, sesión por proyecto)
          ├── Cerebro B: IA local       (Ollama, Qwen 7-8B Q4, carga bajo demanda)
          ├── Cerebro C: Terminal       (SIN LLM: el comando lo tecleas tú, va elevado)
          ├── Cerebro D: la App         (pilota la app de escritorio de Claude, §5.1)
          │
          └──────────► CAPA DE TOOLS (compartida por los cerebros) ◄──────────
                       registry de módulos Python, recarga en caliente
```

**Principio rector:** la capa de tools es **una sola**. Se escribe `build_gradle` una vez y
la invocan los dos cerebros. Añadir una tool la hace aparecer en ambos chats gratis.

**Principio secundario:** para buildear **no se pilota el IDE**. Se llama a `gradlew.bat` o a
Unity en `-batchmode -executeMethod`. Es infinitamente más fiable que buscar el botón de Play
en una captura. El vídeo y el control de ratón son para cuando de verdad hay que *ver* algo,
no para el flujo normal.

**Rutas absolutas:** el PATH no tiene java, adb, gradle ni node. El registry de tools debe
usar rutas absolutas configuradas, nunca depender del PATH.

### 5.1 Cerebro D — pilotar la app de escritorio (2026-08-10)

Los cerebros A, B y C hablan con un modelo o con una shell. Este no: **maneja la aplicación
de escritorio de Claude que está abierta en el PC**, la de verdad. Escribe en su compositor,
pulsa sus botones y lee su conversación. Lo que pasa, pasa en la ventana que ves — no hay
proxy ni copia headless. Existe porque la app tiene cosas que el CLI no (Cowork, artefactos,
conectores, el navegador integrado), y controlarla con AnyDesk es tosco: manda el PC entero
en píxeles y te obliga a apuntar con el dedo a una UI de escritorio.

Vive en `pc/controladora/appctl/`, un fichero por responsabilidad: `hilo` (el hilo único de
COM), `window` (encontrar/abrir la ventana, solo Win32), `uia` (leer y pulsar), `sessions`
(las conversaciones, leídas de disco), `input` (escribir y enviar).

**Nota (v16):** la frase de arriba ("controlarla con AnyDesk es tosco: manda el PC entero
en píxeles") sigue siendo la razón por la que el **chat** con la app pasa por UIA/`input.py`
y no por vídeo genérico. Pero el panel de vídeo que había DENTRO de esta misma pestaña
dejó de estar atado a la ventana de Claude: desde v16 es pantalla completa, con selector de
monitor y control real de ratón/teclado -- justo lo que aquí se descartaba, ahora pedido a
propósito para ese panel. Ver `appctl/pantallas.py` y `appctl/pantalla_input.py`, y la nota
al final de §Fase E más abajo.

**Lo que se descartó, y por qué no se va a volver a intentar.** La app **bloquea el depurador
remoto a propósito**. En `app.asar`:

```js
if (rae(process.argv) && !_9()) process.exit(1)
```

`rae` busca `--remote-debugging-port` / `--remote-debugging-pipe` y `_9` exige un
`CLAUDE_CDP_AUTH` firmado con Ed25519 (clave pública incrustada, caduca a los 300 s, atado a
`CLAUDE_USER_DATA_DIR`). Sin la clave privada de Anthropic no hay CDP. Parchear el asar
rompería la firma MSIX además de saltarse un control del fabricante: **no se hace**.

**Los cuatro hechos que sostienen el diseño.** Todos medidos con `scripts/probe_appctl.py`,
ninguno supuesto:

| Hecho | Consecuencia en el código |
|---|---|
| El árbol de accesibilidad de Chromium está **apagado** hasta que un cliente UIA pregunta (14 nodos → ~990) | El cliente UIA vive en un hilo propio y dura lo que el proceso: si se tira, el árbol se apaga |
| El compositor es un **contenteditable**, así que no tiene `ValuePattern` | No se le puede asignar el texto: hay que teclearlo |
| Con otra ventana delante, los `WM_CHAR` **se descartan en silencio** | Traer la ventana al frente no es opcional. `input.py` enfoca primero y **aborta** si no lo consigue, en vez de teclear a ciegas |
| `SetFocus()` de UIA trae la ventana al frente donde `SetForegroundWindow` falla (probado contra un juego a pantalla completa) | La vía principal es UIA; Win32 es el plan B y el único camino para *devolver* el foco |

**El tipo de control del compositor NO es un selector estable (2026-08-25).** Se buscaba como
un `Group` enfocable con `TextPattern`, y una actualización de la app lo cambió a un `Edit`
(pasó a tiptap). El selector devolvió **cero candidatos** y con eso se cayeron dos cosas a la
vez: escribir desde el móvil (`no encuentro el compositor: no se puede enfocar`) y la lista de
`mandos`, que se calcula respecto a la posición del compositor — o sea que la pestaña App se
quedó sin un solo botón. Desde fuera parecía "la app del móvil está rota".

Lo estable no es el rol sino de qué está hecho: es un **ProseMirror**, y eso sale en el
`ClassName` (`tiptap ProseMirror ProseMirror-focused`). No se traduce y no depende de lo que
la app decida exponer. `_buscar_compositor` busca por ahí y deja el criterio viejo como
respaldo. La lección general: en este árbol, **el rol es un detalle de implementación de la
app; la clase CSS es su contrato con el DOM**.

**Leer no es scrapear.** La app escribe por su cuenta dos cosas mucho mejores que la pantalla:
el índice `%APPDATA%\Claude\claude-code-sessions\<cuenta>\<dispositivo>\local_*.json` (título,
cwd, modelo, esfuerzo, modo de permisos y el `cliSessionId`) y la transcripción en
`~/.claude/projects/<cwd-con-guiones>/<cliSessionId>.jsonl`, que se va escribiendo mientras
Claude trabaja. De ahí sale el texto exacto, con sus bloques separados y sin depender de que
la UI cambie de sitio. La pantalla sólo hace falta para lo que de verdad es visual.

**Cuál es la sesión "activa" tiene dos respuestas y no son la misma.** El índice sabe cuál se
tocó más recientemente; la barra lateral sabe cuál se está **viendo**. Se usa la segunda
(`uia.Vista.titulo_abierto`), y se distingue por una diferencia limpia: el botón de la
cabecera lleva el título pelado y los de la barra lateral lo llevan con el estado delante
("En ejecución X"). Confundirlas muerde justo cuando importa — con otra sesión trabajando en
segundo plano, el índice apunta a esa y se leerían **sus** mensajes como si fueran la
respuesta. Y una sesión recién abierta con "Nuevo" **no existe en el índice** hasta que se
envía el primer mensaje: para esa hay `sessions.aparecida()`.

**Todo el texto traducible está en un solo sitio.** La app está en español en este PC, así
que los selectores son estructurales siempre que se puede (rol + patrones + geometría). Donde
no queda más remedio que mirar palabras —el estado de cada sesión, cuatro botones de
navegación— las tablas `ESTADOS` y `ETIQUETAS` de `uia.py` son el único lugar donde aparecen,
y lo que no se reconoce se devuelve **en crudo** en vez de inventarse un valor.

**Seguridad: el radio de daño crece, y hay que decirlo.** Esto es "teclear lo que sea en una
app que puede estar en modo automático", o sea ejecución remota de código en el PC. La
frontera sigue siendo la de siempre (mTLS + token, §9) y sigue sin correr como administrador,
pero por eso `claude_app_enviar` **siempre** pide confirmación: la tarjeta del móvil es donde
se ve el texto exacto antes de que salga.

**El sistema se puede morder la cola, y cuesta media hora entenderlo.** Si quien pilota la app
es una sesión que corre DENTRO de esa misma app, las órdenes le caen encima a sí misma. Pasó,
tres veces seguidas: `app.stop` manda **Escape** a la ventana, y ese Escape aterrizó sobre la
tarjeta de aprobación de la propia orden que lo había lanzado. La app lo leyó como "cancelado",
la herramienta murió sola y desde fuera se veía exactamente como *"el usuario ha rechazado la
ejecución"* — con el usuario jurando, con razón, que no había tocado nada.

Lo mismo vale para cualquier clic: pulsar un botón trae la ventana al primer plano y puede
cerrar un desplegable o un diálogo que estuviera abierto, sea de quien sea. Reglas que salen
de aquí:

- Las pruebas automáticas **nunca** mandan Escape ni pulsan mandos sueltos sobre la sesión que
  las está ejecutando (ver el comentario largo en `scripts/test_appctl_ws.py`).
- Para probar esa parte hay que apuntar a **otra** conversación (`--sesion`).
- Desde el móvil no es un problema: ahí quien pilota está fuera del PC. Es un peligro del
  banco de pruebas, no del producto — pero el banco de pruebas es donde se pierde el tiempo.

### 5.2 Protocolo v12 y la pestaña "App" (2026-08-10)

`protocol.py` sube a **VERSION 12**: `Brain` gana `"app"`, `CHAT` gana `sesion` y `nueva`
(sólo los mira ese cerebro), y aparecen `app.request` / `app.open` / `app.new` / `app.press` /
`app.stop` con `app.state` de vuelta. Todos los `app.*` **terminan mandando el estado**, sin
excepción: el móvil no supone que su orden funcionó, dibuja lo que la aplicación dice de sí
misma después.

`app.press` es genérico —pulsa un botón por su nombre exacto— y eso no es pereza: es lo que
hace que **una tarjeta de permiso que saque la app se pueda aprobar desde el móvil** sin que
ni el PC ni el móvil tengan que conocerla de antemano. Sus botones llegan dentro de
`app.state.mandos` y se pulsan como cualquier otro. Por eso el Cerebro D no reenvía permisos
por `permission.request`: se aprueban tocando el botón de verdad, no una copia.

En el móvil es una cuarta pestaña de cerebro (`BRAIN_APP`), así que reutiliza entera la
maquinaria que ya había: mismo historial por cerebro, mismo indicador de turno, mismo
`chat.end`. Lo propio es `ui/AppPanel.kt`: la conversación abierta con su punto de estado, la
lista de conversaciones con la suya, los botones de la app y "Nueva"/"Parar". El estado se
refresca solo **sólo mientras se está mirando esa pestaña** — leerlo recorre el árbol de
accesibilidad entero del PC, y hacerlo en segundo plano sería gastar CPU para pintar algo que
nadie ve.

### 5.3 Traspaso: portapapeles y ficheros — protocolo v14 (2026-08-26)

Dos cosas que faltaban para no tener que pasar por WhatsApp para mandarse algo a uno mismo:
**el texto que se copia en el PC aparece en el portapapeles del teléfono**, y **desde el móvil
se eligen archivos y aterrizan en una carpeta del PC**.

Van por caminos distintos, y no por gusto:

- **El texto, por el WebSocket.** Son unos pocos KB y el socket ya está abierto y autenticado.
  `protocol.py` sube a **VERSION 14** con `clip.watch` / `clip.get` / `clip.set` del móvil al
  PC, y `clip.text` de vuelta.
- **Los archivos, por HTTPS** (`POST /upload`), igual que el APK baja por un `GET`
  (`artifacts.py`): una foto son varios MB, y ese socket lleva además el chat en *streaming* y
  el señalizado del vídeo. Meterlos ahí en base64 los infla un 33 % y deja el chat mudo
  mientras pasan. El cuerpo son los bytes pelados y el nombre viaja *percent-encoded* en
  `X-Nombre`: multipart obligaría a arrastrar `python-multipart` para no ganar nada — aquí
  siempre va un archivo por petición.

**Cómo se entera el PC de que has copiado algo.** `controladora/portapapeles.py` pregunta cada
medio segundo por `GetClipboardSequenceNumber`, un contador que Windows sube cuando alguien
escribe en el portapapeles. Consultarlo **no abre el portapapeles**, así que no le estorba a
nadie; sólo cuando el contador cambia se abre para leer. La alternativa "de verdad"
(`AddClipboardFormatListener` con una ventana oculta y su bucle de mensajes) pedía un segundo
hilo con su apartamento de COM, además del que ya tiene `appctl/hilo.py`, para no notarse.
El portapapeles es un recurso **exclusivo de todo Windows**: `OpenClipboard` falla de verdad y
a menudo (justo cuando otra aplicación está copiando), de ahí los reintentos, y se cierra
siempre — dejarlo abierto le cuelga el Ctrl+C al sistema entero, no sólo a nosotros.

El vigilante vive **por conexión**, como el vídeo y al revés que los cerebros: lo que hace es
empujar texto por ESE socket, así que no tiene sentido que siga corriendo cuando el socket
muere (`Session.parar_clip`, en el `finally` de `ws()`). Como muere con el socket, el móvil lo
vuelve a encender en cada `hello`. Y lo enciende **sólo si su interruptor lo dice**: apagado,
el PC ni mira su portapapeles. No es "no me lo mandes", es "no lo mires" — leer el
portapapeles ajeno es de esas cosas que uno quiere poder apagar de verdad.

El eco se corta con `Vigilante.recuerda()`: cuando el móvil manda su portapapeles
(`clip.set`), el PC da ese texto por visto **antes** de escribirlo. Sin eso, escribirlo sube el
contador de Windows, el vigilante lo ve como "algo nuevo copiado en el PC" y se lo devuelve al
móvil, que acaba de mandarlo.

**El techo de Android, que decide media pantalla.** Desde Android 10 una app sólo puede tocar
el portapapeles **mientras está en primer plano** (fue la respuesta a las apps que espiaban lo
que copiabas). `setPrimaryClip` desde el servicio en segundo plano no falla: no hace nada, que
es peor. Así que:

- lo que llega se guarda (`ChatStore._clips`, las diez últimas) marcado como *no copiado*;
- si la app está delante, se copia solo y se marca (`ChatScreen`, con `LifecycleResumeEffect`
  para saber si de verdad lo está);
- si no, sale un **aviso en la barra de notificaciones** en su propio canal, y al abrir la app
  se copia solo. Sin ese aviso, el traspaso de texto sólo funcionaría cuando ya estuvieras
  mirando la app, que es justo cuando menos falta hace.

Dar por copiado algo que Android descartó en silencio sería exactamente la clase de mentira
que este proyecto lleva quitando desde la Fase 1, así que el estado *copiado* sólo se pone
cuando la escritura ocurrió con la app delante.

**Los ficheros.** `controladora/recibidos.py` decide dónde caen: `paths.json` → `"recibidos"`,
y si falta, `Documentos/ControlaPics`. El nombre **lo elige el móvil**, o sea que viene de
fuera: se reduce al último tramo (una ruta dentro del nombre se queda en nada), se le quitan
los caracteres que Windows no admite y los puntos y espacios del final, se desactivan los
nombres reservados del MS-DOS (`CON`, `NUL`, `COM1`…) y **se comprueba que el resultado cae
dentro de la carpeta** aunque la limpieza debiera bastar. No se sobrescribe nunca: un segundo
`image.jpg` se guarda como `image (2).jpg`, porque el móvil llama igual a fotos distintas
constantemente.

Se escribe a `.parte` y se renombra al terminar, así que la carpeta nunca enseña medio fichero
con su nombre bueno; y el móvil manda en `X-Bytes` lo que pesaba, que el PC compara con lo que
recibió — una subida cortada de una forma que no dio error se tira en vez de quedarse ahí
pareciendo entera.

En el móvil es una cuarta pestaña (`ui/Traspaso.kt`). Dos selectores y no uno: el *photo
picker* del sistema (sin ningún permiso, con miniaturas, que es lo que uno espera al mandar una
foto) y el de documentos para todo lo demás. Las subidas van **de una en una** y viven en
`ChatStore` — o sea en el servicio, no en el ViewModel: así una subida de 200 MB sigue viva
aunque salgas de la app, igual que el historial del chat.

`scripts/test_traspaso.py` cubre el lado del PC de punta a punta (las siete comprobaciones
pasan). Lo que **no** cubre es la parte de Compose: la misma lección de la Fase E.1 — aquellas
pruebas pasaban enteras con el móvil sin funcionar.

### 5.4 "Copiar selección" sobre el vídeo — protocolo v15 (2026-08-26)

Cierra el hueco que dejaba abierto el §5.3: el portapapeles del PC viaja solo al móvil, pero
hasta ahora no había forma de **generar** ese portapapeles desde el móvil salvo tecleando. La
Fase E.1 ya permite seleccionar texto sobre el vídeo (mantener pulsado + arrastrar, ver
`GestosVideo.decidir`); lo que faltaba era el Ctrl+C.

**Por qué es la única función del proyecto que usa `SendInput`.** Todo `appctl/input.py` evita
`SendInput` a propósito (ver la cabecera del módulo): inyecta en la cola *global* del sistema y
competiría con lo que el usuario esté tecleando de verdad. Pero un atajo con modificador no se
puede fingir con `PostMessage` — Chromium consulta el estado *real* del teclado
(`GetKeyState(VK_CONTROL)`) para saber si Ctrl estaba pulsado al procesar la tecla, y
`PostMessage` no toca ese estado. `appctl/input.copiar()` es la excepción deliberada: un Ctrl+C
sintetizado con `keybd_event`, sólo cuando el móvil ha pulsado "Copiar selección" a propósito, y
sólo tras comprobar que la ventana está *de verdad* en primer plano justo antes de mandarlo (si
algo se ha puesto delante entre medias, se aborta en vez de copiar a ciegas de otra aplicación).
El `finally` suelta Ctrl pase lo que pase, para que un fallo a mitad no deje la tecla "pulsada"
para el resto del sistema.

**El texto copiado no necesita un mensaje nuevo de vuelta.** `Session.app_copy` (v15,
`protocol.APP_COPY`) manda el Ctrl+C y, si salió bien, llama a `self.clip_get()` — el mismo
camino que ya existía para "dame lo que tengas copiado ahora" (§5.3). Funciona **pase lo que
pase con el interruptor `clip.watch`**: pedir explícitamente "copia esto" es distinto de
"avisame de lo que copies" y no debería depender de que el segundo esté encendido.

En el móvil, `VideoPanel` sólo enseña el botón "Copiar selección" cuando `onArrastrar` dispara
por una selección **real** — mantener pulsado y arrastrar, la misma rama que ya distingue
`GestosVideo` del desplazamiento normal — y se apaga solo con un toque o pasados 8 segundos. No
hace falta rastrear nada más fino: es justo la señal que el gesto ya calculaba.

---

## 6. Catálogo de tools (inicial)

Implementadas en `pc/tools/`. Un fichero = una tool. Contrato: `SPEC` (nombre, descripción,
JSON Schema) + `CONFIRM` (bool) + `run(**kwargs) -> str`. El registry (`controladora/registry.py`)
las descubre solas y las expone a los dos cerebros.

| Tool | Qué hace |
|---|---|
| `open_app(app, proyecto?)` | Lanza Android Studio / IntelliJ / Unity Hub, opcionalmente con un proyecto |
| `build_gradle(proyecto, tarea?)` | `gradlew.bat` con el JDK de Android Studio. Sin `tarea`, la elige `variantes.py`: release por defecto. Devuelve log + ruta del APK |
| `unity_build(proyecto, metodo)` | Unity CLI en batchmode. Requiere método de build en el proyecto |
| `adb_install(apk)` / `adb_devices()` | Instalación en dispositivo conectado al PC |
| `screenshot()` | Captura de pantalla puntual (guarda PNG, aún no viaja al móvil) |
| `list_projects()` | Proyectos conocidos y su estado |
| `ai_sleep()` | Descarga el modelo local de la VRAM (y **confirma** que se liberó) |
| `run_shell(comando, motivo, nombre_tool?)` | **CONFIRM=True: pide Permitir/Denegar/Guardar en el móvil.** Ya no es la vía de escape: es la vía normal para todo lo que se hace con un comando y no tiene tool propia (§8.1). |

Rutas y proyectos viven en `pc/paths.json` — sin secretos, **sí va al repo**, y es lo que
Claude Code edita al ampliar el sistema. El PATH de Windows no tiene java/adb/gradle/node,
así que ahí todo es ruta absoluta.

**Por qué `_util.py` empieza por guión bajo:** el registry ignora esos ficheros. El
`sys.path` lo prepara el registry una vez, no cada tool: cuanto menos boilerplate tenga el
contrato, más difícil es que Claude Code lo escriba mal al auto-ampliarse.

---

## 7. Ciclo de vida de la IA local

Se resuelve con `keep_alive` de Ollama, sin inventar nada:

- Petición con `keep_alive: 0` → el modelo se descarga de VRAM al terminar de responder.
- Petición con `keep_alive: "10m"` → residente ese rato por si la conversación sigue.
- `ollama serve` en reposo: unos cientos de MB de RAM y **0 VRAM**.

"Dormir IA" = descargar el modelo. "Despertar" = simplemente hablarle (3-5 s).
La GPU queda libre para Unity mientras tanto.

---

## 8. Auto-ampliación de tools

### 8.0 Qué es la IA local (corrección de 2026-07-17)

**La IA local es la administradora del PC.** Tiene que poder hacer *cualquier* cosa
que se pueda hacer en este ordenador: abrir y cerrar programas, crear y borrar
ficheros, mirar procesos, red, discos, servicios. Como una persona sentada delante
del teclado, a la que le hablas por un chat.

Esto hay que dejarlo escrito porque **el documento decía lo contrario y era un
malentendido mío**, no una decisión del proyecto. Llegó a poner que la IA local
*"se queda pequeña, rápida y tonta a propósito"* y que su trabajo era *"ejecutar
acciones de desarrollo"*, y el `SYSTEM_PROMPT` de `brain_local.py` decía *"tu único
trabajo es..."*. De ahí salía el síntoma real: pedirle cualquier cosa fuera del
guion y que contestara que no puede.

De dónde salió la confusión: de mezclar **dos cosas que no tienen que ver**.

| Lo que sí es cierto | Lo que NO se sigue de ello |
|---|---|
| El cerebro es pequeño y barato (8B local, cero tokens) | ~~Por tanto sólo puede hacer unas pocas cosas~~ |
| No escribe el código que se ejecuta (§8.1) | ~~Por tanto no puede administrar el PC~~ |
| Todo comando libre lo apruebas tú (§9) | ~~Por tanto hay que restringir lo que puede pedir~~ |

**Lo barato es el cerebro; el alcance es todo.** Puede administrar el PC entero
precisamente *porque* `run_shell` pasa por tu Permitir/Denegar: la frontera no es
lo que puede proponer, es que lo que corre lo lees tú antes (§9). Restringirle el
alcance no añadía ni un gramo de seguridad — sólo la hacía inútil y empujaba a
gastar tokens de Claude Code para abrir un programa.

**Las tools de `pc/tools/` no son su techo, son atajos.** Existen para lo
repetitivo: para no aprobar el mismo comando cada día y para que las secuencias
frágiles (§ `build_and_send`) salgan siempre igual. Que exista `open_app` no
significa que sólo pueda abrir esas tres apps: significa que esas tres son las que
abre sin preguntar.

Caso que lo destapó: desde el gym, querer el código de AnyDesk para recuperar el PC
si `arrancar.bat` se cierra. Ninguna IA fue capaz. Y no era falta de permisos ni de
capacidad — es que AnyDesk **ni siquiera está instalado** (es un portable suelto en
`Downloads`, sin servicio, fuera del PATH), así que no había nada que abrir por
convención y la IA, con el prompt viejo, se rendía en vez de ir a buscarlo. Ahora:
el prompt le dice explícitamente que busque el ejecutable y lo lance, y además hay
tool propia (`anydesk_id`) porque es justo el caso de "acceso rápido a algo
repetitivo" — y encima el único camino de recuperación que no depende de que el
resto del sistema siga en pie.

`MAX_ROUNDS` subió de 5 a 10 por lo mismo: administrar de verdad es encadenar pasos
(mirar si está → lanzarlo → esperar → leer el ID son cuatro), y a la quinta se
cortaba sola justo antes de contestar.

### 8.1 y 8.2 — las dos vías para ampliar

Hay **dos vías**, y la barata cubre la mayoría de los casos. La diferencia no es de
confianza, es de qué hace falta escribir: un comando o un programa.

### 8.1 Vía barata — la IA local congela un comando (sin tokens de Claude)

Para "ver los procesos" no hace falta el cerebro caro: la IA local ya sabe el comando
de PowerShell. Gastar tokens de Claude Code en escribir ese wrapper era desperdiciarlos.

1. Le pides algo para lo que no tiene tool pero **sí sabe hacer con un comando**.
2. Llama a `run_shell` con el comando, un `motivo` y un `nombre_tool` sugerido.
3. El móvil enseña el comando **literal** con tres botones:
   **Permitir** (una vez) · **Denegar** · **Guardar** (ejecutar y dejarlo fijo).
4. Con "Guardar", `controladora/toolgen.py` escribe `tools/<nombre>.py` y el registry
   recarga en caliente. La tool ya existe, sin reiniciar y sin gastar un token.
5. La próxima vez la llama sola, sin tarjeta: nace con `CONFIRM = False`.

**Por qué esto no rompe §9 pese a que la IA local "amplía el sistema":**

- **El modelo no escribe Python.** La plantilla de `toolgen.py` es fija y el comando
  entra como **dato** (`repr()`), nunca interpolado como código. Lo único que decide
  el modelo es el texto del comando — exactamente lo que ya decidía con `run_shell`.
  Verificado con un comando hostil que intentaba cerrar la cadena y colar
  `os.system("calc")`: quedó como texto inerte y PowerShell lo rechazó como sintaxis.
- **Se congela el comando literal, sin parámetros.** Una tool guardada no puede hacer
  nada distinto de lo que hizo delante de tus ojos. Por eso `CONFIRM = False` es
  honesto aquí y no lo sería en `run_shell`: allí el comando varía, aquí no puede.
- **Lo apruebas leyendo lo que se ejecuta**, no una descripción de lo que se ejecuta.
- No se guarda un comando que **falló** (sería congelar un error), ni un nombre que
  **tape un módulo de Python** — `tools/` está en `sys.path`, así que un
  `tools/subprocess.py` secuestraría el `subprocess` de todo el proceso, y el fallo
  aparecería lejos y raro (al compilar algo, media hora después).

Las tools generadas llevan `AUTOGEN = True` y dicen en su docstring de dónde salieron.
Para quitar una: borra el fichero y dale a "Recargar tools".

### 8.2 Vía cara — la escribe Claude Code

Cuando de verdad hace falta *programar*: parámetros, lógica, leer ficheros, encadenar pasos.

1. La IA local emite `missing_tool` ("Acción no disponible: <X>").
2. El botón salta al chat de Claude con el contexto ya montado.
3. Claude escribe `tools/<nueva>.py` conforme al contrato del registry.
4. El diff llega al móvil → lo apruebas.
5. El registry recarga en caliente.

**El sistema se amplía a sí mismo. Lo que se ejecuta lo apruebas tú siempre**, pero solo
se paga el cerebro caro cuando hay que escribir código de verdad.

Lo que aquí ponía —*"la IA local se queda pequeña, rápida y tonta a propósito: eso es
lo que la hace segura y barata"*— **era falso y está corregido en §8.0**. Pequeña y
rápida, sí: es un 8B local. Pero lo que la hace segura no es que sea tonta ni que le
recortemos el alcance, es que **no escribe el código que se ejecuta** y que **el
comando lo apruebas tú leyéndolo**. Con esas dos cosas en pie, puede administrar el
PC entero sin que la frontera de §9 se mueva un milímetro.

---

## 9. Seguridad

Esto es, literalmente, un endpoint de ejecución remota de comandos expuesto a internet.

- **mTLS**: sin certificado de cliente no hay ni handshake. Un escáner de puertos no ve
  un login que atacar, ve una conexión que se corta antes de existir.
- **Token** por encima del mTLS, en cada mensaje.
- **La IA local no tiene shell libre.** Un 8B se deja convencer de cualquier cosa y es
  justo el que está detrás de una caja de chat. `run_shell` siempre pasa por tu
  Permitir/Denegar/Guardar, y lo que lees en el diálogo es el comando literal.
- **El permiso se pide en un diálogo centrado y modal**, no en una tarjeta al final del
  chat. No es estética: como tarjeta, su alto salía de su contenido, y un `Edit` de
  Claude trae el fichero entero dentro de los args — la tarjeta crecía más que la
  pantalla y empujaba fuera de la vista sus propios botones y la caja de texto. El
  permiso quedaba imposible de contestar y la app, bloqueada. Ahora el alto está topado,
  el contenido hace scroll y **los botones viven fuera de ese scroll**. No se cierra
  tocando fuera ni con Atrás: un despiste no puede valer como "sí".
- **Un comando se enseña entero; el contenido de un fichero, en vista previa.** "Lo que
  lees es lo que corre" solo vale si lo que se ejecuta se ve completo, así que
  `run_shell` y `Bash` nunca se recortan (`ui/Args.kt`). El texto de un `Edit`/`Write` sí
  se recorta y **se anuncia el recorte**: ahí lo que apruebas es que Claude toque ese
  fichero, no revisar el diff entero de pie en el gym.
- **Un permiso que ya no se puede contestar se retira solo** (`permission.cancel`, v6):
  si caduca, o si su turno muere, la tarjeta desaparece en vez de quedarse pegada
  esperando una respuesta que ya no escucha nadie.
- **Las tools guardadas (§8.1) no son una excepción a lo anterior**, aunque no vuelvan a
  preguntar: cada una es un comando concreto que ya aprobaste leyéndolo, sin parámetros
  y sin poder variar. Lo que no puede la IA local es escribir el código que corre.
- **El silencio es un "no"**: si no contestas en 120 s, la acción no se ejecuta. Y una
  respuesta con una acción que el servidor no reconoce también cae en denegar.
- **Claude Code sí puede tener shell**, porque sus permisos se reenvían al móvil.
- El servicio corre como usuario normal. **Los comandos de administrador van por un
  ayudante aparte y cada uno se aprueba en el móvil** — ver §9.1.
- El cert de cliente y el token **no se commitean**. Fuera del repo.

### 9.1 Administrador: qué se decidió y qué cuesta (2026-07-17)

Aquí ponía *"el servicio corre como usuario normal, **nunca** como administrador"*.
Ese "nunca" se ha levantado a propósito, sabiendo lo que cuesta.

**El problema:** el UAC de Windows se pide **en el escritorio del PC**. Desde el gym
no hay quien lo pulse, así que *todo* lo que necesitara privilegios —instalar algo,
un servicio, HKLM— moría con "Access denied" y ahí se acababa. Un botón que no
puede funcionar no vale de nada: la IA local no sería la administradora del PC
(§8.0), sería la administradora de media docena de cosas.

**Cómo está montado** (`controladora/elevate.py`):

- Una tarea programada `ControladoraAdmin`, registrada **una sola vez** con
  `pc\instalar_admin.bat` (ese sí pide UAC, con alguien delante), con "privilegios
  más altos" y **sin ningún disparador**: no se ejecuta sola jamás.
- Windows lanza esas tareas ya elevadas y **sin UAC**, así que el servidor (usuario
  normal) puede dispararlas con `schtasks /run`. Deja el comando en
  `pc/.admin/request.json`, la tarea lo ejecuta y devuelve `result.json`.
- El ayudante es de **una sola pasada**: una petición, se ejecuta, se muere. No hay
  nada elevado escuchando de forma permanente.
- El ayudante dice si iba **elevado de verdad** mirando su propio token. Sin eso, una
  tarea mal registrada daría "Access denied" indistinguible de cualquier otro.

**Lo que esto cuesta, sin adornos:** crea un camino permanente para subir a
administrador **sin UAC**, y lo puede usar cualquier cosa que ya corra como este
usuario — no sólo nosotros. Basta con escribir el fichero y disparar la tarea.

**Por qué se acepta:** porque **UAC no es una frontera de seguridad, y lo dice
Microsoft**, no nosotros. Si algo malo ya corre como tú, tiene decenas de formas de
auto-elevarse. La frontera de este proyecto nunca fue UAC y sigue sin serlo: es
**mTLS + token + que tú leas el comando y lo apruebes**. Eso no se ha movido.

**Lo que sí se mantiene, y es lo que hace que esto sea defendible:**

- Lo normal **sigue sin privilegios**. Sólo sube lo que pide `admin=true`.
- Un comando admin **siempre** pasa por la tarjeta, y sale con una **banda roja**
  arriba del todo — antes del comando y **fuera del scroll**, porque si estuviera
  debajo, un comando largo la dejaría fuera de pantalla y aprobarías un admin
  creyendo que era normal.
- **Un comando admin NO se puede congelar como tool** con "Guardar". Una tool
  guardada nace con `CONFIRM=False`: "administrador para siempre y sin tarjeta" es
  exactamente lo que no queremos. Bloqueado en dos sitios: el móvil no ofrece el
  botón (`savable=false`) y el servidor lo rechaza igual aunque se lo pidan.
- Queda **log** en el PC de cada permiso admin pedido.

**Para deshacerlo entero**, como administrador:
`schtasks /delete /tn ControladoraAdmin /f` — sin la tarea, `admin=true` devuelve un
mensaje diciendo que no está instalado y no se ejecuta nada.

---

## 10. Fases

### Fase 0 — Espina dorsal  ▸ VERIFICADA EN DISPOSITIVO REAL (falta prueba fuera de casa)
Servicio FastAPI + WebSocket, mTLS, port forward, DDNS, y app con un chat que hace eco.
Parece poco: es el 80% del riesgo.
**Hecho cuando:** desde datos móviles escribes "hola" y te vuelve "hola" desde tu PC.

Verificado:
- [x] PKI propia (CA + server + client), sin binario de openssl
- [x] Servicio con mTLS obligatorio + token
- [x] Eco en streaming (`chat.delta` / `chat.end`)
- [x] Rechaza sin cert de cliente (corte en TLS) y con token inválido (403)
- [x] App Compose compila; APK con `ca.crt` y `client.p12` dentro
- [x] **Android sí lee el `client.p12`** — el mTLS completo (handshake + WS + token)
      funciona en dispositivo real (Pixel 6 Pro). La preocupación sobre el cifrado
      PKCS12 no se materializó.
- [x] Conectividad resuelta vía **Tailscale** en vez de port forward + DDNS (ver §4.1)
- [x] Chat de extremo a extremo verificado en dispositivo real: "hola" → "eco: hola"
- [x] **No uses `curl` para comprobar si el servicio está vivo.** El curl que trae Windows
      usa schannel, que **no sabe leer certificados PEM de cliente**
      (`Failed to import cert file certs/client.crt, 0x80092002`), así que el mTLS le corta
      el handshake siempre: parece el servidor caído sin estarlo. Para comprobarlo de
      verdad, usa los scripts de `pc/scripts/` (Python sí lee los PEM). Para saber solo si
      el puerto está ocupado:
      `Get-Process -Id (Get-NetTCPConnection -LocalPort 8443 -State Listen).OwningProcess`
- [ ] Confirmar "Ejecutar sin supervisión" quedó activado en el PC (ver §4.1)
- [ ] Prueba real **fuera de casa, con datos móviles** (todo lo probado hasta ahora
      fue en la misma LAN — Tailscale debería funcionar igual, pero no está probado)
- [ ] Limpieza de higiene: seguían existiendo reglas de firewall fantasma
      `Block/Inbound/DisplayName=python.exe` (auto-generadas por Windows al no
      responder a un aviso de "¿permitir esta app?" con el servidor en segundo
      plano). No bloquearon la ruta por Tailscale, pero conviene borrarlas
      igualmente por si se usa alguna vez conexión directa por LAN:
      `Get-NetFirewallRule -DisplayName "python.exe" -Action Block -Direction Inbound`
- [ ] Ya no son necesarios (dejar constancia, no hace falta hacer nada): reserva
      DHCP + port forward en el router, DDNS

### Fase 1 — Tools + IA local  ▸ VERIFICADA EN EL PC (falta probarla desde el móvil)
Ollama + Qwen 7-8B, registry de tools, tool calling, ciclo carga/descarga, botón dormir,
señal `missing_tool`.
**Hecho cuando:** "abre Android Studio" desde el gym abre Android Studio, y luego duerme sola.

Montado: **Ollama 0.31.2** + **qwen3:8b** (Q4, 5.2 GB). `think: false` — Qwen3 razona en voz
alta por defecto y para mapear intención→tool eso es latencia pura.

Medido en la 1080 Ti: **~38 s** la primera respuesta (incluye cargar 5.2 GB en VRAM),
**~0.5 s** las siguientes en caliente. Dormida ocupa **0 VRAM**.

Verificado por WebSocket (`scripts/test_fase1.py`), con el transporte real:
- [x] Registry carga 9 tools, esquemas válidos para Ollama, recarga en caliente
- [x] "lista mis proyectos" → llama a `list_projects` sola
- [x] "apaga las luces del salón" → **"Acción no disponible"** + señal `missing_tool`.
      No se lo inventa ni tira de `run_shell`. Esto es lo que abre el bucle de §8.
- [x] Ciclo de vida: dormida (0 VRAM) → despierta (5.2 GB) → `ai_sleep` → 0 VRAM
- [x] App compila con selector de cerebro, tarjetas de tool y Sí/No de permisos
- [x] App de Fase 1 probada en el móvil real: selector de cerebro, tarjetas de tool,
      estado de VRAM, botón de dormir — todo funciona
- [x] **Flujo de permisos verificado con un humano real tocando la pantalla** (no solo
      simulado por script): pedir un comando de forma explícita ("ejecuta en PowerShell:
      echo hola") dispara `run_shell` con tarjeta Permitir/Denegar, y **Permitir** lo
      ejecuta de verdad. Confirma que la frontera de seguridad del proyecto (§9) funciona.
- [x] ~~Comportamiento por defecto conservador: "¿qué procesos están corriendo?" NO
      dispara `run_shell`, prefiere `missing_tool`.~~ **Revertido a propósito** (ver
      §8.1): era demasiado conservador. Significaba pasar por Claude Code —y por sus
      tokens— para envolver un comando de PowerShell que la IA local ya sabía escribir.
      Ahora `run_shell` es la vía normal cuando no hay tool específica, y `missing_tool`
      queda para lo que de verdad necesita programarse. La frontera no se movió: el
      comando sigue sin ejecutarse hasta que lo lees y lo apruebas.
- [x] **Camino de Denegar confirmado**: responder "deny" no ejecuta nada (probado con un
      comando con marca detectable, que no aparece en ninguna salida). También verificado
      que una acción desconocida cae en denegar, y que un APK viejo que solo manda
      `{allow: bool}` sigue funcionando contra el protocolo v4.
- [ ] **Sin confirmar:** `open_app` con efecto visible (abrir Android Studio)
- [x] `build_gradle` real desde el chat: **verificado** ("compila pokeoverlay")

**Botón "Guardar" verificado de extremo a extremo** (`scripts/test_toolgen.py`, por el WS
real): "¿qué procesos están consumiendo más CPU?" → la IA local propone
`Get-Process | Sort-Object CPU -Descending | Select-Object -First 10`, sugiere el nombre
`listar_procesos`, se guarda, el registry recarga en caliente y el móvil pasa a ver 12
tools. Al volver a pedirlo la llama sola y **sin tarjeta de permiso**. Protocolo v4.

**Ajustes hechos tras uso real (13 tools ya, no 9):**
- **`build_and_install`**: pedir "compílalo y mándalo al móvil" esperaba que el modelo
  encadenase `build_gradle` → `adb_install` por su cuenta. Con un 8B eso es frágil, así
  que se hizo una tool atómica que hace la secuencia completa siempre igual. Verificado:
  "compila pokeoverlay y mándalo al móvil" → una sola llamada a `build_and_install`, 23.7s.
- **`adb_connect`**: el adb inalámbrico normal de Android (`adb-tls-connect`, por mDNS)
  **solo funciona dentro de la misma LAN** — no cruza Tailscale, porque el descubrimiento
  por multicast no se enruta por el túnel. Se cambió a modo `tcpip` con puerto fijo
  (`adb tcpip 5555`), que es una conexión TCP directa y sí viaja por Tailscale igual que
  el resto del sistema. Verificado: `adb connect 100.x.y.z:5555` (IP de Tailscale del
  móvil, no la de LAN) conecta correctamente. **Esto también deja que Android Studio
  despliegue por WiFi estando fuera de casa**, ya que usa el mismo servidor adb.
  Aviso: el modo tcpip se resetea si el móvil reinicia o si se toca el interruptor de
  depuración inalámbrica — no es un arreglo permanente de una vez, por eso existe la tool
  para no depender del cable USB cada vez que pase. **Confirmado en uso real: se reseteó
  en menos de media hora** (motivo exacto sin determinar). `adb_connect` solo sirve si el
  teléfono sigue escuchando en el puerto; si el listener en sí se ha caído, hace falta un
  cable USB o tocar el interruptor de depuración inalámbrica en el móvil una vez. La
  conexión de Tailscale en sí (el chat, WSS) no se ve afectada — son cosas independientes.

**Bug real encontrado y arreglado: proyectos Flutter, APK "no encontrado" pese a existir.**
`build_gradle` y `adb_install` buscaban el APK dentro de `<path>/**/build/outputs/apk/...`,
pero Flutter redirige el `buildDir` de Gradle a la raíz del proyecto Flutter (fuera de
`android/`). Confirmado en disco para `localnts` y `mealplanner_flutter`: el APK real vive
en `<raíz-flutter>/build/app/outputs/apk/...`, no en `<raíz-flutter>/android/build/...`.
Arreglado con un campo `apk_root` explícito en `paths.json` para esos dos proyectos (no se
adivina la ruta por convención) y un helper compartido (`paths.apk_search_root`) que usan
las dos tools. Verificado por resolución de fichero directa (sin recompilar): encuentra
`E:\LocalNTS\build\app\outputs\apk\debug\app-debug.apk` correctamente.

**Bug real encontrado y arreglado: APK que llega al móvil y no se instala ("parece que el
paquete no es válido").** Ese mensaje de Android significa casi siempre *APK sin firmar*.
La IA local compiló con `assembleRelease`, y `movil/` no tenía `signingConfig`: Gradle
sacó `app-release-unsigned.apk` y la tool lo mandó tan contenta. El filtro por variante de
`paths.latest_apk` no lo cazó — ese filtro solo evita que un release se cuele *cuando se
pidió debug*, y aquí el release se pidió de verdad. Arreglado en dos capas:

1. **La release ahora va firmada.** `movil/app/build.gradle.kts` tiene `signingConfig` con
   un keystore (`movil/release.jks`, PKCS12, fuera del repo vía `.gitignore`) que crea
   `sync_app_secrets.py` si falta, con la password en `secrets.properties` como el resto de
   secretos. La password es simbólica igual que la del p12: la clave no sale de este PC y
   la app no se publica en ninguna store; el keystore existe solo porque Android no instala
   APKs sin firma. Si el keystore no está, la firma no se aplica en vez de romper el build.
2. **Nada sin firmar sale del PC.** `controladora/apk.py` mira la firma del *fichero* (APK
   Signing Block v2/v3, o `META-INF/*.SF` para el v1 viejo) y `build_and_send`/`adb_install`
   se paran antes de mover nada, con un mensaje que le dice a la IA qué hacer. Se comprueba
   el hecho, no la convención del nombre de la variante: un `release` firmado es mandable y
   un `debug` raro podría no serlo.

También se corrigió la causa de arriba: la descripción de la tool `build_gradle` ofrecía
`assembleRelease` como "otra tarea útil", sin decir que la release sale sin firmar. Un
modelo de 8B no tiene forma de saber eso — si la tool lo ofrece, lo usa. Ahora la
descripción dice explícitamente que no la use salvo que se la pidan con esas palabras.
Verificado: `assembleRelease` produce `app-release.apk` y `apksigner verify` confirma firma
v2; el detector coincide con `apksigner` en APK firmado, sin firmar y fichero corrupto.

**Bug real encontrado y arreglado: todo lo que se instalaba en el móvil era una build de
debug.** El síntoma que lo destapó, dicho por el usuario: *"las apps siempre van más lentas
y distintas que cuando se manda una build de release"*. Y era exactamente eso, no una
impresión: `build_gradle` y `build_and_send` tenían `tarea="assembleDebug"` como valor por
defecto, y los botones de Acciones rápidas llamaban sin `tarea`. Un APK de debug lleva el
flag `debuggable`, que apaga optimizaciones de ART — la app que acababa instalada iba
medible y notablemente peor que la real, siempre, sin que nadie lo hubiera pedido. Encima
la descripción de la tool le prohibía a la IA usar `assembleRelease` (la corrección del bug
de la firma, arriba, se pasó de frenada: en vez de arreglar la causa, prohibió la variante).

Cambiar el defecto a `assembleRelease` a secas no valía: en un proyecto sin `signingConfig`
la release sale sin firmar y el móvil la rechaza. Se cambiaría "va lento" por "no se
instala", que es peor. Así que decide `controladora/variantes.py`, leyendo el `build.gradle`
del módulo de aplicación **antes** de compilar:

- `signingConfig` dentro de `buildTypes { release { … } }` → `assembleRelease`. Da igual que
  firme con la clave de debug (lo que hace la plantilla de Flutter): lo que importa es que
  el APK salga firmado y el código compile en modo release.
- Sin eso → `assembleDebug`, **diciendo por qué** y qué hace falta para arreglarlo. Que la
  app vaya en modo lento es aceptable; que lo haga en silencio, no.
- No es un módulo Android (los mods de Java) → `build`, que es la tarea que sí existe ahí.
  De paso arregla que a esos proyectos se les mandaba un `assembleDebug` inexistente.

Es lectura de texto, no un parser de Gradle, así que puede pecar de optimista — por eso no
es la última palabra: si la release sale sin firmar, `apk.is_signed()` lo caza igual que
antes y `build_and_send` **recompila solo en debug** y lo avisa, en vez de devolver un error
y dejarte sin nada. `variantes.py` decide qué compilar; `apk.py` comprueba qué salió.

El móvil recibe la variante en `projects.result` (`variante` + `variante_nota`), así que los
botones dicen "Compilar y enviarme el APK (release)" y avisan del proyecto que solo puede
darte una debug **antes** de esperar tres minutos. Debajo queda un botón secundario de debug
explícito, para depurar.

Efecto colateral inevitable, avisado en el texto que devuelve la tool: release y debug van
firmadas con claves distintas, y Android no instala una encima de la otra ("aplicación no
instalada"). La primera vez hay que desinstalar la debug.

Arreglado también lo que salía al aplicarlo:
- `mealplanner` no tenía `signingConfig` (release sin firmar) → keystore propio
  (`release.jks` PKCS12 + `key.properties`, los dos fuera del repo), mismo patrón que
  `movil/`. `pokeoverlay` se deja en debug a propósito: proyecto medio abandonado.
- `mealplanner` ni siquiera compilaba en este PC: su `local.properties` traía un `sdk.dir`
  de otro ordenador (un usuario que aquí no existe) y Gradle moría con "SDK location not
  found" antes de compilar una línea. Arreglado el fichero, y `build_gradle` pasa ahora
  también `ANDROID_HOME` (de `paths.json`) para que un `local.properties` ajeno no vuelva a
  tumbar un build.

Verificado de punta a punta: la detección acierta en los proyectos gradle/unity registrados
en `paths.json` (release en varios de ellos, debug/`build` en otros);
`build_gradle("controladora")` compila `assembleRelease` con BUILD SUCCESSFUL y el APK pasa
`apk.is_signed()`.

**Bug real encontrado y arreglado: "no veo lo que Claude hace hasta que le escribo".** El
síntoma: pasado un rato en segundo plano, los mensajes de Claude Code no aparecían en el
móvil, y solo escribiendo algo ("¿sigues ahí?") se veía lo que estaba haciendo. Se
diagnosticó mal dos veces: se creyó que era un socket zombie y se añadió un botón
"Actualizar" que reconectaba. No era eso, y el botón no podía funcionar.

La causa: el socket ya se había sacado del ViewModel al `ConnectionService` para que
sobreviviera a minimizar la app — correcto y a conciencia — pero **el historial se quedó en
el ViewModel**, que muere con la Activity. Y `ControladoraClient.events` es un
`MutableSharedFlow` con `replay = 0`, que **descarta lo que se emite cuando no hay ningún
collector**. Osea: guardas el móvil → Android destruye la Activity → el servicio mantiene la
conexión viva y el PC sigue mandando → nadie escucha → se tira a la basura → abres y el chat
está vacío → escribes → Claude contesta (vivo y con todo su contexto en el PC, que es la
pista que delató el diagnóstico) → ahora sí hay quien escuche → lo ves. Se arregló el cable
y se seguía tirando el contenido.

Por qué el botón no podía existir: los mensajes no se perdían por el camino, se descartaban
al llegar. No estaban en ningún sitio — ni en el móvil ni en el PC — del que un botón
pudiera recuperarlos. El propio código lo confesaba ("no recupera mensajes que de verdad se
hayan perdido") y aun así se envió con el nombre que se había pedido. Y encima reconectar
mataba la sesión de Claude en el PC (ver el `finally` de `server.py`), así que el botón de
"no perder mensajes" era el que borraba la conversación entera.

Arreglado moviendo la conversación al servicio: `ChatStore` (nuevo) vive en el scope de
`ConnectionService`, escucha los eventos desde `onCreate` y acumula el historial exista la
pantalla o no; `ChatViewModel` queda como fachada que dibuja lo que hay en el store. Los
mensajes ya están al abrir la app, sin pulsar nada, y el botón se quitó. El servicio
sobrevive al unbind porque `connect()` lo arranca con `startForegroundService`, no solo con
`bindService`. Límite conocido: el store vive en memoria del proceso; si Android mata el
proceso entero (raro con la notificación de foreground) el historial se va — sobrevivir a
eso pide persistencia en disco.

**Y quedaba un tercer diagnóstico equivocado, que era el que de verdad se veía a diario:
el scroll.** Con el historial ya a salvo, el síntoma seguía apareciendo de vez en cuando —
solo en el chat de Claude, y solo con respuestas largas. La causa estaba en una línea de
`ChatScreen`: `LaunchedEffect(items.size)`, que baja al último mensaje **cuando la lista
cambia de tamaño**. Una respuesta en streaming no cambia el tamaño de la lista: el primer
delta crea la burbuja y todos los demás engordan el texto de *esa misma* burbuja
(`ChatStore.appendDelta`). Así que se veían las primeras líneas y el resto se escribía por
debajo del borde de la pantalla, con la vista clavada. Escribir cualquier cosa metía un
item nuevo → cambiaba el tamaño → bajaba → "aparecía todo". No aparecía nada: ya estaba
escrito, más abajo.

Por qué en Claude y casi nunca en la IA local: el system prompt le pide a Claude respuestas
de tres líneas, así que lo normal es que quepan. Cuando se pasa (un plan, un error largo,
varias tarjetas de tool seguidas) es cuando se ve.

Arreglado en tres piezas: el efecto mira también cuánto ha crecido el último mensaje, no
solo cuántos hay; se usa `scrollToItem(último, +100000)` para quedarse al **final** de la
burbuja y no en su principio (una respuesta más alta que la pantalla seguía saliendo
cortada aunque el scroll "funcionase"); y solo arrastra si ya estabas mirando el final, que
si has subido a releer algo, que el chat te tire hacia abajo con cada delta es peor que el
bug. Ahora sí hay un botón ↻, y hace exactamente esto: baja al final del último mensaje y
se reengancha al servicio si el bind se hubiera soltado. **No toca el socket ni manda nada
al PC** — los mensajes ya están en el móvil; no hay nada que ir a buscar.

**Arreglado también: cada reconexión real mataba la sesión de Claude en el PC.**
`Session` creaba un `ClaudeBrain` por conexión WebSocket y el `finally` de `ws()` lo cerraba
al caerse — así que salir de casa (WiFi → datos) o cualquier caída de red le borraba a
Claude toda la memoria de la conversación, no solo el botón "Actualizar" del bug de arriba.
Ahora `claude_brain` es una única instancia a nivel de módulo en `server.py`, creada una vez
y compartida por todas las conexiones; `Session` solo guarda una referencia. El `finally` ya
no la cierra. De paso resuelve mejor el problema que motivó ese cierre (un CLI huérfano por
cada reconexión, "y son muchas"): ahora hay como mucho un `claude.exe` vivo en todo el
proceso, en vez de uno nuevo cada vez. Si el proceso entero del PC muere, el Job Object de
`winjob.py` ya se lleva el subproceso por delante, así que no hace falta cerrarlo a mano en
ningún sitio nuevo.

Esto destapó un bug latente que con el diseño viejo no podía manifestarse: `can_use_tool`
(el callback que el SDK llama para pedir permiso) capturaba `on_permission` en el momento en
que se creaba el cliente. Con `ClaudeBrain` recreándose en cada conexión, el cliente también
era nuevo cada vez, así que la captura siempre apuntaba a un WebSocket vivo por pura
coincidencia. En cuanto el cliente pasó a sobrevivir a reconexiones, esa captura se habría
quedado atada al WebSocket de la conexión que lo creó — un permiso pedido tras reconectar
habría intentado mandar la tarjeta por un socket ya cerrado. Arreglado leyendo
`self._on_permission` dentro del callback en vez de cerrar sobre el parámetro; `_ensure_client`
lo actualiza en cada turno, se reutilice el cliente o no.

Efecto colateral que en su momento pareció correcto: `MAX_BUDGET_USD` (el tope de $5 por
conversación) también se reseteaba sin querer con cada caída de red, porque vivía en el
`ClaudeBrain` que se recreaba; al compartirlo, el tope pasó a durar hasta cambiar de proyecto
o reiniciar el PC. **Ese tope ya no existe** — y precisamente arreglarlo fue lo que dejó ver
que sobraba: un límite que antes se borraba solo cada dos por tres empezó a cortar de verdad,
en mitad de conversaciones que no tenían nada que ver con lo que lo había agotado. Ver
"Control de gasto" en la Fase 2.

**Problema de diseño encontrado: pedir "abre el IDE" y "compila/despliega" a la vez falla.**
`build_gradle`/`build_and_install`/`unity_build` NO necesitan el IDE abierto — compilan por
línea de comandos a propósito (§5). Pero si se piden las dos cosas en el mismo mensaje, el
IDE abre su propio Gradle e indexa el proyecto en paralelo con nuestra compilación por
`gradlew.bat`, y compiten por los mismos ficheros de caché de Gradle. No hay forma fiable
de "esperar a que el IDE esté listo" desde fuera sin mirar la pantalla, así que la solución
fue de prompt: decirle al modelo que no abra el IDE cuando lo que piden es compilar/desplegar,
salvo que se pida explícitamente para otra cosa (ver o editar código).

**Decisión sobre `ai_sleep`:** espera y confirma que la VRAM se liberó de verdad antes de
decir que durmió. Ollama descarga en segundo plano, así que preguntar el estado justo
después devolvía "despierta" y la tool afirmaba algo que no había comprobado.

**Deuda conocida:** `screenshot` guarda el PNG en `pc/artifacts/` y devuelve la ruta; todavía
no viaja al móvil (llega con el vídeo, Fase 4).

### Fase 2 — Chat de Claude Code  ▸ CÓDIGO LISTO, BLOQUEADO EN LOGIN
Agent SDK, sesión por proyecto, streaming de respuestas, permisos reenviados al móvil
como botones. Cerrar el bucle de auto-ampliación de la sección 8.
**Hecho cuando:** le explicas una idea desde el gym y hace el cambio, pidiéndote permiso.

**El Agent SDK es un producto distinto de la API de Claude.** No se construye con el SDK
de `anthropic`: es el paquete `claude-agent-sdk`, y **lanza el CLI de Claude Code como
subproceso**. Todo lo demás cuelga de ese hecho.

Tres hallazgos que costaron encontrar y que no hay que volver a descubrir:

1. **El CLI no está en el PATH, ni hace falta Node.** Lo trae empaquetado la app de
   escritorio como ejecutable nativo:
   `%APPDATA%\Claude\claude-code\<version>\claude.exe` (hoy `2.1.209`).
   **La ruta lleva la versión dentro**, así que fijarla a mano se rompe en cuanto Claude
   Code se actualice solo. `controladora/claude_cli.py` la busca y ordena por versión de
   verdad (2.1.209 > 2.1.99 — un sort de texto lo haría al revés). Se le pasa al SDK por
   la opción `cli_path`.

2. **Conflicto de dependencias real.** `claude-agent-sdk` arrastra `mcp`, que exige
   `starlette >= 1.3`. FastAPI 0.115 **no arranca** con ese starlette
   (`Router.__init__() got an unexpected keyword argument 'on_startup'`) — el servidor se
   rompió al instalar el SDK. Resuelto subiendo a **FastAPI 0.139 + uvicorn 0.51**, que es
   la combinación que convive con el Agent SDK. Está anotado en `requirements.txt`.

3. **El CLI necesita su propio login.** Las credenciales de la app de escritorio están en
   el almacén seguro de Windows y el subproceso **no las hereda**: `claude auth status`
   devuelve `{"loggedIn": false, "authMethod": "none"}`. Hay que hacer
   `claude auth login` (o `setup-token` para un token de larga duración) una vez, en el PC.
   No hay forma de saltarse esto desde el servicio, y tampoco se deben ir a extraer las
   credenciales del almacén.

**Control de gasto: NO hay tope, y es a propósito.** Hubo uno (`max_budget_usd` = 5 $ por
conversación) puesto como red de seguridad del "no quiero gastar tokens en cosas que puede
hacer una IA local". Era un límite mal puesto, por tres motivos:

1. **No protegía de ningún gasto.** El CLI está autenticado con la **suscripción**, no con
   una API key. Ese número no es dinero que se cobre: es el coste equivalente en API que el
   SDK va estimando. Con el saldo extra desactivado, el gasto real es 0 pase lo que pase.
2. **Cortaba muchísimo antes que el límite de verdad**, que son los tokens de la ventana de
   5 h de la cuenta. Y desde que el cliente sobrevive a las reconexiones (Fase 1), el corte
   llegaba en mitad de una conversación que no tenía nada que ver con lo que lo agotó.
3. **Era indistinguible del límite real.** El móvil solo veía "límite superado" sin poder
   decir de qué límite ni hasta cuándo — la pregunta que de verdad se hace uno.

Lo que sí se emite ahora: además del evento `cost` de cada turno (gasto estimado del turno y
acumulado), el evento **`limit`** (protocolo v8) con el estado de los **tokens de la cuenta**:
`allowed` / `allowed_warning` / `rejected`, el tipo de ventana (5 h, semanal…) y `resets_at`
— el epoch al que vuelve a haber tokens. Sale del `rate_limit_event` que manda el CLI cuando
el estado cambia, con dos redes por debajo (`AssistantMessage.error == "rate_limit"` y un
`api_error_status` 429), porque la hora de reset **solo** viaja en el primero y el corte puede
llegar en cualquiera de los tres. El móvil lo pinta como banda fija encima de la caja de texto:
"Sin tokens — límite de 5 h. Vuelve a haber a las 21:04".

La red de seguridad del gasto sigue existiendo, pero donde le corresponde: en elegir cerebro
(IA local vs Claude) y en las acciones directas que no pasan por ningún LLM (§ Acciones
rápidas).

**Política de permisos:** reenviar al móvil un Sí/No por *cada* tool de Claude sería
insufrible y no protegería de nada — `Read`, `Glob`, `Grep`, `WebSearch` y compañía se
auto-aprueban (`AUTO_ALLOW`). Todo lo que muta algo (`Write`, `Edit`, `Bash`) sí pasa por
el Sí/No. Aquí Claude **sí** tiene shell, a diferencia de la IA local: la frontera es que
sus permisos llegan al móvil (§9).

**Protocolo v9 (2026-07-21): barra de tokens, modelo/esfuerzo, nueva sesión.** Tres
añadidos al chat de Claude, código listo pero sin verificar en dispositivo (mismo motivo
que el resto de esta fase: bloqueado en login).
- El evento `limit` ya traía `utilizacion` (0.0-1.0 del gasto de la ventana de la cuenta,
  sale de `RateLimitEvent.rate_limit_info.utilization` del SDK) pero el móvil lo tiraba en
  cuanto todo iba bien (`ChatStore._limite` se anula en "allowed", es lo que alimenta el
  banner de aviso). Ahora `ChatStore._ultimoLimiteConocido` guarda SIEMPRE el último valor
  conocido y alimenta una barra continua, borde a borde, encima de Preguntar/Automático/
  Plan — verde por debajo del 60%, amarillo hasta el 85%, rojo por encima.
- `CHAT` gana `model`/`effort` (opcionales, `""` = no forzar nada). `ClaudeBrain` aplica
  el modelo en caliente con `client.set_model()` (preserva la conversación, es lo que
  promete el SDK) pero el esfuerzo **fuerza una reconexión**: el SDK no tiene
  `set_effort`, solo se puede fijar en `ClaudeAgentOptions` al conectar. Un `effort` que
  no está en `EFFORT_LEVELS` se trata como `None` en vez de reventar contra el SDK.
- `session.new` (móvil→PC) `{brain}` / `session.new_ok` (PC→móvil): botón "Nueva sesión"
  para no arrastrar contexto de un proyecto a otro. En el PC llama a
  `claude_brain.close()` o `local_brain.reset()` (los dos ya existían). El móvil no vacía
  el chat hasta que llega la confirmación — no afirma que se limpió algo que no ha
  comprobado, mismo criterio que el resto de la app (ver "Repaso de fiabilidad" más abajo).

**Protocolo v11 (2026-07-23): AskUserQuestion como burbuja azul con botones.** Cuando
Claude llama a la tool `AskUserQuestion` (preguntas de opción múltiple para decidir algo),
antes caía por el flujo genérico de permisos y salía una tarjeta Permitir/Denegar inútil:
no había forma de *elegir* una opción, así que la pregunta se quedaba sin contestar y
caducaba. Ahora tiene su propio camino de punta a punta:
- El SDK no resuelve `AskUserQuestion` con un Sí/No: se responde inyectando la opción
  elegida en `updated_input["answers"]` (`{texto_de_la_pregunta: etiqueta}`), que es como
  el CLI la lee. Verificado leyendo el binario del CLL (`TL.answer(...,{updatedInput:{...,
  answers:{[pregunta]:etiqueta}}})`).
- `brain_claude.can_use_tool` trata `AskUserQuestion` **antes** que `AUTO_ALLOW` y que el
  modo Automático: una pregunta no tiene "autoaprobado" que valga, siempre se manda al
  móvil. Si nadie contesta (caduca), se deniega y el turno sigue.
- `question.request` (PC→móvil) `{req_id, brain, questions}` reutiliza TODA la maquinaria de
  permisos (la `future` de `ask_permission`, la caducidad, `permission.cancel`): lo único
  distinto es la tarjeta y que se contesta con `permission.reply` + `answers` en vez de con
  `allow`/`deny`. Un `req_id` que caduca apaga los botones de la burbuja igual que retira una
  tarjeta de permiso.
- En el móvil es un `Item.Question`: burbuja del mismo azul de "esto lo decides tú"
  (`AzulPregunta`) con cada opción como botón. Una sola pregunta de opción única se contesta
  al pulsar; con varias preguntas o `multiSelect` se va marcando y se pulsa "Enviar" (el PC
  espera una respuesta por pregunta en un solo envío). `respondido != null` deja escrito lo
  elegido y apaga los botones para no contestarla dos veces.

Estado:
- [x] `claude-agent-sdk` 0.2.120 instalado; CLI localizado y verificado (v2.1.209)
- [x] `ClaudeBrain` con sesión por proyecto (`cwd`), streaming y permisos al móvil
- [x] Servidor enruta `brain: "claude"`; protocolo v3 con evento `cost`, v8 con evento `limit`
- [x] Cierre del subproceso al desconectar el móvil (si no, queda un CLI huérfano por reconexión)
- [x] Protocolo v9: barra de tokens, modelo/esfuerzo, nueva sesión — código listo
      (`gradlew assembleDebug` y el import de los módulos Python tocados,
      verificados), sin probar contra el CLI real (ver bloqueo de abajo)
- [ ] **BLOQUEADO:** `claude auth login` en el PC. Sin esto el CLI responde
      "Not logged in" y no hay nada que probar.
- [ ] Sin probar: conversación real, permisos de Claude en el móvil, el bucle de §8
- [ ] Pendiente: selector de proyecto en la app; botón "que la escriba Claude Code" en la
      tarjeta de `missing_tool`

### Repaso de fiabilidad (2026-07-16) — la app dejó de inventarse cosas

Cinco quejas de uso real, y ninguna era lo que parecía. Se dejan escritas porque
cuatro de las cinco son el mismo error de fondo: **la interfaz afirmaba cosas que
no había comprobado**.

**1. «El indicador dice que Claude está trabajando y ni siquiera estoy conectado».**
Cierto, y no era culpa del indicador. `ControladoraClient.send()` hacía
`socket?.send(...)` sin mirar el resultado (que ni devolvía). Sin conexión,
`socket` es null, ese `?.` no hace nada, y no lanza ni avisa: el mensaje se
evaporaba y `ChatStore.send()` marcaba el turno como vivo igualmente. El
resultado era la app contándote los segundos que llevaba "pensando" una IA que
jamás recibió nada. Ahora `enviar()` devuelve el `Boolean` de OkHttp (que además
es false si el socket se está cerrando o la cola está llena), `send()` devuelve
`String?`, y un null NO abre turno: se dice "no se envió: no hay conexión".

**2. «Al mínimo fallo o desconexión se queda pillado».** Un turno solo lo cierra
el `chat.end` del PC, y si la conexión cae a mitad ese `chat.end` no llega nunca:
el turno se quedaba vivo para siempre con el cronómetro corriendo. `ChatStore`
ahora escucha `client.state` y, al perder la conexión, cierra los turnos vivos,
retira las tarjetas de permiso (su `req_id` murió con la `Session` del PC: pulsar
Permitir mandaba un "sí" por un socket inexistente) y lo dice en el chat. Se hace
en el store y no en la pantalla porque tiene que pasar exista o no la Activity.

**3. «La IA local no sabe hacer NADA».** Aquí no había ninguna decisión de
diseño que revertir — el prompt ya decía desde §8.1 que `run_shell` es la vía
normal. Eran dos bugs:

- **`LocalBrain` se creaba por conexión** (`Session.__init__`), o sea que perdía
  todo el historial en cada reconexión. Es **exactamente el bug que ya se
  arregló para Claude** y que no se aplicó aquí, pese a que en la IA local el
  historial *es* toda su memoria. Ahora es una instancia de módulo, como
  `claude_brain`.
- **Ollama usa `num_ctx=4096` si no le dices otra cosa**, y al desbordar no
  avisa: trunca por el principio, que es justo donde vive el system prompt. Con
  15 esquemas de tools (~1.5k tokens antes de hablar) y un tail de log de Gradle
  por build, se llenaba enseguida — y a partir de ahí el modelo ya no sabía que
  existía `run_shell`. No es que sea tonta: se le borraba la hoja de
  instrucciones por debajo. Ahora `num_ctx` va explícito (16384, en `paths.json`)
  y `_trim()` poda por un punto válido **sin tocar nunca el system prompt**.

Verificado por el WS real: conversa sin soltar "acción no disponible", saca
`run_shell` sola para "cuánto espacio queda en D", y **recuerda el contexto**
("¿y en la C?" → vuelve a llamar sola).

**4. «Las acciones rápidas ni funcionan; no encuentra paths.json».** No podían
funcionar. El botón le mandaba a Claude Code el recado *"busca el proyecto X en
pc/paths.json"*, y el `cwd` de Claude es la carpeta del proyecto, no la raíz del
repo: desde ahí ese fichero **de verdad no existe**, así que contestaba justo eso.
Y aunque hubiera funcionado estaba mal: pagar tokens de Claude para abrir un JSON
que está en el disco del propio proceso que atiende el WebSocket es exactamente
lo que este proyecto existe para no hacer. Ahora:

- `projects.request` (v7): la lista la manda el PC leyendo su propio `paths.json`.
  Eliges de una lista de los que hay; no hay nada que "encontrar" ni que teclear
  de memoria en el gym.
- `action.request` acepta **`args`** (v7). Antes solo se podían llamar tools sin
  parámetros, y por eso "compila tal proyecto" tenía que pasar por un LLM que
  adivinase un botón que ya sabía lo que quería. Cero tokens, cero interpretación.
- `run_action` emite los mismos eventos que un turno de chat y `toolrun.py`
  (extraído de `LocalBrain`) le da el progreso en vivo: un `build_and_send` desde
  un botón ya no son minutos de silencio.

**5. «El monitoreo va como el culo, y dice que la CPU no tiene sensor».** Dos
cosas distintas:

- **Lento:** cada lectura dormía medio segundo a propósito
  (`cpu_percent(interval=0.5)`) y arrancaba un `nvidia-smi` nuevo. Ahora la CPU se
  lee por contador acumulado (sin bloquear, y da una media más útil) y la GPU se
  cachea. **Medido: 100 ms la primera lectura, 3 ms las siguientes**, frente a más
  de un segundo. De paso, `nvidia-smi` va con `CREATE_NO_WINDOW`: antes hacía
  parpadear una consola en el escritorio cada 5 segundos.
- **Feo:** llegaba el párrafo formateado para el modelo y se pintaba en
  monoespaciado; no había con qué dibujar. `stats.result` ahora lleva `data` (la
  medida en crudo, `sysinfo.snapshot`) además del texto, medidos **de una sola
  lectura** para que no puedan contradecirse. La pestaña tiene anillos, barras por
  núcleo y color por carga (`ui/Monitor.kt`).
- **La temperatura de CPU: ver el apartado propio de abajo.** El primer intento
  (leerla por WMI) no podía funcionar y hubo que rehacerlo.

**Deuda que esto deja:** `_projects_snapshot` y `sysinfo` tocan disco en cada
petición (cacheado, pero sin vigilar cambios); y `LocalBrain` compartido a nivel
de módulo significa que dos chats simultáneos se pisarían el historial — hoy no
puede pasar (hay un móvil), pero es la misma suposición que ya hace `claude_brain`.

### La temperatura de CPU (2026-07-17) — me equivoqué dos veces

**Conclusión: se lee, y ahora sale.** `Core (Tctl/Tdie)`, verificado a 51,6 °C.

Error 1 — *"no se puede sin tocar la frontera de §9"*. La mecánica que di era
correcta (un Ryzen publica Tctl/Tdie por un registro que pide un driver en anillo
0, y el servicio corre como usuario normal), pero la conclusión no se sigue: **lo
lee cualquier programa que traiga su propio driver**. NZXT CAM ya estaba instalado
en este PC y la enseña. Lo que CAM no hace es publicarla para terceros. Que *este
proceso* no pueda leer un registro no significa que el dato no exista.

Error 2 — el arreglo no podía funcionar. La primera versión leía
`root\LibreHardwareMonitor` **por WMI**, y **LHM 0.9.6 no tiene proveedor WMI**:
ese namespace es de OpenHardwareMonitor (el proyecto del que LHM es fork). En el
binario de LHM no aparece ni una cadena `root\...`. Habría fallado en silencio
para siempre, quedando como "no hay sensor" — la misma mentira que esto venía a
arreglar, sólo que con más código detrás.

Lo que hay montado ahora:

- **LibreHardwareMonitor 0.9.6** instalado con winget, corriendo **como
  administrador** (sin eso el driver no carga y la rama de la CPU no aparece), con
  el **servidor web** activado (`runWebServerMenuItem` + `listenerPort=8085` en
  `LibreHardwareMonitor.config`, junto al .exe). Sirve todos los sensores en JSON.
- **Tarea programada** *"LibreHardwareMonitor (sensores para Controladora)"* al
  iniciar sesión, con privilegios máximos, para que sobreviva a un reinicio.
- `sysinfo._leer_temp_lhm()` baja `http://127.0.0.1:8085/data.json` y busca por
  `SensorId` (`/amdcpu/…/temperature/…`), no por el texto, que está traducido.
  Ojo con el parseo: LHM formatea con la **coma decimal** del sistema (`"51,6 °C"`),
  así que un `float()` directo lanza.
- Si LHM no responde: `None` y una nota que dice exactamente qué falta. Coste de
  no tenerlo: cero (puerto cerrado = *connection refused* inmediato), y hay caché
  negativa de 30 s por si el proceso está vivo pero atascado.

**Convive con NZXT CAM sin problema** — los dos leen los mismos sensores.

### La IA local, en uso real (2026-07-17)

Probado por el WS con el modelo de verdad, y salieron dos cosas que ningún
razonamiento habría encontrado:

- **`temperature` estaba a 0.8** (el defecto de Ollama). Elegir herramienta no es
  creativo: *"dame el código de AnyDesk"* tiene una respuesta correcta, y con 0.8
  la misma frase a veces llamaba a `anydesk_id` y a veces contestaba *"acción no
  disponible: AnyDesk requiere configuración previa"* — inventada. Falló 1 de 4
  veces sin más diferencia entre intentos que el muestreo. A **0.2**: 3/3 y sin
  dudar. Eso solo se ve repitiendo la misma frase; una pasada no prueba nada.
- **No sabía a quién administraba.** *"Apunta esto en un fichero del escritorio"* →
  `C:\Users\<nombre de pila>\Desktop\...`, que no existe: dedujo el usuario de
  Windows del nombre de la persona que sale en el prompt, porque era el único
  dato que tenía.
  Decirle "no inventes rutas" no arregla eso — no había forma de que lo supiera.
  Ahora `_hechos_pc()` le da usuario, carpeta personal, escritorio (comprobado en
  disco: puede estar en OneDrive o llamarse "Escritorio"), descargas, unidades y
  hostname. Verificado: crea, lista y borra en `C:\Users\<usuario>\Desktop` a la
  primera.

### Fase 3 — Builds al móvil
Vigilancia de carpetas de salida, notificación al terminar, descarga e instalación del APK
(`REQUEST_INSTALL_PACKAGES`). Notificación vía foreground service con WS persistente
(sin FCM, sin Firebase — a cambio de algo de batería).
**Hecho cuando:** "buildea X" y te llega el APK instalable al móvil.

### Fase 4 — Vídeo  ▸ HECHA (2026-08-10)
WebRTC, señalización por el mismo WS, media **directa P2P**. **30,4 fps medidos** de extremo
a extremo, y verificado en la tablet real (SM-T870): `recolección ICE: COMPLETE` → `pista de
vídeo recibida` → `CONNECTED`, con la ventana del PC entera y legible.

No se manda el escritorio: se manda **una ventana**. `appctl/capture.py` + `appctl/webrtc.py`
en el PC, `net/VideoCliente.kt` + `ui/VideoPanel.kt` en el móvil, y `rtc.offer` / `rtc.answer`
en el protocolo.

**Señalización sin trickle.** aiortc termina de recolectar candidatos dentro de
`setLocalDescription`, así que el SDP ya los lleva; el móvil hace lo mismo (espera a
`IceGatheringState.COMPLETE` antes de mandar la oferta). Una oferta, una respuesta y a correr:
ni un mensaje `rtc.ice` suelto ni estados a medias que sincronizar.

**Dónde se iba el tiempo, medido y no supuesto.** La primera versión daba 16–18 fps y lo fácil
era culpar al codificador. No era él: codificar sale **por debajo de 1 ms** con libx264. El
gasto estaba en `VideoFrame.from_ndarray`, **28 ms por fotograma**, porque se le pasaba un
array NO contiguo — el recorte `[:, :, :3]` para quitar el byte de relleno del BGRX. Pasando
el búfer de GDI entero (`bgra`) no se copia nada y swscale hace la conversión: de 20 a 30 fps
de un cambio de una línea. Las cinco interpolaciones de swscale dan lo mismo, porque lo caro
es el cambio de formato y no el filtro.

**Una ventana de chat está quieta casi siempre**, así que se comparan los búferes (≈1 ms) y,
si no ha cambiado nada, se reemite el fotograma ya convertido en vez de rehacerlo. Ojo con la
trampa que tiene: hay que guardar una **copia**, porque GDI reescribe ese mismo búfer en la
captura siguiente — comparar contra el búfer vivo daría "igual" siempre y el vídeo se
quedaría congelado.

Las dos correcciones al plan original, las dos medidas:

- **El candidato ICE bueno es la IP `100.x` de Tailscale**, no la pública. Lo de §3 ("hay IP
  pública real, así que P2P directo") se escribió antes de que Tailscale sustituyera al port
  forward (§4.1). Con Tailscale son candidatos host: ni STUN ni TURN, y ni un byte sale de la
  red privada.
- **No hace falta `windows-capture` ni Windows Graphics Capture.** `PrintWindow` con
  `PW_RENDERFULLCONTENT` captura la ventana **aunque esté tapada** y da **59 fps** reutilizando
  los recursos de GDI. Lo que **no** captura es una ventana minimizada: hay que restaurarla
  antes (`window.restaurar`).

Dos correcciones al plan original, las dos medidas:

- **El candidato ICE bueno es la IP `100.x` de Tailscale**, no la pública. Lo de §3 ("hay IP
  pública real, así que P2P directo") se escribió antes de que Tailscale sustituyera al port
  forward (§4.1). Con Tailscale es un candidato host y no hace falta ni STUN ni TURN.
- **No hace falta `windows-capture` ni Windows Graphics Capture.** `PrintWindow` con
  `PW_RENDERFULLCONTENT` captura la ventana de Chromium **aunque esté tapada** y da
  **48,6 fps a 1936x1056** en este PC (medido en `probe_appctl.py`, sonda 6). Sobra para los
  30 fps del objetivo, y es una dependencia menos. Lo que **no** captura es una ventana
  minimizada: hay que restaurarla antes (`window.restaurar`).

### El vídeo congelado, y por qué AnyDesk lo arreglaba (2026-08-25)

El síntoma: cada cierto tiempo el móvil deja de ver la imagen actualizada, **pero los toques
siguen llegando y funcionando**. Se arreglaba entrando por AnyDesk y tocando cualquier cosa en
el PC. Mientras eso siga siendo cierto, AnyDesk no es un apoyo: es una dependencia, y el día
que falle esta aplicación no sirve.

**Los dos caminos no son el mismo, y ahí está todo.** Un gesto vuelve a **buscar la ventana en
cada toque** (`brain_app.tocar` → `window.asegurar`) y se entrega con `PostMessage`, que llega
la pinte quien la pinte. El vídeo **no genera imagen: copia** la última que la ventana pintó.
Si la ventana deja de pintar, la copia sale idéntica, `PistaVentana.recv` reemite el fotograma
cacheado — que es exactamente lo que se le pidió — y desde el móvil eso es indistinguible de
una pantalla que no cambia. Ni error, ni corte, ni una línea en el log.

**La causa principal, y es un círculo vicioso.** `input.py` usa `PostMessage` a propósito y por
buenos motivos, pero **PostMessage no cuenta como actividad del usuario**: no toca el contador
que lee `GetLastInputInfo`, que es el mismo que decide cuándo apagar la pantalla. En este PC,
`VIDEOIDLE` está en 900 s. O sea que puedes estar manejando el PC desde el móvil media hora y
Windows creerse que lleva media hora abandonado: apaga la pantalla, DWM deja de componer, las
ventanas dejan de dibujar y `PrintWindow` devuelve para siempre lo último que hubo. AnyDesk lo
«arreglaba» porque inyecta entrada **real**: reinicia ese contador y despierta la pantalla. No
era que tocar despertara a Claude, era que tocar despertaba al PC.

Lo que se hizo, en tres piezas:

- **`appctl/despierto.py`** — `SetThreadExecutionState` con `ES_DISPLAY_REQUIRED` mientras haya
  un emisor vivo. No cambia el plan de energía del PC ni deja nada tocado si el proceso muere.
  Dos trampas, las dos evitadas ahí: el flag es **por hilo** (se llama desde el bucle de
  eventos, nunca desde un `to_thread` cuyo hilo puede morir y llevarse la petición), y hace
  falta **contar** las peticiones, porque dos móviles mirando son dos motivos y que se vaya uno
  no puede apagarle la pantalla al otro.
- **El vigilante de `PistaVentana`** — cuenta cuánto lleva el fotograma sin cambiar. Que una
  ventana de chat esté quieta es NORMAL, así que no grita por eso: cada 5 s mira si hay algo
  anormal **y con arreglo**. Si la ventana se rehízo, se reengancha al HWND nuevo (esta era una
  avería mortal y silenciosa: el emisor se ata a un HWND al negociar y se quedaba mirando a un
  muerto para siempre, mientras los gestos seguían funcionando porque buscan la ventana en cada
  toque). Si está minimizada, la restaura. Si no, pide repintado y **deja escrito** cuánto lleva
  quieta y cuánta inactividad de teclado y ratón hay — ese segundo número es el que delata al
  apagado de pantalla si vuelve a pasar.
- **El vigilante del móvil (`VideoCliente.vigilar`)** — mira `framesDecoded` por `getStats` y
  renegocia si no sube en 8 s. Cubre lo que el PC no puede ver: un atasco del transporte o del
  decodificador. Y cubre lo que todavía no sabemos que puede pasar, que es lo que de verdad
  quita a AnyDesk del camino crítico.

**Los dos vigilantes se reparten el trabajo, y conviene tener claro cómo.** Con la ventana del
PC quieta, el PC sigue mandando 30 fps del mismo fotograma, así que `framesDecoded` **sube** y
el móvil no se alarma: si la avería es que la ventana no pinta, la ve el PC, que es donde se
puede arreglar. Si el contador se para, la imagen no está llegando: eso lo ve el móvil, y de
eso sí se sale renegociando de cero.

Se prueba con `test_video_vigilante.py`, con la ventana simulada a propósito: una prueba que
dependiera de que la ventana real esté quieta pasaría o fallaría según lo que Claude estuviera
haciendo en ese momento. Y si algún día vuelve a congelarse, `diag_congelado.py` se queda
mirando la ventana y separa las cuatro causas posibles sin tener que adivinar.

### Fase 5 (la «Fase E») — Control de ratón y teclado
Input remoto sobre el stream de la Fase 4. Es la pieza que convierte esto de «control por
botones que el PC ya conoce» a «control de una ventana entera»: hasta ahora puedes **ver** la
ventana de Claude en el móvil y pulsar los mandos que el PC te lista (`app.press`), pero no
puedes tocar sobre la imagen como si fuera la pantalla — clicar un enlace dentro de un
artefacto, seleccionar texto arrastrando, o desplazar algo que no sea uno de esos mandos.

Se parte en dos tramos, y el primero es el que está hecho:

- **E.1 — puntero: tocar, arrastrar y desplazar.** `app.tap`, `app.drag`, `app.scroll`.
- **E.2 — teclado libre.** Escribir en un sitio que no sea el compositor (un formulario dentro
  de un artefacto web) pide un teclado superpuesto en el móvil que mande `app.key` por
  pulsación, reutilizando `entrada.tecla()`, que ya existe.

Ojo con una asimetría que ya está medida (§5.1) y que es justo lo que separa E.1 de E.2: el
**ratón** se puede mandar con `PostMessage` a la ventana esté donde esté, pero el **teclado**
exige además que esté en primer plano. `SendInput` no se usa en ninguno de los dos: inyecta en
la cola global, compite con lo que estés tecleando tú y, si el foco cambia a mitad de frase, el
resto se va a otra aplicación sin que el móvil se entere.

#### E.1 — El puntero  ▸ HECHA (2026-08-23)

`app.tap` / `app.drag` / `app.scroll` en el protocolo (v13), `appctl/input.py` en el PC y
`ui/VideoPanel.kt` + `ui/GestosVideo.kt` en el móvil. Cuatro decisiones, y ninguna es de
estilo:

**Viajan fracciones de la ventana, no píxeles de la pantalla.** El plan de partida decía que
el móvil calculase el punto real (`x_real = ventana.x + u/ancho_video * ventana.ancho`) y
mandase eso. No: `app.state` es una **foto** que se refresca cada pocos segundos, así que entre
la foto y tu dedo la ventana ha podido moverse o cambiar de tamaño — y entonces esa coordenada
absoluta cae en otro sitio de la pantalla, encima de otra aplicación, clicando a ciegas en el
escritorio. Lo que viaja es un par `fx, fy` de 0 a 1 **relativo a la ventana**, y el PC lo
resuelve contra `GetWindowRect` en el instante del clic, recortando a [0, 1]. Es la diferencia
entre «el clic siempre cae dentro de la ventana que estás viendo» y «el clic cae donde estén
ahora esos píxeles». La escala del vídeo (`ANCHO_MAX`) deja de importar por completo, que es el
otro regalo: no hay que ponerlas de acuerdo.

**El letterbox hay que deshacerlo, no ignorarlo.** El renderizador va en `SCALE_ASPECT_FIT`
(ver `VideoPanel`), o sea que casi siempre hay bandas negras: dividir el toque por el ancho de
la vista da un punto desplazado, y cuanto peor cuadre la caja, más. Como `webrtc.py` escala
conservando la proporción, la proporción del vídeo **es** la de `ventana`, y con eso se
reconstruyen el rectángulo dibujado y sus bandas sin preguntarle nada al decodificador. Un
toque sobre la banda se **descarta**: recortarlo a [0, 1] sería clicar en el borde de la
ventana sin que lo hayas pedido.

**El arrastre lo sintetiza el PC.** Va un solo mensaje con los dos extremos y el PC genera la
secuencia que Windows necesita — botón abajo, varios `WM_MOUSEMOVE`, botón arriba. Un
`WM_LBUTTONDOWN` y un `WM_LBUTTONUP` en sitios distintos **no** seleccionan nada: Chromium
necesita ver el movimiento con el botón pulsado. La alternativa (retransmitir cada movimiento
del dedo) inundaría el WS y, si la conexión se cae a mitad de gesto, deja el botón pulsado en
el PC sin nadie que lo suelte. El precio, dicho claro: no ves la selección mientras arrastras,
la ves al levantar el dedo.

**`WM_MOUSEWHEEL` lleva coordenadas de PANTALLA en `lParam`**, al revés que `WM_MOUSEMOVE` y
`WM_LBUTTON*`, que las llevan de cliente. Es una trampa de Win32 y no un detalle: mezclarlas da
una rueda que desplaza lo que haya bajo un punto equivocado, en silencio y sin error.

**Los gestos no piden `app.state`.** `Session.app_command` espera 0,8 s y pide una foto después
de cada mando, y esa foto recorre el árbol de accesibilidad entero. Hacer eso por gesto haría
que arrastrar y desplazar fueran inusables. La pestaña App ya se refresca sola mientras se
mira, que es de donde sale el `ventana` que necesitan los gestos.

En el móvil los tres gestos se distinguen con un dedo, como en cualquier cliente de escritorio
remoto táctil: **tocar** es clicar, **arrastrar** es desplazar (es lo que espera la mano sobre
una pantalla), y **mantener pulsado y luego arrastrar** es arrastrar de verdad — seleccionar
texto, mover algo. La pulsación larga avisa con una vibración, porque un modo en el que entras
sin enterarte es un modo que usarás sin querer.

**Verificado en el PC (2026-08-23):**

- [x] El mapeo fracción → píxel: las esquinas caen donde deben y **101 fracciones de cada eje
      caen todas dentro de la ventana**, incluidos `-3`, `7` e infinitos. Nada puede salirse.
- [x] El empaquetado de `lparam` con coordenadas negativas. No es hipotético: la ventana
      maximizada de este PC está en **(-8, -8)**, así que la vieja fórmula
      `(y << 16) | (x & 0xFFFF)` se llevaba por delante el número entero.
- [x] `WM_MOUSEWHEEL` desplaza de verdad, medido comparando capturas: **12,5 % de los píxeles
      cambian** al bajar 5 muescas y 16,3 % al subirlas. «Mandado» no es «ha funcionado».
- [x] El arrastre selecciona de verdad: con la ventana quieta (**0 px de ruido de fondo en
      2,5 s**, medido), un `app.drag` cambia ~30.000 px y la zona que cambia coincide con el
      recorrido del dedo. Al primer intento no cambió nada donde tocaba porque el arrastre
      cayó en un hueco en blanco entre dos párrafos — mirar la captura fue más rápido que
      teorizar.
- [x] El camino entero por WebSocket con mTLS real (`test_gestos_ws.py`): protocolo v13,
      fracciones fuera de rango, campos ausentes y campos con texto donde iba un número. Y que
      un gesto **no** devuelve `app.state`, que es lo que lo hace usable.
- [x] La app del móvil compila con el detector de gestos dentro.

**Y luego se probó en el móvil, y no funcionaba nada.** Merece quedar escrito, porque la
lección no es sobre WebRTC: **las seis comprobaciones de arriba son ciertas y no servían de
nada**. Todas miden el lado PC, y los tres fallos que dejaban esto inservible estaban en el
lado Compose, que es justo lo que ninguna de ellas toca. Verificado en el móvil real (Pixel 6
Pro, 2026-08-25), esto es lo que había:

1. **Dos capas táctiles solapadas.** El zoom se había puesto en su propia caja `fillMaxSize`
   encima de la de los gestos. Entre hermanos que se solapan, Compose **para el hit-testing en
   el primero que acierta**: la capa de abajo no recibía ni un toque. No funcionaba nada de un
   dedo. Arreglo: un solo `pointerInput` que arbitra contando dedos.
2. **`graphicsLayer` sin `clip`.** Vale `false` por defecto, así que al acercar la imagen el
   vídeo *y la capa táctil* se salían de su caja y se dibujaban y se tocaban encima del resto
   de la pantalla.
3. **El renderizador de WebRTC no hace letterbox dentro de su vista.** Éste es el bueno.
   `SCALE_ASPECT_FIT` sólo influye en su `onMeasure`; en cuanto se le dan medidas exactas
   recorta el fotograma para llenarlas. Con `fillMaxWidth` la proporción salía bien pero la
   vista quedaba ARRIBA de la caja; con `fillMaxSize` llenaba la caja y recortaba. La capa
   táctil, mientras, calculaba las bandas suponiendo la imagen centrada. Medido en el
   dispositivo: vista 1356x2079, ventana 1874x1096, y la cuenta situaba la imagen en local
   y 643..1436 mientras el renderizador la pintaba de 0 a 2079. Los toques de la mitad de
   arriba daban fracción negativa y **se descartaban en silencio**.

   El arreglo no es pelearse con el renderizador sino quitarle la decisión: la caja de la
   imagen lleva `aspectRatio(ancho/alto de la ventana)` y va centrada, así que vista e imagen
   son el mismo rectángulo por construcción y el letterbox desaparece del cálculo — `aFraccion`
   es ahora una división y nada más.

**Verificado en el móvil real (2026-08-25), con números:**

- [x] **Toque**: en el centro de la imagen sale `(-930, 535)` contra un centro real de
      `(-930, 539)`. **0,4 % de error** sobre una ventana de 1096 px de alto. Las cuatro
      esquinas, comprobadas una a una, también caen donde deben.
- [x] **Un toque en la banda negra no genera ningún gesto**, que es lo correcto: ahí no hay
      ventana que tocar.
- [x] **Desplazar**: con la ventana quieta (ruido de fondo 55 px medidos en 2 s), un barrido
      cambia **378 624 px, el 18,4 % de la ventana**. Los signos, comprobados en los dos
      sentidos. Y un detalle que sólo se ve probando: barrer sobre el compositor no desplaza
      nada — no está roto, es que esa zona no scrollea.
- [x] **Arrastrar**: 26 478 px cambiados contra 123 de ruido.
- [x] **30,0 fps sostenidos y 0 fotogramas perdidos** en el móvil (`EglRenderer`), con la
      ventana entera visible y legible.

- [x] **Zoom de dos dedos**, confirmado a mano en el dispositivo (`adb input` no hace
      multitáctil, así que esto no se pudo medir en automático como el resto). Los controles
      de la esquina son iconos y no texto (`Icons.Default.Close` para «Dejar de ver»,
      `Icons.Default.Refresh` para reiniciar el zoom — no hay `RestartAlt` en el set básico de
      Compose, sólo en el extendido, y no compensa tirar de esa dependencia por un icono). La
      resolución de la ventana (`ancho×alto`) se quitó del overlay: es un dato de depuración,
      no algo que se mire viendo el vídeo. En su lugar sale el **% de zoom** — `escala`
      redondeada tal cual, sin normativa detrás; sirve para que quien mira y quien lee un
      mensaje sobre ello hablen del mismo número, no para nada más preciso.

**Pendiente:**

- [ ] Ajustar `PX_POR_MUESCA` (42 dp) con la mano, si se queda corto o va nervioso.

#### E.2 y el vídeo de pantalla completa  ▸ HECHA (v16)

Lo que arriba se llamaba "asimetría medida": el ratón se podía mandar por `PostMessage`
estuviera donde estuviera la ventana, pero el teclado necesitaba primer plano, y por eso
`SendInput` se descartaba para los dos -- "compite con lo que estés tecleando tú".

Esa razón dejó de aplicar cuando el vídeo dejó de ser "la ventana de Claude" y pasó a ser
"la pantalla que elijas", pedido por Ale explícitamente como control real, al estilo
AnyDesk: si el objetivo es controlar el PC entero, no una app concreta en segundo plano,
entonces SÍ hace falta tomar el ratón y el teclado de verdad, y se acepta competir con
quien esté delante del PC -- es la naturaleza de ese modo, no un descuido.

Con eso, `app.tap`/`app.drag`/`app.scroll`/`app.copy` (que eran fracciones de la VENTANA,
resueltas contra `GetWindowRect`) se sustituyen por `screen.tap`/`screen.drag`/
`screen.scroll`/`screen.copy`/`screen.type`/`screen.key` (fracciones de un MONITOR,
resueltas contra `pantallas.punto`), protocolo v16. El teclado libre (E.2) ya no hace
falta pedirlo por separado: es la misma pieza que el resto de `screen.*`.

Lo que NO cambia: el chat con la app de Claude (`app.press`, sesiones, `app.request`) sigue
siendo `PostMessage`/UIA a esa ventana concreta, con las mismas razones de siempre (§5.1).
Sólo el vídeo y los gestos sobre él se movieron a pantalla completa.

Ver `pc/controladora/appctl/pantallas.py` (listar monitores, `EnumDisplayMonitors` +
`GetMonitorInfo`), `pc/controladora/appctl/capture.py` (`BitBlt` desde `GetDC(0)`, en vez de
`PrintWindow`) y `pc/controladora/appctl/pantalla_input.py` (`SetCursorPos`/`mouse_event`
para el ratón, `SendInput` con `KEYEVENTF_UNICODE` solo para el texto imprimible).

---

## 11. Riesgos abiertos

- **IP dinámica**: hay que observar si la IP pública cambia. DDNS lo cubre, pero
  conviene saber cada cuánto.
- **Batería del móvil** con el foreground service permanente (fase 3). Si molesta, la
  alternativa es FCM, a costa de meter Firebase como dependencia.
- **Detalles del Agent SDK** (nombres exactos de API, callback de permisos, reanudar sesión):
  a verificar contra la documentación al llegar a la Fase 2, no darlos por supuestos.
- **Unity en batchmode** necesita un script de build dentro del proyecto; no es gratis.
- El router debe tener **reserva DHCP** para la IP local del PC, o el forward se romperá solo.
