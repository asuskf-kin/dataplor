"""Mapa estático de la base de clientes validada, para el ``_qa.html`` (sin red).

Se dibuja con matplotlib y va embebido como PNG: el QA se abre en cualquier navegador
sin internet, sin teselas ni JavaScript, y las coordenadas de los clientes no quedan
como texto en la página (solo como píxeles). El lienzo usa la paleta de mapas
``prospection_map.MAP_PALETTE``; tipografía de marca en la leyenda.
"""

import io
from collections.abc import Sequence
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import shapely
from matplotlib.axes import Axes
from matplotlib.collections import PathCollection
from numpy.typing import NDArray

from cleaning_agent.adapters.brand import KinBrand
from cleaning_agent.adapters.prospection_map import MAP_PALETTE

PAD_DEG = 1.0  # aire alrededor de los clientes válidos
FAR_DEG = 8.0  # un descartado a más de esto del recuadro no se dibuja: se cuenta en la leyenda
SIMPLIFY_DEG = 0.01  # ~1 km: suficiente para el contorno a esta escala y mucho más liviano


@dataclass(frozen=True)
class PointLayer:
    label: str
    lat: NDArray[np.float64]
    lon: NDArray[np.float64]
    color: str
    size: float
    marker: str = "o"


def _draw_outline(ax: Axes, geom: shapely.Geometry, color: str, width: float) -> None:
    simple = shapely.simplify(geom, SIMPLIFY_DEG, preserve_topology=False)
    for ring in shapely.get_parts(shapely.boundary(simple)):
        xy = shapely.get_coordinates(ring)
        if len(xy):
            ax.plot(xy[:, 0], xy[:, 1], color=color, linewidth=width, zorder=1)


def clients_map_png(
    brand: KinBrand,
    country: shapely.Geometry,
    divisions: Sequence[shapely.Geometry],
    kept: PointLayer,
    removed: Sequence[PointLayer],
) -> bytes:
    """PNG del país con los clientes válidos y, encima, los descartados por motivo."""
    display, body = brand.matplotlib_fonts()
    lat0, lat1 = float(np.min(kept.lat)), float(np.max(kept.lat))
    lon0, lon1 = float(np.min(kept.lon)), float(np.max(kept.lon))
    box = (lon0 - PAD_DEG, lon1 + PAD_DEG, lat0 - PAD_DEG, lat1 + PAD_DEG)

    # Se amplía el recuadro para mostrar descartados cercanos (p. ej. en un país vecino);
    # los muy lejanos (océano, otro continente) solo se cuentan
    visible: list[tuple[PointLayer, NDArray[np.bool_]]] = []
    far = 0
    for layer in removed:
        near = (
            (layer.lon > box[0] - FAR_DEG) & (layer.lon < box[1] + FAR_DEG)
            & (layer.lat > box[2] - FAR_DEG) & (layer.lat < box[3] + FAR_DEG)
        )
        far += int((~near).sum())
        visible.append((layer, near))
    shown_lon = [kept.lon, *(lay.lon[m] for lay, m in visible)]
    shown_lat = [kept.lat, *(lay.lat[m] for lay, m in visible)]
    all_lon, all_lat = np.concatenate(shown_lon), np.concatenate(shown_lat)
    x0, x1 = min(box[0], float(all_lon.min()) - 0.5), max(box[1], float(all_lon.max()) + 0.5)
    y0, y1 = min(box[2], float(all_lat.min()) - 0.5), max(box[3], float(all_lat.max()) + 0.5)

    # Alto proporcional al país (Argentina es larga); grados de lon "achicados" por la latitud
    aspect = 1 / np.cos(np.radians((y0 + y1) / 2))
    width_in = 7.5
    height_in = min(14.0, max(5.0, width_in * (y1 - y0) * aspect / (x1 - x0)))
    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=130)
    fig.patch.set_facecolor(MAP_PALETTE["background"])
    ax.set_facecolor(MAP_PALETTE["background"])
    clip = shapely.box(x0 - 1, y0 - 1, x1 + 1, y1 + 1)
    for div in divisions:
        if shapely.intersects(div, clip):
            _draw_outline(ax, shapely.intersection(div, clip), MAP_PALETTE["low"], 0.4)
    _draw_outline(ax, shapely.intersection(country, clip), MAP_PALETTE["outline"], 0.9)

    ax.scatter(kept.lon, kept.lat, s=kept.size, c=kept.color, alpha=0.45, linewidths=0,
               label=f"{kept.label} ({len(kept.lat):,})", zorder=2)
    for layer, near in visible:
        if not len(layer.lat):
            continue
        ax.scatter(layer.lon[near], layer.lat[near], s=layer.size, c=layer.color,
                   marker=layer.marker, edgecolors=MAP_PALETTE["outline"], linewidths=0.5,
                   label=f"{layer.label} ({len(layer.lat):,})", zorder=3)
    if far:
        ax.scatter([], [], s=0, label=f"{far:,} descartados lejos del país (no dibujados)")

    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect(aspect)
    ax.tick_params(labelsize=7, colors=MAP_PALETTE["outline"])
    for label in (*ax.get_xticklabels(), *ax.get_yticklabels()):
        label.set_fontfamily(body)
    for spine in ax.spines.values():
        spine.set_visible(False)
    legend = ax.legend(loc="lower right", fontsize=8, frameon=True, markerscale=1.0,
                       prop={"family": body, "size": 8})
    # el punto de los válidos es diminuto en el mapa: en la leyenda se agranda para que se vea
    first = legend.legend_handles[0]
    if isinstance(first, PathCollection):
        first.set_sizes([20])
    legend.get_frame().set_facecolor("#ffffff")
    legend.get_frame().set_edgecolor(MAP_PALETTE["low"])
    ax.set_title("Clientes por ubicación", fontfamily=display, fontsize=11,
                 color=MAP_PALETTE["outline"], loc="left")
    fig.tight_layout()
    out = io.BytesIO()
    fig.savefig(out, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return out.getvalue()
