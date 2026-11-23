"""Resources returned by the plugin methods.

A resource is stored in the Ocelescope session as JSON and rendered through
``visualize``. Both are generic: the methods give them a title and the data.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from ocelescope import Plotly, Resource, TableColumn, TableViz


class SustainabilityTable(Resource):
    label = "Sus4PM table"
    description = "A table of sustainability results"

    title: str
    columns: list[TableColumn]
    rows: list[dict[str, Any]]

    def visualize(self) -> TableViz:
        return TableViz(columns=self.columns, rows=self.rows)


class SustainabilityChart(Resource):
    label = "Sus4PM chart"
    description = "A chart of sustainability results"

    title: str
    figure: dict[str, Any]

    def visualize(self) -> Plotly:
        return Plotly(go.Figure(self.figure))


def _cell(value: Any, decimals: int) -> Any:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp | datetime | date):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalar
        value = value.item()
    if isinstance(value, float):
        return None if math.isnan(value) else round(value, decimals)
    return value


def table(
    title: str,
    frame: pd.DataFrame,
    columns: list[tuple[str, str, str]],
    decimals: int = 6,
) -> SustainabilityTable:
    """Build a table from ``frame``; ``columns`` lists (id, label, data_type)."""
    ids = [column_id for column_id, _, _ in columns]
    rows = [
        {column_id: _cell(value, decimals) for column_id, value in zip(ids, record, strict=True)}
        for record in frame.reindex(columns=ids).itertuples(index=False, name=None)
    ]
    return SustainabilityTable(
        title=title,
        columns=[
            TableColumn(id=column_id, label=label, data_type=data_type)  # type: ignore[arg-type]
            for column_id, label, data_type in columns
        ],
        rows=rows,
    )


def chart(title: str, figure: go.Figure) -> SustainabilityChart:
    return SustainabilityChart(title=title, figure=json.loads(pio.to_json(figure, validate=False)))
