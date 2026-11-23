"""Sus4PM Plugin: sustainability analysis of an object-centric event log."""

from __future__ import annotations

from typing import Annotated, Literal

import pandas as pd
from ocelescope import (
    COMPUTED_SELECTION,
    OCEL,
    SLIDER_FIELD,
    OCELAnnotation,
    Plugin,
    PluginInput,
    ResourceAnnotation,
    plugin_method,
)
from pydantic import Field

from ocelescope.discovery.algorithms.dfg_miner import ocdfg_miner

from . import analysis, charts, data, ocdfg
from .ocdfg import SustainabilityGraph
from .resources import SustainabilityChart, SustainabilityTable, chart, table

EventLog = Annotated[
    OCEL,
    OCELAnnotation(
        label="Event log",
        description="An OCEL 2.0 log with the Sus4PM sustainability extension (sust.Measure objects).",
    ),
]
Table = Annotated[SustainabilityTable, ResourceAnnotation(label="Table")]
Chart = Annotated[SustainabilityChart, ResourceAnnotation(label="Chart")]
FlowGraph = Annotated[SustainabilityGraph, ResourceAnnotation(label="OC-DFG")]


# --- inputs -----------------------------------------------------------------


class IndicatorInput(PluginInput):
    indicator: str = COMPUTED_SELECTION(
        provider="indicator_options",
        title="Indicator",
        description="Sustainability category and unit to analyse. Values are only added within one unit.",
    )

    @staticmethod
    def indicator_options(ocel: OCEL | None = None) -> list[str]:
        return data.indicators(ocel) if ocel is not None else []


class ObjectInput(IndicatorInput):
    object_type: str = COMPUTED_SELECTION(
        provider="object_type_options",
        title="Object type",
        description="Business object type to attribute the impact to.",
    )
    strategy: Literal["full", "split"] = Field(
        default="full",
        title="Attribution",
        description=(
            "full: every object related to a measure gets its whole value (as the Sus4PM "
            "platform), so objects sharing a measure each count it. split: the value is "
            "divided equally among the measure's objects of this type, so the rows add up "
            "to the indicator total."
        ),
    )
    top: int = SLIDER_FIELD(
        min=5, max=50, step=5, default=15,
        title="Objects in the chart",
        description="The chart shows the objects with the highest impact; the table lists all.",
    )

    @staticmethod
    def object_type_options(ocel: OCEL | None = None) -> list[str]:
        return data.business_object_types(ocel) if ocel is not None else []


class EvolutionInput(IndicatorInput):
    granularity: Literal["day", "week", "month"] = Field(
        default="day", title="Period", description="Length of each point of the series."
    )


class OCDFGInput(IndicatorInput):
    metric: Literal["total", "per_execution"] = Field(
        default="total",
        title="Colour by",
        description=(
            "total: impact of all the executions of the activity (where the impact accumulates). "
            "per_execution: mean impact of one execution that registered a measure (how "
            "intensive the activity is)."
        ),
    )
    object_types: list[str] = COMPUTED_SELECTION(
        provider="object_type_options",
        title="Object types",
        description="Business object types whose flows are drawn. Leave empty for all.",
        default=[],
    )
    frequency: float = SLIDER_FIELD(
        min=0, max=1, step=0.05, default=1.0,
        title="Edges to keep",
        description=(
            "Share of the most frequent edges kept per object type (1 keeps them all). "
            "Edges needed to keep the graph connected are kept as well."
        ),
    )

    @staticmethod
    def object_type_options(ocel: OCEL | None = None) -> list[str]:
        return data.business_object_types(ocel) if ocel is not None else []


class DetailInput(PluginInput):
    indicator: str | None = COMPUTED_SELECTION(
        provider="indicator_options",
        title="Indicator",
        description="Only measures of this indicator. Leave empty for all.",
        default=None,
    )

    @staticmethod
    def indicator_options(ocel: OCEL | None = None) -> list[str]:
        return data.indicators(ocel) if ocel is not None else []


# --- helpers ----------------------------------------------------------------


def _measures(ocel: OCEL) -> pd.DataFrame:
    measures = data.measures(ocel)
    if measures.empty:
        raise ValueError(
            "The log has no sust.Measure related to an event. It needs the Sus4PM "
            "sustainability extension (see the plugin README)."
        )
    return measures


def _indicator(measures: pd.DataFrame, indicator: str) -> tuple[pd.DataFrame, str]:
    selected = analysis.select_indicator(measures, indicator)
    if selected.empty:
        raise ValueError(f"No measure with a numeric value for the indicator {indicator!r}.")
    return selected, str(selected["unit"].iloc[0])


# --- plugin -----------------------------------------------------------------


class Sus4PMPlugin(Plugin):
    label = "Sus4PM Plugin"
    description = (
        "Sustainability analysis of object-centric event logs that follow the Sus4PM "
        "metamodel: impact by indicator, measure, activity, business object and time."
    )
    version = "0.2.0"

    @plugin_method(
        label="Sustainability overview",
        description="Totals per indicator, and per measure and measurement type.",
    )
    def overview(self, ocel: EventLog) -> tuple[Table, Table, Chart]:
        measures = _measures(ocel)
        totals = analysis.indicator_totals(measures)
        per_measure = analysis.overview(measures)
        return (
            table(
                "Indicators",
                totals,
                [
                    ("category", "Category", "string"),
                    ("unit", "Unit", "string"),
                    ("total", "Total", "number"),
                    ("observations", "Measures", "number"),
                    ("events", "Events", "number"),
                ],
            ),
            table(
                "Measures",
                per_measure,
                [
                    ("category", "Category", "string"),
                    ("unit", "Unit", "string"),
                    ("measure", "Measure", "string"),
                    ("measurement_type", "Measurement type", "string"),
                    ("total", "Total", "number"),
                    ("share", "Share of indicator (%)", "number"),
                    ("observations", "Measures", "number"),
                    ("events", "Events", "number"),
                    ("mean", "Mean per measure", "number"),
                ],
            ),
            chart("Impact by measure", charts.overview_chart(per_measure)),
        )

    @plugin_method(
        label="Impact by activity",
        description="Which activities produce the impact of an indicator, and how much per execution.",
    )
    def impact_by_activity(self, ocel: EventLog, input: IndicatorInput) -> tuple[Table, Chart]:
        measures = _measures(ocel)
        _, unit = _indicator(measures, input.indicator)
        activities = analysis.by_activity(measures, input.indicator)
        stacked = analysis.by_activity_and_measure(measures, input.indicator)
        order = activities.sort_values("total")["activity"].tolist()
        return (
            table(
                f"Impact by activity: {input.indicator}",
                activities,
                [
                    ("activity", "Activity", "string"),
                    ("total", f"Total ({unit})", "number"),
                    ("share", "Share (%)", "number"),
                    ("executions", "Executions", "number"),
                    ("per_execution", f"Per execution ({unit})", "number"),
                    ("observations", "Measures", "number"),
                    ("measures", "Measure types", "string"),
                ],
            ),
            chart(
                f"Impact by activity: {input.indicator}",
                charts.stacked_bars(
                    stacked, "activity", "measure", unit,
                    f"{input.indicator} by activity", order=order,
                ),
            ),
        )

    @plugin_method(
        label="Impact by object",
        description=(
            "Impact attributed to the business objects of a type, related to each measure "
            "through its event or directly."
        ),
    )
    def impact_by_object(self, ocel: EventLog, input: ObjectInput) -> tuple[Table, Chart]:
        measures = _measures(ocel)
        _, unit = _indicator(measures, input.indicator)
        attributed = analysis.by_object(
            measures, data.measure_objects(ocel), input.indicator, input.object_type, input.strategy
        )
        if attributed.empty:
            raise ValueError(f"No {input.object_type} is related to measures of {input.indicator}.")

        top = attributed[attributed["object_label"] != analysis.NO_OBJECT].head(input.top)
        order = top.sort_values("total")["object_label"].tolist()
        bars = top.assign(series=input.object_type)[["object_label", "series", "total"]]
        title = f"{input.indicator} by {input.object_type} ({input.strategy} attribution)"
        return (
            table(
                title,
                attributed,
                [
                    ("object_label", input.object_type, "string"),
                    ("object_id", "Object id", "string"),
                    ("total", f"Total ({unit})", "number"),
                    ("share", "Share of indicator (%)", "number"),
                    ("measures", "Measures", "number"),
                    ("events", "Events", "number"),
                ],
            ),
            chart(title, charts.stacked_bars(bars, "object_label", "series", unit, title, order=order)),
        )

    @plugin_method(
        label="Evolution over time",
        description="Impact of an indicator per day, week or month, one line per measure.",
    )
    def evolution(self, ocel: EventLog, input: EvolutionInput) -> tuple[Table, Chart]:
        measures = _measures(ocel)
        _, unit = _indicator(measures, input.indicator)
        series = analysis.evolution(measures, input.indicator, input.granularity)
        title = f"{input.indicator} per {input.granularity}"
        return (
            table(
                title,
                series,
                [
                    ("period", "Period start", "date"),
                    ("measure", "Measure", "string"),
                    ("total", f"Total ({unit})", "number"),
                    ("observations", "Measures", "number"),
                ],
            ),
            chart(title, charts.evolution_chart(series, unit, title)),
        )

    @plugin_method(
        label="Sustainability OC-DFG",
        description=(
            "Object-centric directly-follows graph of the business objects, with every "
            "activity coloured by its impact on an indicator. Select an activity to see its "
            "impact by measure."
        ),
    )
    def sustainability_ocdfg(self, ocel: EventLog, input: OCDFGInput) -> tuple[FlowGraph, Table]:
        measures = _measures(ocel)
        _, unit = _indicator(measures, input.indicator)
        business = data.business_object_types(ocel)
        unknown = sorted(set(input.object_types) - set(business))
        if unknown:
            raise ValueError(f"Not business object types of the log: {', '.join(unknown)}.")
        graph = ocdfg_miner(
            ocel,
            frequency_threshold=input.frequency,
            included_object_types=input.object_types or business,
        )
        if not graph.edges:
            raise ValueError("The selected object types have no directly-follows relation.")

        activities = analysis.by_activity(measures, input.indicator)
        impacts = ocdfg.activity_impacts(
            graph.activity_names,
            activities,
            analysis.by_activity_and_measure(measures, input.indicator),
        )
        metric = "per execution" if input.metric == "per_execution" else "total"
        title = f"OC-DFG: {input.indicator} ({metric})"
        rows = pd.DataFrame([impact.model_dump(exclude={"measures"}) for impact in impacts])
        rows["measures"] = [", ".join(m.measure for m in impact.measures) for impact in impacts]
        rows = rows.sort_values(input.metric, ascending=False)
        return (
            SustainabilityGraph(
                title=title,
                indicator=input.indicator,
                unit=unit,
                metric=input.metric,
                activities=impacts,
                edges=[ocdfg.FlowEdge(**edge.model_dump(exclude={"annotation"})) for edge in graph.edges],
            ),
            table(
                f"Activities of the OC-DFG: {input.indicator}",
                rows,
                [
                    ("name", "Activity", "string"),
                    ("total", f"Total ({unit})", "number"),
                    ("share", "Share (%)", "number"),
                    ("executions", "Executions with measures", "number"),
                    ("per_execution", f"Per execution ({unit})", "number"),
                    ("measures", "Measure types", "string"),
                ],
            ),
        )

    @plugin_method(
        label="Measure details",
        description="Every measure with its event, result and the parameters it was computed from.",
    )
    def measure_details(self, ocel: EventLog, input: DetailInput) -> Table:
        measures = _measures(ocel)
        if input.indicator:
            measures = measures[measures["indicator"] == input.indicator]
        parameters = data.parameters(ocel)
        parameters["text"] = (
            parameters["parameter"].astype(str)
            + " = "
            + parameters["value"].astype(str)
            + parameters["unit"].map(lambda unit: f" {unit}" if unit else "")
        )
        joined = measures.merge(
            parameters.groupby("measure_id")["text"].apply("; ".join).rename("parameters"),
            left_on="measure_id", right_index=True, how="left",
        )
        return table(
            "Measure details" + (f": {input.indicator}" if input.indicator else ""),
            joined,
            [
                ("timestamp", "Time", "datetime"),
                ("activity", "Activity", "string"),
                ("category", "Category", "string"),
                ("measure", "Measure", "string"),
                ("measurement_type", "Measurement type", "string"),
                ("value", "Value", "number"),
                ("unit", "Unit", "string"),
                ("parameters", "Parameters", "string"),
                ("event_id", "Event", "string"),
                ("measure_id", "Measure id", "string"),
            ],
        )
