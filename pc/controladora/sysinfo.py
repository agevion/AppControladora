"""Estado del PC, medido rapido y devuelto como datos, no como parrafo.

Dos motivos para que esto exista aparte de la tool `system_stats`:

1. **La pantalla de Monitor del movil quiere datos, no texto.** Antes el movil
   recibia el mismo parrafo que lee el modelo y lo pintaba en monoespaciado tal
   cual: imposible dibujar una barra con eso sin re-parsear a mano lo que ya
   veniamos de formatear. Aqui se mide una vez y se sirve estructurado
   (`snapshot()`); el texto para el modelo se genera desde los mismos datos
   (`to_text()`), asi que los dos no pueden contradecirse.

2. **El refresco es cada 5 segundos.** Lo de antes tardaba ~1s largo por lectura
   y se notaba como "el monitor cuesta un huevo de cargar": `cpu_percent(interval=0.5)`
   duerme medio segundo a proposito, y cada lectura arrancaba un proceso
   `nvidia-smi` nuevo (~300ms). Aqui la CPU se lee sin bloquear (contador
   acumulado desde la lectura anterior, que ademas da una media mas util que
   medio segundo suelto) y la GPU se cachea (`GPU_TTL`), asi que abrir la
   pestana pinta al instante.

Sobre la temperatura de CPU, que costo una discusion y en la que me equivoque:

Windows no la expone a un proceso normal. Un Ryzen publica Tctl/Tdie por un
registro que pide un driver en anillo 0, y este servicio corre como usuario
normal a proposito (ARQUITECTURA.md seccion 9). Hasta ahi, correcto -- y de ahi
la conclusion equivocada de que "no se puede": claro que se puede, lo hace
cualquier programa que traiga su propio driver. NZXT CAM, que ya estaba
instalado en este PC, la enseña sin problema. Lo que CAM no hace es publicarla
para que otro la lea.

Asi que la temperatura la lee **LibreHardwareMonitor**, que trae driver Y sabe
publicar: se le activa el servidor web (Options → Remote Web Server) y sirve
todos los sensores en JSON. Tiene que correr **como administrador** o el driver
no carga y la rama de la CPU no aparece.

Ojo con el camino que NO funciona, por si alguien lo intenta otra vez: **LHM
0.9.6 no tiene proveedor WMI**. La primera version de esto leia
`root\\LibreHardwareMonitor` por WMI y no podia funcionar nunca -- ese namespace
es de OpenHardwareMonitor, el proyecto del que LHM es fork, y en el binario de
LHM no aparece ni una cadena `root\\...`. Fallaba en silencio y quedaba como
"no hay sensor", que es justo la mentira que esto viene a arreglar.

Si LHM no esta corriendo se devuelve None y una nota que dice exactamente que
falta. No se dice "no hay sensor": el sensor esta, lo que falta es quien lo lea.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Any

import psutil

log = logging.getLogger("controladora.sysinfo")

# Cuanto vale una lectura de nvidia-smi antes de volver a arrancar el proceso.
# El movil refresca cada 5s y solo hay un movil: esto es sobre todo para que dos
# peticiones seguidas (abrir la pestana + el primer tick del bucle) no arranquen
# dos procesos para lo mismo.
GPU_TTL = 2.0

# Las particiones no cambian entre dos refrescos, y enumerarlas es lo mas caro
# de todo esto (toca cada unidad, y una extraible dormida puede tardar).
DISK_TTL = 30.0

# Donde publica LibreHardwareMonitor. Se puede cambiar en paths.json
# (lhm.url) si algun dia el 8085 choca con otra cosa.
LHM_URL = "http://127.0.0.1:8085/data.json"

# La temperatura se mueve, asi que la cache es corta: es para que dos lecturas
# seguidas no bajen dos veces un JSON de 84 KB, no para congelar el valor.
TEMP_TTL = 2.0

# Cuanto se espera antes de volver a intentarlo cuando LHM NO esta. Un puerto
# cerrado falla al instante (connection refused), asi que esto es sobre todo por
# si el proceso esta ahi pero atascado: no se puede pagar un timeout en cada
# refresco de una pantalla que se pinta cada 3 segundos.
TEMP_RETRY_TTL = 30.0

_lock = threading.Lock()
_gpu_cache: tuple[float, dict[str, Any]] | None = None
_disk_cache: tuple[float, list[dict[str, Any]]] | None = None
_temp_cache: tuple[float, float | None, str | None] | None = None


def _primer_contador() -> None:
    """psutil mide CPU por diferencia contra la lectura anterior, asi que la
    primerisima llamada siempre devuelve 0.0. Se ceba al importar para que el
    primer refresco del movil ya traiga un numero de verdad."""
    psutil.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None, percpu=True)


_primer_contador()


def _lhm_corriendo() -> bool:
    for p in psutil.process_iter(["name"]):
        if (p.info["name"] or "").lower() == "librehardwaremonitor.exe":
            return True
    return False


def _nota_temp() -> str:
    """Por que no hay temperatura, mirando cual de los eslabones falta.

    Esto NO es cosmetico. La primera version soltaba siempre la misma frase --
    "tiene que estar corriendo como administrador y con Options → Remote Web
    Server → Run activado"-- y era un mal consejo heredado de cuando LHM se
    lanzaba a mano: hoy de eso se encarga el sistema solo (ver sensores.py). En
    uso real el motivo era que faltaba pasar `instalar_admin.bat`, y el movil, en
    vez de decirlo, mandaba a toquetear opciones de un programa que ni siquiera
    estaba abierto. Un mensaje de error que te manda al sitio equivocado cuesta
    mas caro que no decir nada.
    """
    from . import sensores

    if not sensores.instalado():
        return (
            "Temperatura de CPU no disponible: falta el ayudante de sensores. "
            "En el PC, UNA sola vez: doble clic en pc\\instalar_admin.bat (pide UAC). "
            "Después cierra y reabre arrancar.bat."
        )
    if not _lhm_corriendo():
        return (
            "Temperatura de CPU no disponible: LibreHardwareMonitor no está corriendo. "
            "Cierra y reabre arrancar.bat (se lanza con él)."
        )
    return (
        "Temperatura de CPU no disponible: LibreHardwareMonitor está corriendo pero no "
        "contesta en su puerto. Comprueba que tenga Options → Remote Web Server → Run "
        "activado, y que el puerto sea el de paths.json (sensores.url)."
    )


def _cpu_temp(url: str = LHM_URL) -> tuple[float | None, str | None]:
    """(temperatura, nota). Uno de los dos siempre es None."""
    global _temp_cache
    ahora = time.monotonic()
    if _temp_cache is not None:
        edad = ahora - _temp_cache[0]
        # Si la ultima vez no habia nadie, no se reintenta en cada refresco: la
        # nota cuesta un `schtasks /query` y un recorrido de procesos.
        ttl = TEMP_TTL if _temp_cache[1] is not None else TEMP_RETRY_TTL
        if edad < ttl:
            return _temp_cache[1], _temp_cache[2]

    valor = _leer_temp_lhm(url)
    nota = None if valor is not None else _nota_temp()
    _temp_cache = (ahora, valor, nota)
    return valor, nota


def _valor_grados(texto: str) -> float | None:
    """'51,6 °C' -> 51.6

    LHM formatea con la coma decimal del sistema (este PC esta en español), asi
    que un float() directo sobre eso lanza. El sufijo tampoco es fijo: puede
    venir con o sin espacio antes del simbolo.
    """
    limpio = texto.replace("°C", "").replace("C", "").strip().replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return None


def _leer_temp_lhm(url: str) -> float | None:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        # LHM no esta abierto, o no tiene el servidor web activo. Es un estado
        # normal del sistema, no un error que haya que gritar.
        return None

    # El JSON es un arbol de nodos con Children; los sensores son las hojas, y lo
    # que los identifica de verdad es SensorId (estable), no el Text (que esta
    # traducido y cambia con la version).
    candidatos: list[tuple[int, float]] = []

    def recorrer(nodo: dict[str, Any]) -> None:
        sid = str(nodo.get("SensorId") or "")
        if "/temperature/" in sid and ("/amdcpu/" in sid or "/intelcpu/" in sid):
            grados = _valor_grados(str(nodo.get("Value") or ""))
            if grados is not None:
                texto = str(nodo.get("Text") or "").lower()
                # El bueno es el del paquete entero (en Ryzen, "Core (Tctl/Tdie)"),
                # no el de un CCD o un nucleo suelto: es el que enseñan CAM y la
                # BIOS, y por tanto el numero que el usuario espera reconocer.
                if "tctl" in texto or "tdie" in texto or "package" in texto:
                    prioridad = 0 if "ccd" not in texto else 1
                else:
                    prioridad = 2
                candidatos.append((prioridad, grados))
        for hijo in nodo.get("Children") or []:
            recorrer(hijo)

    recorrer(data)
    if not candidatos:
        return None
    return min(candidatos, key=lambda c: c[0])[1]


def _gpu() -> dict[str, Any]:
    global _gpu_cache
    ahora = time.monotonic()
    with _lock:
        if _gpu_cache is not None and ahora - _gpu_cache[0] < GPU_TTL:
            return _gpu_cache[1]

    datos = _leer_gpu()
    with _lock:
        _gpu_cache = (ahora, datos)
    return datos


def _leer_gpu() -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            # Sin esto, cada lectura hace parpadear una consola negra en el
            # escritorio del PC. Cada 5 segundos. Para siempre.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        return {"error": "nvidia-smi no encontrado"}
    except subprocess.TimeoutExpired:
        return {"error": "nvidia-smi no respondio en 10s"}

    if proc.returncode != 0:
        return {"error": f"nvidia-smi fallo: {(proc.stderr or '').strip()[:120]}"}

    partes = [p.strip() for p in proc.stdout.strip().split(",")]
    if len(partes) != 6:
        return {"error": f"salida inesperada de nvidia-smi: {proc.stdout.strip()[:120]}"}

    def _num(texto: str) -> float | None:
        try:
            return float(texto)
        except ValueError:
            # nvidia-smi devuelve "[N/A]" en campos que la tarjeta no reporta
            # (la 1080 Ti no da power.draw en algunos drivers).
            return None

    return {
        "nombre": partes[0],
        "temp_c": _num(partes[1]),
        "uso_pct": _num(partes[2]),
        "vram_usada_mb": _num(partes[3]),
        "vram_total_mb": _num(partes[4]),
        "potencia_w": _num(partes[5]),
    }


def _discos() -> list[dict[str, Any]]:
    global _disk_cache
    ahora = time.monotonic()
    with _lock:
        if _disk_cache is not None and ahora - _disk_cache[0] < DISK_TTL:
            return _disk_cache[1]

    salida: list[dict[str, Any]] = []
    for part in psutil.disk_partitions(all=False):
        # Una unidad de CD vacia o una extraible dormida lanza aqui. Un disco
        # que no se puede leer no debe tumbar el monitor entero.
        try:
            uso = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        salida.append(
            {
                "unidad": part.mountpoint.rstrip("\\"),
                "pct": round(uso.percent, 1),
                "usado_gb": round(uso.used / 1024**3, 1),
                "total_gb": round(uso.total / 1024**3, 1),
            }
        )

    with _lock:
        _disk_cache = (ahora, salida)
    return salida


def snapshot() -> dict[str, Any]:
    """Una foto del PC ahora mismo. Sincrono pero rapido (sin sleeps).

    Llamalo desde asyncio.to_thread igualmente: nvidia-smi arranca un proceso
    cuando toca refrescar la cache, y eso no debe pasar en el event loop.
    """
    cpu_pct = psutil.cpu_percent(interval=None)
    por_nucleo = psutil.cpu_percent(interval=None, percpu=True)
    ram = psutil.virtual_memory()

    try:
        freq = psutil.cpu_freq()
        freq_mhz = round(freq.current) if freq else None
    except Exception:
        # cpu_freq no esta disponible en todas las maquinas/permisos.
        freq_mhz = None

    # La URL sale de paths.json (con LHM_URL de reserva) para no tener el puerto
    # escrito en dos sitios que puedan discrepar.
    from . import paths

    temp, nota_temp = _cpu_temp(str(paths.sensores().get("url") or LHM_URL))

    return {
        "cpu": {
            "pct": round(cpu_pct, 1),
            "nucleos": psutil.cpu_count(logical=True),
            "por_nucleo": [round(v, 1) for v in por_nucleo],
            "freq_mhz": freq_mhz,
            "temp_c": temp,
            "temp_nota": nota_temp,
        },
        "ram": {
            "pct": round(ram.percent, 1),
            "usada_gb": round(ram.used / 1024**3, 1),
            "total_gb": round(ram.total / 1024**3, 1),
        },
        "gpu": _gpu(),
        "discos": _discos(),
        "uptime_s": int(time.time() - psutil.boot_time()),
        "ts": time.time(),
    }


def _uptime_txt(segundos: int) -> str:
    dias, resto = divmod(segundos, 86400)
    horas, resto = divmod(resto, 3600)
    minutos = resto // 60
    if dias:
        return f"{dias}d {horas}h {minutos}m"
    if horas:
        return f"{horas}h {minutos}m"
    return f"{minutos}m"


def to_text(snap: dict[str, Any] | None = None) -> str:
    """El mismo estado, en el texto que lee un modelo de 8B.

    Sale de `snapshot()` y no de una segunda lectura a proposito: si el movil y
    el chat miden por su cuenta, acaban diciendo cosas distintas del mismo PC.
    """
    s = snap if snap is not None else snapshot()
    cpu, ram, gpu = s["cpu"], s["ram"], s["gpu"]

    if cpu["temp_c"] is not None:
        cpu_temp = f", {cpu['temp_c']:.0f}°C"
    else:
        cpu_temp = ", temperatura no disponible (LibreHardwareMonitor no responde)"

    freq = f", {cpu['freq_mhz']} MHz" if cpu["freq_mhz"] else ""

    lineas = [
        f"CPU: {cpu['pct']:.0f}% de {cpu['nucleos']} nucleos logicos{freq}{cpu_temp}",
        f"RAM: {ram['pct']:.0f}% — {ram['usada_gb']:.1f} / {ram['total_gb']:.1f} GB",
    ]

    if "error" in gpu:
        lineas.append(f"GPU: no se pudo leer ({gpu['error']})")
    else:
        potencia = f", {gpu['potencia_w']:.0f} W" if gpu.get("potencia_w") is not None else ""
        temp_gpu = f", {gpu['temp_c']:.0f}°C" if gpu.get("temp_c") is not None else ""
        lineas.append(
            f"GPU: {gpu['nombre']} — {gpu['uso_pct']:.0f}% carga{temp_gpu}, "
            f"{gpu['vram_usada_mb']:.0f}/{gpu['vram_total_mb']:.0f} MiB VRAM{potencia}"
        )

    for d in s["discos"]:
        # 'unidad' ya trae los dos puntos de Windows ("C:"), no se le anaden otros.
        lineas.append(f"Disco {d['unidad']} {d['pct']:.0f}% — {d['usado_gb']:.0f} / {d['total_gb']:.0f} GB")

    lineas.append(f"Encendido desde hace {_uptime_txt(s['uptime_s'])}")
    return "\n".join(lineas)
