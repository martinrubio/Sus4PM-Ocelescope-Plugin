"""The plugin as Ocelescope sees it: methods, inputs, providers and resources."""

import json

import pytest

from sus4pm_plugin import Sus4PMPlugin
from sus4pm_plugin.ocdfg import NO_IMPACT_COLOR, SustainabilityGraph, impact_color
from sus4pm_plugin.plugin import DetailInput, EvolutionInput, IndicatorInput, OCDFGInput, ObjectInput
from sus4pm_plugin.resources import SustainabilityChart, SustainabilityTable

from .conftest import expected_totals


@pytest.fixture(scope="module")
def plugin():
    return Sus4PMPlugin()


def _check_resources(result):
    resources = result if isinstance(result, tuple) else (result,)
    for resource in resources:
        assert isinstance(resource, SustainabilityTable | SustainabilityChart | SustainabilityGraph)
        dumped = json.loads(resource.model_dump_json())
        assert type(resource).from_data(dumped) == resource, "resources must round-trip through JSON"
        visualization = resource.visualize()
        json.loads(visualization.model_dump_json())
        if isinstance(resource, SustainabilityTable):
            assert resource.rows, f"{resource.title} is empty"
            ids = {column.id for column in resource.columns}
            assert all(set(row) == ids for row in resource.rows)
    return resources


def test_methods_are_registered():
    methods = Sus4PMPlugin.method_map()
    assert set(methods) == {
        "overview", "impact_by_activity", "impact_by_object", "evolution",
        "sustainability_ocdfg", "measure_details",
    }
    assert Sus4PMPlugin.label == "Sus4PM Plugin"
    assert {r.__name__ for r in Sus4PMPlugin.get_resources()} == {
        "SustainabilityTable", "SustainabilityChart", "SustainabilityGraph",
    }
    for method in methods.values():
        assert [io.name for io in method.inputs] == ["ocel"]


def test_providers_list_the_options_of_the_log(ocel):
    indicators = IndicatorInput.indicator_options(ocel=ocel)
    assert indicators == ["Emissions (kgCO2e)", "Energy (J)", "Material (paper kg)", "Software (J)"]
    assert ObjectInput.object_type_options(ocel=ocel)[0] == "Ambulance"
    assert DetailInput.indicator_options(ocel=ocel) == indicators
    assert IndicatorInput.indicator_options(ocel=None) == []


def test_overview(plugin, ocel):
    indicators, per_measure, _ = _check_resources(plugin.overview(ocel))
    assert len(indicators.rows) == 4


def test_impact_by_activity(plugin, ocel):
    activities, _ = _check_resources(
        plugin.impact_by_activity(ocel, IndicatorInput(indicator="Software (J)"))
    )
    assert activities.rows[0]["total"] >= activities.rows[-1]["total"]


@pytest.mark.parametrize("strategy", ["full", "split"])
def test_impact_by_object(plugin, ocel, strategy):
    objects, figure = _check_resources(
        plugin.impact_by_object(
            ocel, ObjectInput(indicator="Emissions (kgCO2e)", object_type="Ambulance", strategy=strategy, top=5)
        )
    )
    assert len(figure.figure["data"]) == 1


def test_evolution(plugin, ocel):
    _check_resources(plugin.evolution(ocel, EvolutionInput(indicator="Energy (J)", granularity="week")))


def test_measure_details_include_parameters(plugin, ocel):
    (details,) = _check_resources(plugin.measure_details(ocel, DetailInput(indicator="Emissions (kgCO2e)")))
    assert all(row["parameters"] for row in details.rows)
    assert any("kilometers" in row["parameters"] for row in details.rows)


def test_unknown_indicator_is_reported(plugin, ocel):
    with pytest.raises(ValueError, match="Nope"):
        plugin.impact_by_activity(ocel, IndicatorInput(indicator="Nope"))


def test_sustainability_ocdfg(plugin, ocel, oracle):
    graph, activities = _check_resources(
        plugin.sustainability_ocdfg(ocel, OCDFGInput(indicator="Software (J)"))
    )
    expected = expected_totals(
        [p for p in oracle.pairs if p["indicator"] == "Software (J)"], lambda p: p["activity"]
    )
    impacts = {a.name: a for a in graph.activities}
    assert {name for name, a in impacts.items() if a.measures} == set(expected)
    for name, total in expected.items():
        assert impacts[name].total == pytest.approx(total)
        assert sum(m.total for m in impacts[name].measures) == pytest.approx(total)

    visualization = graph.visualize()
    nodes = {node.id: node for node in visualization.nodes}
    edge_types = {edge.object_type for edge in graph.edges}
    assert not any(t.startswith("sust.") for t in edge_types), "measures are not cases of the flow"
    for edge in visualization.edges:
        assert edge.source in nodes and edge.target in nodes
    top = max(expected, key=expected.get)
    assert nodes[top].color == impact_color(1, 1)
    for name, impact in impacts.items():
        assert (nodes[name].color == NO_IMPACT_COLOR) == (not impact.measures)
        assert (nodes[name].annotation is not None) == bool(impact.measures)
    assert activities.rows[0]["name"] == top


def test_sustainability_ocdfg_object_types_and_frequency(plugin, ocel):
    full, _ = plugin.sustainability_ocdfg(ocel, OCDFGInput(indicator="Emissions (kgCO2e)"))
    reduced, _ = plugin.sustainability_ocdfg(
        ocel,
        OCDFGInput(
            indicator="Emissions (kgCO2e)", metric="per_execution",
            object_types=["Ambulance", "Patient"], frequency=0.5,
        ),
    )
    assert {e.object_type for e in reduced.edges} == {"Ambulance", "Patient"}
    assert len(reduced.edges) < len(full.edges)
    assert reduced.metric == "per_execution"
    _check_resources((reduced,))
    with pytest.raises(ValueError, match="sust.Measure"):
        plugin.sustainability_ocdfg(ocel, OCDFGInput(indicator="Emissions (kgCO2e)", object_types=["sust.Measure"]))


def test_impact_color_scale():
    assert impact_color(0, 10) == NO_IMPACT_COLOR
    assert impact_color(5, 0) == NO_IMPACT_COLOR
    assert impact_color(10, 10) == impact_color(20, 10) == "#EF3B2C"
    assert impact_color(1e-9, 10).startswith("#FF")
