"""Shared analysis-results store — the in-app interchange between the Analyze
and Statistics tabs.

Only *derived metrics* live here (one flat row per analyzed file x range), never
raw participant signals. The row schema mirrors the Excel "Results" sheet that
Analyze exports, so the in-app hand-off and an imported .xlsx converge on the
same table:

    row = {"File": str, "Range": str, "<Metric (unit)>": float, ...}

MainWindow owns one instance and injects it into both tabs. Listeners (the
Statistics table) are notified on every change.
"""


class ResultsStore:
    FIXED = ("Folder", "Condition", "File", "Range")

    def __init__(self):
        self._rows = []
        self._listeners = []

    # --- listeners ---
    def add_listener(self, fn):
        if fn not in self._listeners:
            self._listeners.append(fn)

    def _notify(self):
        for fn in list(self._listeners):
            fn()

    # --- mutation ---
    def set_rows(self, rows, source=None):
        self._rows = [dict(r) for r in rows]
        self._notify()

    def add_rows(self, rows, source=None):
        self._rows.extend(dict(r) for r in rows)
        self._notify()

    def clear(self):
        self._rows = []
        self._notify()

    # --- access ---
    def rows(self):
        return list(self._rows)

    def is_empty(self):
        return not self._rows

    def columns(self):
        """Ordered columns: File, Range, then metric columns in first-seen order."""
        cols = list(self.FIXED)
        for r in self._rows:
            for k in r:
                if k not in cols:
                    cols.append(k)
        return cols

    def table(self):
        """Return (headers, rows-as-lists) for display/export."""
        cols = self.columns()
        return cols, [[r.get(c, "") for c in cols] for r in self._rows]
