# Animated Splash (Fade + Smooth Scale) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static startup `QSplashScreen` with an `AnimatedSplash` widget that fades the logo in while scaling it 0.92→1.0, guarantees a minimum 0.8s display, then fades out — for a premium feel.

**Architecture:** A new frameless, translucent, always-on-top `QWidget` (`ui/splash.py`) paints a high-res logo with a live `opacity` and `scale` driven by `QPropertyAnimation`. `main.py` is restructured so `MainWindow` construction is deferred via `QTimer.singleShot`, letting the event loop run and the intro animation paint before the heavy build blocks it; `finish()` reveals the window and plays the outro without blocking.

**Tech Stack:** Python, PyQt6 (`QWidget`, `QPropertyAnimation`, `QEasingCurve`, `QPainter`, `QTimer`, `QElapsedTimer`, `pyqtProperty`).

## Global Constraints

- PyQt6 only (match existing imports; no PyQt5/PySide).
- UI-facing strings stay English (project rule: Visual3D-aligned labels). The splash shows no text, so this is moot, but keep any code identifiers/comments English.
- Tests are headless: set `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` before importing Qt, and use a module-scoped `app` fixture returning `QApplication.instance() or QApplication(sys.argv)` (existing pattern, see `tests/test_ensemble_panel.py`).
- Logo asset: `assets/ballab_icon_master_1024_transparent.png`, resolved via `ui.main_window.resource_path`.
- **Repo root for all paths and commands is the inner `BalanceAnalyzer/` git repo** (it has its own `.git`; current branch `feat/rag-assistant`). All file paths below are relative to that root: `ui/splash.py`, `tests/test_splash.py`, `main.py`. Run pytest and git from there.

---

### Task 1: `AnimatedSplash` widget — properties, geometry, painting

**Files:**
- Create: `ui/splash.py`
- Test: `tests/test_splash.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - Module constants: `BASE_SIZE = 300` (logo px at scale 1.0), `WIDGET_SIZE = 360`, `INTRO_FADE_MS = 700`, `INTRO_SCALE_MS = 800`, `MIN_DISPLAY_MS = 800`, `OUTRO_FADE_MS = 350`, `SCALE_FROM = 0.92`.
  - `class AnimatedSplash(QWidget)`:
    - `__init__(self, pixmap: QPixmap, parent=None)` — stores `self._pixmap`, sets flags/attrs, fixed size `WIDGET_SIZE×WIDGET_SIZE`, centers on screen, `self._opacity = 0.0`, `self._scale = SCALE_FROM`.
    - `opacity` pyqtProperty(float) — getter/setter; setter calls `self.update()`.
    - `scale` pyqtProperty(float) — getter/setter; setter calls `self.update()`.
    - `target_rect(self) -> QRectF` — centered square of side `BASE_SIZE * self._scale` within the widget.
    - `paintEvent(self, event)` — painter with Antialiasing + SmoothPixmapTransform, `setOpacity(self._opacity)`, draw `self._pixmap` into `target_rect()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_splash.py
import os
import sys
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def _make(app):
    from ui.splash import AnimatedSplash
    pm = QPixmap(1024, 1024)
    pm.fill()
    return AnimatedSplash(pm)


def test_initial_state_is_transparent_and_small(app):
    from ui import splash as s
    w = _make(app)
    assert w.opacity == 0.0
    assert w.scale == s.SCALE_FROM
    assert w.width() == s.WIDGET_SIZE and w.height() == s.WIDGET_SIZE


def test_setters_clamp_and_request_repaint(app):
    w = _make(app)
    w.opacity = 0.5
    w.scale = 1.0
    assert w.opacity == 0.5
    assert w.scale == 1.0


def test_target_rect_scales_and_centers(app):
    from ui import splash as s
    w = _make(app)
    w.scale = 1.0
    r = w.target_rect()
    assert round(r.width()) == s.BASE_SIZE
    # centered in the widget
    assert round(r.center().x()) == s.WIDGET_SIZE // 2
    assert round(r.center().y()) == s.WIDGET_SIZE // 2
    w.scale = s.SCALE_FROM
    assert round(w.target_rect().width()) == round(s.BASE_SIZE * s.SCALE_FROM)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_splash.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.splash'`.

- [ ] **Step 3: Write minimal implementation**

```python
# ui/splash.py
"""Animated startup splash: fades the logo in while scaling it up, holds for a
minimum time, then fades out. A frameless, translucent, always-on-top widget so
only the transparent-PNG logo is visible over the brief pre-paint flash."""

from PyQt6.QtCore import Qt, QRectF, pyqtProperty
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QWidget

BASE_SIZE = 300        # logo side length (px) at scale 1.0
WIDGET_SIZE = 360      # widget side; padding so the scaled logo never clips
INTRO_FADE_MS = 700
INTRO_SCALE_MS = 800
MIN_DISPLAY_MS = 800
OUTRO_FADE_MS = 350
SCALE_FROM = 0.92


class AnimatedSplash(QWidget):
    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._opacity = 0.0
        self._scale = SCALE_FROM
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(WIDGET_SIZE, WIDGET_SIZE)
        screen = self.screen() or (self.windowHandle() and self.windowHandle().screen())
        geo = (screen.availableGeometry() if screen else None)
        if geo is not None:
            self.move(geo.center().x() - WIDGET_SIZE // 2,
                      geo.center().y() - WIDGET_SIZE // 2)

    def _get_opacity(self):
        return self._opacity

    def _set_opacity(self, value):
        self._opacity = float(value)
        self.update()

    opacity = pyqtProperty(float, _get_opacity, _set_opacity)

    def _get_scale(self):
        return self._scale

    def _set_scale(self, value):
        self._scale = float(value)
        self.update()

    scale = pyqtProperty(float, _get_scale, _set_scale)

    def target_rect(self):
        side = BASE_SIZE * self._scale
        x = (self.width() - side) / 2.0
        y = (self.height() - side) / 2.0
        return QRectF(x, y, side, side)

    def paintEvent(self, event):
        if self._pixmap is None or self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setOpacity(max(0.0, min(1.0, self._opacity)))
        painter.drawPixmap(self.target_rect(), self._pixmap,
                           QRectF(self._pixmap.rect()))
        painter.end()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_splash.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add ui/splash.py tests/test_splash.py
git commit -m "feat(ui): AnimatedSplash widget — opacity/scale props + painting"
```

---

### Task 2: Intro/outro animation orchestration + min-display gating

**Files:**
- Modify: `ui/splash.py`
- Test: `tests/test_splash.py`

**Interfaces:**
- Consumes: `AnimatedSplash`, constants from Task 1.
- Produces, added to `AnimatedSplash`:
  - `start(self)` — shows nothing new; builds and starts two `QPropertyAnimation`s stored as `self._fade` (b"opacity", 0.0→1.0, `INTRO_FADE_MS`, `OutCubic`) and `self._scale_anim` (b"scale", `SCALE_FROM`→1.0, `INTRO_SCALE_MS`, `OutCubic`); starts `self._elapsed = QElapsedTimer()` via `self._elapsed.start()`.
  - `finish_delay_ms(self, elapsed: int) -> int` — pure: `max(0, MIN_DISPLAY_MS - elapsed)`.
  - `finish(self, win)` — stores `self._win = win`; `QTimer.singleShot(self.finish_delay_ms(self._elapsed.elapsed()), self._outro)`.
  - `_outro(self)` — raises/activates `self._win`, builds `self._fade_out` (b"opacity", current→0.0, `OUTRO_FADE_MS`, `InCubic`), connects its `finished` to `self.close`, starts it.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_splash.py
from PyQt6.QtCore import QEasingCurve


def test_start_builds_intro_anims_with_correct_params(app):
    from ui import splash as s
    w = _make(app)
    w.start()
    assert w._fade.startValue() == 0.0 and w._fade.endValue() == 1.0
    assert w._fade.duration() == s.INTRO_FADE_MS
    assert w._fade.easingCurve().type() == QEasingCurve.Type.OutCubic
    assert w._scale_anim.startValue() == s.SCALE_FROM
    assert w._scale_anim.endValue() == 1.0
    assert w._scale_anim.duration() == s.INTRO_SCALE_MS


def test_finish_delay_respects_minimum(app):
    from ui import splash as s
    w = _make(app)
    assert w.finish_delay_ms(0) == s.MIN_DISPLAY_MS
    assert w.finish_delay_ms(s.MIN_DISPLAY_MS + 500) == 0
    assert w.finish_delay_ms(300) == s.MIN_DISPLAY_MS - 300


def test_outro_starts_fade_to_zero_and_reveals_window(app):
    w = _make(app)
    w.start()
    w._opacity = 1.0

    class _FakeWin:
        def __init__(self):
            self.raised = False
            self.activated = False
        def raise_(self):
            self.raised = True
        def activateWindow(self):
            self.activated = True

    fw = _FakeWin()
    w._win = fw
    w._outro()
    assert fw.raised and fw.activated
    assert w._fade_out.endValue() == 0.0
    assert w._fade_out.duration() == 350
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_splash.py -v`
Expected: FAIL — `AttributeError: 'AnimatedSplash' object has no attribute 'start'`.

- [ ] **Step 3: Write minimal implementation**

Add these imports to the top of `ui/splash.py` (extend the existing `QtCore` import line and add `QtCore` timer/animation names):

```python
from PyQt6.QtCore import (
    Qt, QRectF, QTimer, QElapsedTimer, QPropertyAnimation, QEasingCurve,
    pyqtProperty,
)
```

Add these methods to `AnimatedSplash` (after `paintEvent`):

```python
    def start(self):
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._fade = QPropertyAnimation(self, b"opacity", self)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setDuration(INTRO_FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._scale_anim = QPropertyAnimation(self, b"scale", self)
        self._scale_anim.setStartValue(SCALE_FROM)
        self._scale_anim.setEndValue(1.0)
        self._scale_anim.setDuration(INTRO_SCALE_MS)
        self._scale_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.start()
        self._scale_anim.start()

    def finish_delay_ms(self, elapsed):
        return max(0, MIN_DISPLAY_MS - int(elapsed))

    def finish(self, win):
        self._win = win
        elapsed = self._elapsed.elapsed() if hasattr(self, "_elapsed") else 0
        QTimer.singleShot(self.finish_delay_ms(elapsed), self._outro)

    def _outro(self):
        if getattr(self, "_win", None) is not None:
            self._win.raise_()
            self._win.activateWindow()
        self._fade_out = QPropertyAnimation(self, b"opacity", self)
        self._fade_out.setStartValue(self._opacity)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setDuration(OUTRO_FADE_MS)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_out.finished.connect(self.close)
        self._fade_out.start()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_splash.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add ui/splash.py tests/test_splash.py
git commit -m "feat(ui): AnimatedSplash intro/outro animations + min-display gating"
```

---

### Task 3: Wire `AnimatedSplash` into `main.py` startup flow

**Files:**
- Modify: `main.py:60-86`
- Test: `tests/test_splash.py`

**Interfaces:**
- Consumes: `AnimatedSplash`, `ui.main_window.resource_path`.
- Produces: restructured `main()` that defers `MainWindow` construction via `QTimer.singleShot`.

- [ ] **Step 1: Write the failing test (import smoke + flow shape)**

```python
# append to tests/test_splash.py
def test_main_uses_animated_splash_and_defers_build():
    import inspect
    import main
    src = inspect.getsource(main.main)
    assert "AnimatedSplash" in src
    assert "QSplashScreen" not in src
    assert "singleShot" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_splash.py::test_main_uses_animated_splash_and_defers_build -v`
Expected: FAIL — assert `"AnimatedSplash" in src` is False (main.py still uses `QSplashScreen`).

- [ ] **Step 3: Replace the splash block in `main.py`**

Replace the current block (lines ~62-86, from the `from PyQt6.QtWidgets import QSplashScreen` comment through `sys.exit(app.exec())`) with:

```python
    # Animated logo splash shown while the (heavy) main window is built. The
    # logo fades in while scaling up, holds for a minimum time, then fades out.
    # A translucent background means only the transparent-PNG logo is visible —
    # it also covers the brief white flash before the UI paints.
    from PyQt6.QtCore import QTimer
    from ui.splash import AnimatedSplash
    QPixmap = qt_gui.QPixmap

    logo = QPixmap(resource_path("assets/ballab_icon_master_1024_transparent.png"))
    splash = None
    if not logo.isNull():
        splash = AnimatedSplash(logo)
        splash.show()
        splash.start()
        app.processEvents()

    state = {}

    def build():
        win = MainWindow(qtm_ip=args.ip)
        state["win"] = win                      # keep a reference past this scope
        win.show()
        if args.project and os.path.isfile(args.project):
            win.open_project_path(args.project)
        if splash is not None:
            splash.finish(win)

    if splash is not None:
        # Defer the heavy build so the event loop runs first and the intro
        # animation paints a few frames before the build briefly blocks it.
        QTimer.singleShot(50, build)
    else:
        build()

    sys.exit(app.exec())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_splash.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Manual launch verification**

Run: `python main.py`
Expected: On launch the logo fades in while growing slightly, stays briefly, then fades out as the main window appears. No white flash, no static-then-pop.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_splash.py
git commit -m "feat(ui): wire AnimatedSplash into startup flow (deferred build)"
```

---

## Self-Review

**Spec coverage:**
- Fade + smooth scale → Task 1 (paint w/ opacity+scale) + Task 2 (intro anims). ✓
- Min 0.8s display → Task 2 `finish_delay_ms` / `MIN_DISPLAY_MS = 800`. ✓
- Logo only, no text → Task 1 paints only the pixmap. ✓
- Event-loop-based flow restructure → Task 3 `singleShot` deferral. ✓
- Null-logo fallback → Task 3 `else: build()` path. ✓
- New `ui/splash.py`, modify `main.py`, replace `QSplashScreen` → Tasks 1–3. ✓

**Placeholder scan:** No TBD/TODO; all code blocks complete. ✓

**Type consistency:** `opacity`/`scale` pyqtProperty names match the `QPropertyAnimation` byte-strings (`b"opacity"`, `b"scale"`). `target_rect`, `start`, `finish`, `finish_delay_ms`, `_outro`, `_win`, `_fade`, `_scale_anim`, `_fade_out` used consistently across tasks. Constants (`BASE_SIZE`, `WIDGET_SIZE`, `INTRO_FADE_MS`, `INTRO_SCALE_MS`, `MIN_DISPLAY_MS`, `OUTRO_FADE_MS`, `SCALE_FROM`) defined once in Task 1, referenced via `s.` in tests. ✓
