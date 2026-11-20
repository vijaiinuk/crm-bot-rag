"""S2.4.1: the gate's pure checks (no DB): recall regression and module widening."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from chatbot.evals.metrics import Summary
from chatbot.ingest.gate import (
    GateConfig,
    RegressionConfig,
    load_gate_config,
    regressions,
    widenings,
)

ROOT = Path(__file__).parents[2]
CONFIG = RegressionConfig(metrics=["complete@5", "recall@5", "mrr"], tolerance=0.02)


def summary(complete5: float, recall5: float, mrr: float) -> Summary:
    return Summary(n=207, recall={5: recall5}, complete={5: complete5}, mrr=mrr)


LIVE = summary(0.89, 0.94, 0.87)


# --- recall regression ----------------------------------------------------------------------


def test_identical_or_better_metrics_pass() -> None:
    assert regressions(LIVE, LIVE, CONFIG) == []
    assert regressions(summary(0.95, 0.99, 0.95), LIVE, CONFIG) == []


def test_a_drop_within_tolerance_passes_and_beyond_it_fails() -> None:
    assert regressions(summary(0.87, 0.94, 0.87), LIVE, CONFIG) == []  # exactly 0.02
    [r] = regressions(summary(0.86, 0.94, 0.87), LIVE, CONFIG)  # 0.03
    assert (r.metric, r.live, r.new) == ("complete@5", 0.89, 0.86)
    assert r.drop == pytest.approx(0.03)


def test_every_configured_metric_is_checked() -> None:
    found = regressions(summary(0.80, 0.90, 0.80), LIVE, CONFIG)
    assert [r.metric for r in found] == ["complete@5", "recall@5", "mrr"]


def test_only_configured_metrics_are_checked() -> None:
    mrr_only = RegressionConfig(metrics=["mrr"], tolerance=0.02)
    assert regressions(summary(0.10, 0.10, 0.87), LIVE, mrr_only) == []


def test_the_repo_gate_config_loads_and_bad_ones_are_rejected() -> None:
    config = load_gate_config(ROOT / "config" / "gate.yaml")
    assert config.regression.tolerance == 0.02
    assert "complete@5" in config.regression.metrics
    with pytest.raises(ValidationError):
        GateConfig.model_validate({"regression": {"metrics": ["vibes"], "tolerance": 0.02}})
    with pytest.raises(ValidationError):
        GateConfig.model_validate({"regression": {"metrics": ["mrr"], "tolerance": 0.9}})
    with pytest.raises(ValidationError):
        GateConfig.model_validate({"regression": {"metrics": [], "tolerance": 0.02}})


# --- module widening ------------------------------------------------------------------------


def test_dropping_a_module_widens_access_even_when_another_is_added() -> None:
    """A chunk needs ALL its modules: [deals] -> [campaigns] lets campaigns-only users in."""
    widened, added = widenings({"d": ("deals",)}, {"d": ("campaigns",)})
    assert [(w.doc_id, w.dropped) for w in widened] == [("d", ("deals",))]
    assert added == []


def test_retagging_to_core_widens_and_adding_a_module_only_narrows() -> None:
    widened, _ = widenings(
        {"a": ("deals", "reports"), "b": ("deals",), "c": ("deals",)},
        {"a": ("reports",), "b": ("deals", "reports"), "c": ("deals",)},
    )
    assert [(w.doc_id, w.live, w.new, w.dropped) for w in widened] == [
        ("a", ("deals", "reports"), ("reports",), ("deals",))
    ]


def test_new_docs_are_listed_and_removed_docs_are_not_widening() -> None:
    widened, added = widenings(
        {"old": ("deals",), "gone": ("core",)}, {"old": ("deals",), "new": ("core",)}
    )
    assert widened == [] and added == ["new"]
