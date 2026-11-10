"""Marca cada registro como franquicia (Sí/No) y genera <archivo>_v2.csv + un TXT de marcas.

Uso (desde data_cleaning/, con el venv del proyecto):
    python .claude/skills/marcar-franquicias/scripts/marcar_franquicias.py <csv> [<csv> ...]
        -> diagnóstico: cuántos marca y qué detectó SOLO por sitio web (para revisar)
    python .claude/skills/marcar-franquicias/scripts/marcar_franquicias.py --write <csv> [...]
        -> escribe <csv>_v2.csv y franquicias_encontradas_<carpeta>_v2.txt junto al CSV

Columnas nuevas en el _v2 (al final, el resto queda idéntico):
    es_franquicia     "Sí" / "No"
    franquicia_marca  marca detectada (vacío si No)

Criterio, en orden:
    1. name_clean coincide con una marca de brands.py (On Premise) o brands_off.py (Off Premise).
       Algunas marcas exigen además una categoría (CATEGORY_REQUIRED, p. ej. "One" solo en hoteles).
    2. Si no, el dominio del sitio web es el corporativo de una marca (domains_map.py),
       salvo que el nombre caiga en el bloqueo de ese dominio (dom_block.py): la fuente pega
       dominios de cadenas a negocios genéricos homónimos.
"""
import collections
import os
import re
import sys
import unicodedata

import polars as pl

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from brands import BRANDS as BRANDS_ON, CATEGORY_REQUIRED  # noqa: E402
from brands_off import BRANDS_OFF  # noqa: E402
from domains_map import DOMAIN_BRANDS  # noqa: E402
from dom_block import DOMAIN_NAME_BLOCK  # noqa: E402

# Las On Premise van primero: si un nombre coincide con ambas listas, gana la On Premise
BRANDS = {**BRANDS_ON, **{b: p for b, p in BRANDS_OFF.items() if b not in BRANDS_ON}}
COMPILED = [(b, re.compile(p)) for b, p in BRANDS.items()]
CAT_RX = {b: re.compile(p) for b, p in CATEGORY_REQUIRED.items()}
ANY = re.compile("|".join(f"(?:{p})" for p in BRANDS.values()))  # prefiltro de una pasada
DOM_RX = re.compile(r"^(?:https?://)?(?:www\.)?([^/?#:]+)")
DOM_BLOCK_RX = {d: re.compile(p) for d, p in DOMAIN_NAME_BLOCK.items()}


def norm(s):
    """Minúsculas, sin acentos y con espacios simples (igual que name_clean)."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", s).strip()


def marca_por_nombre(nombre, categoria):
    if not nombre or not ANY.search(nombre):
        return None
    for b, rx in COMPILED:
        if rx.search(nombre) and (b not in CAT_RX or CAT_RX[b].search(categoria or "")):
            return b
    return None


def dominio(url):
    if not url:
        return None
    m = DOM_RX.match(url.strip().lower())
    return m.group(1) if m else None


def procesar(path, escribir):
    df = pl.read_csv(path, infer_schema_length=0)
    # La primera columna es el nombre comercial (en algún archivo viene renombrada, p. ej. "Barrio")
    nombres = df[df.columns[0]].to_list()
    limpios = df["name_clean"].to_list()
    cats = df["business_category"].to_list()
    webs = df["website"].to_list()

    cache, marca, fuente = {}, [], []
    for nm, nc, cat, web in zip(nombres, limpios, cats, webs):
        k = norm(nc) if nc else norm(nm)
        if (k, cat) not in cache:
            cache[(k, cat)] = marca_por_nombre(k, cat)
        b, src = cache[(k, cat)], "nombre"
        if b is None:
            d = dominio(web)
            b = DOMAIN_BRANDS.get(d)
            if b and d in DOM_BLOCK_RX and DOM_BLOCK_RX[d].search(k):
                b = None
            src = "sitio web"
        marca.append(b)
        fuente.append(src if b else None)

    clave = os.path.basename(os.path.dirname(os.path.abspath(path)))  # carpeta = embotellador
    n_si = sum(1 for b in marca if b)
    print(f"== {clave}: filas={df.height:,}  franquicia=Sí {n_si:,} ({n_si / df.height:.1%})  "
          f"por nombre={fuente.count('nombre'):,}  por sitio web={fuente.count('sitio web'):,}")

    det = collections.defaultdict(collections.Counter)
    por_fuente = collections.defaultdict(collections.Counter)
    for nm, b, f in zip(nombres, marca, fuente):
        if b:
            det[b][nm] += 1
            por_fuente[b][f] += 1

    if not escribir:
        # Lo detectado solo por sitio web es lo que más conviene revisar a ojo
        solo_web = [(b, nm) for nm, b, f in zip(nombres, marca, fuente) if f == "sitio web"]
        for b, c in collections.Counter(b for b, _ in solo_web).most_common(30):
            ej = [nm for bb, nm in solo_web if bb == b][:6]
            print(f"   [web] {b}: {c} -> {ej}")
        return

    out = df.with_columns(
        pl.Series("es_franquicia", ["Sí" if b else "No" for b in marca]),
        pl.Series("franquicia_marca", marca, dtype=pl.String),
    )
    stem, ext = os.path.splitext(path)
    out_csv = f"{stem}_v2{ext}"
    out.write_csv(out_csv, include_bom=True)
    print("   escrito:", out_csv)

    txt = os.path.join(os.path.dirname(path), f"franquicias_encontradas_{clave}_v2.txt")
    orden = sorted(det.items(), key=lambda x: -sum(x[1].values()))
    with open(txt, "w", encoding="utf-8") as fh:
        fh.write(f"FRANQUICIAS ENCONTRADAS - {clave.upper()}\n")
        fh.write(f"Archivo: {os.path.basename(out_csv)}\n")
        fh.write(f"Total registros: {df.height:,} | Franquicia = Sí: {n_si:,} ({n_si / df.height:.1%}) | "
                 f"Marcas distintas: {len(det)}\n")
        fh.write("Criterio: el nombre coincide con una marca de franquicia/cadena conocida, "
                 "o el sitio web es el dominio corporativo de la marca.\n")
        fh.write("=" * 80 + "\n\nRESUMEN POR MARCA (locales)\n")
        for b, c in orden:
            fh.write(f"  {sum(c.values()):>6,}  {b}\n")
        fh.write("\n" + "=" * 80 + "\nDETALLE: NOMBRES ENCONTRADOS POR MARCA\n\n")
        for b, c in orden:
            s = por_fuente[b]
            fh.write(f"## {b}  ({sum(c.values()):,} locales; por nombre {s['nombre']:,}, "
                     f"por sitio web {s['sitio web']:,})\n")
            for nm, n in sorted(c.items(), key=lambda x: (-x[1], x[0] or "")):
                fh.write(f"    {nm}" + (f"  (x{n})" if n > 1 else "") + "\n")
            fh.write("\n")
    print("   escrito:", txt)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    for p in args:
        procesar(p, "--write" in sys.argv)
