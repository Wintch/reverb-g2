#!/usr/bin/env python3
"""Registro de pruebas físicas del casco. Existe por un problema real de este proyecto.

La verificación del 90Hz es FÍSICA: sólo vale lo que el usuario ve adentro del casco. Pero
las corridas tenían duración fija, así que una prueba podía "vencer" mientras el usuario
todavía estaba mirando o antes de que contestara, y después no se sabía a qué corrida
correspondía cada "no veo nada". Eso ya contamino resultados.

Reglas que impone este script:
  - cada prueba tiene un ID y queda escrita ANTES de que el usuario mire;
  - el veredicto se anota textual, con las palabras del usuario;
  - una prueba sin veredicto queda marcada PENDIENTE y se ve en el listado.

  ./testlog.py open  "<modo>" "<que reporto el driver>"   -> imprime el ID
  ./testlog.py close <ID> "<lo que dijo el usuario>"
  ./testlog.py list
"""
import datetime, json, os, sys

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "pruebas.jsonl")
LOG = os.path.normpath(LOG)


def load():
    if not os.path.exists(LOG):
        return []
    with open(LOG) as f:
        return [json.loads(l) for l in f if l.strip()]


def stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    rows = load()

    if cmd == "open":
        if len(sys.argv) < 3:
            sys.exit("falta el modo")
        n = len(rows) + 1
        rec = {
            "id": f"T{n:03d}",
            "abierta": stamp(),
            "modo": sys.argv[2],
            "driver": sys.argv[3] if len(sys.argv) > 3 else "",
            "veredicto": None,
            "cerrada": None,
        }
        with open(LOG, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(rec["id"])

    elif cmd == "close":
        if len(sys.argv) < 4:
            sys.exit("uso: close <ID> \"<lo que dijo el usuario>\"")
        tid, verdict = sys.argv[2], sys.argv[3]
        hit = False
        for r in rows:
            if r["id"] == tid:
                r["veredicto"] = verdict
                r["cerrada"] = stamp()
                hit = True
        if not hit:
            sys.exit(f"no existe {tid}")
        with open(LOG, "w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"{tid} cerrada: {verdict}")

    elif cmd == "list":
        if not rows:
            print("  (sin pruebas)")
            return
        for r in rows:
            v = r["veredicto"] if r["veredicto"] else "*** PENDIENTE ***"
            print(f"  {r['id']}  {r['abierta']}  {r['modo']:<26}  {v}")
        pend = [r["id"] for r in rows if not r["veredicto"]]
        if pend:
            print(f"\n  sin veredicto: {', '.join(pend)}")

    else:
        sys.exit(__doc__)


main()
