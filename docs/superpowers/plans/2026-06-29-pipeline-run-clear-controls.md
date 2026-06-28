# Pipeline Run / Clear Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the PIPELINE `▶` a plain generation-only Run button, stop all auto-run, show only raw data before Run, and split deletion into explicit step/result × all/one controls.

**Architecture:** All changes live in the single large PyQt6 view `ui/analyze_tab.py`. The run-state gate is the existing per-dataset flag `dataset["analysis"]` (set by `_run_analysis`, `None` before a run). Rendering of derived artifacts (RESULTS lists, event lines) is gated on a new `_has_run(dataset)` helper. New header/menu actions call small new methods (`_on_run_clicked`, `_clear_pipeline`, `_clear_all_results`, `_delete_result_item`).

**Tech Stack:** Python 3, PyQt6, pyqtgraph, pytest (headless `QT_QPA_PLATFORM=offscreen`).

## Global Constraints

- **Icons:** monochrome only. Reuse the app's dingbat glyphs (`+` `▶` `✎` `✕`) for text buttons; use Qt standard icons (`QStyle.StandardPixmap.SP_TrashIcon`) for the two "clear all" buttons. **No color emoji** anywhere in UI strings or code.
- **No auto-run:** neither preset apply, project load, nor pipeline edits may call `_run_analysis`. Run happens only from the header Run button click.
- **Run is generation-only:** it never deletes results. Every press does a full front-to-back recompute (intermediate caching is out of scope).
- **Pre-Run view:** before a dataset has been run, only raw signals render; derived signals/events/metrics do not.
- **Git:** the working tree's `.git` is empty (no initialized repo). Commit steps below will fail until `git init` is run — treat them as optional. Do NOT run `git init` without the user's say-so; if git is unavailable, skip the commit step and continue.
- **Tests:** new tests go in `tests/test_pipeline_run_controls.py`, following the headless pattern in `tests/test_ui_smoke.py` (module-scoped `app` fixture, `pytestmark` skipif Qt missing). Run the full suite with `python -m pytest` from the repo root.

---

### Task 1: Convert header `▶` from toggle to plain Run button

**Files:**
- Modify: `ui/analyze_tab.py` (build `851-856`; `_on_filter_changed` `3727-3733`; replace `_on_show_results_toggled` `4187-4206`)
- Test: `tests/test_pipeline_run_controls.py`

**Interfaces:**
- Produces: `AnalyzeTab.show_btn` (now a non-checkable `QPushButton`), `AnalyzeTab._on_run_clicked(self)` — calls `_run_analysis()`.
- Consumes: existing `AnalyzeTab._run_analysis()` (unchanged).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_run_controls.py
import os, sys
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PyQt6.QtWidgets import QApplication
    _HAVE_QT = True
except Exception:  # pragma: no cover
    _HAVE_QT = False

pytestmark = pytest.mark.skipif(not _HAVE_QT, reason="Qt unavailable")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def test_run_button_is_plain_not_toggle(app):
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    assert not tab.show_btn.isCheckable()          # plain momentary button
    assert hasattr(tab, "_on_run_clicked")
    assert not hasattr(tab, "_on_show_results_toggled")


def test_run_click_runs_without_clearing(app):
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    calls = []
    tab._run_analysis = lambda: calls.append(1) or True
    tab._on_run_clicked()
    tab._on_run_clicked()
    assert calls == [1, 1]                          # every click runs; nothing clears
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_pipeline_run_controls.py -v`
Expected: FAIL (`show_btn.isCheckable()` is True / `_on_run_clicked` missing).

- [ ] **Step 3: Make the button plain (build site)**

Replace `ui/analyze_tab.py:851-856`:

```python
        self.show_btn = QPushButton("▶")
        self.show_btn.setObjectName("run-icon")
        self.show_btn.setCheckable(True)
        self.show_btn.setFixedSize(22, 20)
        self.show_btn.setToolTip("Run analysis (metrics, cards)")
        self.show_btn.toggled.connect(self._on_show_results_toggled)
```

with:

```python
        self.show_btn = QPushButton("▶")
        self.show_btn.setObjectName("run-icon")
        self.show_btn.setFixedSize(22, 20)
        self.show_btn.setToolTip("Run analysis (generate results)")
        self.show_btn.clicked.connect(self._on_run_clicked)
```

- [ ] **Step 4: Replace the toggle handler with a plain run handler**

Replace the whole `_on_show_results_toggled` method (`ui/analyze_tab.py:4187-4206`) with:

```python
    def _on_run_clicked(self):
        """Run the pipeline and show results. Generation only — never clears
        (clearing is the explicit Clear-all-results control)."""
        self._run_analysis()
```

- [ ] **Step 5: Stop pipeline edits from auto-running**

Replace `ui/analyze_tab.py:3727-3733`:

```python
        if getattr(self, "show_btn", None) is not None and self.show_btn.isChecked():
            self._run_analysis()
        else:
            if dataset is not None:
                self._plot_dataset(dataset)
            else:
                self._refresh_results_panels(None)
```

with (editing the recipe re-renders raw only; Run stays explicit):

```python
        if dataset is not None:
            self._plot_dataset(dataset)
        else:
            self._refresh_results_panels(None)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pipeline_run_controls.py -v`
Expected: PASS (both tests).

- [ ] **Step 7: Commit** (skip if git uninitialized)

```bash
git add tests/test_pipeline_run_controls.py ui/analyze_tab.py
git commit -m "feat: make pipeline Run a plain generation-only button"
```

---

### Task 2: Add "clear all steps" header button

**Files:**
- Modify: `ui/analyze_tab.py` (header build `843-878`; new method near `_delete_pipeline_step` `3707`)
- Test: `tests/test_pipeline_run_controls.py`

**Interfaces:**
- Produces: `AnalyzeTab.clear_steps_btn` (QPushButton), `AnalyzeTab._clear_pipeline(self)` — empties `self.pipeline.steps`, invalidates caches, refreshes list + results.
- Consumes: existing `self.pipeline`, `_invalidate_event_caches`, `_refresh_pipeline_list`, `_on_filter_changed`.

- [ ] **Step 1: Write the failing test**

```python
def test_clear_all_steps_empties_pipeline(app, monkeypatch):
    from ui.analyze_tab import AnalyzeTab
    from core.pipeline import FilterStep
    from core.signals import FilterSpec
    from PyQt6.QtWidgets import QMessageBox
    tab = AnalyzeTab()
    tab.pipeline.steps.append(FilterStep(
        spec=FilterSpec(type="Butterworth", cutoff_hz=10, order=4),
        targets=["fz"], markers=False))
    tab._refresh_pipeline_list()
    assert tab.step_list.count() == 1
    # Auto-confirm the wipe dialog.
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    assert hasattr(tab, "clear_steps_btn")
    tab._clear_pipeline()
    assert len(tab.pipeline.steps) == 0
    assert tab.step_list.count() == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_pipeline_run_controls.py::test_clear_all_steps_empties_pipeline -v`
Expected: FAIL (`clear_steps_btn` / `_clear_pipeline` missing).

- [ ] **Step 3: Build the button and add it to the header**

In `_build_pipeline_section`, immediately after the `add_step_btn` block (after `ui/analyze_tab.py:847`, before the `▶` comment at `849`), insert:

```python
        from PyQt6.QtWidgets import QStyle
        self.clear_steps_btn = QPushButton()
        self.clear_steps_btn.setObjectName("small-btn")
        self.clear_steps_btn.setFixedSize(24, 22)
        self.clear_steps_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        self.clear_steps_btn.setToolTip("Clear all steps")
        self.clear_steps_btn.clicked.connect(self._clear_pipeline)
```

Then change the section's `header_widgets` (`ui/analyze_tab.py:877`) from:

```python
            header_widgets=[self.add_step_btn, self.show_btn],
```

to:

```python
            header_widgets=[self.add_step_btn, self.clear_steps_btn, self.show_btn],
```

- [ ] **Step 4: Add the `_clear_pipeline` method**

Insert directly after `_delete_pipeline_step` (after `ui/analyze_tab.py:3712`):

```python
    def _clear_pipeline(self):
        """Remove every step from the pipeline (the header 'Clear all steps'
        action). Confirms first when the pipeline is non-empty. Does NOT touch
        results — clearing results is a separate, explicit control."""
        if not self.pipeline.steps:
            return
        from PyQt6.QtWidgets import QMessageBox
        if QMessageBox.question(
                self, "Clear all steps",
                "Remove all steps from the pipeline?") != QMessageBox.StandardButton.Yes:
            return
        self.pipeline.steps.clear()
        self._invalidate_event_caches()
        self._refresh_pipeline_list()
        self._on_filter_changed()
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_pipeline_run_controls.py::test_clear_all_steps_empties_pipeline -v`
Expected: PASS.

- [ ] **Step 6: Commit** (skip if git uninitialized)

```bash
git add ui/analyze_tab.py tests/test_pipeline_run_controls.py
git commit -m "feat: add clear-all-steps header button"
```

---

### Task 3: Remove auto-run on project load

**Files:**
- Modify: `ui/analyze_tab.py` (load path `4788-4807`; save manifest `4580-4581`)
- Test: `tests/test_pipeline_run_controls.py`

**Interfaces:**
- Consumes: existing `manifest`, `self.datasets`.
- Produces: no new symbols; the load path no longer references `show_btn.setChecked`.

- [ ] **Step 1: Write the failing test**

```python
def test_no_autorun_on_project_load(app):
    import inspect
    from ui.analyze_tab import AnalyzeTab
    # The load path must not flip the run button on (auto-run removed).
    src = inspect.getsource(AnalyzeTab)
    assert "show_btn.setChecked(True)" not in src
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_pipeline_run_controls.py::test_no_autorun_on_project_load -v`
Expected: FAIL (the string is still present at line 4803).

- [ ] **Step 3: Delete the auto-run-on-load block**

Remove `ui/analyze_tab.py:4788-4807` entirely (the comment block plus the
`if manifest.get("results_shown") ...` try/except). After removal, the
surrounding method continues straight from the preceding `pass` to
`_parse_file_meta`.

- [ ] **Step 4: Make the saved `results_shown` flag truthful**

Replace `ui/analyze_tab.py:4580-4581`:

```python
            "results_shown": bool(self.show_btn.isChecked())
            if hasattr(self, "show_btn") else False,
```

with (the button is no longer checkable; derive from real run state):

```python
            "results_shown": any(
                d.get("analysis") is not None for d in self.datasets),
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_pipeline_run_controls.py::test_no_autorun_on_project_load -v`
Expected: PASS.

- [ ] **Step 6: Commit** (skip if git uninitialized)

```bash
git add ui/analyze_tab.py tests/test_pipeline_run_controls.py
git commit -m "feat: stop auto-running pipeline on project load"
```

---

### Task 4: Gate derived rendering on run state (raw-only before Run)

**Files:**
- Modify: `ui/analyze_tab.py` (new `_has_run`; `_refresh_results_panels` `1402-1416`; `_draw_events` `6182-6185`)
- Test: `tests/test_pipeline_run_controls.py`

**Interfaces:**
- Produces: `AnalyzeTab._has_run(self, dataset) -> bool` — True iff `dataset` is not None and has been run (`dataset.get("analysis") is not None`).
- Consumes: existing `_build_results`, `_populate_signals_list`, `_populate_events_list`, `_populate_metrics_list`, `_add_empty_hint`, `signals_list`, `results_events_list`, `metrics_list`.

- [ ] **Step 1: Write the failing test**

```python
def test_has_run_gate(app):
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    assert tab._has_run(None) is False
    assert tab._has_run({"analysis": None}) is False
    assert tab._has_run({"analysis": {"file": "x"}}) is True


def test_results_panels_empty_before_run(app):
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    # A dataset whose pipeline could produce signals, but not yet run.
    ds = {"name": "t", "analysis": None}
    tab._refresh_results_panels(ds)
    # All three RESULTS lists hold only the non-selectable "press Run" hint row.
    for lst in (tab.signals_list, tab.results_events_list, tab.metrics_list):
        for i in range(lst.count()):
            from PyQt6.QtCore import Qt
            assert lst.item(i).flags() == Qt.ItemFlag.NoItemFlags


def test_draw_events_skipped_before_run(app):
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    tab.event_lines = ["sentinel"]   # would be cleared if _draw_events proceeded
    drew = []
    tab._draw_auto_events = lambda ds: drew.append(1)
    tab._draw_events({"analysis": None, "events": [
        {"name": "HS", "time": 1.0, "frame": 10, "enabled": True}]})
    assert drew == []                # auto events never drawn pre-run
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_pipeline_run_controls.py -k "has_run or before_run or events_skipped" -v`
Expected: FAIL (`_has_run` missing; panels populated; events drawn).

- [ ] **Step 3: Add the `_has_run` helper**

Insert directly above `_refresh_results_panels` (before `ui/analyze_tab.py:1402`):

```python
    def _has_run(self, dataset):
        """True once ``dataset`` has been run (results exist). The run-state gate
        for all derived rendering: before a run only raw data shows."""
        return dataset is not None and dataset.get("analysis") is not None
```

- [ ] **Step 4: Gate `_refresh_results_panels` to empty hints before a run**

Replace the body of `_refresh_results_panels` (`ui/analyze_tab.py:1408-1416`, the lines after the docstring) with:

```python
        if not hasattr(self, "signals_list"):
            return
        if dataset is None:
            dataset = self._current_dataset()
        if not self._has_run(dataset):
            # Pre-run: raw data only. Show a "press Run" hint in each list rather
            # than listing what the recipe *would* produce.
            for lst in (self.signals_list, self.results_events_list,
                        self.metrics_list):
                lst.clear()
                self._add_empty_hint(lst, "Press ▶ Run to generate results.")
            self._refresh_ensemble_panel()
            return
        data = self._build_results(dataset)
        self._populate_signals_list(dataset, data["signal"])
        self._populate_events_list(data["event"])
        self._populate_metrics_list(data["metric"])
        self._refresh_ensemble_panel()
```

- [ ] **Step 5: Gate `_draw_events` to skip when not run**

Replace `ui/analyze_tab.py:6182-6185`:

```python
    def _draw_events(self, dataset):
        self._clear_event_lines()
        if dataset is None:
            return
```

with:

```python
    def _draw_events(self, dataset):
        self._clear_event_lines()
        if not self._has_run(dataset):
            return   # events are a derived product: nothing before Run
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pipeline_run_controls.py -k "has_run or before_run or events_skipped" -v`
Expected: PASS.

- [ ] **Step 7: Run the full suite to catch regressions**

Run: `python -m pytest -q`
Expected: PASS (no pre-existing tests assume derived signals/events list before a run; if one does, update it to call `_run_analysis` first or assert the new pre-run hint).

- [ ] **Step 8: Commit** (skip if git uninitialized)

```bash
git add ui/analyze_tab.py tests/test_pipeline_run_controls.py
git commit -m "feat: show only raw data until the pipeline is run"
```

---

### Task 5: Add "clear all results" control

**Files:**
- Modify: `ui/analyze_tab.py` (RESULTS header build `773`; new `_clear_all_results` method)
- Test: `tests/test_pipeline_run_controls.py`

**Interfaces:**
- Produces: `AnalyzeTab.clear_results_btn` (QPushButton), `AnalyzeTab._clear_all_results(self)` — drops `analysis` on every dataset, resets to raw view.
- Consumes: existing `self.datasets`, `self.analysis_results`, `self.summary_rows`, `_set_placeholder`, `_current_dataset`, `_plot_dataset`, `view_mode`. Mirrors the body retired from the old toggle-off branch.

**Note:** `_make_section` builds the section header internally and does not accept
header widgets the way `_build_pipeline_section` does. Add the clear-results
button as the first row INSIDE `results_inner` (a compact right-aligned action
row above the Signals list), so it sits in the RESULTS panel without changing
`_make_section`'s signature.

- [ ] **Step 1: Write the failing test**

```python
def test_clear_all_results_resets_to_raw(app, monkeypatch):
    from ui.analyze_tab import AnalyzeTab
    from PyQt6.QtWidgets import QMessageBox
    tab = AnalyzeTab()
    tab.datasets = [{"name": "a", "analysis": {"file": "a"}},
                    {"name": "b", "analysis": {"file": "b"}}]
    tab.analysis_results = [1, 2]
    tab.summary_rows = [1]
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    assert hasattr(tab, "clear_results_btn")
    tab._clear_all_results()
    assert all(d["analysis"] is None for d in tab.datasets)
    assert tab.analysis_results == []
    assert tab.summary_rows == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_pipeline_run_controls.py::test_clear_all_results_resets_to_raw -v`
Expected: FAIL (`clear_results_btn` / `_clear_all_results` missing).

- [ ] **Step 3: Add the clear-results action row inside RESULTS**

In `_build_results_section`, immediately after `ri.setSpacing(2)` (after
`ui/analyze_tab.py:741`), insert:

```python
        from PyQt6.QtWidgets import QStyle, QHBoxLayout
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 4, 0)
        action_row.addStretch(1)
        self.clear_results_btn = QPushButton()
        self.clear_results_btn.setObjectName("small-btn")
        self.clear_results_btn.setFixedSize(24, 22)
        self.clear_results_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        self.clear_results_btn.setToolTip("Clear all results")
        self.clear_results_btn.clicked.connect(self._clear_all_results)
        action_row.addWidget(self.clear_results_btn)
        ri.addLayout(action_row)
```

- [ ] **Step 4: Add the `_clear_all_results` method**

Insert directly after `_refresh_results_panels` (after the method ending near
`ui/analyze_tab.py:1416`):

```python
    def _clear_all_results(self):
        """Drop generated results for ALL datasets and return to raw review.
        The explicit standalone replacement for the retired Run-toggle-off."""
        if not any(d.get("analysis") is not None for d in self.datasets):
            return
        from PyQt6.QtWidgets import QMessageBox
        if QMessageBox.question(
                self, "Clear all results",
                "Clear all generated results?") != QMessageBox.StandardButton.Yes:
            return
        for d in self.datasets:
            d["analysis"] = None
        self.analysis_results = []
        self.summary_rows = []
        self._set_placeholder("Press ▶ Run to generate results.")
        dataset = self._current_dataset()
        if dataset is not None:
            self.view_mode = "review"
            self._plot_dataset(dataset)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_pipeline_run_controls.py::test_clear_all_results_resets_to_raw -v`
Expected: PASS.

- [ ] **Step 6: Commit** (skip if git uninitialized)

```bash
git add ui/analyze_tab.py tests/test_pipeline_run_controls.py
git commit -m "feat: add explicit clear-all-results control"
```

---

### Task 6: Add per-item result delete

**Files:**
- Modify: `ui/analyze_tab.py` (`__init__` near `304`; `_populate_signals_list` `1456-1460`; `_populate_metrics_list`; signals/metrics context menus `_show_results_signals_menu` / `_show_results_metrics_menu`; clear hidden set in `_run_analysis` near `5980`)
- Test: `tests/test_pipeline_run_controls.py`

**Interfaces:**
- Produces: `AnalyzeTab._hidden_result_keys` (set of `"<kind>:<key>"`), `AnalyzeTab._delete_result_item(self, kind, key)` — hides one RESULTS item (view-level), like the existing per-event hide.
- Consumes: existing `_hidden_event_labels` pattern, `_refresh_results_panels`, the right-click menu builders for signals/metrics.

**Design note (deviation from spec's "hover ✕"):** RESULTS rows are plain
`QListWidgetItem`s in menu-driven lists, not custom hover-widget rows like the
PIPELINE list. To stay consistent with the existing Events list (which already
deletes via its right-click menu), per-item delete is implemented as a
**"Remove from results" right-click menu entry** on signal and metric rows, not
a hover `✕`. Same outcome (remove one item), matching the existing interaction
model. Flag this to the user at review.

- [ ] **Step 1: Write the failing test**

```python
def test_delete_result_item_hides_key(app):
    from ui.analyze_tab import AnalyzeTab
    tab = AnalyzeTab()
    assert hasattr(tab, "_hidden_result_keys")
    refreshed = []
    tab._refresh_results_panels = lambda *a, **k: refreshed.append(1)
    tab._delete_result_item("signal", "fz:filt")
    assert "signal:fz:filt" in tab._hidden_result_keys
    assert refreshed == [1]


def test_run_clears_hidden_result_keys(app, monkeypatch):
    from ui.analyze_tab import AnalyzeTab
    from PyQt6.QtWidgets import QMessageBox
    # The "no files" path pops a modal — stub it so the headless run returns.
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    tab = AnalyzeTab()
    tab._hidden_result_keys.add("signal:fz:filt")
    # Minimal run: no files -> guarded early return, but the hidden set must be
    # cleared at the top of a fresh run alongside _hidden_event_labels.
    tab.datasets = []
    tab._run_analysis()
    assert tab._hidden_result_keys == set()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_pipeline_run_controls.py -k "delete_result_item or clears_hidden" -v`
Expected: FAIL (`_hidden_result_keys` / `_delete_result_item` missing).

- [ ] **Step 3: Initialize the hidden-keys set**

In `__init__`, directly after the `_hidden_event_labels` initialization (the set
described at `ui/analyze_tab.py:304`), add:

```python
        # RESULTS items the user removed view-level (signals/metrics), mirroring
        # _hidden_event_labels. Cleared on every ▶Run so a fresh run restores all.
        self._hidden_result_keys = set()
```

- [ ] **Step 4: Add the `_delete_result_item` method**

Insert after `_clear_all_results` (Task 5):

```python
    def _delete_result_item(self, kind, key):
        """Hide one RESULTS item (signal/metric) from the view, like the per-event
        view-level Delete. A fresh ▶Run clears the hidden set and restores it."""
        self._hidden_result_keys.add(f"{kind}:{key}")
        self._refresh_results_panels(self._current_dataset())
```

- [ ] **Step 5: Skip hidden keys when populating signals**

In `_populate_signals_list`, inside the `for e in members:` loop, add a skip at
the top of the loop body (before `ui/analyze_tab.py:1457` `indent = ...`):

```python
                if f"signal:{e.key}" in self._hidden_result_keys:
                    continue
```

- [ ] **Step 6: Skip hidden keys when populating metrics**

In `_populate_metrics_list`, at the top of its per-entry loop (mirror the signals
skip, using the metric entry's `.key`):

```python
                if f"metric:{e.key}" in self._hidden_result_keys:
                    continue
```

- [ ] **Step 7: Add "Remove from results" to the signals and metrics menus**

In `_show_results_signals_menu`, after the existing menu actions are built and
before the menu is executed, add an action wired to delete the row under the
cursor (use the same `(kind, key)` UserRole the list items already carry):

```python
        item = self.signals_list.itemAt(pos)
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        if data:
            menu.addSeparator()
            act_remove = menu.addAction("Remove from results")
            act_remove.triggered.connect(
                lambda _=False, k=data[1]: self._delete_result_item("signal", k))
```

Apply the symmetric change in `_show_results_metrics_menu` (using
`self.metrics_list` and `kind="metric"`). Read each menu method first to splice
into its existing build/exec structure without dropping current actions.

- [ ] **Step 8: Clear the hidden set on a fresh run**

In `_run_analysis`, next to `self._hidden_event_labels.clear()` (near
`ui/analyze_tab.py:5980`), add — and move both lines above the early `return`
guards so they run even when the run aborts on no files (the test relies on
this):

```python
        self._hidden_result_keys.clear()
```

Concretely, relocate the `_hidden_event_labels.clear()` + `_hidden_result_keys.clear()`
pair to the very top of `_run_analysis`, before the `if not self.datasets:` guard.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pipeline_run_controls.py -k "delete_result_item or clears_hidden" -v`
Expected: PASS.

- [ ] **Step 10: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 11: Commit** (skip if git uninitialized)

```bash
git add ui/analyze_tab.py tests/test_pipeline_run_controls.py
git commit -m "feat: add per-item result delete (signals/metrics)"
```

---

## Final Verification

- [ ] Run the full suite: `python -m pytest -q` — all pass.
- [ ] Manual smoke (optional, needs a display): launch `python main.py`, Quick Start → walk treadmill. Confirm: steps appear but no results until `▶`; pressing `▶` twice keeps results; the two trash buttons clear steps / results independently; raw signals show before Run.

## Notes / Out of Scope

- Per-step ("개별 run") execution and intermediate-result caching are deferred (see spec).
- Per-item result delete uses the right-click menu rather than a hover `✕` (Task 6 design note) — surface at review.
- The header `▶` keeps its `run-icon` object name for styling continuity even though it is no longer a toggle.
