"""Que esta haciendo ahora mismo la app de escritorio de Claude.

Solo lee: ni escribe, ni pulsa, ni trae la ventana al frente. Por eso no pide
confirmacion.
"""

from __future__ import annotations

from controladora.appctl import sessions, uia, window

SPEC = {
    "name": "claude_app_estado",
    "description": (
        "Mira la aplicacion de escritorio de Claude en el PC (no el CLI): que sesiones "
        "tiene, cual esta trabajando, con que modelo, cuanto contexto lleva gastado y "
        "los ultimos mensajes de la sesion activa. Solo lee, no toca nada."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mensajes": {
                "type": "integer",
                "description": "Cuantos mensajes recientes mostrar de la sesion activa (por defecto 8).",
            }
        },
        "required": [],
    },
}

CONFIRM = False


def run(mensajes: int = 8) -> str:
    v = window.buscar()
    if v is None:
        return (
            "La app de escritorio de Claude no esta abierta.\n"
            "(Se puede abrir sola cuando haga falta: window.asegurar())"
        )

    lineas = [f"Ventana: '{v.titulo}' (hwnd={v.hwnd}, pid={v.pid})"]

    todas = sessions.listar()
    lineas.append(f"Sesiones en el indice: {len(todas)}")

    try:
        uia.despertar(v.hwnd)
        vista = uia.vista(v.hwnd, sessions.titulos())
    except Exception as e:
        lineas.append(f"No pude leer la interfaz: {type(e).__name__}: {e}")
        vista = None

    if vista is not None:
        if vista.modelo:
            lineas.append(f"Modelo: {vista.modelo}")
        if vista.uso:
            lineas.append(f"Uso: {vista.uso}")
        if vista.compositor.strip():
            lineas.append(f"En el compositor: {vista.compositor.strip()[:120]!r}")

        # El estado de cada sesion sale de la barra lateral, que es quien de
        # verdad sabe cual esta corriendo. El indice de disco solo sabe cuando
        # se toco por ultima vez.
        en_marcha = [s.titulo for s in vista.sesiones if s.trabajando]
        if en_marcha:
            lineas.append(f"Trabajando ahora: {', '.join(en_marcha)}")
        else:
            lineas.append("Ninguna sesion visible esta trabajando.")

        desconocidos = {s.estado_crudo for s in vista.sesiones if s.trabajando is None}
        if desconocidos:
            # Si la app cambia de idioma o de vocabulario, esto sale a la luz en
            # vez de mentir diciendo "parada".
            lineas.append(f"Estados que no reconozco: {sorted(desconocidos)}")

    activa = sessions.activa()
    if activa is None:
        return "\n".join(lineas)

    lineas.append("")
    lineas.append(
        f"Sesion activa: '{activa.titulo}'\n"
        f"  carpeta={activa.cwd}  modelo={activa.modelo}  "
        f"esfuerzo={activa.esfuerzo}  permisos={activa.modo}"
    )

    jsonl = sessions.transcripcion(activa)
    if jsonl is None:
        lineas.append("  (todavia no tiene transcripcion en disco)")
        return "\n".join(lineas)

    todos, _ = sessions.leer(jsonl)
    lineas.append(f"  ultimos {min(mensajes, len(todos))} de {len(todos)} mensajes:")
    for m in todos[-mensajes:]:
        if m.tipo == "tool":
            lineas.append(f"    [{m.rol}] herramienta {m.nombre}")
        elif m.tipo == "pensando":
            lineas.append(f"    [{m.rol}] (razonando)")
        else:
            lineas.append(f"    [{m.rol}] {m.texto[:160]}")

    return "\n".join(lineas)
