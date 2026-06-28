"""3D marker view (motion-capture "video") for the Analyze tab.

Wraps pyqtgraph.opengl's GLViewWidget. The import is guarded so the rest of the
app keeps working if PyOpenGL is unavailable — ``make_marker_view`` then returns
a small placeholder widget instead.
"""

import numpy as np
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QMenu, QToolTip
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QVector4D, QFont, QImage, QPainter, QMatrix4x4

from ui import style as S

try:
    import pyqtgraph as pg
    import pyqtgraph.opengl as gl
    import OpenGL.GL as _ogl
    GL_AVAILABLE = True
except Exception:  # pragma: no cover - depends on PyOpenGL/driver
    GL_AVAILABLE = False


def _rgbf(hex_color, alpha=1.0):
    c = QColor(hex_color)
    return (c.redF(), c.greenF(), c.blueF(), alpha)


# Marker dot diameters in mm (world units; markers use pxMode=False so they
# scale with zoom like real objects instead of staying a fixed pixel size).
_SIZES = {"S": 16.0, "M": 26.0, "L": 40.0}

# Cohesive 3D-view colour presets (user-switchable via right-click → Scene style).
# Each preset themes the whole scene so nothing competes with the marker hero.
SCENE_STYLES = {
    "aurora": {
        "label": "Aurora Teal",
        "marker": "#92A8A2", "highlight": "#FB923C",
        "bone": "#6BA891", "joint": "#AFB8B8", "pelvis": "#ABCDEF",
        "plate": "#2B3647", "edge": "#3A4658", "plate_label": "#5E7C86",
        "grf": "#EF4444", "cop": "#FCA5A5", "grid": "#2A3340", "floor": "#222A33",
        "axis": ("#F2706E", "#4FD08A", "#5B9DF9"),
    },
    "mono": {
        "label": "Mono Graphite + Coral",
        "marker": "#E6ECF3", "highlight": "#2DD4BF",
        "bone": "#9AA7B8", "joint": "#E6ECF3", "pelvis": "#7DD3C8",
        "plate": "#323A48", "edge": "#586273", "plate_label": "#AEB8C7",
        "grf": "#FF6B6B", "cop": "#FFA8A8", "grid": "#2A3340", "floor": "#242A33",
        "axis": ("#F2706E", "#4FD08A", "#5B9DF9"),
    },
    "violet": {
        "label": "Violet Nebula",
        "marker": "#67E8F9", "highlight": "#A78BFA",
        "bone": "#C7CEDD", "joint": "#A78BFA", "pelvis": "#C4B5FD",
        "plate": "#2E2A4A", "edge": "#8B7CF0", "plate_label": "#C4B5FD",
        "grf": "#F472B6", "cop": "#FBCFE8", "grid": "#2C2A45", "floor": "#211E33",
        "axis": ("#F2706E", "#4FD08A", "#5B9DF9"),
    },
}
_DEFAULT_STYLE = "aurora"


def _cylinder_mesh(p0, p1, radius, n=16):
    """Vertices/faces for a closed cylinder between p0 and p1 (axis shaft)."""
    p0 = np.asarray(p0, float); p1 = np.asarray(p1, float)
    axis = p1 - p0
    h = float(np.linalg.norm(axis))
    if h < 1e-9:
        return np.zeros((3, 3)), np.array([[0, 1, 2]])
    d = axis / h
    a = np.array([1.0, 0.0, 0.0]) if abs(d[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(d, a); u /= (np.linalg.norm(u) or 1.0)
    w = np.cross(d, u)
    ang = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    off = radius * (np.cos(ang)[:, None] * u[None, :] + np.sin(ang)[:, None] * w[None, :])
    bottom = p0[None, :] + off
    top = p1[None, :] + off
    verts = np.vstack([bottom, top, p0[None, :], p1[None, :]])
    bc, tc = 2 * n, 2 * n + 1
    faces = []
    for k in range(n):
        k2 = (k + 1) % n
        faces.append([k, k2, n + k2])         # side
        faces.append([k, n + k2, n + k])
        faces.append([bc, k2, k])             # bottom cap
        faces.append([tc, n + k, n + k2])     # top cap
    return verts, np.asarray(faces)


def _sphere_unit(lat=8, lon=12):
    """Unit-sphere verts/faces (cached, reused for every joint)."""
    phi = np.linspace(0.0, np.pi, lat + 1)
    th = np.linspace(0.0, 2.0 * np.pi, lon, endpoint=False)
    verts = [[np.sin(p) * np.cos(t), np.sin(p) * np.sin(t), np.cos(p)]
             for p in phi for t in th]
    faces = []
    for i in range(lat):
        for j in range(lon):
            a = i * lon + j; b = i * lon + (j + 1) % lon
            c = (i + 1) * lon + j; d = (i + 1) * lon + (j + 1) % lon
            faces.append([a, b, d]); faces.append([a, d, c])
    return np.asarray(verts, float), np.asarray(faces)


def _text_image(text, hex_color, px=128):
    """Render ``text`` to an (H,W,4) uint8 RGBA array (transparent background)."""
    w, h = px * 2, px
    img = QImage(w, h, QImage.Format.Format_RGBA8888)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setPen(QColor(hex_color))
    p.setFont(QFont("Arial", int(px * 0.55), QFont.Weight.Bold))
    p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    ptr = img.constBits()
    ptr.setsize(h * w * 4)
    return np.frombuffer(ptr, np.uint8).reshape(h, w, 4).copy()


_UNIT_SPHERE = None


def _spheres_mesh(points, r):
    """One combined mesh of equal-radius spheres at ``points`` (joint markers)."""
    global _UNIT_SPHERE
    if _UNIT_SPHERE is None:
        _UNIT_SPHERE = _sphere_unit()
    uv, uf = _UNIT_SPHERE
    vs, fs, off = [], [], 0
    for c in points:
        vs.append(uv * r + np.asarray(c, float))
        fs.append(uf + off); off += len(uv)
    if not vs:
        return np.zeros((3, 3)), np.array([[0, 1, 2]])
    return np.vstack(vs), np.vstack(fs)


def _tubes_mesh(segments, r):
    """One combined mesh of cylinders for a list of (p0, p1) bone segments."""
    vs, fs, off = [], [], 0
    for p0, p1 in segments:
        v, f = _cylinder_mesh(p0, p1, r, n=10)
        vs.append(v); fs.append(f + off); off += len(v)
    if not vs:
        return np.zeros((3, 3)), np.array([[0, 1, 2]])
    return np.vstack(vs), np.vstack(fs)


def _cone_mesh(apex, base_center, radius, n=16):
    """Vertices/faces for a filled cone (arrowhead) pointing from base to apex."""
    apex = np.asarray(apex, dtype=float)
    base_center = np.asarray(base_center, dtype=float)
    axis = apex - base_center
    h = float(np.linalg.norm(axis))
    if h < 1e-9:
        return np.zeros((3, 3)), np.array([[0, 1, 2]])
    d = axis / h
    a = np.array([1.0, 0.0, 0.0]) if abs(d[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(d, a)
    u /= (np.linalg.norm(u) or 1.0)
    w = np.cross(d, u)
    ang = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    ring = base_center[None, :] + radius * (np.cos(ang)[:, None] * u[None, :]
                                            + np.sin(ang)[:, None] * w[None, :])
    verts = np.vstack([apex[None, :], ring, base_center[None, :]])  # 0=apex, 1..n=ring, n+1=base
    faces = []
    for k in range(n):
        k2 = (k + 1) % n
        faces.append([0, 1 + k, 1 + k2])        # cone side
        faces.append([n + 1, 1 + k2, 1 + k])    # base cap
    return verts, np.asarray(faces)


class _FallbackView(QWidget):
    """Shown when OpenGL is unavailable."""

    marker_picked = pyqtSignal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lbl = QLabel("3D marker view unavailable.\nInstall PyOpenGL (pip install PyOpenGL).")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(f"color:{S.TEXT_SECONDARY};font-size:12px;")
        lay.addWidget(lbl)

    # No-op API so callers don't need to special-case it.
    def set_owner(self, owner): pass
    def set_markers(self, markers, positions=None): pass
    def set_positions(self, positions): pass
    def update_frame(self, t_seconds, idx=None): pass
    def apply_theme(self): pass
    def set_overlay(self, points=None, segments=None, pelvis=None): pass
    def set_overlay_colors(self, bones=None, joints=None, pelvis=None): pass
    def set_marker_colors(self, color=None, highlight=None): pass
    def set_marker_size(self, key): pass
    def set_visible_mask(self, mask): pass
    def set_highlight(self, indices): pass
    def set_force_plates(self, plates): pass
    def set_grf(self, grf): pass


if GL_AVAILABLE:

    class MarkerView(gl.GLViewWidget):
        """Animated 3D scatter of markers, driven by ``update_frame(seconds)``."""

        # Emitted when a marker is left-clicked (not dragged): (index, global QPoint).
        marker_picked = pyqtSignal(int, object)

        def __init__(self, parent=None):
            super().__init__(parent)
            self._owner = None
            self._markers = None
            self._pos = None               # (M,F,3) positions to draw (raw or filtered)
            self._labels = []
            self._cur_idx = 0
            self._visible_mask = None
            self._highlight = set()
            self._label_mode = "hover"     # off | hover | always
            self._marker_size = _SIZES["M"]
            self._grid_on = True
            self._axes_on = False
            self._marker_color = _rgbf(S.ACCENT_TEAL)
            self._hi_color = _rgbf(S.ACCENT_ORANGE if hasattr(S, "ACCENT_ORANGE") else S.ACCENT_RED)
            # Model-overlay palette (configurable via Appearance; no red, no glow).
            self._c_bone = _rgbf("#E8EEF2")
            self._c_joint = _rgbf("#2FB8A8")
            self._c_pelvis = _rgbf("#5BC0EB")
            self._right_dragging = False
            self._right_moved = False
            self._left_pressed = False
            self._left_moved = False
            self.setMouseTracking(True)
            # We drive the right-click menu ourselves (so right-drag can pan).
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
            self.setCameraPosition(distance=2000, elevation=18, azimuth=-70)

            self._grid = gl.GLGridItem()
            self._grid.setSize(6000, 6000)
            self._grid.setSpacing(100, 100)
            self.addItem(self._grid)

            # XYZ gnomon: cone-tipped cylinders (line width is GL-driver-limited, so
            # we use real geometry to guarantee a thick, V3D-style arrow). Toggled
            # via right-click → Axes. Colours are the lab-standard R/G/B.
            self._axis_items = []
            L = 400.0
            shaft_r, head_len, head_r = 9.0, 90.0, 26.0
            # Lift the gnomon slightly off the floor so the X/Y arrows don't
            # overlap / z-fight the grid and force plates.
            o = np.array([0.0, 0.0, 70.0])
            axes = [(np.array([L, 0, 0.0]), "X", (0.95, 0.44, 0.43, 1.0)),
                    (np.array([0, L, 0.0]), "Y", (0.31, 0.82, 0.54, 1.0)),
                    (np.array([0, 0, L], float), "Z", (0.36, 0.62, 0.98, 1.0))]
            for vec, label, col in axes:
                end = o + vec
                d = vec / np.linalg.norm(vec)
                neck = end - d * head_len
                sv, sf = _cylinder_mesh(o, neck, shaft_r)
                shaft = gl.GLMeshItem(vertexes=sv, faces=sf, color=col, smooth=True, drawEdges=False)
                shaft.setGLOptions("opaque")
                shaft.setVisible(False)
                self.addItem(shaft)
                self._axis_items.append(shaft)
                hv, hf = _cone_mesh(end, neck, head_r)
                head = gl.GLMeshItem(vertexes=hv, faces=hf, color=col, smooth=True, drawEdges=False)
                head.setGLOptions("opaque")
                head.setVisible(False)
                self.addItem(head)
                self._axis_items.append(head)
                if hasattr(gl, "GLTextItem"):
                    txt = gl.GLTextItem(
                        pos=o + vec * 1.10, text=label,
                        color=QColor.fromRgbF(*col), font=QFont("Arial", 13, QFont.Weight.Bold))
                    txt.setVisible(False)
                    self.addItem(txt)
                    self._axis_items.append(txt)

            self._overlay_active = False    # True while a model skeleton is shown
            self._bone_r = 9.0
            self._pelvis_r = 7.0
            self._joint_r = 15.0

            # Always-on text labels (created per dataset).
            self._text_items = []

            # Model overlay (added BEFORE the marker scatter so raw markers
            # depth-sort on top instead of being buried in the bone tubes):
            # bone tubes + pelvis tubes + joint spheres.
            def _mesh():
                m = gl.GLMeshItem(vertexes=np.zeros((3, 3)), faces=np.array([[0, 1, 2]]),
                                  smooth=True, drawEdges=False)
                m.setGLOptions("opaque")
                m.setVisible(False)
                self.addItem(m)
                return m
            self._overlay_bones = _mesh()
            self._overlay_pelvis = _mesh()
            self._overlay_joints = _mesh()

            # Markers draw on top (depth test off) so they are never buried inside
            # the bone tubes, and use pxMode=False so their size is in world mm.
            on_top = {_ogl.GL_DEPTH_TEST: False, _ogl.GL_BLEND: True,
                      "glBlendFunc": (_ogl.GL_SRC_ALPHA, _ogl.GL_ONE_MINUS_SRC_ALPHA)}
            self._scatter = gl.GLScatterPlotItem(pos=np.zeros((1, 3)), size=self._marker_size, pxMode=False)
            self._scatter.setGLOptions(on_top)
            self._scatter.setDepthValue(10)   # drawn last → never painted over by the plates
            self.addItem(self._scatter)
            self._hi_scatter = gl.GLScatterPlotItem(pos=np.zeros((1, 3)), size=self._marker_size, pxMode=False)
            self._hi_scatter.setGLOptions(on_top)
            self._hi_scatter.setDepthValue(11)
            self.addItem(self._hi_scatter)

            # Force plates (FORCE_PLATFORMS:CORNERS) + GRF vector — the floor
            # rectangle and force arrow that Visual3D shows in its 3D view.
            self._plates_on = True
            self._grf_on = True
            self._plate_items = []          # plate fill/border/label GL items
            self._plate_data = None         # remembered plate dicts (for restyle)
            self._plate_diag = 500.0        # mm; drives GRF arrow scaling
            self._plate_floor_z = None      # lowest plate corner z, to seat the grid below
            self._grid_xy = (0.0, 0.0)      # remembered grid centre (set in set_markers)
            self._marker_floor_z = 0.0
            # Active scene-style palette (resolved colours).
            self._style = _DEFAULT_STYLE
            sty = SCENE_STYLES[self._style]
            self._c_plate = _rgbf(sty["plate"])
            self._c_plate_edge = _rgbf(sty["edge"])
            self._c_grf = _rgbf(sty["grf"])
            self._c_cop = _rgbf(sty["cop"])
            self._grf_list = []            # one {time, point, vector} per force plate
            self._grf_scale = 0.5          # mm drawn per Newton (auto-set in set_grf)
            self._cur_t = 0.0
            # GRF arrows: one solid 3D cylinder shaft + cone head per plate (mesh,
            # so they depth-sort instead of showing through). Pool grows on demand
            # to however many plates the lab has (2, 6, ...).
            self._grf_shafts = []
            self._grf_heads = []

            self._apply_style_colors()
            self.apply_theme()

        def set_owner(self, owner):
            self._owner = owner

        # ----- data -----
        def set_markers(self, markers, positions=None):
            self._markers = markers
            for t in self._text_items:
                self.removeItem(t)
            self._text_items = []
            if not markers:
                self._pos = None
                self._labels = []
                self._visible_mask = None
                self._scatter.setData(pos=np.zeros((0, 3)))
                self._hi_scatter.setData(pos=np.zeros((0, 3)))
                return
            self._pos = positions if positions is not None else markers["data"]
            self._labels = list(markers["labels"])
            n = self._pos.shape[0]
            self._visible_mask = np.ones(n, dtype=bool)
            self._highlight = set()
            self._hi_arr = np.zeros(n, dtype=bool)   # cached highlight mask

            data = self._pos
            finite = data[np.isfinite(data).all(axis=2)]
            if finite.size:
                lo = finite.min(axis=0)
                hi = finite.max(axis=0)
                center = (lo + hi) / 2.0
                span = float(np.linalg.norm(hi - lo)) or 1000.0
                self.opts["center"] = pg.Vector(center[0], center[1], center[2])
                self.setCameraPosition(distance=span * 1.8)
                # A generously wide floor grid so it reads as ground, not a small pad.
                gx = max(4000.0, (hi[0] - lo[0]) * 4.0)
                gy = max(4000.0, (hi[1] - lo[1]) * 4.0)
                self._grid.setSize(gx, gy)
                self._grid_xy = (center[0], center[1])
                self._marker_floor_z = float(lo[2])
                self._place_grid()

            # Pre-build text items for "always" mode.
            col = QColor(S.TEXT_PRIMARY)
            for lab in self._labels:
                ti = gl.GLTextItem(pos=np.zeros(3), text=lab, color=col, font=QFont("Arial", 9))
                ti.setVisible(False)
                self.addItem(ti)
                self._text_items.append(ti)

            self.update_frame(markers["time"][0] if len(markers["time"]) else 0.0)

        def set_positions(self, positions):
            """Swap the drawn positions (e.g. raw <-> filtered) without resetting
            the camera or labels; re-renders the current frame."""
            if self._markers is None or positions is None:
                return
            self._pos = positions
            self._render_idx()

        def update_frame(self, t_seconds, idx=None):
            m = self._markers
            if not m or self._pos is None:
                return
            if idx is None:
                t = m["time"]
                idx = int(np.searchsorted(t, float(t_seconds))) if len(t) else 0
                idx = max(0, min(len(t) - 1, idx))
            self._cur_idx = int(idx)
            self._cur_t = float(t_seconds)
            self._render_idx()
            self._render_grf()

        def _render_idx(self):
            if self._pos is None:
                return
            pts = self._pos[:, self._cur_idx, :]
            finite = np.isfinite(pts).all(axis=1)
            vis = finite & self._visible_mask
            hi_mask = self._hi_arr & vis
            main_mask = vis & ~hi_mask
            # Per-point colour array — GLScatterPlotItem's point-sprite shader
            # ignores a single colour tuple (renders white), so tile per point.
            main_pts = pts[main_mask] if main_mask.any() else np.zeros((0, 3))
            hi_pts = pts[hi_mask] if hi_mask.any() else np.zeros((0, 3))
            # When the skeleton is shown, shrink raw markers a little so they read
            # as dots ON the model rather than competing with the bone tubes.
            msize = self._marker_size * (0.85 if self._overlay_active else 1.0)
            self._scatter.setData(
                pos=main_pts, size=msize,
                color=np.tile(self._marker_color, (len(main_pts), 1)) if len(main_pts) else np.zeros((0, 4)))
            self._hi_scatter.setData(
                pos=hi_pts, size=msize,
                color=np.tile(self._hi_color, (len(hi_pts), 1)) if len(hi_pts) else np.zeros((0, 4)))
            if self._label_mode == "always":
                for i, ti in enumerate(self._text_items):
                    if vis[i]:
                        ti.setData(pos=pts[i])
                        ti.setVisible(True)
                    else:
                        ti.setVisible(False)
            else:
                for ti in self._text_items:
                    ti.setVisible(False)

        def set_visible_mask(self, mask):
            if self._markers is None:
                return
            n = self._markers["data"].shape[0]
            self._visible_mask = np.asarray(mask, dtype=bool)[:n]
            if self._visible_mask.size != n:
                self._visible_mask = np.ones(n, dtype=bool)
            self.update_frame(self._markers["time"][self._cur_idx])

        def set_highlight(self, indices):
            self._highlight = set(int(i) for i in (indices or []))
            if self._pos is not None:
                self._hi_arr = np.zeros(self._pos.shape[0], dtype=bool)
                for i in self._highlight:
                    if 0 <= i < len(self._hi_arr):
                        self._hi_arr[i] = True
            if self._markers is not None:
                self._render_idx()

        # ----- view controls -----
        def set_grid_visible(self, on):
            self._grid_on = bool(on)
            self._grid.setVisible(self._grid_on)

        def set_axes_visible(self, on):
            self._axes_on = bool(on)
            for it in self._axis_items:
                it.setVisible(self._axes_on)

        def set_label_mode(self, mode):
            self._label_mode = mode if mode in ("off", "hover", "always") else "off"
            if self._markers is not None:
                self.update_frame(self._markers["time"][self._cur_idx])

        def set_marker_size(self, key):
            self._marker_size = _SIZES.get(key, 12.0)
            self._scatter.setData(size=self._marker_size)
            self._hi_scatter.setData(size=self._marker_size)
            if self._pos is not None:
                self._render_idx()

        def set_marker_colors(self, color=None, highlight=None):
            if color:
                self._marker_color = _rgbf(color)
            if highlight:
                self._hi_color = _rgbf(highlight)
            if self._pos is not None:
                self._render_idx()

        def reset_view(self):
            # Keep the user's current viewing angle; just recentre + zoom out to
            # frame the data (set_markers re-frames distance/centre, not the angle).
            if self._markers:
                self.set_markers(self._markers)

        # ----- model overlay (bone tubes + pelvis tubes + joint spheres) -----
        def set_overlay_colors(self, bones=None, joints=None, pelvis=None):
            if bones:
                self._c_bone = _rgbf(bones)
            if joints:
                self._c_joint = _rgbf(joints)
            if pelvis:
                self._c_pelvis = _rgbf(pelvis)
            self._overlay_bones.setColor(self._c_bone)
            self._overlay_pelvis.setColor(self._c_pelvis)
            self._overlay_joints.setColor(self._c_joint)

        def set_overlay(self, points=None, segments=None, pelvis=None):
            # joint centres → spheres
            if points is not None and len(points):
                v, f = _spheres_mesh(np.asarray(points, float), self._joint_r)
                self._overlay_joints.setMeshData(vertexes=v, faces=f)
                self._overlay_joints.setColor(self._c_joint)
                self._overlay_joints.setVisible(True)
            else:
                self._overlay_joints.setVisible(False)
            # bone segments → tubes (flat list of point pairs)
            if segments:
                seg = np.asarray(segments, float).reshape(-1, 2, 3)
                v, f = _tubes_mesh(seg, self._bone_r)
                self._overlay_bones.setMeshData(vertexes=v, faces=f)
                self._overlay_bones.setColor(self._c_bone)
                self._overlay_bones.setVisible(True)
            else:
                self._overlay_bones.setVisible(False)
            # pelvis → thinner tubes
            if pelvis:
                pel = np.asarray(pelvis, float).reshape(-1, 2, 3)
                v, f = _tubes_mesh(pel, self._pelvis_r)
                self._overlay_pelvis.setMeshData(vertexes=v, faces=f)
                self._overlay_pelvis.setColor(self._c_pelvis)
                self._overlay_pelvis.setVisible(True)
            else:
                self._overlay_pelvis.setVisible(False)
            # Toggle the marker-shrink hierarchy and refresh the dot sizes.
            self._overlay_active = bool(segments or points)
            if self._pos is not None:
                self._render_idx()

        # ----- force plates + GRF vector -----
        def set_force_plates(self, plates):
            """Draw the lab's force plates as floor rectangles from their corner
            coords (FORCE_PLATFORMS:CORNERS). ``plates`` is a list of dicts with a
            ``corners`` (4,3) array, or None/empty to clear."""
            for it in self._plate_items:
                self.removeItem(it)
            self._plate_items = []
            self._plate_data = plates
            self._plate_diag = 500.0
            self._plate_floor_z = None
            if not plates:
                self._place_grid()
                return
            faces = np.array([[0, 1, 2], [0, 2, 3]])
            fill = (*self._c_plate[:3], 1.0)   # opaque
            diags = []
            for idx, plate in enumerate(plates):
                c = np.asarray(plate.get("corners"), dtype=float)
                if c.shape != (4, 3) or not np.isfinite(c).all():
                    continue
                mesh = gl.GLMeshItem(vertexes=c, faces=faces, faceColors=None,
                                     color=fill, smooth=False, drawEdges=False)
                mesh.setGLOptions("opaque")
                mesh.setVisible(self._plates_on)
                self.addItem(mesh)
                self._plate_items.append(mesh)
                border = gl.GLLinePlotItem(
                    pos=np.vstack([c, c[0]]), color=self._c_plate_edge, width=1.6, antialias=False)
                border.setGLOptions("opaque")   # depth-sort so it can't show through other items
                border.setVisible(self._plates_on)
                self.addItem(border)
                self._plate_items.append(border)
                self._add_plate_label(idx, c, plate.get("R"))
                diags.append(float(np.linalg.norm(c[0] - c[2])))
                z_min = float(np.min(c[:, 2]))
                self._plate_floor_z = z_min if self._plate_floor_z is None \
                    else min(self._plate_floor_z, z_min)
            if diags:
                self._plate_diag = float(np.mean(diags))
            # Drop the floor grid just under the (now opaque) plates so it doesn't
            # show through / float above them.
            self._place_grid()

        def _add_plate_label(self, idx, c, R):
            """An 'FP1'/'FP2' tag projected flat onto the plate surface (lying in
            the plate plane), mirrored so it reads upright on screen."""
            if not hasattr(gl, "GLImageItem"):
                return
            sty = SCENE_STYLES.get(self._style, SCENE_STYLES[_DEFAULT_STYLE])
            arr = _text_image(f"FP{idx + 1}", sty["plate_label"])    # (H, W, 4)
            arr = arr[:, ::-1, :]                                    # mirror → reads upright on the floor
            arr = np.ascontiguousarray(arr.transpose(1, 0, 2))       # (W, H, 4) for GLImageItem
            W, H = arr.shape[0], arr.shape[1]
            if R is not None:
                R = np.asarray(R, float)
                ex, ey = R[:, 0], R[:, 1]
            else:
                ex = c[3] - c[0]; ex /= (np.linalg.norm(ex) or 1.0)
                ey = c[1] - c[0]; ey /= (np.linalg.norm(ey) or 1.0)
            if np.cross(ex, ey)[2] < 0:     # keep it facing up
                ey = -ey
            label_h = max(45.0, 0.09 * float(np.linalg.norm(c[0] - c[2])))
            label_w = label_h * (W / H)
            sx, sy = label_w / W, label_h / H
            origin = c.mean(axis=0)
            anchor = origin - ex * (label_w / 2.0) - ey * (label_h / 2.0)
            anchor[2] = float(c[:, 2].max()) + 3.0
            M = np.eye(4)
            M[:3, 0] = ex * sx
            M[:3, 1] = ey * sy
            M[:3, 2] = np.array([0.0, 0.0, 1.0])
            M[:3, 3] = anchor
            item = gl.GLImageItem(arr)
            item.setGLOptions("translucent")
            item.setTransform(QMatrix4x4(*M.flatten().tolist()))
            item.setVisible(self._plates_on)
            self.addItem(item)
            self._plate_items.append(item)

        def _place_grid(self):
            """Seat the floor grid at the marker floor, or just below the plates
            when force plates are present (avoids the grid showing over them)."""
            z = self._marker_floor_z
            if self._plate_floor_z is not None:
                # Well below the opaque plates so it can't z-fight / bleed through.
                z = min(z, self._plate_floor_z) - 25.0
            self._grid.resetTransform()
            self._grid.translate(self._grid_xy[0], self._grid_xy[1], z)

        def set_grf(self, grf):
            """Store one GRF timeline per force plate and auto-scale arrows so the
            peak is ~90% of the plate size. ``grf`` is a list of dicts (or a single
            dict) with ``time``/``point``/``vector`` arrays, or None to clear."""
            if not grf:
                self._grf_list = []
                self._hide_arrows()
                return
            grfs = grf if isinstance(grf, (list, tuple)) else [grf]
            self._grf_list = [{
                "time": np.asarray(g["time"], float),
                "point": np.asarray(g["point"], float),
                "vector": np.asarray(g["vector"], float),
            } for g in grfs if g]
            # One shared scale (across all plates) so arrow lengths are comparable.
            mags = [np.linalg.norm(g["vector"], axis=1) for g in self._grf_list]
            allm = np.concatenate(mags) if mags else np.array([])
            allm = allm[np.isfinite(allm)]
            peak = float(np.percentile(allm, 95)) if allm.size else 0.0
            self._grf_scale = (0.9 * self._plate_diag) / peak if peak > 1e-6 else 0.5
            self._ensure_grf_pool(len(self._grf_list))
            self._render_grf()

        def _ensure_grf_pool(self, n):
            while len(self._grf_shafts) < n:
                shaft = gl.GLMeshItem(vertexes=np.zeros((3, 3)), faces=np.array([[0, 1, 2]]),
                                      smooth=True, drawEdges=False)
                shaft.setGLOptions("opaque"); shaft.setVisible(False)
                self.addItem(shaft); self._grf_shafts.append(shaft)
                head = gl.GLMeshItem(vertexes=np.zeros((3, 3)), faces=np.array([[0, 1, 2]]),
                                     smooth=True, drawEdges=False)
                head.setGLOptions("opaque"); head.setVisible(False)
                self.addItem(head); self._grf_heads.append(head)

        def _hide_arrows(self):
            for it in self._grf_shafts + self._grf_heads:
                it.setVisible(False)

        def _render_grf(self):
            if not self._grf_on or not self._grf_list:
                self._hide_arrows()
                return
            for j in range(len(self._grf_shafts)):
                shaft, head = self._grf_shafts[j], self._grf_heads[j]
                if j >= len(self._grf_list):
                    shaft.setVisible(False); head.setVisible(False)
                    continue
                g = self._grf_list[j]
                t = g["time"]
                if len(t) == 0:
                    shaft.setVisible(False); head.setVisible(False)
                    continue
                i = max(0, min(len(t) - 1, int(np.searchsorted(t, self._cur_t))))
                p0, v = g["point"][i], g["vector"][i]
                if not (np.isfinite(p0).all() and np.isfinite(v).all()):
                    shaft.setVisible(False); head.setVisible(False)
                    continue
                self._draw_arrow(shaft, head, p0, p0 + v * self._grf_scale)

        def _draw_arrow(self, shaft, head, start, end):
            d = np.asarray(end, dtype=float) - np.asarray(start, dtype=float)
            length = float(np.linalg.norm(d))
            if length < 1e-6:
                shaft.setVisible(False); head.setVisible(False)
                return
            direction = d / length
            head_len = min(max(0.18 * length, 28.0), 70.0, 0.5 * length)
            neck = np.asarray(end, float) - direction * head_len
            shaft_r = max(7.0, 0.014 * self._plate_diag)
            sv, sf = _cylinder_mesh(np.asarray(start, float), neck, shaft_r)
            shaft.setMeshData(vertexes=sv, faces=sf)
            shaft.setColor(self._c_grf)
            shaft.setVisible(True)
            hv, hf = _cone_mesh(np.asarray(end, float), neck, head_len * 0.42)
            head.setMeshData(vertexes=hv, faces=hf)
            head.setColor(self._c_grf)
            head.setVisible(True)

        def set_force_plates_visible(self, on):
            self._plates_on = bool(on)
            for it in self._plate_items:
                it.setVisible(self._plates_on)

        def set_grf_visible(self, on):
            self._grf_on = bool(on)
            self._render_grf()

        # ----- scene style + theme -----
        def _apply_style_colors(self):
            """Apply the active scene-style palette to every element the style
            owns (markers, skeleton, plates, GRF, grid). Appearance settings may
            still override marker/overlay colours afterwards."""
            sty = SCENE_STYLES.get(self._style, SCENE_STYLES[_DEFAULT_STYLE])
            self._marker_color = _rgbf(sty["marker"])
            self._hi_color = _rgbf(sty["highlight"])
            self._c_bone = _rgbf(sty["bone"])
            self._c_joint = _rgbf(sty["joint"])
            self._c_pelvis = _rgbf(sty["pelvis"])
            self._c_plate = _rgbf(sty["plate"])
            self._c_plate_edge = _rgbf(sty["edge"])
            self._c_grf = _rgbf(sty["grf"])
            self._c_cop = _rgbf(sty["cop"])
            # GLGridItem.setColor routes through mkColor (0-255), so pass a QColor.
            gc = QColor(sty["grid"]); gc.setAlpha(140)
            self._grid.setColor(gc)
            self._overlay_bones.setColor(self._c_bone)
            self._overlay_pelvis.setColor(self._c_pelvis)
            self._overlay_joints.setColor(self._c_joint)
            if self._pos is not None:
                self._render_idx()
            self._render_grf()

        def apply_theme(self):
            self.setBackgroundColor(QColor(S.GRAPH_BG))
            self._apply_style_colors()
            col = QColor(S.TEXT_PRIMARY)
            for ti in self._text_items:
                ti.setData(color=col)

        # ----- hover marker name -----
        def _screen_positions(self):
            m = self._markers
            if not m or self._pos is None:
                return None
            pts = self._pos[:, self._cur_idx, :]
            vp = self.getViewport()
            mvp = self.projectionMatrix(vp, vp) * self.viewMatrix()
            w, h = vp[2], vp[3]
            out = np.full((pts.shape[0], 2), np.nan)
            for i, p in enumerate(pts):
                if not np.isfinite(p).all():
                    continue
                c = mvp.map(QVector4D(float(p[0]), float(p[1]), float(p[2]), 1.0))
                cw = c.w()
                if cw == 0:
                    continue
                out[i] = ((c.x() / cw * 0.5 + 0.5) * w, (1 - (c.y() / cw * 0.5 + 0.5)) * h)
            return out

        # ----- mouse: left=orbit, middle/right-drag=pan, right-click=menu, hover=name -----
        def mouseDoubleClickEvent(self, ev):
            # Double-click anywhere recentres the camera on the data.
            self.reset_view()
            ev.accept()

        def mousePressEvent(self, ev):
            self.mousePos = ev.position()
            if ev.button() == Qt.MouseButton.RightButton:
                self._right_dragging = True
                self._right_moved = False
                ev.accept()
            else:
                if ev.button() == Qt.MouseButton.LeftButton:
                    self._left_pressed = True
                    self._left_moved = False
                super().mousePressEvent(ev)

        def mouseReleaseEvent(self, ev):
            if ev.button() == Qt.MouseButton.RightButton and self._right_dragging:
                self._right_dragging = False
                if not self._right_moved:
                    self._show_controls_menu(ev.globalPosition().toPoint())
                ev.accept()
                return
            if ev.button() == Qt.MouseButton.LeftButton and self._left_pressed:
                self._left_pressed = False
                if not self._left_moved:
                    # A click (not an orbit drag): pick the nearest marker.
                    i = self._pick_marker(ev.position())
                    if i is not None:
                        self.marker_picked.emit(i, ev.globalPosition().toPoint())
                        ev.accept()
                        return
            super().mouseReleaseEvent(ev)

        def mouseMoveEvent(self, ev):
            if self._right_dragging and (ev.buttons() & Qt.MouseButton.RightButton):
                diff = ev.position() - self.mousePos
                self.mousePos = ev.position()
                if abs(diff.x()) + abs(diff.y()) > 1:
                    self._right_moved = True
                self.pan(diff.x(), diff.y(), 0, relative="view-upright")
                ev.accept()
                return
            if self._left_pressed and (ev.buttons() & Qt.MouseButton.LeftButton):
                d = ev.position() - self.mousePos
                if abs(d.x()) + abs(d.y()) > 2:
                    self._left_moved = True
            super().mouseMoveEvent(ev)

        def _pick_marker(self, pos):
            """Index of the visible marker nearest the cursor (within ~16px), else None."""
            sp = self._screen_positions()
            if sp is None:
                return None
            dpr = self.devicePixelRatioF()
            mx, my = pos.x() * dpr, pos.y() * dpr
            best, best_d = None, 16.0 * dpr
            for i, (sx, sy) in enumerate(sp):
                if not np.isfinite(sx) or (self._visible_mask is not None and not self._visible_mask[i]):
                    continue
                d = ((sx - mx) ** 2 + (sy - my) ** 2) ** 0.5
                if d < best_d:
                    best_d, best = d, i
            return best
            if self._label_mode != "hover" or not self._markers or ev.buttons():
                return
            sp = self._screen_positions()
            if sp is None:
                return
            dpr = self.devicePixelRatioF()
            mx, my = ev.position().x() * dpr, ev.position().y() * dpr
            best, best_d = None, 16.0 * dpr
            for i, (sx, sy) in enumerate(sp):
                if not np.isfinite(sx) or not self._visible_mask[i]:
                    continue
                d = ((sx - mx) ** 2 + (sy - my) ** 2) ** 0.5
                if d < best_d:
                    best_d, best = d, i
            if best is not None:
                QToolTip.showText(ev.globalPosition().toPoint(), self._labels[best], self)
            else:
                QToolTip.hideText()

        # ----- right-click controls menu -----
        def _show_controls_menu(self, global_pos):
            menu = QMenu(self)
            a_grid = menu.addAction("Floor grid")
            a_grid.setCheckable(True)
            a_grid.setChecked(self._grid_on)
            a_grid.toggled.connect(self.set_grid_visible)
            a_axes = menu.addAction("Axes")
            a_axes.setCheckable(True)
            a_axes.setChecked(self._axes_on)
            a_axes.toggled.connect(self.set_axes_visible)

            if self._plate_items:
                a_plates = menu.addAction("Force plates")
                a_plates.setCheckable(True)
                a_plates.setChecked(self._plates_on)
                a_plates.toggled.connect(self.set_force_plates_visible)
            if self._grf_list:
                a_grf = menu.addAction("GRF vector")
                a_grf.setCheckable(True)
                a_grf.setChecked(self._grf_on)
                a_grf.toggled.connect(self.set_grf_visible)

            label_menu = menu.addMenu("Marker labels")
            for mode, text in [("off", "Off"), ("hover", "On hover"), ("always", "Always")]:
                act = label_menu.addAction(text)
                act.setCheckable(True)
                act.setChecked(self._label_mode == mode)
                act.triggered.connect(lambda _=False, mm=mode: self.set_label_mode(mm))

            size_menu = menu.addMenu("Marker size")
            for key in ("S", "M", "L"):
                act = size_menu.addAction(key)
                act.setCheckable(True)
                act.setChecked(abs(self._marker_size - _SIZES[key]) < 0.1)
                act.triggered.connect(lambda _=False, k=key: self.set_marker_size(k))

            menu.addAction("Reset view", self.reset_view)

            if self._owner is not None and hasattr(self._owner, "set_markers3d_side"):
                menu.addSeparator()
                pos_menu = menu.addMenu("Position")
                cur = getattr(self._owner, "_markers3d_side", "right")
                for side, text in [("left", "Left"), ("right", "Right")]:
                    act = pos_menu.addAction(text)
                    act.setCheckable(True)
                    act.setChecked(cur == side)
                    act.triggered.connect(lambda _=False, s=side: self._owner.set_markers3d_side(s))

            menu.exec(global_pos)


def make_marker_view(parent=None):
    """Return a 3D MarkerView, or a placeholder widget if OpenGL is unavailable."""
    if GL_AVAILABLE:
        try:
            return MarkerView(parent)
        except Exception:
            return _FallbackView(parent)
    return _FallbackView(parent)
