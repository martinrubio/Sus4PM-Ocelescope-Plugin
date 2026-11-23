# Sus4PM Plugin for Ocelescope

[Ocelescope](https://www.ocelescope.org) plugin that analyses the sustainability measures of an
OCEL 2.0 log following the Sus4PM metamodel. It works with any process: the business object types,
activities, categories and measures are read from the log. What the log must contain is described
in [Log requirements](#log-requirements).

Developed and tested against **Ocelescope v1.2.5** (library `ocelescope` 0.13.0).

The plugin is part of [Sus4PM](https://gitlab.fing.edu.uy/open-coal/sus4pm-sustainabilitypm), a
sustainability-aware process mining environment that records sustainability measures while a
process runs, materialises them in XES and OCEL 2.0 logs, and analyses them.

## Quick start

1. Download the plugin, [`dist/Sus4PMPlugin.zip`](dist/Sus4PMPlugin.zip), and an example log from
   [`examples/`](examples/), for instance
   [`Object-Centric-Example.xmlocel`](examples/Object-Centric-Example.xmlocel).
2. Open Ocelescope v1.2.5. To run it locally, clone this repository and start it with Docker:

   ```sh
   docker compose up -d        # -> http://localhost:3001
   ```

3. In Ocelescope, upload the zip on the plugins page and the log on the logs page, then open
   **Sus4PM Plugin** from the plugins page.

Ocelescope silently ignores a plugin whose name and version are already installed: to install a
newer zip, delete the installed plugin first.

## Methods

| Method | Input | Output |
|---|---|---|
| Sustainability overview | log | Indicator totals, totals per measure and measurement type, chart per indicator |
| Impact by activity | indicator | Total, share, executions and impact per execution of each activity; stacked chart by measure |
| Impact by object | indicator, object type, attribution, objects in chart | Impact attributed to each business object of the selected type |
| Evolution over time | indicator, day/week/month | Impact per period and measure, line chart |
| Sustainability OC-DFG | indicator, colour by total/per execution, object types, edges to keep | Object-centric directly-follows graph with each activity coloured by its impact; selecting an activity shows its impact by measure. Table of the activities |
| Measure details | indicator (optional) | Every measure with its event, value and the parameters it was computed from |

An *indicator* is a category together with a unit, shown as `Category (unit)`: values are only
added within one unit.

## Log requirements

The plugin relies only on the Sus4PM metamodel, never on the business object types or activities of
a particular process.

| Element | Requirement |
|---|---|
| `sust.Measure` objects | Attributes `value` (numeric), `unit`, `measurement_type` and `label` |
| `sust.Category` objects | Attribute `label` |
| `sust.Parameter` objects | Attributes `label`, `value` and `unit` |
| Event → measure | E2O relation from the event that registered the measure to the `sust.Measure` |
| Measure → category | O2O relation from the measure to one `sust.Category`; the qualifier `belongs-to-category` is preferred when there are several |
| Measure → parameters | O2O relations from the measure to its `sust.Parameter` objects, with any qualifier |
| Measure → business objects (optional) | O2O relations from the measure to business objects, with any qualifier |

Every object type that does not start with `sust.` is a business object type. A measure without a
category is reported as `Uncategorized`, and a measure without a numeric `value` is listed in
*Measure details* but not added to any total.

The metamodel calls the attribute that names a measure, category or parameter `name`, but
Ocelescope 0.13.0 loses the value of any object attribute called `name`, `id` or `time`, and of any
event attribute called `id`, `time` or `ocel_type`, when it imports a log (the columns collide in an
internal `PIVOT`). Logs for Ocelescope therefore use `label`, `identifier`, `time_value` and
`event_type` instead, as the logs in [`examples/`](examples/) do. The plugin still reads `name` when
there is no `label`, so it will also work with the metamodel names once Ocelescope fixes the import.

## How the values are computed

The calculations follow the same rules as the [Sus4PM](https://gitlab.fing.edu.uy/open-coal/sus4pm-sustainabilitypm) platform:

- A measure counts once for each event related to it by E2O. Measures are read from the events, so
  the methods respect Ocelescope filters: a filtered-out event takes its measures with it.
- The category and the parameters of a measure are its O2O neighbours.
- **Attribution to objects.** A measure is attributed to the business objects of its event and to
  the business objects it points to directly by O2O. With `full`, as in the platform, each object
  gets the whole value, so objects that share a measure each count it. With `split`, the value is
  divided among the measure's objects of the selected type, so the rows add up to the indicator
  total.
- **OC-DFG.** The graph is the one Ocelescope's `ocdfg_miner` discovers, restricted to the business
  object types: `sust.*` objects are not cases flowing through the process. Edges keep the colour
  of their object type and show their count. An activity's colour goes from light to dark red in
  proportion to its value against the highest one (the scale starts at 0, so small differences
  look small); activities without measures of the indicator are grey. *Per execution* divides by
  the executions that registered a measure of the indicator, as in *Impact by activity*.

## Building the plugin

The zip in `dist/` is built from `src/sus4pm_plugin` with the `ocelescope` build tool. Requires
Python 3.13:

```sh
py -3.13 -m venv .venv
.venv/Scripts/python -m pip install -e . pytest
PYTHONIOENCODING=utf-8 .venv/Scripts/ocelescope build    # -> dist/Sus4PMPlugin.zip
```

(`PYTHONIOENCODING` is only needed on Windows, where the build tool fails printing emojis. On Linux
or macOS use `.venv/bin/` instead of `.venv/Scripts/`.)

The zip contains only the plugin's modules. Plugin code may only use relative imports among its own
modules, because Ocelescope loads the zip as a package.

When the code changes, raise `version` in `src/sus4pm_plugin/plugin.py`, rebuild and commit the new
`dist/Sus4PMPlugin.zip`, so the zip in the repository matches the code.

## Development

`pyproject.toml` pins `ocelescope` 0.13.0 (the version in Ocelescope v1.2.5) and `r4pm-full` 0.6.2:
`ocelescope` 0.13.0 does not work with `r4pm-full` 0.7. Run the tests with:

```sh
.venv/Scripts/python -m pytest
```

The tests run the plugin on `examples/Object-Centric-Example.xmlocel` and compare it
against values computed directly from that log's XML, without Ocelescope.

`scripts/smoke_test_api.py` installs `dist/Sus4PMPlugin.zip` in the Ocelescope started by
`docker compose` and runs every method on the same log through the HTTP API:

```sh
.venv/Scripts/python scripts/smoke_test_api.py
```

Code layout:

| File | Content |
|---|---|
| `src/sus4pm_plugin/data.py` | SQL over the OCEL tables (measures, parameters, objects) |
| `src/sus4pm_plugin/analysis.py` | Aggregations (pandas), independent of Ocelescope |
| `src/sus4pm_plugin/charts.py` | Plotly figures |
| `src/sus4pm_plugin/resources.py` | Table and chart resources returned to Ocelescope |
| `src/sus4pm_plugin/ocdfg.py` | The OC-DFG resource: activity impacts, colour scale and graph |
| `src/sus4pm_plugin/plugin.py` | The plugin class, its methods and their inputs |

## Authors

- Martin Rubio Mata (mrubio@fing.edu.uy)
- Andrea Delgado

## License

[GNU General Public License v3.0](LICENSE).
