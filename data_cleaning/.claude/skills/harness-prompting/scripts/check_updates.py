"""Detecta cambios en Learn Harness Engineering (walkinglabs) desde la última revisión.

Compara el hash (blob SHA) de cada archivo bajo docs/en/ del repo github.com/walkinglabs/learn-harness-engineering
(desde ahí se publica https://walkinglabs.github.io/learn-harness-engineering/en/) contra el guardado en ../estado.json.
Detecta archivos nuevos, modificados y eliminados sin depender del tamaño de los commits.

Uso:
  python check_updates.py            # lista cambios (no toca el estado)
  python check_updates.py --marcar   # guarda el estado actual como revisado
  python check_updates.py --si-toca  # sale en silencio si la última revisión tiene < DIAS días
"""
import json
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

DIAS = 7
REPO = "walkinglabs/learn-harness-engineering"
PREFIJO = "docs/en/"
ESTADO = Path(__file__).resolve().parent.parent / "estado.json"
RAW = f"https://raw.githubusercontent.com/{REPO}/main/"

sys.stdout.reconfigure(encoding="utf-8")


def arbol():
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/git/trees/main?recursive=1",
                                 headers={"User-Agent": "curso-prompt-skill", "Accept": "application/vnd.github+json"})
    d = json.loads(urllib.request.urlopen(req, timeout=30).read())
    if d.get("truncated"):
        raise SystemExit("El árbol de GitHub vino truncado: revisar a mano docs/en en el repo.")
    archivos = {x["path"]: x["sha"] for x in d["tree"] if x["type"] == "blob" and x["path"].startswith(PREFIJO)}
    if not archivos:
        raise SystemExit("No encontré archivos en docs/en: ¿cambió la estructura del repo?")
    return archivos


def main():
    args = set(sys.argv[1:])
    estado = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {}
    ultima = estado.get("ultima_revision")
    if "--si-toca" in args and ultima and (date.today() - datetime.fromisoformat(ultima).date()).days < DIAS:
        return
    actual, previo = arbol(), estado.get("archivos", {})
    print(f"Última revisión: {ultima or 'nunca'} · archivos en docs/en: {len(actual)}")
    if not previo:
        print("Sin estado previo: leer el sitio completo y luego --marcar.")
    else:
        cambios = ([f"NUEVO: {RAW}{p}" for p in sorted(actual.keys() - previo.keys())]
                   + [f"MODIFICADO: {RAW}{p}" for p in sorted(p for p in actual.keys() & previo.keys() if actual[p] != previo[p])]
                   + [f"ELIMINADO: {p}" for p in sorted(previo.keys() - actual.keys())])
        print("\n".join(cambios) or "Sin novedades.")
    if "--marcar" in args:
        ESTADO.write_text(json.dumps({"ultima_revision": date.today().isoformat(), "archivos": actual}, indent=1),
                          encoding="utf-8")
        print(f"Estado guardado en {ESTADO}")


if __name__ == "__main__":
    main()
