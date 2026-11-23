"""End-to-end check of the plugin in a running Ocelescope (see docker-compose.yml).

It opens a new session, uploads the plugin zip and the prepared log, runs every
plugin method through the HTTP API, saves the results and fetches their
visualizations. Only the standard library is used.

Usage::

    docker compose up -d
    python scripts/smoke_test_api.py [--api http://127.0.0.1:8100]
        [--plugin dist/Sus4PMPlugin.zip]
        [--log examples/Object-Centric-Example.xmlocel]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSION_HEADER = "ocelescope-session-id"
PLUGIN = "/modules/plugin/v1"


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.session: str | None = None

    def request(self, method: str, path: str, body: bytes | None = None, content_type: str | None = None):
        request = urllib.request.Request(self.base + path, data=body, method=method)
        if self.session:
            request.add_header(SESSION_HEADER, self.session)
        if content_type:
            request.add_header("Content-Type", content_type)
        with urllib.request.urlopen(request, timeout=120) as response:
            self.session = response.headers.get(SESSION_HEADER, self.session)
            payload = response.read()
        return json.loads(payload) if payload else None

    def get(self, path: str):
        return self.request("GET", path)

    def post(self, path: str, data) -> object:
        return self.request("POST", path, json.dumps(data).encode(), "application/json")

    def upload(self, path: Path):
        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; "
            f"filename=\"{path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
        ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        return self.request("POST", "/session/upload", body, f"multipart/form-data; boundary={boundary}")


def wait_for(fetch, what: str, timeout: float = 120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fetch()
        if result:
            return result
        time.sleep(1)
    raise TimeoutError(f"timed out waiting for {what}")


METHODS = [
    ("overview", {}),
    ("impact_by_activity", {"indicator": "Software (J)"}),
    ("impact_by_object", {"indicator": "Emissions (kgCO2e)", "object_type": "Ambulance", "strategy": "full", "top": 15}),
    ("impact_by_object", {"indicator": "Software (J)", "object_type": "Patient", "strategy": "split", "top": 15}),
    ("evolution", {"indicator": "Energy (J)", "granularity": "day"}),
    ("sustainability_ocdfg", {"indicator": "Software (J)"}),
    ("sustainability_ocdfg", {"indicator": "Emissions (kgCO2e)", "metric": "per_execution",
                              "object_types": ["Ambulance", "Patient"], "frequency": 0.5}),
    ("measure_details", {"indicator": "Emissions (kgCO2e)"}),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", default="http://127.0.0.1:8100")
    parser.add_argument("--plugin", type=Path, default=ROOT / "dist" / "Sus4PMPlugin.zip")
    parser.add_argument("--log", type=Path, default=ROOT / "examples" / "Object-Centric-Example.xmlocel")
    args = parser.parse_args(argv)

    api = Api(args.api)
    api.get("/tasks/system")  # opens a session
    print(f"session {api.session}")

    # Ocelescope ignores a plugin whose name and version are already installed,
    # so the previous build is removed first to test the current one.
    for installed in api.get(f"{PLUGIN}/plugins"):
        if installed["name"] == "Sus4PMPlugin":
            api.request("DELETE", f"{PLUGIN}/plugin/{installed['id']}")
            print(f"removed installed {installed['name']} {installed['version']}")

    api.upload(args.plugin)
    plugin = wait_for(
        lambda: next((p for p in api.get(f"{PLUGIN}/plugins") if p["name"] == "Sus4PMPlugin"), None),
        "the plugin",
    )
    print(f"plugin {plugin['label']} {plugin['version']}: {sorted(m['name'] for m in plugin['methods'])}")

    api.upload(args.log)
    ocel = wait_for(lambda: next(iter(api.get("/modules/ocel/v1/ocels")), None), "the log", timeout=300)
    print(f"log {ocel['name']} ({ocel['id']})")

    plugin_path = f"{PLUGIN}/plugin/{plugin['id']}"
    inputs = {"ocel": ocel["id"]}
    options = api.post(
        f"{plugin_path}/impact_by_activity/computed/indicator_options",
        {"input_resources": inputs, "configuration_input": {}},
    )
    print(f"indicators {options}")
    assert options, "the indicator provider returned nothing"

    failures = 0
    for method, configuration in METHODS:
        task = api.post(f"{plugin_path}/{method}", {"input_resources": inputs, "input": configuration})
        try:
            outputs = wait_for(lambda: api.get(f"{PLUGIN}/task/{task}"), f"{method}")
            saved = api.post(
                f"{PLUGIN}/task/{task}/save",
                [{"id": output["id"], "name": output["name"]} for output in outputs],
            )
            kinds = []
            for resource_id in saved["resource_ids"]:
                visualization = api.get(f"/resources/resource/{resource_id}/visualization")
                kind = visualization["type"]
                size = len(
                    visualization.get("rows")
                    or visualization.get("nodes")
                    or visualization.get("data", {}).get("data", [])
                )
                assert size, f"{method}: empty {kind}"
                kinds.append(f"{kind}[{size}]")
            print(f"ok   {method:<20} {', '.join(kinds)}")
        except Exception as error:  # noqa: BLE001 - report every method
            failures += 1
            print(f"FAIL {method:<20} {error}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
