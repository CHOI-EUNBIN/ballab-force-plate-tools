"""Metric-computation failure diagnostics (core.diagnostics).

The single source of truth that turns a machine REASON code into a human-readable
(English) message explaining WHY a metric value is missing or partial. Pinned so
every UI/engine consumer reads the same wording.
"""

import core.diagnostics as diag


def test_status_constants_are_the_three_states():
    assert diag.OK == "ok"
    assert diag.PARTIAL == "partial"
    assert diag.UNAVAILABLE == "unavailable"


def test_every_reason_code_has_a_nonempty_english_message():
    # Pin that each declared reason resolves to a real sentence (not the code).
    for reason in diag.ALL_REASONS:
        msg = diag.message_for(reason)
        assert isinstance(msg, str) and msg.strip()
        assert reason not in msg  # message is prose, not the raw code


def test_unknown_reason_is_empty_string():
    assert diag.message_for("no_such_reason") == ""
    assert diag.message_for(None) == ""


def test_no_signal_message_names_the_input_key():
    msg = diag.message_for(diag.NO_SIGNAL, input="angle:Knee")
    assert "angle:Knee" in msg


def test_not_cop_message_names_the_input_key():
    msg = diag.message_for(diag.NOT_COP, input="fp1:fz")
    assert "fp1:fz" in msg


def test_no_event_instances_message_names_the_event():
    msg = diag.message_for(diag.NO_EVENT_INSTANCES, event="HS")
    assert "HS" in msg


def test_unknown_op_message_names_the_op():
    msg = diag.message_for(diag.UNKNOWN_OP, op="frobnicate")
    assert "frobnicate" in msg


def test_partial_cycles_message_states_n_of_m():
    msg = diag.message_for(diag.PARTIAL_CYCLES, n=3, m=5)
    assert "3" in msg and "5" in msg


def test_missing_format_context_does_not_raise():
    # A reason whose template wants {input} but none supplied -> graceful fallback.
    msg = diag.message_for(diag.NO_SIGNAL)
    assert isinstance(msg, str) and msg.strip()
