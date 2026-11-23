"""Object-centric directly-follows graph annotated with a sustainability indicator.

The graph is the OC-DFG that Ocelescope mines (``ocdfg_miner``) over the
business object types; the ``sust.*`` objects are left out, since a measure is
not a case that flows through the process. Each activity is coloured by its
impact on one indicator, and its edges keep the colour of their object type as
in the standard OC-DFG.

The resource stores plain data and builds the :class:`Graph` in ``visualize``,
so it round-trips through JSON without depending on how Ocelescope serialises
nested visualizations.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd
from ocelescope import (
    DIRECTED_ELK_GRAPH_LAYOUT,
    Graph,
    GraphEdge,
    GraphNode,
    Resource,
    TableColumn,
    TableViz,
    generate_color_map,
)
from ocelescope.visualization.default.graph import NodeStyle
from pydantic import BaseModel, Field

Metric = Literal["total", "per_execution"]

# Sequential scale from light to medium red: the label (dark text) stays legible.
LOW_COLOR = (0xFF, 0xF5, 0xF0)
HIGH_COLOR = (0xEF, 0x3B, 0x2C)
NO_IMPACT_COLOR = "#E9ECEF"
NO_IMPACT_BORDER = "#ADB5BD"


class MeasureImpact(BaseModel):
    measure: str
    total: float
    observations: int


class ActivityImpact(BaseModel):
    name: str
    total: float = 0.0
    share: float = 0.0
    executions: int = 0
    per_execution: float = 0.0
    measures: list[MeasureImpact] = Field(default_factory=list)


class FlowEdge(BaseModel):
    object_type: str
    source: str | None = None
    target: str | None = None
    count: int = 0
    object_count: int = 0


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(channel):02X}" for channel in rgb)


def impact_color(value: float, maximum: float) -> str:
    """Colour of ``value`` on the scale that ends at ``maximum``."""
    if value <= 0 or maximum <= 0:
        return NO_IMPACT_COLOR
    ratio = min(value / maximum, 1.0)
    return _hex(tuple(low + (high - low) * ratio for low, high in zip(LOW_COLOR, HIGH_COLOR, strict=True)))


def format_value(value: float) -> str:
    if value == 0:
        return "0"
    if abs(value) >= 100:
        return f"{value:,.0f}"
    if abs(value) >= 1:
        return f"{value:,.2f}"
    return f"{value:.3g}"


class SustainabilityGraph(Resource):
    label = "Sus4PM OC-DFG"
    description = "Object-centric directly-follows graph coloured by a sustainability indicator"

    title: str
    indicator: str
    unit: str
    metric: Metric
    activities: list[ActivityImpact]
    edges: list[FlowEdge]

    def _value(self, activity: ActivityImpact) -> float:
        return activity.total if self.metric == "total" else activity.per_execution

    def _label(self, activity: ActivityImpact) -> str:
        if not activity.measures:
            return f"{activity.name} · no measures"
        if self.metric == "total":
            return f"{activity.name} · {format_value(activity.total)} {self.unit} ({activity.share:g}%)"
        return f"{activity.name} · {format_value(activity.per_execution)} {self.unit}/exec."

    def _breakdown(self, activity: ActivityImpact) -> TableViz | None:
        if not activity.measures:
            return None
        return TableViz(
            columns=[
                TableColumn(id="measure", label="Measure", data_type="string"),
                TableColumn(id="total", label=f"Total ({self.unit})", data_type="number"),
                TableColumn(id="observations", label="Measures", data_type="number"),
            ],
            rows=[
                {"measure": m.measure, "total": round(m.total, 6), "observations": m.observations}
                for m in activity.measures
            ],
        )

    def visualize(self) -> Graph:
        maximum = max((self._value(a) for a in self.activities), default=0.0)
        object_types = sorted({edge.object_type for edge in self.edges})
        colors = generate_color_map(object_types, "custom")

        activity_nodes = [
            GraphNode(
                id=activity.name,
                label=self._label(activity),
                shape="rectangle",
                width=190,
                height=56,
                color=impact_color(self._value(activity), maximum),
                border_color="#000000" if activity.measures else NO_IMPACT_BORDER,
                annotation=self._breakdown(activity),
            )
            for activity in self.activities
        ]

        def endpoint(kind: Literal["start", "end"], object_type: str) -> GraphNode:
            return GraphNode(
                id=f"{kind}_{object_type}",
                label=object_type,
                shape="circle",
                color=colors[object_type],
                border_color="#000000",
                width=44,
                height=44,
                style=NodeStyle(inner_symbol="triangle" if kind == "start" else "square"),
                label_pos="bottom",
            )

        starts = sorted({e.object_type for e in self.edges if e.source is None and e.target is not None})
        ends = sorted({e.object_type for e in self.edges if e.target is None and e.source is not None})

        edges = [
            GraphEdge(
                source=edge.source if edge.source is not None else f"start_{edge.object_type}",
                target=edge.target if edge.target is not None else f"end_{edge.object_type}",
                end_arrow="triangle",
                color=colors[edge.object_type],
                label=str(edge.count),
            )
            for edge in self.edges
        ]

        return Graph(
            nodes=activity_nodes
            + [endpoint("start", t) for t in starts]
            + [endpoint("end", t) for t in ends],
            edges=edges,
            layout_config=DIRECTED_ELK_GRAPH_LAYOUT,
        )


def activity_impacts(
    activity_names: list[str], by_activity: pd.DataFrame, by_measure: pd.DataFrame
) -> list[ActivityImpact]:
    """Impact of every activity of the graph; activities without measures get zeros.

    ``by_activity`` and ``by_measure`` are the frames of
    :func:`.analysis.by_activity` and :func:`.analysis.by_activity_and_measure`.
    """
    rows = by_activity.set_index("activity")
    impacts = []
    for name in activity_names:
        measures = by_measure[by_measure["activity"] == name].sort_values("total", ascending=False)
        if name not in rows.index:
            impacts.append(ActivityImpact(name=name))
            continue
        row = rows.loc[name]
        impacts.append(
            ActivityImpact(
                name=name,
                total=float(row["total"]),
                share=float(row["share"]),
                executions=int(row["executions"]),
                per_execution=float(row["per_execution"]),
                measures=[
                    MeasureImpact(measure=str(m.measure), total=float(m.total), observations=int(m.observations))
                    for m in measures.itertuples(index=False)
                ],
            )
        )
    return impacts
