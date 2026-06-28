"""Metric-computation failure diagnostics — the single source of truth that maps
a machine REASON code to a human-readable (English) message.

When a :class:`~core.pipeline.MetricStep` cannot produce a (full) value, the
engine tags the result with a ``status`` and a ``reason`` code; this module turns
that code into a sentence the UI can show inline (mirroring the angle ⚠ tooltip).
Keeping the wording here — not scattered through the engine/UI — means every
consumer says the same thing, and adding a new failure mode is one table entry.

Status (three states):
  * ``OK``           — value computed, no caveat.
  * ``PARTIAL``      — a value IS present but with a caveat (some cycles dropped,
                       or a whole-trial fallback was used). UI marks it ``◐``.
  * ``UNAVAILABLE``  — no value (NaN); the ``reason`` says why. UI marks it ``⚠``.

Reason codes group into the three buckets the design calls out:
  * data missing        — NO_SIGNAL / NOT_COP / NO_EVENT_INSTANCES / NO_CYCLES
  * insufficient data   — WINDOW_TOO_SHORT / WINDOW_ALL_NAN / NEEDS_TWO_CYCLES
  * cannot compute      — UNKNOWN_OP / NO_MASS / NO_REFERENCE / DIVIDE_BY_ZERO /
                          NO_SEGMENT
  * partial / fallback  — PARTIAL_CYCLES / WHOLE_TRIAL_FALLBACK
"""

# -- status states ----------------------------------------------------------
OK = "ok"
PARTIAL = "partial"
UNAVAILABLE = "unavailable"

# -- reason codes -----------------------------------------------------------
# data missing
NO_SIGNAL = "no_signal"
NOT_COP = "not_cop"
NO_EVENT_INSTANCES = "no_event_instances"
NO_CYCLES = "no_cycles"
# insufficient data
WINDOW_TOO_SHORT = "window_too_short"
WINDOW_ALL_NAN = "window_all_nan"
NEEDS_TWO_CYCLES = "needs_two_cycles"
# cannot compute
UNKNOWN_OP = "unknown_op"
NO_MASS = "no_mass"
NO_REFERENCE = "no_reference"
DIVIDE_BY_ZERO = "divide_by_zero"
NO_SEGMENT = "no_segment"
# partial / fallback (value present, with a caveat)
PARTIAL_CYCLES = "partial_cycles"
WHOLE_TRIAL_FALLBACK = "whole_trial_fallback"

#: Every reason code, for round-trip tests + UI completeness checks.
ALL_REASONS = (
    NO_SIGNAL, NOT_COP, NO_EVENT_INSTANCES, NO_CYCLES,
    WINDOW_TOO_SHORT, WINDOW_ALL_NAN, NEEDS_TWO_CYCLES,
    UNKNOWN_OP, NO_MASS, NO_REFERENCE, DIVIDE_BY_ZERO, NO_SEGMENT,
    PARTIAL_CYCLES, WHOLE_TRIAL_FALLBACK,
)

#: reason code -> English message template. ``{input}``/``{event}``/``{op}``/
#: ``{n}``/``{m}``/``{seg0}``/``{seg1}`` are filled from the metric step's context
#: when available; a missing key falls back to a generic (still-correct) sentence.
_TEMPLATES = {
    NO_SIGNAL: (
        "Input signal '{input}' is not available — no model angle, no markers, "
        "no such force plate, or an upstream Compute step produced nothing.",
        "An input signal is not available — no model angle, no markers, no such "
        "force plate, or an upstream Compute step produced nothing.",
    ),
    NOT_COP: (
        "This operation needs a COP signal (e.g. 'fp1:cop'); '{input}' is not one.",
        "This operation needs a COP signal (e.g. 'fp1:cop').",
    ),
    NO_EVENT_INSTANCES: (
        "Event '{event}' has no detected instances to read a value at.",
        "The chosen event has no detected instances to read a value at.",
    ),
    NO_CYCLES: (
        "No complete cycles found for segment [{seg0} -> {seg1}].",
        "No complete cycles found for the chosen segment.",
    ),
    WINDOW_TOO_SHORT:
        "The window has fewer than 2 valid samples — a rate/derivative needs at "
        "least two points.",
    WINDOW_ALL_NAN:
        "The window is entirely missing (NaN) — likely marker occlusion over "
        "this interval.",
    NEEDS_TWO_CYCLES:
        "This statistic needs at least 2 cycles; only 1 was available.",
    UNKNOWN_OP: (
        "Unknown operation '{op}'.",
        "Unknown operation.",
    ),
    NO_MASS:
        "Subject mass is required for this jump metric — set the subject mass.",
    NO_REFERENCE:
        "A referenced metric is missing or not finite.",
    DIVIDE_BY_ZERO:
        "Division by zero.",
    NO_SEGMENT:
        "This operation needs an event segment (a start/end event pair).",
    PARTIAL_CYCLES:
        "Computed {n} of {m} cycles.",
    WHOLE_TRIAL_FALLBACK:
        "No complete cycles found — computed over the whole trial instead.",
}


def message_for(reason, **ctx):
    """English message for a ``reason`` code, formatted with ``ctx`` when given.

    A template may be a single string or a ``(detailed, generic)`` pair: the
    detailed form is used when ``ctx`` supplies its placeholders, otherwise the
    generic form (so a missing ``input``/``event`` never raises or leaves a hole).
    Unknown / ``None`` reason -> ``""`` (the caller treats it as "no caveat").
    """
    tmpl = _TEMPLATES.get(reason)
    if tmpl is None:
        return ""
    if isinstance(tmpl, tuple):
        detailed, generic = tmpl
        try:
            return detailed.format(**ctx)
        except (KeyError, IndexError):
            return generic
    try:
        return tmpl.format(**ctx)
    except (KeyError, IndexError):
        return tmpl
