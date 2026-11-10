"""Detecta cambios en la documentación oficial de LangGraph y en las versiones publicadas desde la última revisión.

Fuentes:
- Repo github.com/langchain-ai/docs (desde ahí se publica https://docs.langchain.com): blob SHA de cada archivo
  de LangGraph y de las páginas de comparación que usa la skill.
- PyPI: versión actual de los paquetes que usan los ejemplos.
Estado en ../estado.json.

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
REPO = "langchain-ai/docs"
PREFIJOS = ("src/oss/langgraph/",)
EXACTOS = {
    "src/oss/python/releases/langgraph-v1.mdx",
    "src/oss/python/migrate/langgraph-v1.mdx",
    "src/oss/concepts/products.mdx",
    "src/oss/deepagents/overview.mdx",
    "src/oss/langchain/middleware/built-in.mdx",
    "src/oss/langchain/human-in-the-loop.mdx",
}
PAQUETES = ("langgraph", "langgraph-checkpoint-sqlite", "langchain", "langchain-anthropic", "deepagents", "duckdb")
ESTADO = Path(__file__).resolve().parent.parent / "estado.json"
RAW = f"https://raw.githubusercontent.com/{REPO}/main/"
UA = {"User-Agent": "curso-prompt-skill"}

sys.stdout.reconfigure(encoding="utf-8")


def get_json(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read())


def arbol():
    d = get_json(f"https://api.github.com/repos/{REPO}/git/trees/main?recursive=1")
    if d.get("truncated"):
        raise SystemExit("El árbol de GitHub vino truncado: revisar a mano src/oss/langgraph en el repo.")
    archivos = {x["path"]: x["sha"] for x in d["tree"]
                if x["type"] == "blob" and (x["path"].startswith(PREFIJOS) or x["path"] in EXACTOS)}
    faltan = EXACTOS - archivos.keys()
    if not any(p.startswith(PREFIJOS) for p in archivos) or faltan:
        print(f"AVISO: no encontré {sorted(faltan) or PREFIJOS}: ¿cambió la estructura del repo de docs?")
    return archivos


def versiones():
    return {p: get_json(f"https://pypi.org/pypi/{p}/json")["info"]["version"] for p in PAQUETES}


def main():
    args = set(sys.argv[1:])
    estado = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {}
    ultima = estado.get("ultima_revision")
    if "--si-toca" in args and ultima and (date.today() - datetime.fromisoformat(ultima).date()).days < DIAS:
        return
    actual, vers = arbol(), versiones()
    previo, vprevio = estado.get("archivos", {}), estado.get("versiones", {})
    print(f"Última revisión: {ultima or 'nunca'} · archivos seguidos: {len(actual)}")
    if not previo:
        print("Sin estado previo: leer las páginas y luego --marcar.")
    else:
        cambios = ([f"NUEVO: {RAW}{p}" for p in sorted(actual.keys() - previo.keys())]
                   + [f"MODIFICADO: {RAW}{p}" for p in sorted(p for p in actual.keys() & previo.keys()
                                                              if actual[p] != previo[p])]
                   + [f"ELIMINADO: {p}" for p in sorted(previo.keys() - actual.keys())]
                   + [f"VERSIÓN: {p} {vprevio.get(p, '?')} -> {v} (https://pypi.org/project/{p}/#history)"
                      for p, v in vers.items() if vprevio.get(p) != v])
        print("\n".join(cambios) or "Sin novedades.")
    if "--marcar" in args:
        ESTADO.write_text(json.dumps({"ultima_revision": date.today().isoformat(), "versiones": vers,
                                      "archivos": actual}, indent=1), encoding="utf-8")
        print(f"Estado guardado en {ESTADO}")


if __name__ == "__main__":
    main()
