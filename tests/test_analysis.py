import pytest

from sus4pm_plugin import analysis, data

from .conftest import expected_totals


@pytest.fixture(scope="module")
def measures(ocel):
    return data.measures(ocel)


@pytest.fixture(scope="module")
def objects(ocel):
    return data.measure_objects(ocel)


def test_overview_shares_add_up_per_indicator(measures):
    overview = analysis.overview(measures)
    shares = overview.groupby(["category", "unit"])["share"].sum()
    assert shares.tolist() == pytest.approx([100] * len(shares), abs=0.05)
    assert overview["total"].sum() == pytest.approx(measures["value"].sum())


@pytest.mark.parametrize("indicator", ["Emissions (kgCO2e)", "Software (J)"])
def test_by_activity_matches_the_original_log(measures, oracle, indicator):
    activities = analysis.by_activity(measures, indicator)
    pairs = [p for p in oracle.pairs if p["indicator"] == indicator]
    expected = expected_totals(pairs, lambda p: p["activity"])

    assert dict(zip(activities["activity"], activities["total"], strict=True)) == pytest.approx(expected)
    assert activities["share"].sum() == pytest.approx(100, abs=0.05)
    assert (activities["per_execution"] * activities["executions"]).tolist() == pytest.approx(
        activities["total"].tolist()
    )


def test_full_attribution_gives_each_object_the_whole_value(measures, objects, oracle):
    indicator = "Emissions (kgCO2e)"
    attributed = analysis.by_object(measures, objects, indicator, "Ambulance", "full")

    expected = {}
    for pair in oracle.pairs:
        if pair["indicator"] != indicator:
            continue
        targets = oracle.measure_objects[(pair["event_id"], pair["measure_id"])]
        for object_id, object_type in targets.items():
            if object_type == "Ambulance":
                expected[object_id] = expected.get(object_id, 0) + pair["value"]
    actual = dict(zip(attributed["object_id"], attributed["total"], strict=True))
    actual.pop("", None)
    assert actual == pytest.approx(expected)


@pytest.mark.parametrize("object_type", ["Patient", "Ambulance", "Driver"])
def test_split_attribution_adds_up_to_the_indicator(measures, objects, object_type):
    for indicator in measures["indicator"].unique():
        attributed = analysis.by_object(measures, objects, indicator, object_type, "split")
        total = analysis.select_indicator(measures, indicator)["value"].sum()
        assert attributed["total"].sum() == pytest.approx(total)


def test_patients_shared_by_a_measure_count_more_than_once_in_full_mode(measures, objects):
    full = analysis.by_object(measures, objects, "Software (J)", "Patient", "full")
    split = analysis.by_object(measures, objects, "Software (J)", "Patient", "split")
    assert full["total"].sum() > split["total"].sum()


@pytest.mark.parametrize("granularity", ["day", "week", "month"])
def test_evolution_keeps_the_total(measures, granularity):
    indicator = "Energy (J)"
    series = analysis.evolution(measures, indicator, granularity)
    assert series["total"].sum() == pytest.approx(analysis.select_indicator(measures, indicator)["value"].sum())
    periods = series["period"].drop_duplicates().sort_values()
    assert periods.is_unique
    if granularity == "day":
        assert (periods.diff().dropna().dt.days == 1).all(), "every day of the range is present"
