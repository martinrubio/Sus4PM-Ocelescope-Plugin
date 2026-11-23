"""Plotly figures for the plugin methods.

Conventions (shared with the dataviz guidance used across Sus4PM):

* one value axis per chart: indicators with different units go to separate
  panels, never to a second axis;
* categorical colours in a fixed order, at most eight; further series are
  folded into "Other";
* thin bars with a small gap, recessive grid, hover on every mark, a legend
  whenever there are two or more series.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Validated categorical palette (light surface), in slot order.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
OTHER = "#8c8c8c"
INK = "#3d3d3a"
MUTED = "#73726c"
GRID = "rgba(115, 114, 108, 0.18)"

# Measurement types are a closed set: each keeps its colour in every chart.
MEASUREMENT_TYPE_COLORS = {
    "INSTRUMENT_BASED": SERIES[0],
    "EMPIRICAL_ESTIMATION": SERIES[1],
    "THEORETICAL_ESTIMATION": SERIES[2],
}

MAX_SERIES = len(SERIES)


def series_colors(names: list[str]) -> dict[str, str]:
    """Colour per series name, by sorted name so a series keeps its colour."""
    ordered = sorted(set(names))
    return {name: SERIES[index] if index < MAX_SERIES else OTHER for index, name in enumerate(ordered)}


def fold_series(frame: pd.DataFrame, column: str, value: str = "total") -> pd.DataFrame:
    """Keep the largest series and fold the rest into "Other"."""
    totals = frame.groupby(column)[value].sum().sort_values(ascending=False)
    if len(totals) <= MAX_SERIES:
        return frame
    keep = set(totals.index[: MAX_SERIES - 1])
    folded = frame.copy()
    folded[column] = folded[column].where(folded[column].isin(keep), "Other")
    others = [c for c in folded.columns if c not in (column, value)]
    return folded.groupby([*others, column], as_index=False)[value].sum()


def _layout(figure: go.Figure, title: str, height: int) -> go.Figure:
    figure.update_layout(
        # Title and legend are placed in pixels from the top of the figure, above
        # the plot area, so they never run into subplot titles.
        title={
            "text": title, "font": {"size": 15, "color": INK},
            "x": 0, "xanchor": "left", "yref": "container", "y": 1, "yanchor": "top", "pad": {"t": 12},
        },
        height=height,
        margin={"l": 8, "r": 16, "t": 96, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, system-ui, sans-serif", "size": 12, "color": INK},
        legend={
            "orientation": "h", "yref": "container", "y": 1 - 44 / height, "yanchor": "top",
            "x": 0, "title": None, "entrywidth": 0, "valign": "middle",
        },
        bargap=0.35,
        hoverlabel={"bgcolor": "white", "font": {"color": INK}},
    )
    figure.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont={"color": MUTED})
    figure.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont={"color": MUTED}, automargin=True)
    return figure


def _bar_marker(color: str) -> dict:
    return {"color": color, "line": {"color": "white", "width": 2}, "cornerradius": 4}


def overview_chart(overview: pd.DataFrame) -> go.Figure:
    """One panel per indicator: the total of each measure, by measurement type."""
    frame = overview.copy()
    frame["indicator"] = frame["category"] + " (" + frame["unit"] + ")"
    indicators = sorted(frame["indicator"].unique())
    figure = make_subplots(
        rows=max(1, len(indicators)), cols=1, subplot_titles=indicators, vertical_spacing=0.12
    )
    shown: set[str] = set()
    for row, indicator in enumerate(indicators, start=1):
        panel = frame[frame["indicator"] == indicator]
        unit = panel["unit"].iloc[0]
        for measurement_type, group in panel.groupby("measurement_type"):
            color = MEASUREMENT_TYPE_COLORS.get(str(measurement_type), OTHER)
            figure.add_bar(
                x=group["total"], y=group["measure"], orientation="h",
                name=str(measurement_type).replace("_", " ").lower(),
                legendgroup=str(measurement_type),
                showlegend=measurement_type not in shown,
                marker=_bar_marker(color),
                hovertemplate=f"%{{y}}<br>%{{x:,.4~f}} {unit}<extra>%{{fullData.name}}</extra>",
                row=row, col=1,
            )
            shown.add(measurement_type)
        figure.update_xaxes(title_text=unit, title_font={"color": MUTED}, row=row, col=1)
    figure.update_layout(barmode="stack")
    return _layout(figure, "Sustainability impact by measure", 180 + 170 * len(indicators))


def stacked_bars(
    frame: pd.DataFrame,
    category: str,
    series: str,
    unit: str,
    title: str,
    order: list[str] | None = None,
) -> go.Figure:
    """Horizontal bars per ``category``, stacked by ``series``."""
    frame = fold_series(frame, series)
    colors = series_colors([s for s in frame[series].unique() if s != "Other"])
    colors["Other"] = OTHER
    order = order or frame.groupby(category)["total"].sum().sort_values().index.tolist()
    figure = go.Figure()
    for name in sorted(frame[series].unique(), key=lambda s: (s == "Other", s)):
        group = frame[frame[series] == name].set_index(category).reindex(order).reset_index()
        figure.add_bar(
            x=group["total"], y=group[category], orientation="h", name=str(name),
            marker=_bar_marker(colors[name]),
            hovertemplate=f"%{{y}}<br>%{{x:,.4~f}} {unit}<extra>%{{fullData.name}}</extra>",
        )
    figure.update_layout(barmode="stack", showlegend=frame[series].nunique() > 1)
    figure.update_xaxes(title_text=unit, title_font={"color": MUTED})
    figure.update_yaxes(categoryorder="array", categoryarray=order)
    return _layout(figure, title, 160 + 34 * len(order))


def evolution_chart(frame: pd.DataFrame, unit: str, title: str) -> go.Figure:
    """One line per measure over time."""
    frame = fold_series(frame.drop(columns=["observations"], errors="ignore"), "measure")
    colors = series_colors([s for s in frame["measure"].unique() if s != "Other"])
    colors["Other"] = OTHER
    figure = go.Figure()
    for name in sorted(frame["measure"].unique(), key=lambda s: (s == "Other", s)):
        group = frame[frame["measure"] == name].sort_values("period")
        figure.add_scatter(
            x=group["period"], y=group["total"], mode="lines+markers", name=str(name),
            line={"color": colors[name], "width": 2},
            marker={"size": 8, "color": colors[name], "line": {"color": "white", "width": 2}},
            hovertemplate=f"%{{x|%Y-%m-%d}}<br>%{{y:,.4~f}} {unit}<extra>%{{fullData.name}}</extra>",
        )
    figure.update_layout(hovermode="x unified", showlegend=frame["measure"].nunique() > 1)
    figure.update_yaxes(title_text=unit, title_font={"color": MUTED}, rangemode="tozero")
    return _layout(figure, title, 420)
