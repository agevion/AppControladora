# AppControladora

Controla tu PC desde el móvil, en cualquier lugar, viendo su pantalla en directo — y pídele
a una IA que haga cosas por ti en él, en vez de manejar cada control a mano.

> **English:** Remote-control your PC from your phone over a live video feed, from anywhere —
> and ask an AI to actually operate the PC for you (open apps, manage files, run routine
> tasks) instead of hunting for the right button. Full write-up in Spanish below
> ([ARQUITECTURA.md](ARQUITECTURA.md) has the deep technical detail).

## Qué hace

- **Ves la pantalla del PC en directo** desde el móvil (streaming de vídeo en tiempo real,
  30 fps sostenidos) y la **controlas tocándola**: clic, arrastre, desplazamiento y zoom de
  dos dedos sobre cualquier punto de la imagen — no solo sobre botones predefinidos.
  Precisión verificada: 0,4 % de error de toque en un Pixel 6 Pro.
- **Le hablas a una IA y ella opera el PC por ti.** Hay dos "cerebros" intercambiables:
  una **IA local** (Ollama, Qwen 7-8B) que resuelve tareas rutinarias sin gastar ni un
  token, y **Claude Code** para lo que necesita más criterio — ambos comparten la misma
  capa de herramientas (abrir apps, gestionar ficheros, ejecutar comandos con permiso).
  Añadir una capacidad nueva es escribir un fichero: aparece en los dos cerebros gratis.
- **Portapapeles y ficheros viajan entre PC y móvil** en ambas direcciones, y puedes copiar
  texto seleccionado en el PC directamente al portapapeles del teléfono sin tocar su teclado.
- **Todo pasa por una red privada (Tailscale)**, nunca por internet abierto: sin exponer
  puertos, sin DDNS, con mTLS obligatorio de extremo a extremo — el PC nunca es alcanzable
  desde fuera de tu propia red privada.

## Stack técnico

**PC:** Python, FastAPI + WebSocket sobre mTLS, Ollama (LLM local), Claude Agent SDK.
**Móvil:** Kotlin, Jetpack Compose.
**Red:** Tailscale (WireGuard), certificados propios (pinning, sin CA pública).

---

## Documentación de desarrollo

Lo que sigue es la documentación con la que se construyó y se mantiene el proyecto día a
día — decisiones de diseño, cómo levantarlo en tu propia máquina, cómo añadir una
herramienta nueva, y el estado exacto de cada fase. El diseño completo, con el porqué de
cada decisión, está en [ARQUITECTURA.md](ARQUITECTURA.md).

**Estado: Fase E.1 — funcionando en el móvil.** Se ve la ventana del PC por vídeo (Fase 4) y
se puede **tocar esa imagen**: clic, arrastre y desplazamiento sobre cualquier punto de la
ventana, no sólo sobre los botones que el PC sabe nombrar. Verificado en un Pixel 6 Pro:
toque con 0,4 % de error, desplazamiento que mueve el 18 % de la ventana, zoom de dos dedos
confirmado a mano, y 30 fps sostenidos sin perder un fotograma. Queda la Fase E.2, el
teclado libre.

Aviso para quien siga: las pruebas del PC (`test_gestos.py`, `test_gestos_ws.py`) pasaban
enteras mientras en el móvil **no funcionaba nada**. Los tres fallos estaban en el lado
Compose, que ninguna de ellas toca. Ver ARQUITECTURA.md §10, Fase E.1. Ver ARQUITECTURA.md §10.

**Traspaso PC <-> móvil (v14).** Lo que copies en el PC aparece en el portapapeles del
teléfono, y desde el móvil se eligen fotos o archivos que aterrizan en una carpeta del PC
(`Documentos\ControlaPics`, configurable en `paths.json`). Pestaña **Traspaso** en la app.
Ver [ARQUITECTURA.md §5.3](ARQUITECTURA.md).

**"Copiar selección" (v15).** Sobre el vídeo de la pestaña App: mantén pulsado y arrastra
para seleccionar texto (ya existía, Fase E.1), y ahora aparece un botón **Copiar selección**
que manda Ctrl+C y lo trae solo al portapapeles del móvil por el mismo camino del punto
anterior — sin tocar el teclado del PC. Ver [ARQUITECTURA.md §5.4](ARQUITECTURA.md).

La app le habla al PC por su **IP de Tailscale** (`100.x.y.z`), no por la IP de LAN ni por
IP pública. No hace falta port forward, DDNS, ni exponer ningún puerto a internet — ver
[ARQUITECTURA.md §4.1](ARQUITECTURA.md) para el porqué del cambio.

---

## Estructura

```
pc/                 servicio Python (FastAPI + WebSocket sobre mTLS)
  controladora/     config, protocolo, servidor, registry, cerebro local
    appctl/         pilota la app de escritorio de Claude (ARQUITECTURA.md §5.1)
    portapapeles.py el portapapeles de Windows: leer, escribir y vigilar
    recibidos.py    donde aterrizan los ficheros que manda el movil
  tools/            UNA TOOL POR FICHERO. El punto de extension.
  scripts/          PKI, sincronizacion de secretos, tests
  certs/            CA + certs. NO va al repo.
  config.json       puerto, token, passwords y host real. NO va al repo.
  paths.json        rutas de IDEs y proyectos. Sin secretos: SI va al repo.
movil/              app Android (Kotlin + Compose)
```

## Tests

Con el servicio arrancado:

```powershell
.\.venv\Scripts\python.exe scripts\test_client.py      # Fase 0: mTLS y rechazos
.\.venv\Scripts\python.exe scripts\test_registry.py    # carga de tools
.\.venv\Scripts\python.exe scripts\test_local_brain.py # IA local: tools + VRAM
.\.venv\Scripts\python.exe scripts\test_fase1.py       # todo junto, por el WebSocket
```

Estos dos no necesitan el servicio, sólo que la app de escritorio de Claude esté abierta:

```powershell
.\.venv\Scripts\python.exe scripts\probe_appctl.py     # 10 sondas: se puede pilotar la app?
.\.venv\Scripts\python.exe scripts\test_appctl.py      # la capa appctl, de punta a punta
```

El puntero remoto de la Fase E.1 (tocar, arrastrar y desplazar sobre el vídeo). El primero
no necesita el servicio; el segundo sí:

```powershell
.\.venv\Scripts\python.exe scripts\test_gestos.py      # el mapeo y la rueda, sin servidor
.\.venv\Scripts\python.exe scripts\test_gestos_ws.py   # los app.tap/drag/scroll por el WS
```

Ninguno de los dos **clica** por defecto, y no es prudencia de más: se suelen lanzar desde una
conversación que corre dentro de la propia aplicación que van a manejar, así que un clic a
ciegas puede caer sobre la tarjeta de permiso de la orden que lo lanzó. Desplazar y arrastrar
no activan nada. Para clicar de verdad hay que pedirlo: `--tocar 0.5 0.5` (fracciones de la
ventana, de 0 a 1 — ver `protocol.APP_TAP` para el porqué no son píxeles).

El traspaso de la v14 (portapapeles y ficheros). Necesita el servicio arrancado:

```powershell
.\.venv\Scripts\python.exe scripts\test_traspaso.py         # 7 comprobaciones
.\.venv\Scripts\python.exe scripts\test_traspaso.py 8444    # contra otra instancia
```

Toca el portapapeles de verdad (es lo que prueba), así que guarda lo que hubiera copiado y lo
devuelve al terminar. El segundo modo es para probar sin tumbar el servicio que esté
atendiendo al móvil: `python scripts\_serv_prueba.py 8444` levanta una instancia aparte con
los mismos certificados.

El vídeo y su vigilante. Ninguno de los dos necesita el servicio ni el móvil:

```powershell
.\.venv\Scripts\python.exe scripts\test_video_vigilante.py  # imagen congelada y reenganche
.\.venv\Scripts\python.exe scripts\diag_congelado.py        # sonda: se queda mirando la ventana
```

La sonda es para cuando algo se congele y haya que saber POR QUÉ: escribe cuánto lleva la
ventana sin cambiar, cuánta inactividad de teclado y ratón hay, y si Windows la tiene oculta o
minimizada. Con eso se distingue "el PC dejó de pintar" de "la imagen no está llegando al
móvil", que desde el móvil se ven igual. Ver ARQUITECTURA.md, «El vídeo congelado».

`probe_appctl.py` no toca nada; `--enviar "texto"` le añade escribir y enviar de verdad.
`test_appctl.py --escribir "texto"` teclea y borra sin enviar (seguro), y `--enviar` sí manda.

## Anadir una tool

Crea `pc/tools/mi_tool.py`:

```python
from _util import run_process, tail          # helpers (el registry ya prepara el sys.path)
from controladora import paths               # rutas absolutas: nunca uses el PATH

SPEC = {
    "name": "mi_tool",
    "description": "Que hace, en una linea. Lo lee el modelo: se claro.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}
CONFIRM = False        # True -> pide Si/No en el movil antes de ejecutar

def run() -> str:
    return "texto que leen el modelo Y el humano"
```

Y dale a **Recargar tools** en la app: se carga en caliente, sin reiniciar el servicio.

## Puesta en marcha

### PC

```powershell
cd E:\AppControladora\pc
.\.venv\Scripts\python.exe scripts\gen_certs.py       # solo la primera vez
.\.venv\Scripts\python.exe run.py                     # arranca el servicio
```

Comprobar que todo responde (con el servicio arrancado, en otra consola):

```powershell
.\.venv\Scripts\python.exe scripts\test_client.py
```

Verifica las tres cosas que importan: eco en streaming con cert válido, rechazo sin
certificado de cliente, y rechazo con token inválido.

### App

```powershell
cd E:\AppControladora\pc
.\.venv\Scripts\python.exe scripts\sync_app_secrets.py --host 100.x.y.z   # IP de Tailscale del PC (la tuya)

cd E:\AppControladora\movil
$env:JAVA_HOME='C:\Program Files\Android\Android Studio\jbr'
.\gradlew.bat assembleRelease
```

El APK sale en `movil\app\build\outputs\apk\release\app-release.apk`, firmado con
`movil\release.jks` (lo crea `sync_app_secrets.py`). Usa `assembleDebug` solo para depurar:
un APK de debug lleva el flag `debuggable` y la app va notablemente más lenta. Es la misma
regla que aplican solas las tools `build_gradle` / `build_and_send` (ver
`pc\controladora\variantes.py`).

Ojo la primera vez que se pasa de debug a release: van firmadas con claves distintas y
Android no instala una encima de la otra — hay que desinstalar la de debug antes.

`sync_app_secrets.py` copia `ca.crt` y `client.p12` a los assets y escribe el host+token en
`secrets.properties`. **Hay que reejecutarlo cada vez que se regeneren los certificados o
cambie la IP de Tailscale.**

## Pendiente de configurar a mano

### 1. Tailscale en el PC — "Ejecutar sin supervisión"

Clic derecho en el icono de la bandeja del sistema → Preferencias → **Ejecutar sin
supervisión**. Sin esto, la conexión de Tailscale queda atada a la sesión de escritorio
interactiva: si el PC se reinicia sin que nadie inicie sesión, Tailscale se queda en
`NeedsLogin` y el móvil no puede llegar al servicio.

Verificar el estado en cualquier momento:

```powershell
& "C:\Program Files\Tailscale\tailscale.exe" status
```

Debe decir `Running` (no `Logged out` / `NeedsLogin`). `run.py` ya intenta reactivarlo solo
al arrancar (`controladora/tailscale.py`), pero eso no sustituye al modo sin supervisión.

### 2. Si la IP de Tailscale del PC cambia

Añadirla a los SAN del certificado y reemitir solo el del servidor (la CA y el cert de
cliente que ya tenga la app instalada siguen valiendo):

```powershell
# editar el array "san" en pc\config.json y luego:
.\.venv\Scripts\python.exe scripts\gen_certs.py --force-server
.\.venv\Scripts\python.exe scripts\sync_app_secrets.py --host <nueva-ip-100.x.y.z>
```

### 3. Limpieza pendiente (no bloquea nada, pero conviene hacerla)

Quedaron reglas de firewall fantasma bloqueando `python.exe` en el perfil Público —
Windows las crea solas cuando un programa pide escuchar en un puerto y nadie contesta al
aviso (pasa si el servidor arranca en segundo plano, sin ventana). No afectaron a la ruta
por Tailscale, pero sí bloquearían una conexión directa por LAN. Revisar y borrar (PowerShell
**como administrador**):

```powershell
Get-NetFirewallRule -DisplayName "python.exe" -Action Block -Direction Inbound |
  ForEach-Object {
    Write-Host "Eliminando: $($_.Name) [$($_.DisplayName)]"
    Remove-NetFirewallRule -Name $_.Name
  }
```

## Seguridad

- `certs/`, `config.json` y `movil/secrets.properties` **nunca** al repo.
- La app **no usa el almacén de confianza del sistema**: solo confía en nuestra CA.
  Eso es el pinning, y hace que ni una CA pública comprometida pueda hacer MITM.
- El servicio corre como usuario normal. **Nunca como administrador.**
