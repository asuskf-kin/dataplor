"""Busca cadenas regionales que todavía no están en las listas de marcas.

Uso (desde data_cleaning/):
    python .claude/skills/marcar-franquicias/scripts/descubrir_cadenas.py <csv> [--min 4]

Imprime:
  * prefijos de 1, 2 y 3 palabras de name_clean que se repiten (n = registros, c = ciudades)
  * dominios web compartidos por varios registros (sin redes sociales)
Lo que sea una MARCA (no un nombre genérico como "tacos el guero" o "abarrotes la esquina")
y se repita en varias ciudades es candidato a agregar en brands.py / brands_off.py.
"""
import sys

import polars as pl

SOCIAL = (r"facebook|instagram|google|wa\.me|whatsapp|negocio\.site|business\.site|linktr|"
          r"tiktok|wixsite|ueniweb|airbnb|abnb|booking|cloudbeds|direct-book|bit\.ly|fb\.")


def main(path, minimo):
    df = pl.read_csv(path, infer_schema_length=0,
                     columns=["name_clean", "city", "state", "channel_cat", "website"])
    print(df.shape, df["channel_cat"].value_counts().rows(),
          df["state"].value_counts().sort("count", descending=True).head(5).rows())
    t = df.with_columns(t=pl.col("name_clean").fill_null("").str.split(" "))
    for n in (1, 2, 3):
        g = (
            t.with_columns(k=pl.col("t").list.head(n).list.join(" "), l=pl.col("t").list.len())
            .filter(pl.col("l") >= n)
            .group_by("k").agg(pl.len().alias("n"), pl.col("city").n_unique().alias("c"))
            .filter(pl.col("n") >= minimo).sort("n", descending=True).head(200)
        )
        print(f"\n-- prefijos de {n} palabra(s) (texto:n:c):")
        print("; ".join(f"{a}:{b}:{c}" for a, b, c in g.iter_rows()))
    d = (
        df.with_columns(dom=pl.col("website").str.to_lowercase()
                        .str.extract(r"^(?:https?://)?(?:www\.)?([^/?#:]+)", 1))
        .filter(pl.col("dom").is_not_null() & ~pl.col("dom").str.contains(SOCIAL))
        .group_by("dom").agg(pl.len().alias("n"), pl.col("name_clean").mode().first().alias("ejemplo"))
        .filter(pl.col("n") >= 2).sort("n", descending=True)
    )
    print("\n-- dominios compartidos (dominio:n:nombre más común):")
    print("; ".join(f"{a}:{b}:{c}" for a, b, c in d.iter_rows()))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    minimo = int(sys.argv[sys.argv.index("--min") + 1]) if "--min" in sys.argv else 4
    main(args[0], minimo)
