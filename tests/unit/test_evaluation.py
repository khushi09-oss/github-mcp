"""The benchmark must not credit the wrong callsite or hide failed trials."""

import runpy
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2] / "benchmarks/evaluate.py"


def test_relation_scoring_requires_paths_labels_and_callsite():
    score = runpy.run_path(str(MODULE))["score"]
    expected = [
        dict(
            source="main.py",
            target="helpers.py",
            caller="handle()",
            callee="normalize()",
            line=3,
        )
    ]
    view = dict(
        nodes=[
            dict(id="a", label="handle()", evidence=dict(path="main.py")),
            dict(id="b", label="normalize()", evidence=dict(path="helpers.py")),
        ],
        edges=[
            dict(
                source="a",
                target="b",
                relation="calls",
                confidence="EXTRACTED",
                evidence=dict(path="main.py", start_line=3, end_line=3),
            )
        ],
    )
    assert score(view, expected) == [True]
    view["edges"][0]["evidence"]["start_line"] = 4
    assert score(view, expected) == [False]


def test_summary_keeps_failed_runs_and_does_not_invent_model_metrics():
    summarize = runpy.run_path(str(MODULE))["summarize"]
    runs = [
        dict(arm="graph", elapsed_seconds=1, error="worker_failed"),
        dict(arm="graph", elapsed_seconds=2, bytes=200),
        dict(arm="graph", elapsed_seconds=3, labelled_relations_found=[False]),
    ]
    result = summarize(runs)
    assert result["graph"]["failures"] == 2
    assert result["graph"]["trials"] == 3
    assert result["graph"]["median_success_seconds"] == 2
