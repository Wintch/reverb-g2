#!/usr/bin/env python3
"""Log of physical headset tests. Exists because of a real problem in this project.

Verifying 90Hz is PHYSICAL: only what the user sees inside the headset counts. But
the runs had a fixed duration, so a test could "expire" while the user was still
looking or before they answered, and afterward there was no way to know which run
each "I don't see anything" corresponded to. That already contaminated results.

Rules this script enforces:
  - every test has an ID and is written BEFORE the user looks;
  - the verdict is recorded verbatim, in the user's own words;
  - a test with no verdict is marked PENDING and shows up in the listing.

  ./testlog.py open  "<mode>" "<what the driver reported>"   -> prints the ID
  ./testlog.py close <ID> "<what the user said>"
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
            sys.exit("missing mode")
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
            sys.exit("usage: close <ID> \"<what the user said>\"")
        tid, verdict = sys.argv[2], sys.argv[3]
        hit = False
        for r in rows:
            if r["id"] == tid:
                r["veredicto"] = verdict
                r["cerrada"] = stamp()
                hit = True
        if not hit:
            sys.exit(f"{tid} does not exist")
        with open(LOG, "w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"{tid} closed: {verdict}")

    elif cmd == "list":
        if not rows:
            print("  (no tests)")
            return
        for r in rows:
            v = r["veredicto"] if r["veredicto"] else "*** PENDING ***"
            print(f"  {r['id']}  {r['abierta']}  {r['modo']:<26}  {v}")
        pend = [r["id"] for r in rows if not r["veredicto"]]
        if pend:
            print(f"\n  no verdict: {', '.join(pend)}")

    else:
        sys.exit(__doc__)


main()
