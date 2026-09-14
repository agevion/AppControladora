"""Pilotar la app de escritorio de Claude (la de verdad, la que se ve en el PC).

Esto es el Cerebro D: a diferencia del Cerebro A (`brain_claude.py`), que habla
con el CLI de Claude Code por el Agent SDK, aqui no se habla con ningun modelo.
Se maneja LA APLICACION: se escribe en su compositor, se pulsan sus botones y se
lee su conversacion. Lo que pase, pasa en la ventana que tienes delante en el PC.

Reparto de responsabilidades, una por fichero:

    hilo.py      un unico hilo para todo lo que toque COM/UIA, y por que
    window.py    encontrar (o abrir) la ventana. Solo Win32, sin accesibilidad
    uia.py       leer y pulsar. EL UNICO sitio que sabe como es la interfaz
    sessions.py  las sesiones y la conversacion, leidas de disco
    input.py     escribir y enviar, con verificacion

Las dos decisiones que explican todo lo demas, y las dos estan medidas:

- **No hay depurador remoto.** La app se mata sola si la arrancas con
  `--remote-debugging-port`, salvo con un token firmado por Anthropic que caduca
  a los 300 s. Asi que se pilota por la accesibilidad de Windows, que es una API
  hecha para esto.
- **Para escribir hay que traer la ventana al primer plano.** Sin eso, los
  mensajes de teclado se descartan en silencio. Por eso `input.py` enfoca
  primero y aborta si no lo consigue, en vez de teclear a ciegas.
"""

from . import input, sessions, uia, window  # noqa: F401
from .input import NoSePudoEscribir  # noqa: F401
from .window import NoEstaLaApp, Ventana  # noqa: F401
