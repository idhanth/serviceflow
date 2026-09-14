"""The documentation may only quote numbers the committed benchmark results contain.

Every benchmark figure in README.md and docs/benchmarks.md is generated from
benchmarks/results/*.json by benchmarks/render_docs.py. These tests fail when a
number was typed in by hand, when a result was rerun without regenerating the
docs, or when a committed result does not describe a passing run.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
RESULTS = REPO / "benchmarks/results"


def _renderer():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("render_docs", REPO / "benchmarks/render_docs.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_docs_match_the_committed_benchmark_results() -> None:
    assert _renderer().main(["--check"]) == 0


def test_every_generated_section_has_a_result_behind_it() -> None:
    renderer = _renderer()
    rendered = renderer.sections()
    for path in renderer.DOCS:
        text = path.read_text()
        for name in rendered:
            if f"benchmark:{name}:start" in text:
                assert f"benchmark:{name}:end" in text, f"{path.name}: unterminated section {name}"


@pytest.mark.skipif(not (RESULTS / "tenant_isolation.json").exists(), reason="no result committed")
def test_the_committed_isolation_result_is_a_passing_run() -> None:
    result = json.loads((RESULTS / "tenant_isolation.json").read_text())
    summary = result["summary"]
    assert result["passed"] is True
    assert summary["unexpected_successes"] == 0
    assert summary["server_errors"] == 0
    assert summary["blocked"] == summary["attempted"]
    assert summary["attempted"] == sum(c["attempted"] for c in result["categories"].values())
    assert all(value == 0 for value in result["database_invariants_violations"].values())
    assert not result["controls"]["failed"]


@pytest.mark.skipif(not (RESULTS / "load_test.json").exists(), reason="no result committed")
def test_the_committed_load_result_is_internally_consistent() -> None:
    result = json.loads((RESULTS / "load_test.json").read_text())
    latency = result["results"]["latency_ms"]
    assert latency["p50"] <= latency["p95"] <= latency["p99"] <= latency["max"]
    raw = REPO / result["raw_summary"]
    assert raw.exists(), "the raw k6 summary the report was built from must be committed"
    summary = json.loads(raw.read_text())
    assert (
        round(summary["metrics"]["http_reqs"]["rate"], 1)
        == result["results"]["requests_per_second"]
    )
    assert round(summary["metrics"]["http_req_duration"]["p(95)"], 1) == latency["p95"]
