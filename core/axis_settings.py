from PyQt6.QtCore import QObject, QSettings, pyqtSignal


AXIS_KEYS = ("Fx", "Fy", "Fz", "Mx", "My", "Mz", "COP_AP", "COP_ML")


class AxisSettings(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._settings = QSettings("BALLAB", "BALLAB")
        self.live_signs = self._load_signs()
        self.foot_displacement_normalized = self._load_bool(
            "analysis/foot_displacement_normalized", False
        )
        self.filter_enabled = self._load_bool("filter/enabled", True)
        self.filter_type = self._load_str("filter/type", "Butterworth")
        self.filter_cutoff_hz = self._load_float("filter/cutoff_hz", 10.0)
        self.filter_order = self._load_int("filter/order", 4)

    def _load_signs(self):
        signs = {}
        for key in AXIS_KEYS:
            value = self._settings.value(f"axis/live/{key}", 1, type=int)
            signs[key] = -1 if int(value) < 0 else 1
        return signs

    def set_live_sign(self, axis, sign):
        if axis not in AXIS_KEYS:
            return
        sign = -1 if int(sign) < 0 else 1
        if self.live_signs[axis] == sign:
            return
        self.live_signs[axis] = sign
        self._settings.setValue(f"axis/live/{axis}", sign)
        self.changed.emit()

    def set_foot_displacement_normalized(self, enabled):
        enabled = bool(enabled)
        if self.foot_displacement_normalized == enabled:
            return
        self.foot_displacement_normalized = enabled
        self._settings.setValue("analysis/foot_displacement_normalized", enabled)
        self.changed.emit()

    def set_filter_enabled(self, enabled):
        self._set_attr("filter_enabled", "filter/enabled", bool(enabled))

    def set_filter_type(self, filter_type):
        self._set_attr("filter_type", "filter/type", str(filter_type))

    def set_filter_cutoff_hz(self, cutoff_hz):
        self._set_attr("filter_cutoff_hz", "filter/cutoff_hz", float(cutoff_hz))

    def set_filter_order(self, order):
        self._set_attr("filter_order", "filter/order", int(order))

    def _set_attr(self, attr, key, value):
        if getattr(self, attr) == value:
            return
        setattr(self, attr, value)
        self._settings.setValue(key, value)
        self.changed.emit()

    def _load_bool(self, key, default=False):
        value = self._settings.value(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def _load_str(self, key, default=""):
        return str(self._settings.value(key, default))

    def _load_float(self, key, default=0.0):
        try:
            return float(self._settings.value(key, default))
        except (TypeError, ValueError):
            return float(default)

    def _load_int(self, key, default=0):
        try:
            return int(float(self._settings.value(key, default)))
        except (TypeError, ValueError):
            return int(default)

    def transform_live(self, fx, fy, fz, cop_ap, cop_ml, mx, my, mz):
        signs = self.live_signs
        return (
            fx * signs["Fx"],
            fy * signs["Fy"],
            fz * signs["Fz"],
            cop_ap * signs["COP_AP"],
            cop_ml * signs["COP_ML"],
            mx * signs["Mx"],
            my * signs["My"],
            mz * signs["Mz"],
        )
