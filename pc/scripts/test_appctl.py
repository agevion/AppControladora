"""Prueba la capa `controladora/appctl` sin levantar el servidor.

    python scripts/test_appctl.py                  # solo lee
    python scripts/test_appctl.py --enviar "hola"  # ademas escribe y envia

Las sondas (`probe_appctl.py`) comprobaron que la via es posible con Win32 y UIA
en crudo. Esto comprueba otra cosa: que la capa que se ha construido encima
hace lo mismo, con su API, y desde el hilo de COM que usara el servidor.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from controladora.appctl import sessions, uia, window  # noqa: E402
from controladora.appctl import input as entrada  # noqa: E402
from controladora.registry import Registry  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--escribir",
        metavar="TEXTO",
        help="teclea TEXTO en el compositor, comprueba que llego entero y lo borra. NO lo envia.",
    )
    ap.add_argument("--enviar", metavar="TEXTO", help="escribe TEXTO en la app y lo envia DE VERDAD")
    ap.add_argument("--espera", type=int, default=90)
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    fallos = 0

    print("--- la ventana ---")
    v = window.buscar()
    if v is None:
        print("  la app no esta abierta; probando a abrirla...")
        try:
            v = window.asegurar()
        except window.NoEstaLaApp as e:
            print(f"  FALLO: {e}")
            return 1
    print(f"  {v.titulo!r} hwnd={v.hwnd} render={v.render} pid={v.pid}")
    print(f"  rectangulo={window.rect(v)} en_primer_plano={window.en_primer_plano(v)}")

    print("\n--- el arbol de accesibilidad ---")
    nodos = uia.despertar(v.hwnd)
    print(f"  {nodos} nodos")
    if nodos <= 50:
        print("  FALLO: el contenido web no se expone")
        fallos += 1

    print("\n--- las sesiones (indice en disco) ---")
    todas = sessions.listar()
    print(f"  {len(todas)} sesiones")
    for s in todas[:3]:
        print(f"    {s.titulo!r} modelo={s.modelo} esfuerzo={s.esfuerzo} permisos={s.modo}")
    if not todas:
        print("  FALLO: no hay ninguna sesion en el indice")
        fallos += 1

    print("\n--- la vista de la interfaz ---")
    vista = uia.vista(v.hwnd, sessions.titulos())
    print(f"  texto de pantalla: {len(vista.texto)} caracteres")
    print(f"  compositor: {vista.compositor.strip()[:60]!r}")
    print(f"  sesion que se esta viendo: {vista.titulo_abierto!r}")
    print(f"  modelo={vista.modelo!r}  uso={vista.uso!r}")
    print(f"  barra bajo el compositor: {[m.nombre for m in vista.barra]}")
    print(f"  mandos visibles: {len(vista.mandos)}")
    for s in vista.sesiones[:5]:
        print(f"    sesion {s.titulo!r} estado={s.estado_crudo!r} trabajando={s.trabajando}")
    if not vista.texto:
        print("  FALLO: no se lee el texto de la pantalla")
        fallos += 1
    if not vista.sesiones:
        print("  FALLO: ninguna sesion del disco casa con la barra lateral")
        fallos += 1

    print("\n--- la transcripcion ---")
    activa = sessions.activa()
    jsonl = sessions.transcripcion(activa) if activa else None
    if jsonl is None:
        print("  FALLO: la sesion activa no tiene .jsonl")
        fallos += 1
    else:
        msgs, pos = sessions.leer(jsonl)
        print(f"  {jsonl.name}: {len(msgs)} mensajes, desplazamiento final {pos}")
        for m in msgs[-4:]:
            etiqueta = m.nombre if m.tipo == "tool" else m.texto[:70]
            print(f"    [{m.rol}/{m.tipo}] {etiqueta}")
        # Leer desde el final no debe devolver nada: es lo que hace el streaming
        # despues de enviar, y si aqui saliera algo, el movil veria mensajes
        # viejos como si fueran la respuesta nueva.
        nuevos, _ = sessions.leer(jsonl, pos)
        if nuevos:
            print(f"  FALLO: leer desde el final devolvio {len(nuevos)} mensajes")
            fallos += 1
        else:
            print("  leer desde el final no devuelve nada: correcto")

    print("\n--- el registry ve las tools nuevas ---")
    reg = Registry()
    reg.load()
    for nombre in ("claude_app_estado", "claude_app_enviar"):
        t = reg.get(nombre)
        if t is None:
            print(f"  FALLO: falta la tool {nombre}")
            fallos += 1
        else:
            print(f"  {nombre}: OK (confirma={t.confirm})")
    if reg.errors():
        print(f"  FALLO: tools con error: {reg.errors()}")
        fallos += 1

    if args.escribir:
        # Todo el camino de escritura menos la ultima tecla: enfocar, traer la
        # ventana al frente, teclear por mensajes y comprobar que llego entero.
        # Sin Enter, asi que no se envia nada ni se gasta un token.
        print(f"\n--- escribir sin enviar: {args.escribir!r} ---")
        antes_foco = window.ventana_al_frente()
        try:
            quedo = entrada.escribir(v, args.escribir)
            print(f"  el compositor dice: {quedo.strip()[:120]!r}")
            if args.escribir not in quedo:
                print("  FALLO: el texto no llego entero")
                fallos += 1
            else:
                print("  el texto llego entero")
        except entrada.NoSePudoEscribir as e:
            print(f"  FALLO: {e}")
            fallos += 1
        finally:
            entrada.limpiar(v)
            restante = uia.texto_compositor(v.hwnd)
            print(f"  compositor tras limpiar: {restante.strip()[:60]!r}")
            if args.escribir in restante:
                print("  FALLO: no se pudo borrar lo que se escribio")
                fallos += 1
            if antes_foco and antes_foco != v.hwnd:
                window.traer_al_frente(antes_foco)

    if args.enviar:
        print(f"\n--- enviar de verdad: {args.enviar!r} ---")
        desde = sessions.tamano(jsonl) if jsonl else 0
        try:
            entrada.enviar(v, args.enviar)
            print("  enviado")
        except entrada.NoSePudoEscribir as e:
            print(f"  FALLO: {e}")
            return fallos + 1
        if jsonl:
            print(f"  esperando respuesta hasta {args.espera}s...")
            algo = False
            for m in sessions.esperar(jsonl, desde, espera=args.espera):
                if m.rol != "assistant":
                    continue
                algo = True
                etiqueta = m.nombre if m.tipo == "tool" else m.texto[:100]
                print(f"    >> [{m.tipo}] {etiqueta}")
                if m.tipo == "texto":
                    break
            if not algo:
                print("  FALLO: no llego nada del asistente")
                fallos += 1

    print("\n" + "=" * 60)
    if fallos:
        print(f"{fallos} comprobaciones han fallado.")
        return 1
    print("appctl OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
