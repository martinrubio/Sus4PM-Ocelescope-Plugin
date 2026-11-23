import warnings

import pytest

from sus4pm_plugin import data

from .conftest import expected_totals


def test_measures_match_the_original_log(ocel, oracle):
    measures = data.measures(ocel)

    assert len(measures) == len(oracle.pairs)
    assert set(zip(measures["event_id"], measures["measure_id"], strict=True)) == {
        (p["event_id"], p["measure_id"]) for p in oracle.pairs
    }
    assert measures["value"].notna().all()
    assert not (measures["category"] == "Uncategorized").any()

    expected = expected_totals(oracle.pairs, lambda p: p["indicator"])
    actual = measures.groupby("indicator")["value"].sum().to_dict()
    assert actual.keys() == expected.keys()
    for indicator, total in expected.items():
        assert actual[indicator] == pytest.approx(total)

    expected_names = {p["measure"] for p in oracle.pairs}
    assert set(measures["measure"]) == expected_names


def test_parameters_keep_their_names(ocel, oracle):
    parameters = data.parameters(ocel)

    assert len(parameters) == oracle.parameters
    assert parameters["parameter"].notna().all()
    assert not parameters["parameter"].isin(["name", "label"]).any()
    assert "duration_seconds" in set(parameters["parameter"])


def test_measure_objects_match_the_original_log(ocel, oracle):
    objects = data.measure_objects(ocel)
    actual = {}
    for row in objects.itertuples():
        actual.setdefault((row.event_id, row.measure_id), {})[row.object_id] = row.object_type
    assert actual == {key: value for key, value in oracle.measure_objects.items() if value}


def test_business_object_types_exclude_the_extension(ocel):
    types = data.business_object_types(ocel)
    assert "Ambulance" in types
    assert not [t for t in types if t.startswith("sust.")]


def test_measures_follow_the_events_left_by_a_filter(ocel, oracle):
    from ocelescope import TimeFrameFilter

    times = sorted(p["time"] for p in oracle.pairs)
    cut = times[len(times) // 2]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        filtered = ocel.filter([TimeFrameFilter(time_range=(None, cut.isoformat()))])

    measures = data.measures(filtered)
    expected = [p for p in oracle.pairs if p["time"] <= cut]
    assert 0 < len(measures) == len(expected) < len(oracle.pairs)
    # The filter keeps every measure object alive through its O2O relations;
    # only the ones still related to an event may count.
    measure_objects = filtered.sql(
        """SELECT count(*) FROM objects WHERE "ocel:type" = 'sust.Measure'"""
    ).fetchone()[0]
    assert measure_objects > measures["measure_id"].nunique()
