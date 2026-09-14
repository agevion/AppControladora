"""Garantiza que NADA de lo que este proceso lanza sobrevive a este proceso.

Cerrar la ventana con la X, Ctrl+C, un crash, un `taskkill /F` -- todo eso
termina el proceso de una forma u otra, y NINGUNA de esas formas ejecuta con
fiabilidad nuestro propio codigo de limpieza:

- `atexit` (que ya usa claude_agent_sdk para matar su `claude.exe`) NO corre en
  una terminacion forzosa. Cerrar la consola con la X manda CTRL_CLOSE_EVENT y
  da ~5s de margen; si el proceso no ha terminado el, Windows lo mata en seco
  y ningun atexit llega a ejecutarse.
- Un `taskkill /F` o un crash tampoco dan ninguna oportunidad de limpiar.

La garantia de verdad la da el kernel, no nuestro codigo: un Job Object con
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE mata a todo lo que este dentro del job en
cuanto se cierra el ultimo handle del job -- y Windows SIEMPRE cierra los
handles de un proceso al terminar, sin excepcion, sea cual sea el motivo.

Como usarlo: al arrancar `run.py`, se mete el PROPIO proceso dentro del job
(`protect_self()`). A partir de ahi, cualquier proceso hijo que se lance desde
aqui -- Ollama, un `claude.exe` del Agent SDK, un `gradlew.bat` a medias --
hereda el job automaticamente (asi es como funcionan los Job Objects en
Windows por defecto). No hace falta acordarse de proteger cada tool nueva: se
protegen solas en cuanto existen, mientras nazcan de este proceso.

No hace falta ser administrador para esto: un proceso puede meterse a si mismo
y a sus propios hijos en un job sin privilegios especiales.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_JobObjectExtendedLimitInformation = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_PROCESS_ALL_ACCESS = 0x1F0FFF


class _IoCounters(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


# Los HANDLE de Windows son de 8 bytes en 64 bits. Sin fijar restype/argtypes,
# ctypes los trata como c_int (4 bytes) por defecto y el valor se corrompe: el
# job "funcionaria" a medias y fallaria raro y lejos, no aqui.
_kernel32.CreateJobObjectW.restype = wintypes.HANDLE
_kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
_kernel32.SetInformationJobObject.restype = wintypes.BOOL
_kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
_kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
_kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.GetCurrentProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class JobError(Exception):
    """Fallo de la API de Windows. Quien llama decide si es fatal o solo un aviso."""


class KillOnCloseJob:
    """Un job vivo mientras viva este objeto en memoria.

    NO llames a `close()` durante el funcionamiento normal: el job debe seguir
    abierto hasta que el proceso entero termine, sea como sea. Cerrarlo antes
    mataria a los hijos en ese mismo instante, no al final.
    """

    def __init__(self) -> None:
        handle = _kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise JobError(f"CreateJobObjectW fallo: {ctypes.get_last_error()}")
        self._handle = handle

        info = _ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = _kernel32.SetInformationJobObject(
            self._handle, _JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
        )
        if not ok:
            err = ctypes.get_last_error()
            _kernel32.CloseHandle(self._handle)
            raise JobError(f"SetInformationJobObject fallo: {err}")

    def protect_self(self) -> None:
        """Mete AL PROPIO PROCESO en el job.

        A partir de aqui, todo lo que este proceso lance como hijo (Ollama via
        subprocess.Popen, el `claude.exe` del Agent SDK, cualquier tool que
        haga run_shell/build_gradle/...) hereda el job sin que haya que tocar
        nada mas: asi es como funcionan los Job Objects en Windows por
        defecto, salvo que el hijo pida explicitamente escaparse.
        """
        self._assign(_kernel32.GetCurrentProcess())

    def protect_pid(self, pid: int) -> None:
        """Red de seguridad extra para un proceso concreto ya lanzado.

        Normalmente no hace falta: si `protect_self()` funciono, sus hijos ya
        estan dentro. Esto cubre el caso raro en que meter al propio proceso
        fallara (ej. si algo externo ya lo metio en OTRO job sin permiso de
        anidar) pero abrir el hijo suelto si funcione.
        """
        handle = _kernel32.OpenProcess(_PROCESS_ALL_ACCESS, False, pid)
        if not handle:
            raise JobError(f"OpenProcess({pid}) fallo: {ctypes.get_last_error()}")
        try:
            self._assign(handle)
        finally:
            _kernel32.CloseHandle(handle)

    def _assign(self, handle: int) -> None:
        if not _kernel32.AssignProcessToJobObject(self._handle, handle):
            raise JobError(f"AssignProcessToJobObject fallo: {ctypes.get_last_error()}")
