"""Tests for NormalizeStep in the pipeline."""
from core.pipeline import NormalizeStep, PipelineStep


def test_normalize_step_produces_and_requires_cycle():
    s = NormalizeStep(input="angle:R_KNEE_FE", name="knee_cycle",
                      mode="cycle", event="HS")
    assert s.kind == "normalize" and s.stage == "normalize"
    assert s.produces() == {"norm:knee_cycle"}
    assert s.requires() == {"angle:R_KNEE_FE", "event:HS"}


def test_normalize_step_window_requires_both_events():
    s = NormalizeStep(input="fz:filt", name="jump", mode="window",
                      start_event="ON", end_event="OFF")
    assert s.requires() == {"fz:filt", "event:ON", "event:OFF"}


def test_normalize_step_roundtrip():
    s = NormalizeStep(input="fz", name="n", mode="trial", points=51)
    d = s.to_dict()
    s2 = PipelineStep.from_dict(d)
    assert isinstance(s2, NormalizeStep)
    assert (s2.input, s2.name, s2.mode, s2.points) == ("fz", "n", "trial", 51)
