"""Headless tests for the AI assistant panel's typewriter + thinking indicator.

Timers don't fire without an event loop, so we drive the typewriter tick
manually and assert: the answer text is fully revealed, the trailing cursor is
gone when finished, and sources are rendered only after typing completes.
Skipped cleanly if Qt is unavailable.
"""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PyQt6.QtWidgets import QApplication
    _HAVE_QT = True
except Exception:  # pragma: no cover
    _HAVE_QT = False

pytestmark = pytest.mark.skipif(not _HAVE_QT, reason="PyQt6 unavailable")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _drive_to_end(panel):
    # Drive the typewriter without the event loop until all tokens revealed.
    guard = 0
    while panel._type_timer is not None and guard < 10000:
        panel._type_tick()
        guard += 1
    return guard


def test_typing_reveals_full_answer_and_drops_cursor(app):
    from ui.ai_assistant_panel import AiAssistantPanel
    panel = AiAssistantPanel()
    panel._enter_message_mode()
    panel._pending_body, panel._pending_src, panel._pending_indicator = panel._add_answer_block()
    panel._pending_indicator.start()

    answer = "Step width SD is the standard deviation of step width across cycles."
    panel._pending_res = {"sources": [], "timings": {"llm": 1.2}}
    panel._start_typing(answer)

    # Indicator hidden once typing starts; body shown.
    assert not panel._pending_body.isHidden()
    assert panel._pending_indicator.isHidden()

    _drive_to_end(panel)

    # Full text, no trailing cursor glyph.
    assert panel._pending_body.text() == answer
    assert "▍" not in panel._pending_body.text()
    panel.shutdown()


def test_sources_render_only_after_typing_done(app):
    from ui.ai_assistant_panel import AiAssistantPanel
    panel = AiAssistantPanel()
    panel._enter_message_mode()
    panel._pending_body, panel._pending_src, panel._pending_indicator = panel._add_answer_block()

    answer = "one two three four five"
    panel._pending_res = {"sources": [{"source": "Smith 2014", "doi": ""}], "timings": {"llm": 0.5}}
    panel._start_typing(answer)

    # Mid-typing: sources still hidden.
    panel._type_tick()
    assert panel._pending_src.isHidden()

    _drive_to_end(panel)
    # After completion the source line is populated and shown.
    assert not panel._pending_src.isHidden()
    assert "Smith 2014" in panel._pending_src.text()
    panel.shutdown()


def test_empty_answer_finishes_cleanly(app):
    from ui.ai_assistant_panel import AiAssistantPanel
    panel = AiAssistantPanel()
    panel._enter_message_mode()
    panel._pending_body, panel._pending_src, panel._pending_indicator = panel._add_answer_block()
    panel._pending_res = {"sources": [], "timings": {"llm": 0.1}}
    panel._start_typing("")
    # No timer left running; body empty.
    assert panel._type_timer is None
    assert panel._pending_body.text() == ""
    panel.shutdown()
