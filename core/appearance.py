"""User-customisable appearance settings (graph + 3D overlay colours).

QSettings-backed, like ``AxisSettings``. Values are committed in a batch via
``apply()`` (the Appearance dialog edits a local copy and only commits on Apply),
emitting ``changed`` once so the views re-render.
"""

from PyQt6.QtCore import QObject, QSettings, pyqtSignal


# key -> default. Colours are hex strings; matches the current hard-coded values
# (so defaults look identical) except the 3D overlay, which drops the old red.
DEFAULTS = {
    # 3D segment overlay (muted scene defaults)
    "overlay/bones": "#6BA891",
    "overlay/joints": "#AFB8B8",
    "overlay/pelvis": "#ABCDEF",
    # graph curve colours (defaults = former analyze_tab C_* constants)
    "curve/cop": "#42A5F5",
    "curve/ap": "#7F77DD",
    "curve/ml": "#D4537E",
    "curve/raw": "#555550",
    "curve/fx": "#D86A3A",
    "curve/fy": "#3B8FD9",
    "curve/fz": "#1D9E75",
    # graph geometry
    "grid_default": True,
    "line_width": 1.5,
    # 3D markers (Aurora Teal scene defaults)
    "marker/color": "#92A8A2",
    "marker/highlight": "#FB923C",
    "marker/size": "M",
}

COLOR_KEYS = [k for k in DEFAULTS if k.startswith(("overlay/", "curve/", "marker/"))
              and k != "marker/size"]


class Appearance(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._settings = QSettings("Balancelab", "Balancelab")
        self._values = {}
        for key, default in DEFAULTS.items():
            self._values[key] = self._load(key, default)

    def _load(self, key, default):
        raw = self._settings.value(f"appearance/{key}", None)
        if raw is None:
            return default
        if isinstance(default, bool):
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("1", "true", "yes", "on")
        if isinstance(default, float):
            try:
                return float(raw)
            except (TypeError, ValueError):
                return default
        return str(raw)

    # ----- access -----
    def get(self, key):
        return self._values.get(key, DEFAULTS.get(key))

    def all(self):
        return dict(self._values)

    def color(self, key):
        return self._values.get(key, DEFAULTS.get(key))

    def grid_default(self):
        return bool(self._values["grid_default"])

    def line_width(self):
        return float(self._values["line_width"])

    def marker_size(self):
        return str(self._values["marker/size"])

    # ----- commit (batch) -----
    def apply(self, values):
        """Commit a dict of {key: value}; persists changed keys and emits once."""
        dirty = False
        for key, value in values.items():
            if key not in DEFAULTS:
                continue
            if self._values.get(key) != value:
                self._values[key] = value
                self._settings.setValue(f"appearance/{key}", value)
                dirty = True
        if dirty:
            self.changed.emit()
        return dirty

    def reset_defaults(self):
        self.apply(dict(DEFAULTS))
