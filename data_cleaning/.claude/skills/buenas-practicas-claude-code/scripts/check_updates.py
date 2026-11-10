"""Detecta novedades oficiales de Claude Code desde la última revisión.

Fuentes: changelog y "What's new" de code.claude.com, índice llms.txt (páginas nuevas o eliminadas),
claude.com/blog y anthropic.com/engineering. Estado en ../estado.json.

Uso:
  python check_updates.py            # muestra novedades (no toca el estado)
  python check_updates.py --marcar   # guarda lo visto como revisado
  python check_updates.py --si-toca  # sale en silencio si la última revisión tiene < DIAS días
"""
import json
import re
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

DIAS = 7
ESTADO = Path(__file__).resolve().parent.parent / "estado.json"
DOCS = "https://code.claude.com/docs"
BLOGS = {
    "claude.com/blog": ("https://claude.com/blog", r'href="(/resources/articles/[a-z0-9-]{6,})"', "https://claude.com"),
    "anthropic engineering": ("https://www.anthropic.com/engineering",
                              r'href="(/(?:engineering|research)/[a-z0-9-]{6,})"', "https://www.anthropic.com"),
}

sys.stdout.reconfigure(encoding="utf-8")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (curso-prompt skill checker)"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")


def leer_estado():
    return json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {}


def main():
    args = set(sys.argv[1:])
    estado = leer_estado()
    ultima = estado.get("ultima_revision")
    if "--si-toca" in args and ultima and (date.today() - datetime.fromisoformat(ultima).date()).days < DIAS:
        return
    nuevo, hallazgos = {}, []

    # 1. Versión más reciente del changelog
    changelog = get(f"{DOCS}/en/changelog.md")
    versiones = re.findall(r"^(?:#+\s*|\*\*)\[?v?(\d+\.\d+\.\d+)", changelog, re.M)
    if not versiones:
        raise SystemExit("No pude leer versiones del changelog: revisar el formato de la página.")
    nuevo["version"] = versiones[0]
    vistas = estado.get("version")
    if vistas != versiones[0]:
        lista = versiones[: versiones.index(vistas)] if vistas in versiones else versiones[:10]
        hallazgos.append(f"CHANGELOG: versiones nuevas {', '.join(lista)} (antes: {vistas}). Leer {DOCS}/en/changelog.md")

    # 2. Digest semanal
    semanas = re.findall(r"\((https://code\.claude\.com/docs/en/whats-new/[\w-]+\.md)\)", get(f"{DOCS}/en/whats-new.md"))
    nuevo["whats_new"] = sorted(set(semanas))
    for s in sorted(set(semanas) - set(estado.get("whats_new", []))):
        hallazgos.append(f"WHAT'S NEW: {s}")

    # 3. Páginas de docs nuevas / eliminadas
    paginas = sorted(set(re.findall(r"\((https://code\.claude\.com/docs/en/[^)]+\.md)\)", get(f"{DOCS}/llms.txt"))))
    nuevo["paginas"] = paginas
    if estado.get("paginas"):
        for p in sorted(set(paginas) - set(estado["paginas"])):
            hallazgos.append(f"DOCS página nueva: {p}")
        for p in sorted(set(estado["paginas"]) - set(paginas)):
            hallazgos.append(f"DOCS página eliminada: {p}")

    # 4. Blogs
    for nombre, (url, patron, base) in BLOGS.items():
        try:
            posts = sorted({base + p for p in re.findall(patron, get(url))})
        except OSError as e:  # un blog caído no debe ocultar el resto, pero se reporta
            hallazgos.append(f"AVISO: no pude leer {url}: {e}")
            continue
        nuevo[nombre] = posts
        if nombre in estado:
            for p in sorted(set(posts) - set(estado[nombre])):
                hallazgos.append(f"BLOG ({nombre}): {p}")

    print(f"Última revisión: {ultima or 'nunca'} · versión vista: {vistas or '-'} · versión actual: {versiones[0]}")
    print("\n".join(hallazgos) if hallazgos else "Sin novedades.")
    if "--marcar" in args:
        nuevo["ultima_revision"] = date.today().isoformat()
        ESTADO.write_text(json.dumps({**estado, **nuevo}, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"Estado guardado en {ESTADO}")


if __name__ == "__main__":
    main()
