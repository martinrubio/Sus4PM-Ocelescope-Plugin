"""Aggregations of the sustainability measures, as plain pandas frames.

Every function takes the frames built by :mod:`.data` and is independent of
Ocelescope, so it can be tested on its own. Values are summed only within one
indicator (category + unit): units differ between categories.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

AttributionStrategy = Literal["full", "split"]
Granularity = Literal["day", "week", "month"]

NO_OBJECT = "(no object of this type)"

# Period frequencies; a week ends on Sunday, so it starts on Monday.
_PERIODS = {"day": "D", "week": "W-SUN", "month": "M"}


def _numeric(measures: pd.DataFrame) -> pd.DataFrame:
    return measures.dropna(subset=["value"])


def _share(part: pd.Series, total: float) -> pd.Series:
    return (part / total * 100).round(2) if total else part * 0


def select_indicator(measures: pd.DataFrame, indicator: str) -> pd.DataFrame:
    return _numeric(measures)[measures["indicator"] == indicator]


def overview(measures: pd.DataFrame) -> pd.DataFrame:
    """Totals per indicator and measure, split by measurement type."""
    numeric = _numeric(measures)
    if numeric.empty:
        return pd.DataFrame(
            columns=[
                "category", "unit", "measure", "measurement_type",
                "total", "observations", "events", "mean", "share",
            ]
        )
    grouped = (
        numeric.groupby(["category", "unit", "indicator", "measure", "measurement_type"])
        .agg(total=("value", "sum"), observations=("value", "size"),
             events=("event_id", "nunique"), mean=("value", "mean"))
        .reset_index()
    )
    indicator_totals = grouped.groupby("indicator")["total"].transform("sum")
    grouped["share"] = (grouped["total"] / indicator_totals * 100).where(indicator_totals != 0, 0).round(2)
    return (
        grouped.sort_values(["category", "unit", "total"], ascending=[True, True, False])
        .drop(columns="indicator")
        .reset_index(drop=True)
    )


def indicator_totals(measures: pd.DataFrame) -> pd.DataFrame:
    numeric = _numeric(measures)
    return (
        numeric.groupby(["indicator", "category", "unit"])
        .agg(total=("value", "sum"), observations=("value", "size"), events=("event_id", "nunique"))
        .reset_index()
        .sort_values("indicator")
        .reset_index(drop=True)
    )


def by_activity(measures: pd.DataFrame, indicator: str) -> pd.DataFrame:
    """Impact of each activity on one indicator.

    ``executions`` counts the events of the activity that registered a measure
    of the indicator; ``per_execution`` is the mean impact of one of them.
    """
    selected = select_indicator(measures, indicator)
    total = float(selected["value"].sum())
    grouped = (
        selected.groupby("activity")
        .agg(total=("value", "sum"), executions=("event_id", "nunique"),
             observations=("value", "size"))
        .reset_index()
    )
    grouped["share"] = _share(grouped["total"], total)
    grouped["per_execution"] = grouped["total"] / grouped["executions"]
    grouped["measures"] = grouped["activity"].map(
        selected.groupby("activity")["measure"].apply(lambda names: ", ".join(sorted(set(names))))
    )
    return grouped.sort_values("total", ascending=False).reset_index(drop=True)


def by_activity_and_measure(measures: pd.DataFrame, indicator: str) -> pd.DataFrame:
    """Long frame (activity, measure, total, observations) for a stacked chart."""
    selected = select_indicator(measures, indicator)
    return (
        selected.groupby(["activity", "measure"])
        .agg(total=("value", "sum"), observations=("value", "size"))
        .reset_index()
    )


def by_object(
    measures: pd.DataFrame,
    objects: pd.DataFrame,
    indicator: str,
    object_type: str,
    strategy: AttributionStrategy = "full",
) -> pd.DataFrame:
    """Impact attributed to each object of ``object_type``.

    * ``full``: every object related to a measure gets its whole value, as the
      Sus4PM platform does. A measure shared by several objects counts for each
      of them, so the rows add up to more than the indicator total.
    * ``split``: the value is divided equally among the measure's objects of
      this type, so the rows add up to the indicator total.

    Measures related to no object of the type are reported in one extra row.
    """
    selected = select_indicator(measures, indicator)[["event_id", "measure_id", "value", "measure"]]
    of_type = objects[objects["object_type"] == object_type]
    joined = selected.merge(of_type, on=["event_id", "measure_id"], how="left")

    if strategy == "split":
        sharing = joined.groupby(["event_id", "measure_id"])["object_id"].transform("count")
        joined["attributed"] = joined["value"] / sharing.where(sharing > 0, 1)
    else:
        joined["attributed"] = joined["value"]

    joined["object_label"] = joined["object_label"].fillna(NO_OBJECT)
    joined["object_id"] = joined["object_id"].fillna("")
    total = float(selected["value"].sum())
    grouped = (
        joined.groupby(["object_label", "object_id"])
        .agg(total=("attributed", "sum"), measures=("measure_id", "nunique"),
             events=("event_id", "nunique"))
        .reset_index()
    )
    grouped["share"] = _share(grouped["total"], total)
    grouped["is_unattributed"] = grouped["object_label"] == NO_OBJECT
    return (
        grouped.sort_values(["is_unattributed", "total"], ascending=[True, False])
        .drop(columns="is_unattributed")
        .reset_index(drop=True)
    )


def evolution(measures: pd.DataFrame, indicator: str, granularity: Granularity = "day") -> pd.DataFrame:
    """Total per period and measure, with every period of the range present."""
    selected = select_indicator(measures, indicator).copy()
    if selected.empty:
        return pd.DataFrame(columns=["period", "measure", "total", "observations"])
    period = _PERIODS[granularity]
    timestamps = pd.to_datetime(selected["timestamp"])
    selected["period"] = timestamps.dt.to_period(period).dt.start_time
    grouped = (
        selected.groupby(["period", "measure"])
        .agg(total=("value", "sum"), observations=("value", "size"))
        .reset_index()
    )
    periods = pd.period_range(timestamps.min(), timestamps.max(), freq=period).start_time
    full = pd.MultiIndex.from_product([periods, sorted(grouped["measure"].unique())], names=["period", "measure"])
    return (
        grouped.set_index(["period", "measure"])
        .reindex(full, fill_value=0)
        .reset_index()
        .sort_values(["period", "measure"])
        .reset_index(drop=True)
    )
