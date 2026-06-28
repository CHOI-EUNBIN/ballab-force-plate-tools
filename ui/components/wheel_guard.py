"""Wheel-scroll guard for value widgets (spin boxes / combo boxes / sliders).

Problem: a ``QSpinBox`` / ``QDoubleSpinBox`` / ``QComboBox`` eats mouse-wheel
events to change its own value. Inside a scroll area this is a trap — the user
scrolls past the control and silently changes a parameter (a force threshold, a
filter cutoff) without noticing. Visual3D-grade tools never do this.

Fix: one shared :class:`WheelGuard` event filter that *ignores* wheel events on
the value widget (so the wheel bubbles up to the enclosing scroll area and just
scrolls). We also relax the focus policy from ``WheelFocus`` to ``StrongFocus``
so the widget no longer grabs wheel focus on hover — it only takes keyboard/click
focus. ``install_wheel_guard(root)`` walks a widget tree and arms every value
widget at once, so a whole dialog/panel is covered in a single call.

Sliders are intentionally left alone: dragging/wheeling a slider is the slider's
whole job, and they are rarely nested in a scroll trap.
"""

from PyQt6.QtCore import QObject, QEvent, Qt
from PyQt6.QtWidgets import QAbstractSpinBox, QComboBox


class WheelGuard(QObject):
    """A singleton-style event filter that swallows wheel events.

    Returning ``True`` from :meth:`eventFilter` marks the wheel event handled
    *without* the widget acting on it, and Qt then does NOT forward it to the
    parent — so we instead ``ignore()`` the event and return ``False`` only when
    the widget is unfocused, letting it propagate to the scroll area. When the
    widget has keyboard focus we still block the value change (a focused control
    should not change from an accidental wheel either), which matches the user's
    request that the wheel never edits a value.
    """

    def eventFilter(self, obj, event):  # noqa: N802 (Qt naming)
        # This filter is installed both per-widget AND app-wide, so it can be
        # handed *every* event. Cheap early-outs keep that affordable: only Wheel
        # events on a spin/combo are ever touched; everything else passes through.
        if event.type() == QEvent.Type.Wheel and isinstance(
                obj, (QAbstractSpinBox, QComboBox)):
            # Swallow the wheel so the value never changes. (We don't re-post it
            # to the parent: that risks double-scrolling; the user just gets a
            # control that ignores the wheel, like a read-pinned field.)
            event.ignore()
            return True
        return super().eventFilter(obj, event)


#: One shared instance — event filters are stateless here, so a module-level
#: singleton avoids creating a QObject per widget (and avoids parent-less leaks).
#: Created lazily via :func:`_guard` so that if the underlying ``QApplication`` is
#: ever torn down and recreated (the C++ ``WheelGuard`` is deleted with it — this
#: happens between Qt test modules), the next call transparently rebuilds it
#: instead of raising "wrapped C/C++ object ... has been deleted".
_GUARD = None


def _guard():
    """The shared :class:`WheelGuard`, (re)creating it if its C++ side is gone."""
    global _GUARD
    if _GUARD is None:
        _GUARD = WheelGuard()
        return _GUARD
    # If the QApplication that owned it was destroyed, the Python wrapper survives
    # but its C++ object is deleted; touching it raises RuntimeError. Detect that
    # and rebuild a fresh filter.
    try:
        _GUARD.objectName()
    except RuntimeError:
        _GUARD = WheelGuard()
    return _GUARD


def app_guard():
    """The shared guard instance for an app-wide ``installEventFilter`` call.

    Use this (not the ``_GUARD`` global) so the lazy/self-healing creation in
    :func:`_guard` applies to the app-wide install too."""
    return _guard()


def guard_widget(widget):
    """Arm a single value widget against wheel-scroll value changes."""
    widget.installEventFilter(_guard())
    # Drop WheelFocus so hovering + scrolling never first focuses the widget.
    if widget.focusPolicy() == Qt.FocusPolicy.WheelFocus:
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)


def install_wheel_guard(root):
    """Walk ``root``'s widget tree and arm every spin box / combo box found.

    Call once after a dialog/panel finishes building its widgets. Idempotent:
    installing the same filter twice on a widget is a no-op in Qt.
    """
    if root is None:
        return
    targets = root.findChildren(QAbstractSpinBox) + root.findChildren(QComboBox)
    for w in targets:
        guard_widget(w)
