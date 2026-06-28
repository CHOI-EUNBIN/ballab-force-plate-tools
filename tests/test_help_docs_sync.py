"""Regression tests that keep the COP help text in sync with the engine.

The single source of truth for which COP metrics exist is
``core.metrics.METRIC_KEYS``. The user-facing documentation lives in
``ui.help_dialog`` in two places:

* ``METRIC_TOOLTIPS`` - one-line sidebar hover text, keyed **1:1** with
  ``METRIC_KEYS`` (e.g. "RMS AP", "RMS ML", ...).
* ``METRIC_DOCS`` - the full reference dialog. To keep the dialog short, the
  AP/ML pair of a metric is folded into a single entry (``name``), so the doc
  ``name`` set is NOT 1:1 with ``METRIC_KEYS`` (e.g. "RMS AP"/"RMS ML" -> "RMS",
  "Mean power freq AP"/"... ML" -> "Mean power frequency").

These tests catch "drift": a metric added to the engine without docs, or a doc
entry left behind after a metric was renamed/removed. They are headless and
import no Qt widgets beyond the module-level constants (``help_dialog`` defines
classes but instantiates nothing at import time, so it imports fine without a
QApplication).
"""

import pytest

from core.metrics import METRIC_KEYS
from ui.help_dialog import METRIC_DOCS, METRIC_TOOLTIPS, OP_TOOLTIPS


# --- AP/ML folding ----------------------------------------------------------
# Axis suffixes used on the per-axis metric keys.
_AXES = ("AP", "ML")

# The only genuinely ambiguous fold: the bare "Mean AP"/"Mean ML" keys are mean
# *position*, but "Mean velocity" and "Mean power freq ..." also begin with
# "Mean" and have their own dedicated keys. Everything else is resolved
# automatically by token-stem matching below, so this stays a one-line table.
_BASE_ALIASES = {"Mean": "Mean position"}

# Doc entries that intentionally describe a SIGNAL/TRAJECTORY rather than a
# selectable per-window metric, so they have no METRIC_KEYS counterpart. The
# "COP" resultant curve and the ML-AP trajectory are plotted signals / spatial
# pictures (the basis the metrics summarise), documented for the reader but not
# computed as scalar metrics. They are exempt from the strict 1:1 metric mapping.
_NON_METRIC_DOCS = {
    "COP resultant distance (RD)",
    "COP trajectory (statokinesigram)",
    # Round B1 named pipeline ops (scalar OP_INFO, not COP METRIC_KEYS): they have
    # their own sync test (test_named_ops_match_engine_one_to_one); exempt here so
    # they are not flagged as orphan COP docs.
    "Peak angular velocity",
    "Peak angular acceleration",
    "Rate of force development (RFD)",
    "Loading rate",
    "Impulse",
    "Braking impulse",
    "Propulsive impulse",
    # Round B2 named ops (event / jump / symmetry-variability families). Same
    # rationale: pinned by test_named_ops_match_engine_one_to_one, exempt here.
    "Time between events",
    "Cadence",
    "Stance %",
    "Swing %",
    "Jump height (flight time)",
    "Jump height (impulse-momentum)",
    "Takeoff velocity",
    "Reactive Strength Index (RSI)",
    "Symmetry index (Robinson SI)",
    "Symmetry ratio (L/R)",
    "Coefficient of variation (CV)",
    "Product (a x b)",
    "Quotient (a / b)",
    "Sum (a + b)",
    "Double support %",
    # Spatial displacement op (gait distance family). Same rationale.
    "Displacement between events",
    # Explanatory pipeline-concept entries (time-normalize + ensemble): not COP
    # metric keys, documented for the reader. See the "Time-normalization &
    # Ensemble" category in METRIC_DOCS.
    "Time-normalization (0–100% cycle)",
    "Ensemble average (mean ± SD)",
    # Explanatory gait-event entry (Literature→Method→Results→Comparison): not a
    # COP metric key, documented for the reader. See the "Gait events on a
    # treadmill" category in METRIC_DOCS.
    "Treadmill gait-event detection (Zeni coordinate method)",
    # Signal-operation building blocks (ComputeStep methods, COMPUTE_METHODS):
    # signal->signal/scalar ops authored in the "Compute signal" Add-step dialog,
    # NOT COP metric keys and NOT named OP_INFO ops. Documented for the reader as
    # the "Signal operations (building blocks)" category in METRIC_DOCS.
    "Derivative (rate of change)",
    "Integral (accumulate over time)",
    "Magnitude (resultant of axes)",
    "Absolute value |x| (rectify)",
    "Normalize (÷ constant or ÷ metric)",
    "Extrapolated CoM (XCOM, Hof 2005)",
    # Explanatory quick-start preset entry: describes how the Walk presets seed an
    # editable pipeline. Not a metric key. See the "Quick start — task presets"
    # category in METRIC_DOCS.
    "Walk preset (seeds a full pipeline)",
}


def _tokens(s):
    """Split a metric label into comparison tokens ("95%" -> "95%")."""
    return s.replace("%", "% ").split()


def _base_of(key):
    """Drop a trailing axis suffix ("RMS AP" -> "RMS"); leave others as-is."""
    toks = _tokens(key)
    if toks and toks[-1] in _AXES:
        toks = toks[:-1]
    return " ".join(toks)


def _doc_names():
    return [m["name"] for cat in METRIC_DOCS for m in cat["metrics"]]


def test_ensemble_doc_explains_per_cycle_vs_per_subject():
    """The ensemble help entry must teach the per-cycle vs per-subject weighting
    choice and when to use each — beginner guidance the user asked for."""
    doc = next(m for cat in METRIC_DOCS for m in cat["metrics"]
               if m["name"] == "Ensemble average (mean ± SD)")
    for lang in ("en", "kr"):
        t = doc["desc"][lang].lower()
        assert "per cycle" in t and "per subject" in t, lang
    en = doc["desc"]["en"].lower()
    assert "group" in en and "single" in en          # says when to use each


def _stem_run(doc_toks, base_toks):
    """True if every base token aligns with the doc token at the same position
    by a stem-prefix relation (one is a prefix of the other, case-insensitive).

    This is what lets the abbreviated key "Mean power freq" match the spelled-out
    doc name "Mean power frequency" without a hardcoded mapping.
    """
    if len(base_toks) > len(doc_toks):
        return False
    for dt, bt in zip(doc_toks, base_toks):
        a, b = dt.lower(), bt.lower()
        if not (a.startswith(b) or b.startswith(a)):
            return False
    return True


def _docs_for_base(base):
    """All doc names that could cover a (axis-stripped) metric base.

    Among candidates whose leading tokens stem-match the base, the longest
    (most-specific) name wins, e.g. "Mean velocity" beats nothing because the
    key already carries "velocity"; an ambiguous bare base is resolved via
    ``_BASE_ALIASES``.
    """
    if base in _BASE_ALIASES:
        return [_BASE_ALIASES[base]]
    base_toks = _tokens(base)
    cands = [(len(_tokens(n)), n) for n in _doc_names() if _stem_run(_tokens(n), base_toks)]
    if not cands:
        return []
    best_len = max(length for length, _ in cands)
    return [name for length, name in cands if length == best_len]


# --- tests ------------------------------------------------------------------

def test_tooltips_match_metric_keys_one_to_one():
    """METRIC_TOOLTIPS keys must equal METRIC_KEYS exactly (no gaps, no extras)."""
    keys = set(METRIC_KEYS)
    tips = set(METRIC_TOOLTIPS)
    missing = keys - tips          # metrics with no sidebar tooltip
    extra = tips - keys            # tooltips for metrics that no longer exist
    assert not missing and not extra, (
        "METRIC_TOOLTIPS is out of sync with core.metrics.METRIC_KEYS.\n"
        f"  missing tooltips (metric has no hover text): {sorted(missing)}\n"
        f"  extra tooltips (no such metric in engine):   {sorted(extra)}"
    )


def test_metric_keys_have_no_duplicates():
    """Guards the source of truth itself: keys must be unique."""
    dupes = sorted({k for k in METRIC_KEYS if METRIC_KEYS.count(k) > 1})
    assert not dupes, f"duplicate keys in core.metrics.METRIC_KEYS: {dupes}"


def test_docs_cover_every_metric_key():
    """Every METRIC_KEYS entry must resolve to exactly one METRIC_DOCS entry,
    accounting for AP/ML folding, and no doc entry may be orphaned."""
    unresolved = {}      # key -> the candidate doc names found (0 or >1)
    covered_docs = set()
    for key in METRIC_KEYS:
        names = _docs_for_base(_base_of(key))
        if len(names) == 1:
            covered_docs.add(names[0])
        else:
            unresolved[key] = names

    orphan_docs = sorted(set(_doc_names()) - covered_docs - _NON_METRIC_DOCS)
    assert not unresolved and not orphan_docs, (
        "METRIC_DOCS is out of sync with core.metrics.METRIC_KEYS.\n"
        f"  keys not covered by exactly one doc entry: {unresolved}\n"
        f"  doc entries not referenced by any key:     {orphan_docs}"
    )


# --- Round B1 named derivative/integral ops -------------------------------
# These are scalar pipeline ops (OP_INFO/SCALAR_OPS), NOT COP METRIC_KEYS, so
# they have their own docs surface: OP_TOOLTIPS (Add-step hover) + a METRIC_DOCS
# entry each. Pin the key-sets so a new op can't ship without docs.
_B1_OPS = {
    "peak_angular_velocity", "peak_angular_acceleration",
    "rfd", "loading_rate", "impulse", "braking_impulse", "propulsive_impulse",
}

# Round B2 named ops: event-pair (spatiotemporal), jump, symmetry/variability.
# Unlike B1, several ops can share one doc entry (e.g. step+stride cadence ->
# "Cadence"; both time/frames-between-events -> "Time between events"), so the
# strict label==doc-name test below covers only the ops whose OP_INFO label IS
# the doc name. The doc-coverage check uses the op->doc map.
_B2_OPS = {
    "time_between_events", "frames_between_events", "jump_height_flight_time",
    "jump_height_impulse", "takeoff_velocity",
    "cadence", "cadence_stride", "stance_pct", "swing_pct", "rsi",
    "symmetry_index", "symmetry_ratio", "cv",
    "product", "quotient", "add", "double_support_pct",
    # Spatial displacement ops (gait distance family).
    "displacement_between_events",
}

_NAMED_OPS = _B1_OPS | _B2_OPS

# Op key -> the METRIC_DOCS "name" that documents it. For B1 the OP_INFO label
# equals the doc name (bridged by test_named_op_labels_match_doc_names); for B2
# several ops fold into one doc entry, so the label may differ from the doc name.
_OP_DOC_NAME = {
    "peak_angular_velocity": "Peak angular velocity",
    "peak_angular_acceleration": "Peak angular acceleration",
    "rfd": "Rate of force development (RFD)",
    "loading_rate": "Loading rate",
    "impulse": "Impulse",
    "braking_impulse": "Braking impulse",
    "propulsive_impulse": "Propulsive impulse",
    # Round B2
    "time_between_events": "Time between events",
    "frames_between_events": "Time between events",
    "jump_height_flight_time": "Jump height (flight time)",
    "jump_height_impulse": "Jump height (impulse-momentum)",
    "takeoff_velocity": "Takeoff velocity",
    "cadence": "Cadence",
    "cadence_stride": "Cadence",
    "stance_pct": "Stance %",
    "swing_pct": "Swing %",
    "rsi": "Reactive Strength Index (RSI)",
    "symmetry_index": "Symmetry index (Robinson SI)",
    "symmetry_ratio": "Symmetry ratio (L/R)",
    "cv": "Coefficient of variation (CV)",
    "product": "Product (a x b)",
    "quotient": "Quotient (a / b)",
    "add": "Sum (a + b)",
    "double_support_pct": "Double support %",
    # Spatial displacement ops (gait distance family).
    "displacement_between_events": "Displacement between events",
}


def _engine_named_ops():
    """The set of *named clinical* ops in ``OP_INFO`` that MUST be documented.

    Derived from the engine (not a hardcoded list) so a NEW named op added to
    ``core.metrics`` automatically joins the drift check below. A named op is
    one the Add-step popup shows with clinical naming + a tooltip + a reference
    doc entry — i.e. everything EXCEPT the generic primitives:

      * generic scalar reduces (min/max/mean/range/std/rms/integral/sum): no
        ``signal_kind`` (only the named scalar ops carry that hint);
      * COP composites (category ``cop``): documented on the COP surface
        (METRIC_DOCS COP entries / METRIC_TOOLTIPS), tested above;
      * ``value_at_event`` (a generic windowing op, category reference / input
        ``sample``).

    So a named op is: category ``event`` or ``jump``; a ``reference`` op whose
    input is a ``metric`` (cadence/symmetry/CV/...); a ``scalar`` op that
    carries a ``signal_kind`` hint (the B1 clinical derivatives/integrals); or
    a ``displacement`` op (spatial gait distance family).
    """
    from core.metrics import OP_INFO
    named = set()
    for op, info in OP_INFO.items():
        cat, inp = info.get("category"), info.get("input")
        if cat in ("event", "jump", "displacement"):
            named.add(op)
        elif cat == "reference" and inp == "metric":
            named.add(op)
        elif cat == "scalar" and "signal_kind" in info:
            named.add(op)
    return named


def test_named_op_set_matches_op_info():
    """The hardcoded ``_NAMED_OPS`` (which drives the doc-coverage maps below)
    must equal the named-op set DERIVED from ``OP_INFO``. This is the new
    OP_INFO-wide drift guard: add a named op to the engine without listing it in
    the docs maps here and this fails, naming the op."""
    engine = _engine_named_ops()
    missing = engine - _NAMED_OPS    # engine has a named op the test doesn't track
    extra = _NAMED_OPS - engine      # test tracks an op the engine no longer names
    assert not missing and not extra, (
        "named-op set drift between OP_INFO and the help-sync test.\n"
        f"  named in engine but UNTRACKED here (needs tooltip+doc+map): {sorted(missing)}\n"
        f"  tracked here but no longer a named op in engine:            {sorted(extra)}"
    )


def test_every_named_op_has_doc_name_mapping():
    """Every named op in ``OP_INFO`` must have a ``_OP_DOC_NAME`` entry that
    resolves to a real METRIC_DOCS entry. Driven from the engine, so a new op
    with no METRIC_DOCS entry is flagged here (by op key) instead of KeyError-ing
    deep inside the one-to-one test."""
    doc_names = set(_doc_names())
    no_map = sorted(op for op in _engine_named_ops() if op not in _OP_DOC_NAME)
    no_doc = sorted(op for op in _engine_named_ops()
                    if op in _OP_DOC_NAME and _OP_DOC_NAME[op] not in doc_names)
    assert not no_map and not no_doc, (
        "named ops missing documentation (OP_INFO-wide check).\n"
        f"  no _OP_DOC_NAME mapping:        {no_map}\n"
        f"  mapped but no METRIC_DOCS entry: {no_doc}"
    )


def test_named_ops_match_engine_one_to_one():
    """The named ops in the engine == OP_TOOLTIPS keys == documented set. Catches
    an op added without a tooltip/doc (or a stale doc)."""
    from core.metrics import OP_INFO, SCALAR_OPS
    # B1 ops are scalar ops; B2 event/jump/reference ops live only in OP_INFO.
    assert _B1_OPS <= set(SCALAR_OPS)
    assert _NAMED_OPS <= set(OP_INFO)
    # tooltips are exactly the named ops (no gaps, no extras)
    assert set(OP_TOOLTIPS) == _NAMED_OPS, (
        f"OP_TOOLTIPS drift: missing={_NAMED_OPS - set(OP_TOOLTIPS)}, "
        f"extra={set(OP_TOOLTIPS) - _NAMED_OPS}"
    )
    # every named op has a METRIC_DOCS entry under its mapped doc name
    doc_names = set(_doc_names())
    for op in _NAMED_OPS:
        assert _OP_DOC_NAME[op] in doc_names, f"{op}: no METRIC_DOCS entry"


def test_named_op_labels_match_doc_names():
    """The OP_INFO human label and the METRIC_DOCS name agree for B1 ops, so the
    popup and the reference dialog show the same spelling. (B2 ops may fold
    several ops into one doc entry, so they are exempt from the strict match.)"""
    from core.metrics import OP_INFO
    for op in _B1_OPS:
        assert OP_INFO[op]["label"] == _OP_DOC_NAME[op]


_REQUIRED_FIELDS = ("name", "unit", "desc", "axes", "formula")
_BILINGUAL_FIELDS = ("desc", "axes")  # axes may be intentionally empty (see below)


def _iter_doc_metrics():
    for cat in METRIC_DOCS:
        for m in cat["metrics"]:
            yield m


@pytest.mark.parametrize(
    "metric",
    list(_iter_doc_metrics()),
    ids=[m["name"] for m in _iter_doc_metrics()],
)
def test_doc_entry_has_required_fields(metric):
    """Each doc entry carries the full schema; en/kr are both present.

    ``axes`` is allowed to hold empty strings (some metrics are axis-agnostic,
    e.g. sway path length) but the en/kr keys must still exist. ``name``,
    ``unit``, ``formula`` and both ``desc`` languages must be non-empty.
    """
    for field in _REQUIRED_FIELDS:
        assert field in metric, f"{metric.get('name', '?')!r}: missing field {field!r}"

    for field in _BILINGUAL_FIELDS:
        sub = metric[field]
        assert isinstance(sub, dict) and {"en", "kr"} <= set(sub), (
            f"{metric['name']!r}: {field!r} must be a dict with 'en' and 'kr'"
        )

    for field in ("name", "unit", "formula"):
        assert str(metric[field]).strip(), f"{metric['name']!r}: {field!r} is empty"

    for lang in ("en", "kr"):
        assert str(metric["desc"][lang]).strip(), (
            f"{metric['name']!r}: desc[{lang!r}] is empty"
        )
