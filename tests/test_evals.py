"""The eval suite runs end to end, and the mock passes every scenario in it."""

import json

from conftest import TODAY

from evals import run_evals
from stockpot.llm.mock import Mock


def test_every_check_a_scenario_names_exists():
    data = json.loads(run_evals.SCENARIOS.read_text(encoding="utf-8"))
    for scenario in data["scenarios"]:
        assert scenario.get("kitchen", "empty") in data["kitchens"], scenario["id"]
        for spec in scenario["checks"]:
            assert spec["check"] in run_evals.CHECKS, (scenario["id"], spec["check"])


def test_the_mock_passes_every_scenario():
    data = json.loads(run_evals.SCENARIOS.read_text(encoding="utf-8"))
    results = run_evals.run(Mock(delay=0), data["scenarios"], data["kitchens"], TODAY)
    assert [(result["id"], result["failures"]) for result in results if result["failures"]] == []
