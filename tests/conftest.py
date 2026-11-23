"""Shared fixtures: the example log, read by Ocelescope, and an independent oracle.

The oracle reads the log's XML with ElementTree, without Ocelescope or the
plugin, so the tests check the whole path: Ocelescope import -> SQL -> analysis.
"""

from __future__ import annotations

import warnings
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_LOG = ROOT / "examples" / "Object-Centric-Example.xmlocel"


@dataclass
class Oracle:
    """Expected values, computed from the original XML."""

    pairs: list[dict] = field(default_factory=list)  # one per (event, measure)
    parameters: int = 0
    measure_objects: dict = field(default_factory=dict)  # (event, measure) -> {object id: type}


def _attributes(element: ET.Element) -> dict[str, str]:
    return {a.get("name"): (a.text or "") for a in element.iterfind("attributes/attribute")}


def _relations(element: ET.Element) -> list[tuple[str, str]]:
    return [(r.get("object-id"), r.get("qualifier")) for r in element.iterfind("objects/relationship")]


def build_oracle(path: Path) -> Oracle:
    root = ET.parse(path).getroot()
    objects = {o.get("id"): o for o in root.iterfind("objects/object")}
    types = {oid: o.get("type") for oid, o in objects.items()}
    oracle = Oracle()
    oracle.parameters = sum(
        1
        for o in objects.values()
        if o.get("type") == "sust.Measure"
        for target, _ in _relations(o)
        if types.get(target) == "sust.Parameter"
    )
    for event in root.iterfind("events/event"):
        event_relations = _relations(event)
        for measure_id, _ in event_relations:
            if types.get(measure_id) != "sust.Measure":
                continue
            measure = objects[measure_id]
            attributes = _attributes(measure)
            category = next(
                _attributes(objects[t])["label"]
                for t, _ in _relations(measure)
                if types.get(t) == "sust.Category"
            )
            oracle.pairs.append(
                {
                    "event_id": event.get("id"),
                    "activity": event.get("type"),
                    "time": datetime.fromisoformat(event.get("time").replace("Z", "+00:00")),
                    "measure_id": measure_id,
                    "measure": attributes["label"],
                    "unit": attributes["unit"],
                    "value": float(attributes["value"]),
                    "indicator": f"{category} ({attributes['unit']})",
                }
            )
            targets = {
                t: types[t]
                for t, _ in [*event_relations, *_relations(measure)]
                if t in types and not types[t].startswith("sust.")
            }
            oracle.measure_objects[(event.get("id"), measure_id)] = targets
    return oracle


@pytest.fixture(scope="session")
def oracle() -> Oracle:
    return build_oracle(EXAMPLE_LOG)


@pytest.fixture(scope="session")
def ocel():
    from ocelescope import OCEL

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return OCEL.read(EXAMPLE_LOG)


def expected_totals(pairs, key) -> dict:
    totals = defaultdict(float)
    for pair in pairs:
        totals[key(pair)] += pair["value"]
    return dict(totals)
