"""On-brand Excel building blocks (skill brand-guidelines-kin): one style, shared.

Colors come from the brand tokens; fonts are named (Excel renders them where installed).
"""

from typing import Any

from openpyxl.styles import Border, Font, PatternFill, Side
from openpyxl.worksheet.worksheet import Worksheet

from cleaning_agent.adapters.brand import (
    FONT_BODY_FAMILY,
    FONT_DISPLAY_FAMILY,
    KinBrand,
)


class XlsxStyle:
    """openpyxl styles from the brand tokens (fonts render where installed)."""

    def __init__(self, brand: KinBrand) -> None:
        def rgb(token: str) -> str:
            return brand.color(token).lstrip("#")

        self.black, self.white = rgb("ka-color-black"), rgb("ka-color-white")
        self.yellow, self.gray4 = rgb("ka-color-yellow"), rgb("ka-color-gray-4")
        self.gray1, self.gray3 = rgb("ka-color-gray-1"), rgb("ka-color-gray-3")
        rule = Side(style="thin", color=rgb("ka-color-gray-2"))
        self.border = Border(bottom=rule)
        self.title = Font(
            name=FONT_DISPLAY_FAMILY, size=18, bold=True, color=self.white
        )
        self.eyebrow = Font(name=FONT_BODY_FAMILY, size=9, bold=True, color=self.yellow)
        self.section = Font(
            name=FONT_DISPLAY_FAMILY, size=13, bold=True, color=self.black
        )
        self.header = Font(name=FONT_BODY_FAMILY, size=10, bold=True, color=self.white)
        self.body = Font(name=FONT_BODY_FAMILY, size=10, color=self.black)
        self.muted = Font(name=FONT_BODY_FAMILY, size=9, color=self.gray3)
        self.number = Font(
            name=FONT_DISPLAY_FAMILY, size=14, bold=True, color=self.black
        )
        self.band = PatternFill("solid", fgColor=self.black)
        self.head_fill = PatternFill("solid", fgColor=self.gray4)
        self.zebra = PatternFill("solid", fgColor=self.gray1)
        # Yellow only as the accent bar of a section and the key figure's cell
        self.accent = PatternFill("solid", fgColor=self.yellow)


def band(ws: Worksheet, style: XlsxStyle, eyebrow: str, title: str, width: int) -> int:
    for row in (1, 2, 3):
        for col in range(1, width + 1):
            ws.cell(row, col).fill = style.band
    ws.cell(1, 1, eyebrow.upper()).font = style.eyebrow
    ws.cell(2, 1, title).font = style.title
    ws.cell(3, 1, "kinanalytics.com").font = style.muted
    ws.row_dimensions[2].height = 30
    return 5


def section(ws: Worksheet, style: XlsxStyle, row: int, text: str) -> int:
    ws.cell(row, 1).fill = style.accent
    ws.cell(row, 2, text).font = style.section
    return row + 1


def table(
    ws: Worksheet,
    style: XlsxStyle,
    row: int,
    headers: list[str],
    rows: list[list[Any]],
    first_col: int = 2,
) -> int:
    for i, header in enumerate(headers):
        cell = ws.cell(row, first_col + i, header)
        cell.font, cell.fill = style.header, style.head_fill
    for r, values in enumerate(rows, start=1):
        for i, value in enumerate(values):
            cell = ws.cell(row + r, first_col + i, value)
            cell.font, cell.border = style.body, style.border
            if r % 2 == 0:
                cell.fill = style.zebra
    return row + len(rows) + 2
