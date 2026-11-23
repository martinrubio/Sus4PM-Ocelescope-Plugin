"""Read the sustainability extension out of an Ocelescope OCEL.

The log follows the Sus4PM metamodel::

    Event --E2O--> sust.Measure --O2O belongs-to-category--> sust.Category
                               \\--O2O has-parameter---------> sust.Parameter

An OCEL in Ocelescope is a DuckDB database with the tables ``events``, ``objects``,
``e2o``, ``o2o`` and ``object_changes``; every query here runs on it through
``OCEL.sql``. The rules match the Sus4PM platform (``ocel_source.py``):

* A measure counts once for every event it is related to by E2O. Measures are
  read from the events, never from the object table: a time filter keeps a
  measure object alive through its O2O relations after its event is gone.
* The category and the parameters of a measure are its O2O neighbours.
* The business objects of a measure are those of its event (E2O) plus those the
  measure itself points to (O2O), excluding the ``sust.*`` types.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from ocelescope import OCEL

SUSTAINABILITY_PREFIX = "sust."
MEASURE_TYPE = "sust.Measure"
CATEGORY_TYPE = "sust.Category"
PARAMETER_TYPE = "sust.Parameter"

# The attribute that names a measure, category or parameter. Ocelescope 0.13.0
# loses the value of an object attribute called ``name`` when it imports a log,
# so the logs for it call the attribute ``label``; ``name`` is still read in case
# Ocelescope fixes the import.
NAME_FIELDS = ("label", "name")

MEASURE_COLUMNS = [
    "event_id",
    "activity",
    "timestamp",
    "measure_id",
    "measure",
    "measurement_type",
    "unit",
    "value",
    "category",
    "indicator",
]


def ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _change_columns(ocel: OCEL) -> set[str]:
    return {row[0] for row in ocel.sql("DESCRIBE object_changes").fetchall()}


def _attribute(columns: set[str], *fields: str) -> str:
    """Latest value of the first available attribute among ``fields``, as text.

    A value equal to the attribute's own name is ignored: that is what the
    Ocelescope import leaves in a ``name`` column instead of the value.
    """
    options = [
        f"arg_max(CAST({ident(field)} AS VARCHAR), {ident('ocel:timestamp')}) "
        f"FILTER (WHERE {ident('ocel:field')} = {literal(field)} "
        f"AND CAST({ident(field)} AS VARCHAR) <> {literal(field)})"
        for field in fields
        if field in columns
    ]
    if not options:
        return "CAST(NULL AS VARCHAR)"
    return options[0] if len(options) == 1 else f"coalesce({', '.join(options)})"


def _attributes_cte(ocel: OCEL, object_type: str, fields: dict[str, tuple[str, ...]]) -> str:
    """A CTE body with one row per object of ``object_type`` and its attributes."""
    columns = _change_columns(ocel)
    selected = ",\n".join(
        f"{_attribute(columns, *sources)} AS {ident(alias)}" for alias, sources in fields.items()
    )
    return f"""
        SELECT o.{ident("ocel:oid")} AS oid,
        {selected}
        FROM objects o
        LEFT JOIN object_changes c USING ({ident("ocel:oid")})
        WHERE o.{ident("ocel:type")} = {literal(object_type)}
        GROUP BY o.{ident("ocel:oid")}
    """


def _short_id(column: str) -> str:
    """The last ``:``-separated part of an id, as the platform labels objects."""
    return f"regexp_extract({column}, '[^:]*$')"


def measures(ocel: OCEL) -> pd.DataFrame:
    """One row per (event, measure) with the measure's result and category."""
    measure_attributes = _attributes_cte(
        ocel,
        MEASURE_TYPE,
        {
            "measure": NAME_FIELDS,
            "measurement_type": ("measurement_type",),
            "unit": ("unit",),
            "value": ("value",),
        },
    )
    category_attributes = _attributes_cte(ocel, CATEGORY_TYPE, {"category": NAME_FIELDS})
    oid, eid = ident("ocel:oid"), ident("ocel:eid")

    query = f"""
        WITH
        measure_attributes AS ({measure_attributes}),
        category_attributes AS ({category_attributes}),
        measure_events AS (
            SELECT DISTINCT r.{eid} AS event_id, r.{oid} AS measure_id
            FROM e2o r
            JOIN objects o ON o.{oid} = r.{oid}
            WHERE o.{ident("ocel:type")} = {literal(MEASURE_TYPE)}
        ),
        measure_category AS (
            -- a measure has one category; belongs-to-category is preferred
            SELECT r.{ident("ocel:oid_1")} AS measure_id,
                   arg_min(
                       coalesce(ca.category, {_short_id(f"r.{ident('ocel:oid_2')}")}),
                       r.{ident("ocel:qualifier")} <> 'belongs-to-category'
                   ) AS category
            FROM o2o r
            JOIN objects t ON t.{oid} = r.{ident("ocel:oid_2")}
            LEFT JOIN category_attributes ca ON ca.oid = r.{ident("ocel:oid_2")}
            WHERE t.{ident("ocel:type")} = {literal(CATEGORY_TYPE)}
            GROUP BY 1
        )
        SELECT
            me.event_id,
            e.{ident("ocel:activity")} AS activity,
            e.{ident("ocel:timestamp")} AS timestamp,
            me.measure_id,
            coalesce(ma.measure, {_short_id("me.measure_id")}) AS measure,
            coalesce(ma.measurement_type, '') AS measurement_type,
            coalesce(ma.unit, '') AS unit,
            TRY_CAST(ma.value AS DOUBLE) AS value,
            coalesce(mc.category, 'Uncategorized') AS category
        FROM measure_events me
        JOIN events e ON e.{eid} = me.event_id
        LEFT JOIN measure_attributes ma ON ma.oid = me.measure_id
        LEFT JOIN measure_category mc ON mc.measure_id = me.measure_id
        ORDER BY timestamp, me.event_id, me.measure_id
    """
    frame = ocel.sql(query).df()
    frame["indicator"] = indicator_name(frame["category"], frame["unit"])
    return frame.reindex(columns=MEASURE_COLUMNS)


def indicator_name(category, unit):
    """``Category (unit)``: the dashboard's grouping, since units differ by category."""
    return category.astype(str) + " (" + unit.astype(str) + ")"


def parameters(ocel: OCEL) -> pd.DataFrame:
    """One row per (measure, parameter): the values the measure was computed from."""
    parameter_attributes = _attributes_cte(
        ocel,
        PARAMETER_TYPE,
        {"parameter": NAME_FIELDS, "value": ("value",), "unit": ("unit",)},
    )
    oid = ident("ocel:oid")
    query = f"""
        WITH parameter_attributes AS ({parameter_attributes})
        SELECT r.{ident("ocel:oid_1")} AS measure_id,
               r.{ident("ocel:oid_2")} AS parameter_id,
               coalesce(pa.parameter, {_short_id(f"r.{ident('ocel:oid_2')}")}) AS parameter,
               pa.value,
               coalesce(pa.unit, '') AS unit
        FROM o2o r
        JOIN objects s ON s.{oid} = r.{ident("ocel:oid_1")}
        JOIN objects t ON t.{oid} = r.{ident("ocel:oid_2")}
        LEFT JOIN parameter_attributes pa ON pa.oid = r.{ident("ocel:oid_2")}
        WHERE s.{ident("ocel:type")} = {literal(MEASURE_TYPE)}
          AND t.{ident("ocel:type")} = {literal(PARAMETER_TYPE)}
        ORDER BY 1, 3
    """
    return ocel.sql(query).df()


def business_object_types(ocel: OCEL) -> list[str]:
    rows = ocel.sql(
        f"SELECT DISTINCT {ident('ocel:type')} FROM objects "
        f"WHERE NOT starts_with({ident('ocel:type')}, {literal(SUSTAINABILITY_PREFIX)}) ORDER BY 1"
    ).fetchall()
    return [row[0] for row in rows]


def measure_objects(ocel: OCEL) -> pd.DataFrame:
    """The business objects each (event, measure) is attributed to.

    Columns: ``event_id``, ``measure_id``, ``object_id``, ``object_type``,
    ``object_label``. An object reached both through the event and through the
    measure appears once.
    """
    oid, eid, otype = ident("ocel:oid"), ident("ocel:eid"), ident("ocel:type")
    business = f"NOT starts_with(b.{otype}, {literal(SUSTAINABILITY_PREFIX)})"
    query = f"""
        WITH measure_events AS (
            SELECT DISTINCT r.{eid} AS event_id, r.{oid} AS measure_id
            FROM e2o r
            JOIN objects o ON o.{oid} = r.{oid}
            WHERE o.{otype} = {literal(MEASURE_TYPE)}
        ),
        targets AS (
            SELECT me.event_id, me.measure_id, b.{oid} AS object_id, b.{otype} AS object_type
            FROM measure_events me
            JOIN e2o r ON r.{eid} = me.event_id
            JOIN objects b ON b.{oid} = r.{oid}
            WHERE {business}
            UNION
            SELECT me.event_id, me.measure_id, b.{oid}, b.{otype}
            FROM measure_events me
            JOIN o2o r ON r.{ident("ocel:oid_1")} = me.measure_id
            JOIN objects b ON b.{oid} = r.{ident("ocel:oid_2")}
            WHERE {business}
        )
        SELECT *, {_short_id("object_id")} AS object_label
        FROM targets
        ORDER BY event_id, measure_id, object_id
    """
    return ocel.sql(query).df()


def indicators(ocel: OCEL) -> list[str]:
    frame = measures(ocel)
    return sorted(frame["indicator"].dropna().unique().tolist())
