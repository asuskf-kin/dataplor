import polars as pl

DAY_COLS = [
    "monday_hours",
    "tuesday_hours",
    "wednesday_hours",
    "thursday_hours",
    "friday_hours",
    "saturday_hours",
    "sunday_hours",
]
BAD_HOURS = {"Not available", "", "nan", "00:00-00:00"}


def parse_hours_duration(h_str):
    if h_str is None or str(h_str).strip() in BAD_HOURS:
        return None
    try:
        parts = str(h_str).strip().split("-")
        if len(parts) != 2:
            return None

        def to_float(t):
            h, m = t.strip().split(":")
            return int(h) + int(m) / 60

        o, c = to_float(parts[0]), to_float(parts[1])
        duration = (24 - o) + c if c < o else c - o
        return duration if duration > 0 else None
    except ValueError:
        return None


def opening_hour(h_str):
    if h_str is None or str(h_str).strip() in BAD_HOURS:
        return None
    try:
        parts = str(h_str).strip().split("-")
        if len(parts) != 2:
            return None
        h, m = parts[0].strip().split(":")
        return int(h) + int(m) / 60
    except ValueError:
        return None


def compute_hours_row(row_dict, night_start):
    durations = [parse_hours_duration(row_dict.get(c)) for c in DAY_COLS]
    valid_durations = [d for d in durations if d is not None]
    total_weekly = sum(valid_durations) if valid_durations else None

    opens = [opening_hour(row_dict.get(c)) for c in DAY_COLS]
    valid_opens = [o for o in opens if o is not None]

    is_night = None
    if valid_opens:
        is_night = all(o >= night_start for o in valid_opens)

    return {"_total_weekly_hours": total_weekly, "_is_night_only": is_night}


def apply_hours_filter_logic(
    df: pl.DataFrame, min_hours: int, night_start: int
) -> pl.DataFrame:
    """
    Applies the hours calculations to the DataFrame and sets 'flag_hours' and 'drop_reason'.
    """
    hours_computed = df.select(DAY_COLS).to_dicts()
    computed_results = [compute_hours_row(row, night_start) for row in hours_computed]

    total_weekly_list = [res["_total_weekly_hours"] for res in computed_results]
    is_night_list = [res["_is_night_only"] for res in computed_results]

    df = df.with_columns(
        [
            pl.Series("_total_weekly_hours", total_weekly_list, dtype=pl.Float64),
            pl.Series("_is_night_only", is_night_list, dtype=pl.Boolean),
        ]
    )

    is_night_only = pl.col("_is_night_only") == True
    too_few_hours = pl.col("_total_weekly_hours") < min_hours
    condicion_rechazo = pl.col("_total_weekly_hours").is_not_null() & (
        is_night_only | too_few_hours
    )

    df = df.with_columns((~condicion_rechazo).alias("flag_hours"))

    dropped_by_hours = pl.col("drop_reason").is_null() & pl.col("flag_hours").not_()
    df = df.with_columns(
        pl.when(dropped_by_hours)
        .then(pl.lit("2_Hours_Filter"))
        .otherwise(pl.col("drop_reason"))
        .alias("drop_reason"),
        # Which of the two hour rules rejected it
        pl.when(dropped_by_hours & is_night_only)
        .then(pl.lit(f"night_only (opens at or after {night_start}:00)"))
        .when(dropped_by_hours)
        .then(pl.lit(f"weekly_hours < {min_hours}"))
        .otherwise(pl.col("drop_match"))
        .alias("drop_match"),
        pl.when(dropped_by_hours)
        .then(
            pl.concat_str(
                pl.lit("total_weekly_hours="),
                pl.col("_total_weekly_hours").round(1).cast(pl.String),
            )
        )
        .otherwise(None)
        .cast(pl.String)
        .alias("drop_detail"),
    )

    return df
