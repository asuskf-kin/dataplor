"""Small HTML pieces shared by the on-brand QA pages (bars, tables, escaping)."""

import html
from collections.abc import Sequence

QA_CSS = """
.bar{display:grid;grid-template-columns:minmax(10rem,2fr) 3fr auto;gap:.75rem;align-items:center;margin:.4rem 0}
.bar .track{background:var(--ka-color-bg-layout);border-radius:var(--ka-radius-pill);height:.75rem;overflow:hidden}
.bar .fill{display:block;height:100%;background:var(--ka-color-black)}
.bar .val{font-family:var(--ka-font-display);font-size:var(--ka-size-caption)}
.map{margin:0 0 1.25rem}.map img{display:block;width:100%;height:auto;border-radius:var(--ka-radius-box)}
.map figcaption{font-size:var(--ka-size-caption);color:var(--ka-color-text-secondary);margin-top:.5rem}
details summary{cursor:pointer;font-weight:var(--ka-weight-semibold)}
pre{white-space:pre-wrap;font-size:var(--ka-size-caption)}
.alert{border-left:4px solid var(--ka-color-black);padding:.5rem .75rem;margin:.5rem 0;background:var(--ka-color-bg-layout)}
@media (max-width:40rem){.bar{grid-template-columns:1fr}}
"""


def esc(value: object) -> str:
    return html.escape(str(value))


def bars(items: Sequence[tuple[str, int]], total: int) -> str:
    rows = []
    for label, n in items:
        pct = 100 * n / total if total else 0
        rows.append(
            f'<div class="bar"><span class="lbl">{esc(label)}</span>'
            f'<span class="track"><span class="fill" style="width:{pct:.1f}%"></span></span>'
            f'<span class="val">{n:,} · {pct:.1f}%</span></div>'
        )
    return "".join(rows)


def table(rows: Sequence[tuple[object, ...]], head: tuple[str, ...]) -> str:
    th = "".join(f"<th>{esc(h)}</th>" for h in head)
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in rows
    )
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"
