"""Module 0: keeps only nightlife businesses (bars, antros, cantinas, karaoke...).

Every record is classified with the signals found in the Dataplor columns:

- "seguro"   : bar/antro category (naics, sic, business_category, sub_category)
               confirmed by attributes, or an unmistakable activity (dancing,
               karaoke nights, bar games).
- "probable" : live music/shows, happy hour, watching sports, opens late,
               or serves alcohol and closes late (alcohol is not required), and
               is not a breakfast place.
- "horario"  : open at night on any day (e.g. 16:30-01:00), with no other signal.

The night / late-opening hours come from config.yaml (night_close_hour,
late_open_hour).

Shops, services, schools and daytime food places (liquor/beer stores, pharmacies,
supermarkets, gyms, bakeries, breakfast places...) are never nightlife unless their
category is a confirmed bar.

A bar category is never enough on its own: it must be confirmed by attributes
(alcohol, dancing/karaoke/bar games, live music, happy hour or watching sports).
Otherwise the record is dropped, whatever its hours.

A record with every activity column empty (dwell_time, popularity, sentiment,
reviews, stars, website) is dropped too: nothing shows the place is operating.

The name is only a supporting signal, never decisive on its own:
- a bar-like name (bar, cantina, cerveza...) makes a record "probable" only
  together with alcohol or evening/night hours; it never confirms a bar category.
- a shop-like name (Six, Modelorama, Depósito, Herbalife, Farmacia...) drops the
  record unless strong attributes (dancing, karaoke, bar games, live music) say
  otherwise.
Survivors carry 'nocturno_nivel' and 'nocturno_senales' so the final file explains
why each record was kept; the dropped file explains the rest with drop_match /
drop_detail.
"""

import polars as pl

from cleaning_agent.domain.cleaning.drop_audit import (
    report_drop_lines,
    strip_audit_cols,
)
from cleaning_agent.domain.cleaning.hours_filter import BAD_HOURS

# --- 1. Category (direct signal) ---------------------------------------------
NIGHTLIFE_NAICS = ["722410", "711120", "711130", "713210"]
NIGHTLIFE_SIC = ["5813"]
NIGHTLIFE_BUSINESS_CATEGORIES = [
    "bar", "night_club", "cocktail_bar", "lounge", "pub", "irish_pub",
    "karaoke_bar", "karaoke", "gay_bar", "gay_night_club", "beer_hall",
    "beer_garden", "brewpub", "wine_bar", "dance_hall", "dance_club", "disco",
    "jazz_club", "live_music_bar", "sports_bar", "adult_entertainment_club",
    "salsa_bar", "tiki_bar", "bar_and_grill", "brewery", "gastropub",
    "piano_bar", "stand_bar", "dart_bar", "girl_bar",
]  # fmt: skip
NIGHTLIFE_SUB_CATEGORIES = ["adult_entertainment", "performance_entertainment"]

# --- 2. place_attributes -------------------------------------------------------
ATTR_SURE = [
    "activity_bar_games", "activity_karaoke_nights", "activity_dancing",
    "offering_food_at_bar_available",
]  # fmt: skip
ATTR_ALCOHOL = [
    "offering_alcohol", "offering_beer", "known_for_beer", "offering_liquor",
    "offering_cocktails", "known_for_cocktails", "offering_wine", "known_for_wine",
    "feature_onsite_bar",
]  # fmt: skip
ATTR_SHOWS = ["offering_live_performances", "offering_live_music"]
ATTR_HAPPY_HOUR = ["offering_happy_hour_drinks", "offering_happy_hour_food"]
ATTR_SPORTS = ["activity_watching_sports"]
# children_friendly / family_friendly are NOT used: they are on 29% of all records
# and blocked ~2,600 places that serve alcohol
ATTR_NEGATIVE = ["offering_breakfast", "offering_popular_breakfast"]

# --- 3. Not nightlife even if open late (unless the category is a bar) ----------
# Matched against business_category: retail (incl. liquor/beer/wine stores),
# services, schools and daytime food
NOT_NIGHTLIFE_CATEGORY_REGEX = (
    r"(grocery|_store$|^store$|market|pharmacy|drugstore|gym|gas_station|school|"
    r"universit|college|butcher|bakery|pastry|cake_shop|breakfast|brunch|deli$|"
    r"delivery|internet_cafe|fruit|candy|soft_drinks|ice_cream|dessert_shop|"
    r"creperie|coffee_shop|^cafe$|espresso_bar|cafeteria|snack_bar|poke_bar)"
)

# --- 4. Name: supporting signal only (word boundaries; "club" and bare "michel"
#     left out on purpose, they catch nutrition clubs and people named Michel) ----
NIGHTLIFE_NAME_REGEX = (
    r"(?i)\b(bar|cantina|botanero|mezcaler[ií]a|antro|pulquer[ií]a|"
    r"cervecer[ií]a|cervez\w*|karaoke|disco|pub|lounge|michelad\w*|micheler[ií]a)\b"
)
# Take-away alcohol and shops often filed under 'bar' or a restaurant category
NOT_NIGHTLIFE_NAME_REGEX = (
    r"(?i)\b(six|modelorama|dep[oó]sito|vinos\s+y\s+licores|herbalife|"
    r"club\s+de\s+nutrici[oó]n|nutrici[oó]n|farmacias?|abarrotes|miscel[aá]nea|"
    r"minis[uú]per|oxxo|gasolinera|gimnasio|escuela|panader[ií]a|pasteler[ií]a|"
    r"tortiller[ií]a|carnicer[ií]a|papeler[ií]a|helader[ií]a|paleter[ií]a)\b"
)

# --- 5. Activity evidence: at least one must be filled in ----------------------
ACTIVITY_COLS = [
    "dwell_time", "popularity_score", "sentiment_score", "number_of_reviews",
    "average_stars", "website",
]  # fmt: skip

DAY_HOURS = {
    "lun": "monday_hours",
    "mar": "tuesday_hours",
    "mie": "wednesday_hours",
    "jue": "thursday_hours",
    "vie": "friday_hours",
    "sab": "saturday_hours",
    "dom": "sunday_hours",
}


def _col_or_null(df: pl.DataFrame, col: str) -> pl.Expr:
    """Column as string, or a null literal when the input does not have it."""
    if col in df.columns:
        return pl.col(col).cast(pl.String)
    return pl.lit(None, dtype=pl.String)


def _has_attr(attrs: list[str]) -> pl.Expr:
    """True when place_attributes has any of `attrs` set to true."""
    pattern = r'"(?:' + "|".join(attrs) + r')"\s*:\s*true'
    return pl.col("_attrs").str.contains(pattern).fill_null(False)


def _hour_part(df: pl.DataFrame, col: str, part: int) -> pl.Expr:
    """Opening (part=1) or closing (part=2) time as decimal hours; null if unusable.

    '00:00-00:00' and 'Not available' are discarded: they mean 24h or bad capture
    and show up equally in bars and non-bars.
    """
    raw = _col_or_null(df, col).str.strip_chars()
    m = raw.str.extract_groups(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")
    h_idx, m_idx = (1, 2) if part == 1 else (3, 4)
    value = (
        m.struct.field(str(h_idx)).cast(pl.Float64)
        + m.struct.field(str(m_idx)).cast(pl.Float64) / 60
    )
    return pl.when(raw.is_in(list(BAD_HOURS))).then(None).otherwise(value)


def _hour_features(
    df: pl.DataFrame, night_close_hour: float, late_open_hour: float
) -> pl.DataFrame:
    """Builds the hour variables: past midnight, open at night (closes after
    `night_close_hour`, any day and Fri/Sat) and opens late (every known day at
    `late_open_hour` or later)."""
    exprs = []
    for day, col in DAY_HOURS.items():
        exprs += [
            _hour_part(df, col, 1).alias(f"_open_{day}"),
            _hour_part(df, col, 2).alias(f"_close_{day}"),
        ]
    df = df.with_columns(exprs)

    def past_midnight(day):
        return (pl.col(f"_close_{day}") < pl.col(f"_open_{day}")).fill_null(False)

    def late_close(day):
        return past_midnight(day) | (
            pl.col(f"_close_{day}") > night_close_hour
        ).fill_null(False)

    opens = [pl.col(f"_open_{d}") for d in DAY_HOURS]
    return df.with_columns(
        pl.any_horizontal([past_midnight(d) for d in DAY_HOURS]).alias(
            "_cierra_despues_medianoche"
        ),
        (late_close("vie") | late_close("sab")).alias("_vie_sab_tarde"),
        pl.any_horizontal([late_close(d) for d in DAY_HOURS]).alias(
            "_abierto_de_noche"
        ),
        # Every day with known hours opens at late_open_hour or later
        (pl.min_horizontal(opens) >= late_open_hour)
        .fill_null(False)
        .alias("_abre_tarde"),
    )


def classify_nightlife(
    df: pl.DataFrame, night_close_hour: float = 21, late_open_hour: float = 16
) -> pl.DataFrame:
    """Adds '_nivel' (seguro / probable / horario / None) and '_senales' to `df`."""
    df = df.with_columns(
        _col_or_null(df, "place_attributes").alias("_attrs"),
        _col_or_null(df, "naics_code").str.replace(r"\.0$", "").alias("_naics"),
        _col_or_null(df, "sic_code").str.replace(r"\.0$", "").alias("_sic"),
        _col_or_null(df, "business_category").str.to_lowercase().alias("_bcat"),
        _col_or_null(df, "sub_category").str.to_lowercase().alias("_subcat"),
    )
    df = _hour_features(df, night_close_hour, late_open_hour)

    signals = {
        # Category
        "naics_bar": pl.col("_naics").is_in(NIGHTLIFE_NAICS),
        "sic_bar": pl.col("_sic").is_in(NIGHTLIFE_SIC),
        "categoria_bar": pl.col("_bcat").is_in(NIGHTLIFE_BUSINESS_CATEGORIES),
        "subcategoria_entretenimiento": pl.col("_subcat").is_in(
            NIGHTLIFE_SUB_CATEGORIES
        ),
        "actividad_nocturna": _has_attr(ATTR_SURE),
        # Probable
        "alcohol": _has_attr(ATTR_ALCOHOL),
        "vie_sab_tarde": pl.col("_vie_sab_tarde"),
        "musica_en_vivo": _has_attr(ATTR_SHOWS),
        "happy_hour": _has_attr(ATTR_HAPPY_HOUR),
        "deportes_en_tv": _has_attr(ATTR_SPORTS),
        "abre_tarde": pl.col("_abre_tarde"),
        "cierra_despues_medianoche": pl.col("_cierra_despues_medianoche"),
        "abierto_de_noche": pl.col("_abierto_de_noche"),
        # Against
        "desayunos": _has_attr(ATTR_NEGATIVE),
        "no_nocturno": pl.col("_bcat").str.contains(NOT_NIGHTLIFE_CATEGORY_REGEX),
        "nombre_no_nocturno": pl.col("name").str.contains(NOT_NIGHTLIFE_NAME_REGEX),
        # Nobody visits, rates or reviews it: may be closed or not exist (e.g. an
        # abandoned warehouse filed as 'bar' with every activity column empty)
        "sin_actividad": ~pl.any_horizontal(
            [
                _col_or_null(df, c)
                .str.strip_chars()
                .is_in(["", "0", "0.0"])
                .not_()
                .fill_null(False)
                for c in ACTIVITY_COLS
            ]
        ),
        # Name (supporting only)
        "nombre_bar": pl.col("name").str.contains(NIGHTLIFE_NAME_REGEX),
    }
    df = df.with_columns(
        [expr.fill_null(False).alias(f"_s_{k}") for k, expr in signals.items()]
    )
    s = lambda k: pl.col(f"_s_{k}")

    # Attributes that confirm a bar category
    confirmed = (
        s("alcohol")
        | s("actividad_nocturna")
        | s("musica_en_vivo")
        | s("happy_hour")
        | s("deportes_en_tv")
    )
    bar_category = (
        s("naics_bar")
        | s("sic_bar")
        | s("categoria_bar")
        | s("subcategoria_entretenimiento")
    )
    # Bar category but nothing backs it up: e.g. 'Club Herbalife' or a person's
    # name filed under 'bar'
    unconfirmed_bar = bar_category & ~confirmed

    # A shop-like name only loses against strong night-life attributes
    shop_name = s("nombre_no_nocturno") & ~(
        s("actividad_nocturna") | s("musica_en_vivo")
    )

    sure = (bar_category & confirmed) | s("actividad_nocturna")
    # Alcohol is not required: night-life attributes or an afternoon/evening
    # opening are enough on their own. A bar-like name helps, but only next to
    # alcohol or evening/night hours
    probable = (
        (s("alcohol") & (s("vie_sab_tarde") | s("cierra_despues_medianoche")))
        | s("musica_en_vivo")
        | s("happy_hour")
        | s("deportes_en_tv")
        | s("abre_tarde")
        | (s("nombre_bar") & (s("alcohol") | s("abierto_de_noche") | s("abre_tarde")))
    ) & ~s("desayunos")
    df = df.with_columns(
        unconfirmed_bar.alias("_bar_sin_atributos"),
        shop_name.alias("_nombre_de_tienda"),
        pl.when(s("sin_actividad") | shop_name)
        .then(None)
        .when(sure)
        .then(pl.lit("seguro"))
        .when(unconfirmed_bar)
        .then(None)
        .when(s("no_nocturno"))
        .then(None)
        .when(probable)
        .then(pl.lit("probable"))
        .when(s("abierto_de_noche"))
        .then(pl.lit("horario"))
        .otherwise(None)
        .cast(pl.String)
        .alias("_nivel"),
        pl.concat_str(
            [pl.when(s(k)).then(pl.lit(k)) for k in signals],
            separator=", ",
            ignore_nulls=True,
        ).alias("_senales"),
    )
    return df


def keep_nightlife_businesses(
    df: pl.DataFrame,
    include_probable: bool = True,
    include_night_hours: bool = True,
    night_close_hour: float = 21,
    late_open_hour: float = 16,
    items_to_track: list[str] | None = None,
) -> tuple[pl.DataFrame, list[str] | None, str | None, pl.DataFrame]:
    """Keeps nightlife businesses and drops everything else.

    Parameters
    ----------
    df : pl.DataFrame
        Raw Dataplor records.
    include_probable : bool
        Also keep "probable" places (alcohol + late hours / live music...), e.g.
        restaurants that work as bars at night.
    include_night_hours : bool
        Keep records open at night on any day even with no other signal.
    night_close_hour : float
        Closing after this hour (or past midnight) counts as night hours.
    late_open_hour : float
        Opening at this hour or later every day counts as opening late.
    items_to_track : list[str], optional
        Names to trace in the audit file.

    Returns
    -------
    tuple
        Survivors (with 'nocturno_nivel' and 'nocturno_senales'), updated tracked
        items, audit report (or None) and dropped records with drop_reason.
    """
    is_auditing = items_to_track is not None and len(items_to_track) > 0
    df = classify_nightlife(df, night_close_hour, late_open_hour)

    levels = ["seguro"]
    if include_probable:
        levels.append("probable")
    if include_night_hours:
        levels.append("horario")
    kept = pl.col("_nivel").is_in(levels).fill_null(False)

    df = df.with_columns(
        pl.when(kept)
        .then(None)
        .otherwise(pl.lit("0_Not_Nightlife"))
        .alias("drop_reason"),
        pl.when(kept)
        .then(None)
        .when(pl.col("_s_sin_actividad"))
        .then(pl.lit("sin actividad (sin reseñas, popularidad, visitas ni web)"))
        .when(pl.col("_nombre_de_tienda"))
        .then(pl.lit("nombre de tienda/depósito sin atributos nocturnos fuertes"))
        .when(pl.col("_bar_sin_atributos"))
        .then(pl.lit("categoría de bar sin atributos que lo confirmen"))
        .when(pl.col("_s_no_nocturno"))
        .then(pl.lit("no_nocturno (tienda, servicio o comida de día)"))
        .when(pl.col("_nivel").is_not_null())
        .then(pl.concat_str(pl.lit("nivel desactivado: "), pl.col("_nivel")))
        .otherwise(pl.lit("sin señales nocturnas"))
        .alias("drop_match"),
        pl.when(kept).then(None).otherwise(pl.col("_senales")).alias("drop_detail"),
        pl.col("_nivel").alias("nocturno_nivel"),
        pl.col("_senales").alias("nocturno_senales"),
    )

    helper_cols = [c for c in df.columns if c.startswith("_")]
    df_dropped = df.filter(pl.col("drop_reason").is_not_null()).drop(
        [*helper_cols, "nocturno_nivel", "nocturno_senales"]
    )
    df_survivors = strip_audit_cols(df.filter(kept), extra=helper_cols)

    if not is_auditing:
        return df_survivors, items_to_track, None, df_dropped

    # --- BUILD AUDIT REPORT & UPDATE TRACKED ITEMS ---
    report_lines = []
    dropped_items_set = set()

    for text in items_to_track:
        text_lower = text.lower()
        survived = df_survivors.filter(
            pl.col("name").str.to_lowercase().str.contains(text_lower, literal=True)
        )
        dropped = df_dropped.filter(
            pl.col("name").str.to_lowercase().str.contains(text_lower, literal=True)
        )

        if len(survived) == 0 and len(dropped) == 0:
            continue

        report_lines.append(f"\n🔍 Tracked text: '{text}'")

        if len(survived) > 0:
            report_lines.append(
                f"\n    ✅ SURVIVED: Passed this filter successfully ({len(survived)} records)."
            )

        if len(dropped) > 0:
            dropped_items_set.add(text)
            report_lines.extend(report_drop_lines(dropped))

    updated_items_to_track = [
        item for item in items_to_track if item not in dropped_items_set
    ]

    if len(report_lines) == 0:
        return df_survivors, updated_items_to_track, None, df_dropped

    final_report_text = (
        "=" * 45
        + "\n🎯 AUDIT: MODULE 0 (Nightlife Filter)\n"
        + "=" * 45
        + "".join(report_lines)
        + "\n"
    )

    return df_survivors, updated_items_to_track, final_report_text, df_dropped
