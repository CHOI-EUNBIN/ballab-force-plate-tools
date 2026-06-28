"""Label-based biomechanical kinematic model (pure numpy, no Qt).

A lightweight version of the Visual3D/OpenSim marker pipeline:
    marker set  ->  joint centres  ->  segments  ->  joint angles

Three layers (the reusable, JSON-serialisable model template):
  * joints   = [{name, medial, lateral, cluster:[>=3 labels]}]
      A STATIC calibration trial has medial markers, so JC = midpoint(medial,
      lateral), stored as a rigid offset of a tracking cluster. DYNAMIC trials
      lack medial markers; each JC is reconstructed per frame by fitting the
      cluster's rigid transform (Kabsch/SVD) and applying the offset.
  * segments = [{name, proximal, distal, frame?}]
      vector distal-proximal; each point = a JC name or marker label. An
      optional ``frame`` builds a segment coordinate system (SCS) for JCS
      angles -- see ``compute_frames``. Omitting it keeps legacy behaviour.
  * angles   = [{name, segment_a, segment_b, mode?, sequence?}]
      ``mode`` absent/"vector" -> unsigned angle between the two segment
      vectors (legacy). ``mode`` "jcs" -> signed Grood-Suntay/Cardan 3-component
      angle (needs both segments to declare a ``frame``); ``sequence`` (default
      "xyz") sets the Cardan/Euler order ("yxy" for the shoulder, etc.).

Marker labels change between trials, so the model is label-based: ``label_map``
remaps model labels to a trial's actual labels (e.g. {"RFSHANK": "RFSHKANK"}).

Marker container: ``markers = {labels:[...], data:(M,F,3), time:(F,), ...}``.
"""

import difflib
import logging

import numpy as np

log = logging.getLogger(__name__)


def kabsch(P_ref, P_cur):
    """Rigid transform (R, t) mapping P_ref -> P_cur, both (k, 3). Rotation
    (no reflection) via SVD."""
    P_ref = np.asarray(P_ref, float)
    P_cur = np.asarray(P_cur, float)
    cr = P_ref.mean(axis=0)
    cc = P_cur.mean(axis=0)
    H = (P_ref - cr).T @ (P_cur - cc)
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    t = cc - R @ cr
    return R, t


def cluster_pose_per_frame(cluster_xyz, P_ref):
    """Per-frame rigid rotation of a marker cluster relative to a reference
    configuration ``P_ref`` (k,3), vectorised over frames (batched Kabsch/SVD).

    ``cluster_xyz`` = (k,F,3) cluster-marker world trajectories. Returns
    ``R`` (F,3,3): the rotation mapping the (centroid-removed) reference cluster
    into frame f, i.e. ``R_f @ (P_ref - mean(P_ref)) ~ P_f - mean(P_f)``. A
    cluster-LOCAL vector ``v`` is therefore carried to world frame f by ``R_f @ v``.

    Frames missing ANY cluster marker are returned as NaN. This is the same
    rigid-body fit as ``MarkerModel._reconstruct_joint`` (which also applies a
    translation to place a joint centre); here we keep only the rotation, because
    a cluster-embedded ML AXIS is direction-only (translation-invariant).
    """
    cluster_xyz = np.asarray(cluster_xyz, float)            # (k, F, 3)
    P_ref = np.asarray(P_ref, float)
    k, F, _ = cluster_xyz.shape
    R = np.full((F, 3, 3), np.nan)
    vis = np.isfinite(cluster_xyz).all(axis=2).all(axis=0)  # (F,) all markers ok
    if not vis.any():
        return R
    P = np.transpose(cluster_xyz[:, vis, :], (1, 0, 2))     # (Nf, k, 3)
    cr = P_ref.mean(axis=0)
    cc = P.mean(axis=1)                                     # (Nf, 3)
    ref_c = P_ref - cr                                      # (k, 3)
    cur_c = P - cc[:, None, :]                              # (Nf, k, 3)
    H = np.einsum('ki,nkj->nij', ref_c, cur_c)             # (Nf, 3, 3)
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(np.matmul(np.transpose(Vt, (0, 2, 1)),
                                        np.transpose(U, (0, 2, 1)))))
    D = np.zeros((d.shape[0], 3, 3))
    D[:, 0, 0] = 1.0
    D[:, 1, 1] = 1.0
    D[:, 2, 2] = d
    Rf = np.matmul(np.transpose(Vt, (0, 2, 1)),
                   np.matmul(D, np.transpose(U, (0, 2, 1))))  # (Nf, 3, 3)
    R[vis] = Rf
    return R


def angle_between(va, vb):
    """Angle (degrees) between two (F,3) vector trajectories; NaN-safe -> (F,)."""
    va = np.asarray(va, float)
    vb = np.asarray(vb, float)
    na = np.linalg.norm(va, axis=1)
    nb = np.linalg.norm(vb, axis=1)
    denom = na * nb
    with np.errstate(invalid="ignore", divide="ignore"):
        cos = np.sum(va * vb, axis=1) / denom
    cos = np.clip(cos, -1.0, 1.0)
    ang = np.degrees(np.arccos(cos))
    ang[~np.isfinite(denom) | (denom == 0)] = np.nan
    return ang


# --------------------------------------------------------------------------
# Segment coordinate systems (SCS) + JCS Cardan joint angles (Visual3D / ISB)
# --------------------------------------------------------------------------
#
# Each rigid segment carries an orthonormal coordinate system (a (F,3,3)
# rotation matrix whose COLUMNS are the segment axes expressed in the world /
# lab frame). We follow the Visual3D / ISB (Wu et al. 2002, 2005) convention:
#
#   * z (column 2) = LONGITUDINAL axis, pointing DISTAL -> PROXIMAL (up the limb).
#   * x (column 0) = MEDIO-LATERAL axis, pointing to the subject's RIGHT (+).
#   * y (column 1) = ANTERO-POSTERIOR axis, pointing ANTERIOR (+), = z x x.
#
# The frame is built from two points (a distal origin and a proximal point that
# define z) plus a third "plane" point that fixes the frontal plane; the
# remaining two axes follow from cross products. ``side`` ("R"/"L") flips the ML
# axis so +x is anatomical-right (i.e. lateral on the right, medial on the left)
# and the resulting clinical angle signs are mirror-consistent across legs.

def _unit_rows(v):
    """Normalise each row of a (F,3) array; zero/NaN rows -> NaN. Vectorised."""
    v = np.asarray(v, float)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = v / n
    out[~np.isfinite(n[..., 0]) | (n[..., 0] == 0)] = np.nan
    return out


def segment_frame(origin, proximal_point, plane_point, side="R"):
    """Build a segment coordinate system per frame, returning (R, origin).

    Parameters (each (F,3) world-frame trajectories)
      origin          : distal endpoint -> frame origin.
      proximal_point  : proximal endpoint; defines the longitudinal z axis
                        (origin -> proximal_point, i.e. distal -> proximal).
      plane_point     : a third non-collinear point (a marker or joint centre)
                        used to fix the frontal/sagittal plane.
      side            : "R" or "L"; flips the ML (x) axis so +x is the subject's
                        anatomical right for both legs.

    Returns
      R      : (F,3,3) rotation matrix; columns = [e_ml, e_ap, e_long] (x,y,z)
               in world coordinates. Orthonormal, right-handed (det +1).
      origin : (F,3) the frame origin (= ``origin`` input), for convenience.

    NaN-safe: any frame with a missing/collinear marker yields an all-NaN R.
    """
    origin = np.asarray(origin, float)
    proximal_point = np.asarray(proximal_point, float)
    plane_point = np.asarray(plane_point, float)
    F = origin.shape[0]

    e_long = _unit_rows(proximal_point - origin)            # z: distal -> proximal
    v_plane = plane_point - origin                          # toward the plane point

    # Temporary AP axis = z x v_plane, then re-orthogonalise.  The sign of the
    # ML axis is set so +x points to the subject's right.  For a right segment
    # the lateral marker (knee/ankle 'L' marker, or RASIS) lies to the right; we
    # encode that by choosing e_ml then flipping by side.
    e_ap_tmp = np.cross(e_long, v_plane)                    # ~ anterior (or post)
    e_ap_tmp = _unit_rows(e_ap_tmp)
    e_ml = _unit_rows(np.cross(e_ap_tmp, e_long))           # right-handed x = y x z
    if str(side).upper().startswith("L"):
        e_ml = -e_ml
    # Recompute AP so (x,y,z) is exactly right-handed after the side flip.
    e_ap = np.cross(e_long, e_ml)                           # y = z x x

    R = np.stack([e_ml, e_ap, e_long], axis=-1)             # (F,3,3), columns = axes
    # If any axis is undefined (missing marker or a collinear plane point), make
    # the WHOLE frame NaN so downstream JCS math is unambiguously NaN-safe.
    bad = ~np.isfinite(R).all(axis=(1, 2))
    R[bad] = np.nan
    return R, origin


def segment_frame_from_ml(origin, proximal_point, ml_dir, side="R"):
    """Build a segment coordinate system per frame from the LONGITUDINAL axis and
    an explicit MEDIO-LATERAL axis direction (instead of a frontal-plane point).

    This is the CAST / cluster-embedded analogue of ``segment_frame``: rather than
    a single body-surface plane marker (whose soft-tissue wobble swings the frontal
    plane), the ML axis is supplied directly -- typically an anatomical ML axis
    defined once in a static trial (the medial-lateral marker line) and transported
    rigidly per frame by the tracking cluster's pose (Cappozzo 1995). The frame
    therefore inherits the cluster's stability, not a lone marker's noise.

    Same column convention as ``segment_frame`` (columns = [e_ml, e_ap, e_long],
    i.e. x=ML right, y=AP anterior, z=long distal->proximal). The supplied ML is
    re-orthogonalised against the long axis (Gram-Schmidt) so the result is exactly
    orthonormal even if the transported ML drifted slightly off-perpendicular.

    Parameters (each (F,3) world-frame trajectories)
      origin          : distal endpoint -> frame origin.
      proximal_point  : proximal endpoint; defines the long (z) axis
                        (origin -> proximal_point, distal -> proximal).
      ml_dir          : the medio-lateral axis direction in world coordinates
                        (need NOT be a unit vector nor exactly perpendicular to z).
                        For a RIGHT segment +ml points to the subject's right
                        (lateral); ``side`` flips it on the left so +x stays
                        anatomical-right for both legs (mirror-consistent signs).
      side            : "R" or "L".

    Returns (R, origin) with R (F,3,3) columns = [e_ml, e_ap, e_long]. NaN-safe:
    a missing/zero ML or long axis (or ML collinear with long) yields an all-NaN R.
    """
    origin = np.asarray(origin, float)
    proximal_point = np.asarray(proximal_point, float)
    ml_dir = np.asarray(ml_dir, float)

    e_long = _unit_rows(proximal_point - origin)            # z: distal -> proximal
    ml_u = _unit_rows(ml_dir)
    if str(side).upper().startswith("L"):
        ml_u = -ml_u
    # Orthogonalise ML against the long axis, then AP = long x ml (right-handed).
    proj = np.sum(ml_u * e_long, axis=1, keepdims=True)
    e_ml = _unit_rows(ml_u - proj * e_long)
    e_ap = np.cross(e_long, e_ml)                           # y = z x x

    R = np.stack([e_ml, e_ap, e_long], axis=-1)             # (F,3,3), columns = axes
    bad = ~np.isfinite(R).all(axis=(1, 2))
    R[bad] = np.nan
    return R, origin


def pelvis_frame(rasis, lasis, mid_psis):
    """Build the pelvis segment coordinate system per frame (ISB / Plug-in-Gait).

    The pelvis has no superior marker, so its SCS cannot use the generic
    ``segment_frame`` (which makes z = origin->proximal). Instead we build the
    ISB CODA/Plug-in-Gait pelvis frame from the ASIS pair and the mid-PSIS, then
    map it onto THIS module's column convention (x=ML, y=AP, z=long) so that a
    HIP JCS = jcs_angles(R_pelvis, R_thigh) is ~0 in neutral standing.

    Parameters (each (F,3) world-frame trajectories)
      rasis, lasis : right/left ASIS markers.
      mid_psis     : mid-PSIS (or sacrum) point.

    Returns (R, origin) with R (F,3,3); columns = [e_ml, e_ant, e_sup] mapped to
    (x, y, z). e_ml -> subject right (RASIS-LASIS), e_ant -> anterior,
    e_sup -> superior. origin = mid-ASIS. NaN-safe (missing/collinear -> NaN).

    Note: z (the longitudinal column) is the SUPERIOR axis here, matching a
    standing thigh whose z points proximally (up); x/y match ML/AP so all three
    HIP components are ~0 in neutral.
    """
    rasis = np.asarray(rasis, float)
    lasis = np.asarray(lasis, float)
    mid_psis = np.asarray(mid_psis, float)
    mid_asis = (rasis + lasis) / 2.0

    e_ml = _unit_rows(rasis - lasis)               # x: +subject-right
    ant_tmp = mid_asis - mid_psis                  # roughly anterior
    e_sup = _unit_rows(np.cross(e_ml, ant_tmp))    # z: up (ML x anterior)
    e_ant = _unit_rows(np.cross(e_sup, e_ml))      # y: anterior (orthonormal)

    R = np.stack([e_ml, e_ant, e_sup], axis=-1)    # columns = (x=ML, y=AP, z=sup)
    bad = ~np.isfinite(R).all(axis=(1, 2))
    R[bad] = np.nan
    return R, mid_asis


def thorax_frame(ij, c7, px, t8):
    """Build the thorax/trunk segment coordinate system per frame (ISB; Wu et al.
    2005, shoulder/elbow/wrist recommendation).

    The thorax has no single proximal joint centre, so (like the pelvis) it gets
    its own builder rather than the generic ``segment_frame``. ISB definition:

      * y (superior) = unit( mid(IJ, C7) - mid(PX, T8) ), pointing UP.
      * z (to the subject's RIGHT) = unit( y x (anterior-ish in the IJ/C7/PX/T8
        plane) ) -- built so +z is the subject's right.
      * x (anterior) = y x z (orthonormal).

    Mapped onto THIS module's column convention (x=ML right, y=AP anterior,
    z=long up) so that a SHOULDER/ELBOW JCS is well-behaved in neutral standing.

    Parameters (each (F,3) world trajectories)
      ij : incisura jugularis / suprasternal notch (IJ, a.k.a. CLAV/STRN-top).
      c7 : 7th cervical spinous process.
      px : xiphoid process (PX), lower sternum.
      t8 : 8th thoracic spinous process.

    Returns (R, origin); R (F,3,3) columns = (x=ML, y=AP, z=sup); origin = IJ.
    NaN-safe (missing/collinear -> NaN).
    """
    ij = np.asarray(ij, float)
    c7 = np.asarray(c7, float)
    px = np.asarray(px, float)
    t8 = np.asarray(t8, float)
    mid_up = (ij + c7) / 2.0          # upper thorax (mid of IJ & C7)
    mid_lo = (px + t8) / 2.0          # lower thorax (mid of PX & T8)

    e_sup = _unit_rows(mid_up - mid_lo)          # z: up (inferior -> superior)
    ant_tmp = ij - c7                            # anterior-ish (front IJ vs back C7)
    e_ml = _unit_rows(np.cross(ant_tmp, e_sup))  # x: subject right (anterior x up)
    e_ant = _unit_rows(np.cross(e_sup, e_ml))    # y: anterior (orthonormal)

    R = np.stack([e_ml, e_ant, e_sup], axis=-1)  # columns = (x=ML, y=AP, z=sup)
    bad = ~np.isfinite(R).all(axis=(1, 2))
    R[bad] = np.nan
    return R, ij


def _decompose_cardan(R_rel, sequence="xyz"):
    """Decompose a batch of rotation matrices into three Cardan/Euler angles.

    ``R_rel`` : (F,3,3) relative rotation (distal expressed in proximal frame),
    i.e. R_rel = R_prox^T @ R_dist, so a column vector in the distal frame maps
    to the proximal frame by R_rel @ v.

    ``sequence`` : a 3-char string of axes, e.g. "xyz" (Cardan) or "yxy" (Euler,
    shoulder).  The rotation is interpreted as the INTRINSIC sequence
    R_rel = Rot(a0, seq[0]) @ Rot(a1, seq[1]) @ Rot(a2, seq[2]).

    Returns (F,3) angles in DEGREES for (seq[0], seq[1], seq[2]).  Gimbal-lock
    frames (middle axis at its singular value) return the well-defined sum/
    difference on the first axis with the third set to 0.  NaN-safe.
    """
    R = np.asarray(R_rel, float)
    if R.ndim == 2:
        R = R[None]
    seq = sequence.lower()
    if len(seq) != 3 or any(c not in "xyz" for c in seq):
        raise ValueError(f"bad rotation sequence: {sequence!r}")

    idx = {"x": 0, "y": 1, "z": 2}
    i, j, k = idx[seq[0]], idx[seq[1]], idx[seq[2]]
    repeated = seq[0] == seq[2]
    # +1 when (i, j, k) is an even (cyclic) permutation of (0,1,2), else -1.
    s = 1.0 if ((j - i) % 3) == 1 else -1.0
    F = R.shape[0]
    a0 = np.full(F, np.nan)
    a1 = np.full(F, np.nan)
    a2 = np.full(F, np.nan)
    good = np.isfinite(R).all(axis=(1, 2))
    if good.any():
        M = R[good]
        if repeated:
            # Proper Euler (e.g. y x y).  l = the axis not in {i, j}.
            #   R = Rot(a0,i) Rot(a1,j) Rot(a0-axis again) ... intrinsic.
            # Standard factorisation:
            #   a1 = atan2( sqrt(R[j,i]^2 + R[l,i]^2), R[i,i] )
            #   a0 = atan2( R[j,i],  -s*R[l,i] )
            #   a2 = atan2( R[i,j],   s*R[i,l] )
            l = 3 - i - j
            sy = np.sqrt(M[:, j, i] ** 2 + M[:, l, i] ** 2)
            b1 = np.arctan2(sy, M[:, i, i])
            b0 = np.empty(M.shape[0])
            b2 = np.empty(M.shape[0])
            singular = sy < 1e-9
            ns = ~singular
            b0[ns] = np.arctan2(M[:, j, i][ns], -s * M[:, l, i][ns])
            b2[ns] = np.arctan2(M[:, i, j][ns], s * M[:, i, l][ns])
            # Gimbal lock: a1 = 0 or pi; fold a2 into a0.
            b0[singular] = np.arctan2(-s * M[:, l, j][singular], M[:, j, j][singular])
            b2[singular] = 0.0
        else:
            # Cardan / Tait-Bryan (e.g. x y z), intrinsic R = Rot(a0,i)Rot(a1,j)Rot(a2,k):
            #   a1 = arcsin( s * R[i,k] )
            #   a0 = atan2( -s*R[j,k], R[k,k] )
            #   a2 = atan2( -s*R[i,j], R[i,i] )
            sin_a1 = np.clip(s * M[:, i, k], -1.0, 1.0)
            b1 = np.arcsin(sin_a1)
            b0 = np.empty(M.shape[0])
            b2 = np.empty(M.shape[0])
            singular = np.abs(sin_a1) > 1.0 - 1e-9
            ns = ~singular
            b0[ns] = np.arctan2(-s * M[:, j, k][ns], M[:, k, k][ns])
            b2[ns] = np.arctan2(-s * M[:, i, j][ns], M[:, i, i][ns])
            # Gimbal lock: middle axis +-90 deg; fold a2 into a0.
            b0[singular] = np.arctan2(s * M[:, k, j][singular], M[:, j, j][singular])
            b2[singular] = 0.0
        a0[good] = b0
        a1[good] = b1
        a2[good] = b2

    out = np.degrees(np.stack([a0, a1, a2], axis=-1))
    return out[0] if R_rel.ndim == 2 else out


def jcs_angles(R_prox, R_dist, sequence="xyz"):
    """Three-component joint angle from two segment coordinate systems.

    R_prox, R_dist : (F,3,3) proximal & distal SCS rotation matrices (columns =
    axes in world). Relative rotation R_rel = R_prox^T @ R_dist describes the
    distal segment in the proximal frame; it is decomposed by ``sequence`` into
    three signed angles (degrees), (F,3). NaN-safe & vectorised.

    With the SCS convention here (x=ML right, y=AP anterior, z=long up) and the
    default "xyz" sequence the components are, clinically:
      [0] x  -> flexion(+)/extension(-)        (sagittal, rotation about ML)
      [1] y  -> ab(+)/adduction(-)             (frontal, rotation about AP)
      [2] z  -> internal(+)/external(-) rot.   (transverse, about long axis)
    (Exact sign/plane labels depend on segment construction and the chosen
    sequence; see the module docstring.)
    """
    Rp = np.asarray(R_prox, float)
    Rd = np.asarray(R_dist, float)
    R_rel = np.einsum('fki,fkj->fij', Rp, Rd)   # R_prox^T @ R_dist, batched
    return _decompose_cardan(R_rel, sequence)


class MarkerModel:
    def __init__(self, joints=None, segments=None, angles=None, name=""):
        self.name = name
        self.joints = [dict(j) for j in (joints or [])]
        self.segments = [dict(s) for s in (segments or [])]
        self.angles = [dict(a) for a in (angles or [])]
        self._calib = {}   # joint name -> {cluster, P_ref(k,3), jc_local(3)}
        # segment name -> {cluster, P_ref(k,3), ml_local(3)} for cluster-embedded
        # (CAST) ML frames, populated from the static trial in ``calibrate``.
        self._frame_calib = {}

    # ----- serialisation -----
    def to_dict(self):
        return {"name": self.name, "joints": self.joints,
                "segments": self.segments, "angles": self.angles}

    @classmethod
    def from_dict(cls, d):
        return cls(joints=d.get("joints"), segments=d.get("segments"),
                   angles=d.get("angles"), name=d.get("name", ""))

    # ----- label resolution -----
    @staticmethod
    def _index(markers, label, label_map=None):
        actual = (label_map or {}).get(label, label)
        try:
            return markers["labels"].index(actual)
        except ValueError:
            raise KeyError(f"label not found in trial: {label} (-> {actual})")

    def joint_names(self):
        return {j["name"] for j in self.joints}

    def pelvis_labels(self):
        """Pelvis landmark labels (for drawing the pelvis body), gathered from any
        hip joints: an ordered ring [RASIS, LASIS, LPSIS, RPSIS/sacrum] when
        available. Empty when the model has no hip joint."""
        for j in self.joints:
            if j.get("method") != "hip":
                continue
            ring = [j.get("asis_r"), j.get("asis_l"),
                    j.get("psis_l"), j.get("psis_r") or j.get("sacrum")]
            return [lab for lab in ring if lab]
        return []

    def cluster_labels(self):
        """Marker labels needed in a DYNAMIC trial (clusters + any raw-marker
        segment endpoints; medial markers are NOT needed)."""
        jn = self.joint_names()
        labs = set()
        for j in self.joints:
            labs.update(j.get("cluster", []))
        for s in self.segments:
            for pt in (s.get("proximal"), s.get("distal")):
                if pt and pt not in jn:
                    labs.add(pt)
            # cluster-embedded (CAST) ML frames track a marker cluster each dynamic
            # frame, so those labels are needed dynamically too (the medial pair
            # marker is NOT -- it is only read on the static during calibration).
            fr = s.get("frame") or {}
            if fr.get("ml_source") == "cluster":
                labs.update(fr.get("cluster", []))
        return labs

    # ----- calibration (STATIC) -----
    def calibrate(self, static_markers, label_map=None):
        data = static_markers["data"]
        self._calib = {}
        for j in self.joints:
            if j.get("method") == "hip":
                jc = self._hip_jc_harrington(static_markers, j, label_map)
            elif j.get("method") == "marker":
                # Single-landmark joint centre (e.g. SHOULDER = acromion). A true
                # glenohumeral-centre regression (Meskers 1998) needs a scapular
                # marker cluster we cannot assume; using the acromion directly is
                # the conservative simplification (ISB-acceptable surface estimate).
                jc = np.nanmean(data[self._index(static_markers, j["landmark"], label_map)], axis=0)
            else:
                med = data[self._index(static_markers, j["medial"], label_map)]
                lat = data[self._index(static_markers, j["lateral"], label_map)]
                jc = np.nanmean((med + lat) / 2.0, axis=0)
            cluster = j.get("cluster", [])
            if len(cluster) < 3:
                raise ValueError(f"joint '{j['name']}' needs >=3 cluster markers")
            cidx = [self._index(static_markers, c, label_map) for c in cluster]
            P_ref = np.nanmean(data[cidx], axis=1)            # (k,3)
            R, t = kabsch(P_ref, P_ref)
            jc_local = R.T @ (jc - t)
            self._calib[j["name"]] = {"cluster": cluster, "P_ref": P_ref, "jc_local": jc_local}
        self._calibrate_frames(static_markers, label_map)
        return self

    def _calibrate_frames(self, static_markers, label_map=None):
        """Calibrate cluster-embedded (CAST) ML axes for any segment whose frame
        declares ``ml_source == "cluster"``. Runs on the STATIC trial, where the
        anatomical ML axis can be defined from a true medial+lateral marker pair
        (the trans-epicondylar / trans-malleolar line) -- markers that are absent
        in dynamic trials. The world ML axis is averaged over static frames, mapped
        into the tracking cluster's reference (local) frame, and stored so that
        ``compute_frames`` can transport it rigidly per dynamic frame.

        Pure / NaN-safe: a segment whose pair or cluster markers are missing simply
        gets no calibration entry, and ``compute_frames`` then falls back to the
        single plane marker (backward compatible).
        """
        self._frame_calib = {}
        data = static_markers["data"]

        def mpos(label):
            return np.nanmean(
                data[self._index(static_markers, label, label_map)], axis=0)

        for s in self.segments:
            fr = s.get("frame") or {}
            if fr.get("ml_source") != "cluster":
                continue
            cluster = fr.get("cluster") or []
            med, lat = fr.get("ml_medial"), fr.get("ml_lateral")
            side = fr.get("side") or (s["name"][0] if s["name"][:1] in "RL" else "R")
            if len(cluster) < 3 or not (med and lat):
                continue
            try:
                cidx = [self._index(static_markers, c, label_map) for c in cluster]
                # static cluster reference = per-marker mean over frames (k,3)
                P_ref = np.nanmean(data[cidx], axis=1)              # (k,3)
                # anatomical ML in world = lateral - medial (averaged over static),
                # pointing to the subject's right on a RIGHT segment.
                ml_world = mpos(lat) - mpos(med)                    # (3,)
            except (KeyError, IndexError):
                continue
            n = np.linalg.norm(ml_world)
            if not np.isfinite(P_ref).all() or n == 0 or not np.isfinite(n):
                continue
            ml_world = ml_world / n
            # mean cluster rotation over the static trial (orthonormalised), so the
            # world ML maps into the cluster-local frame consistently with the
            # rigid pose used dynamically.
            R = cluster_pose_per_frame(data[cidx], P_ref)           # (F,3,3)
            good = np.isfinite(R).all(axis=(1, 2))
            if not good.any():
                continue
            R_mean = R[good].mean(axis=0)
            U, _, Vt = np.linalg.svd(R_mean)
            R_mean = U @ Vt                                         # nearest rotation
            ml_local = R_mean.T @ ml_world                         # cluster-local ML
            self._frame_calib[s["name"]] = {
                "cluster": list(cluster), "P_ref": P_ref,
                "ml_local": ml_local, "side": side}

    def _hip_jc_harrington(self, static_markers, j, label_map=None):
        """Static hip-joint centre from pelvis markers via the Harrington (2007)
        pelvis-width / pelvis-depth regression. Returns the world-frame HJC (3,).

        Pelvis frame (origin = mid-ASIS): e_ml → right (RASIS-LASIS),
        e_sup → up, e_ant → anterior. The regression places the HJC posterior,
        inferior and lateral to mid-ASIS.
        """
        data = static_markers["data"]

        def mpos(label):
            return np.nanmean(data[self._index(static_markers, label, label_map)], axis=0)

        rasis = mpos(j["asis_r"])
        lasis = mpos(j["asis_l"])
        if j.get("psis_r") and j.get("psis_l"):
            mid_psis = (mpos(j["psis_r"]) + mpos(j["psis_l"])) / 2.0
        elif j.get("sacrum"):
            mid_psis = mpos(j["sacrum"])
        else:
            raise ValueError(f"hip joint '{j['name']}' needs PSIS pair or sacrum marker")
        mid_asis = (rasis + lasis) / 2.0

        def unit(v):
            n = np.linalg.norm(v)
            return v / n if n > 0 else v

        e_ml = unit(rasis - lasis)                 # +X to subject's right
        ant_tmp = mid_asis - mid_psis              # roughly anterior
        e_sup = unit(np.cross(e_ml, ant_tmp))      # up
        e_ant = unit(np.cross(e_sup, e_ml))        # anterior (orthonormal)

        pw = float(np.linalg.norm(rasis - lasis))           # pelvis width
        pd = float(np.linalg.norm(mid_asis - mid_psis))     # pelvis depth

        # Harrington 2007 PW/PD regression (mm); HJC is posterior/inferior/lateral.
        ap = -0.24 * pd - 9.9        # along anterior axis (negative = posterior)
        sup = -0.30 * pw - 10.9      # along superior axis (negative = inferior)
        ml = 0.33 * pw + 7.3         # along ML axis, toward this leg's side
        side = j.get("side") or (j["name"][0].upper())
        ml_sign = 1.0 if side == "R" else -1.0
        return mid_asis + ap * e_ant + sup * e_sup + ml_sign * ml * e_ml

    def calibration_selfcheck(self, static_markers, label_map=None):
        """Max error (mm) between reconstructed JC and the midpoint over static
        frames (0 if no joints)."""
        if not self.joints:
            return 0.0
        jcs = self.reconstruct(static_markers, label_map)
        worst = 0.0
        for j in self.joints:
            if j.get("method") in ("hip", "marker"):
                continue   # regression/single-landmark — no medial/lateral ground truth
            med = static_markers["data"][self._index(static_markers, j["medial"], label_map)]
            lat = static_markers["data"][self._index(static_markers, j["lateral"], label_map)]
            err = np.linalg.norm(jcs[j["name"]] - (med + lat) / 2.0, axis=1)
            worst = max(worst, float(np.nanmax(err)))
        return worst

    # ----- reconstruction (DYNAMIC) -----
    def reconstruct(self, markers, label_map=None):
        if not self._calib:
            raise RuntimeError("model not calibrated")
        data = markers["data"]
        F = data.shape[1]
        out = {}
        for j in self.joints:
            cal = self._calib[j["name"]]
            # A cluster marker that is ABSENT from this trial (different label set,
            # or occluded the whole trial) used to raise KeyError and crash the
            # entire model computation. Treat it as fully occluded (a NaN
            # trajectory) instead: ``_reconstruct_joint`` already degrades a frame
            # with < 3 visible cluster markers to NaN, so a missing marker now
            # simply lowers the per-frame visible count rather than aborting the
            # whole reconstruct (graceful degradation, no silent wrong number).
            cluster = self._gather_cluster(markers, cal["cluster"], F, label_map)
            P_ref, jc_local = cal["P_ref"], cal["jc_local"]
            out[j["name"]] = self._reconstruct_joint(cluster, P_ref, jc_local, F)
        return out

    def _gather_cluster(self, markers, cluster_labels, F, label_map=None):
        """Stack the cluster markers' (F,3) trajectories into a ``(k, F, 3)`` array.

        A label missing from the trial contributes an all-NaN (F,3) slab so it
        counts as occluded everywhere — keeping the cluster ordering aligned with
        the calibrated ``P_ref`` rows without raising."""
        data = markers["data"]
        rows = []
        for c in cluster_labels:
            try:
                idx = self._index(markers, c, label_map)
            except KeyError:
                rows.append(np.full((F, 3), np.nan))
                continue
            rows.append(np.asarray(data[idx], dtype=float))
        return np.stack(rows, axis=0)

    @staticmethod
    def _reconstruct_joint(cluster_xyz, P_ref, jc_local, F):
        """Per-frame rigid placement of a joint centre, vectorised over frames.

        ``cluster_xyz`` = (k, F, 3) cluster-marker trajectories. Frames where the
        whole cluster is visible are solved in one batched SVD; the (usually few)
        partially-occluded frames fall back to a per-frame solve; frames with
        < 3 visible markers stay NaN.
        """
        cluster_xyz = np.asarray(cluster_xyz, float)          # (k, F, 3)
        jc = np.full((F, 3), np.nan)
        vis = np.isfinite(cluster_xyz).all(axis=2)            # (k, F)
        full = vis.all(axis=0)                                # frames with all markers

        if full.any():
            P = np.transpose(cluster_xyz[:, full, :], (1, 0, 2))   # (Nf, k, 3)
            cr = P_ref.mean(axis=0)                                # (3,)
            cc = P.mean(axis=1)                                    # (Nf, 3)
            ref_c = P_ref - cr                                     # (k, 3)
            cur_c = P - cc[:, None, :]                             # (Nf, k, 3)
            H = np.einsum('ki,nkj->nij', ref_c, cur_c)            # (Nf, 3, 3)
            U, _, Vt = np.linalg.svd(H)
            d = np.sign(np.linalg.det(np.matmul(np.transpose(Vt, (0, 2, 1)),
                                                np.transpose(U, (0, 2, 1)))))
            D = np.zeros((d.shape[0], 3, 3))
            D[:, 0, 0] = 1.0
            D[:, 1, 1] = 1.0
            D[:, 2, 2] = d
            R = np.matmul(np.transpose(Vt, (0, 2, 1)),
                          np.matmul(D, np.transpose(U, (0, 2, 1))))   # (Nf, 3, 3)
            t = cc - np.einsum('nij,j->ni', R, cr)                    # (Nf, 3)
            jc[full] = np.einsum('nij,j->ni', R, jc_local) + t

        # Partially-occluded frames (some but not all markers visible).
        partial = (~full) & (vis.sum(axis=0) >= 3)
        for f in np.flatnonzero(partial):
            ok = vis[:, f]
            R, t = kabsch(P_ref[ok], cluster_xyz[ok, f, :])
            jc[f] = R @ jc_local + t
        return jc

    # ----- segments + angles -----
    def _point_traj(self, name, markers, joint_centers, label_map):
        if name in joint_centers:
            return joint_centers[name]
        return markers["data"][self._index(markers, name, label_map)]

    def compute_segments(self, markers, joint_centers, label_map=None):
        out = {}
        for s in self.segments:
            prox = self._point_traj(s["proximal"], markers, joint_centers, label_map)
            dist = self._point_traj(s["distal"], markers, joint_centers, label_map)
            out[s["name"]] = np.asarray(dist, float) - np.asarray(prox, float)
        return out

    def compute_frames(self, markers, joint_centers, label_map=None):
        """Per-frame segment coordinate systems for segments that declare a
        ``frame`` (a (F,3,3) rotation matrix keyed by segment name).

        Backward compatible: segments WITHOUT a ``frame`` field are skipped
        (they keep the legacy difference-vector behaviour). The ``frame`` schema
        is::

            "frame": {"origin": <pt>, "long": <pt>, "plane": <pt>, "side": "R"}

        where each ``<pt>`` is a joint-centre name or a marker label, ``origin``
        is the distal endpoint, ``long`` the proximal point defining the z axis,
        and ``plane`` a third point fixing the frontal plane. ``side`` is
        optional (defaults to the segment name's leading R/L, else "R").

        The PELVIS is special-cased with ``{"type": "pelvis", "rasis": <pt>,
        "lasis": <pt>, "psis": <pt>}`` because the pelvis lacks a superior
        landmark (see ``pelvis_frame``). The THORAX is likewise special-cased
        with ``{"type": "thorax", "ij": <pt>, "c7": <pt>, "px": <pt>,
        "t8": <pt>}`` (see ``thorax_frame``).
        """
        out = {}
        for s in self.segments:
            fr = s.get("frame")
            if not fr:
                continue
            if fr.get("type") == "pelvis":
                rasis = self._point_traj(fr["rasis"], markers, joint_centers, label_map)
                lasis = self._point_traj(fr["lasis"], markers, joint_centers, label_map)
                psis = self._point_traj(fr["psis"], markers, joint_centers, label_map)
                R, _ = pelvis_frame(rasis, lasis, psis)
                out[s["name"]] = R
                continue
            if fr.get("type") == "thorax":
                ij = self._point_traj(fr["ij"], markers, joint_centers, label_map)
                c7 = self._point_traj(fr["c7"], markers, joint_centers, label_map)
                px = self._point_traj(fr["px"], markers, joint_centers, label_map)
                t8 = self._point_traj(fr["t8"], markers, joint_centers, label_map)
                R, _ = thorax_frame(ij, c7, px, t8)
                out[s["name"]] = R
                continue
            origin = self._point_traj(fr["origin"], markers, joint_centers, label_map)
            longp = self._point_traj(fr["long"], markers, joint_centers, label_map)
            side = fr.get("side") or (s["name"][0] if s["name"][:1] in "RL" else "R")
            # Cluster-embedded (CAST) ML frame: transport the calibrated anatomical
            # ML axis by the tracking cluster's rigid pose. Used when the segment's
            # frame declares ``ml_source == "cluster"`` AND it was calibrated on a
            # static trial (``_calibrate_frames``). Otherwise (legacy models, or an
            # uncalibrated cluster frame) fall back to the single plane marker.
            cal = self._frame_calib.get(s["name"])
            if fr.get("ml_source") == "cluster" and cal is not None:
                cidx = [self._index(markers, c, label_map) for c in cal["cluster"]]
                R_cl = cluster_pose_per_frame(markers["data"][cidx], cal["P_ref"])
                ml_world = np.einsum('fij,j->fi', R_cl, cal["ml_local"])  # (F,3)
                R, _ = segment_frame_from_ml(origin, longp, ml_world,
                                             side=cal.get("side", side))
                out[s["name"]] = R
                continue
            plane = self._point_traj(fr["plane"], markers, joint_centers, label_map)
            R, _ = segment_frame(origin, longp, plane, side=side)
            out[s["name"]] = R
        return out

    # Suffixes for the three JCS components, exposed as separate angle channels
    # so the downstream ``angles`` dict (name -> (F,) array) stays unchanged.
    _JCS_SUFFIX = ("_FE", "_AB", "_IE")

    def _angle_side(self, a):
        """Body side ("R"/"L"/"") of a JCS angle, for the left/right sign
        unification (see ``_left_sign_flip``). Read from the angle name's leading
        side token first (``L_KNEE_angle`` -> "L"); fall back to the DISTAL
        segment's frame ``side`` (the moving limb that carries the clinical
        meaning). Returns "" when no side can be determined (then no flip)."""
        nm = str(a.get("name", "")).upper()
        if nm[:2] in ("R_", "L_"):
            return nm[0]
        if nm[:1] in ("R", "L") and (len(nm) == 1 or not nm[1].isalpha()):
            return nm[0]
        for s in self.segments:                     # distal segment frame side
            if s.get("name") == a.get("segment_b"):
                fr = s.get("frame") or {}
                sd = str(fr.get("side", "")).upper()[:1]
                return sd if sd in ("R", "L") else ""
        return ""

    # Left/right SIGN UNIFICATION of JCS components.
    #
    # ``segment_frame`` flips the ML axis (``e_ml``) on the LEFT so +x is the
    # subject's anatomical right for BOTH legs. That makes the SAGITTAL component
    # (a rotation about the ML/x axis) come out with the same sign on both legs,
    # but it leaves the components about the AP (y) and LONG (z) axes
    # MIRROR-OPPOSITE: the left frame is the right frame conjugated by
    # S = diag(-1, 1, 1) (an ML reflection), and S-conjugation NEGATES every
    # rotation about a non-ML axis while PRESERVING rotation about ML. Verified
    # on synthetic mirror-image limbs and on real static trials (left/right
    # standing internal rotation came out with opposite signs).
    #
    # The convention here is a SINGLE clinical sign for both sides (abduction +,
    # inversion +, internal rotation + on either limb -- not Visual3D's
    # opposite-side signing). So on the LEFT we negate exactly the output
    # components whose Cardan axis is NOT 'x' (ML). For the lower-limb "xyz"/
    # "xzy" orders that is [FE, -AB, -IE]; for the shoulder "zxz"/"yxy"
    # proper-Euler orders the about-ML term is the MIDDLE one, so the flip is
    # [-, +, -]. The pattern is therefore SEQUENCE-DEPENDENT (see
    # ``_left_sign_flip``), not a fixed [1,-1,-1].

    @staticmethod
    def _ml_mirror_signs(sequence):
        """Per-output sign change of a Cardan/Euler decomposition under a
        medio-lateral (x-axis) reflection S=diag(-1,1,1): +1 for an output whose
        axis is 'x' (rotation about ML is preserved), -1 otherwise (rotations
        about AP/long are negated). Returns a (3,) float array aligned with the
        decomposition's [0,1,2] components for ``sequence``."""
        seq = str(sequence).lower()
        return np.array([1.0 if c == "x" else -1.0 for c in seq])

    def _left_sign_flip(self, comp, side, sequence="xyz"):
        """Sign-unify a LEFT (F,3) JCS block so every clinical component matches
        the right side. Negates the components whose Cardan axis is not ML (see
        ``_ml_mirror_signs``); no-op for "R"/"" (any non-"L" side). Pure;
        returns a new array when it flips."""
        if str(side).upper().startswith("L"):
            return comp * self._ml_mirror_signs(sequence)
        return comp

    def compute_angles(self, markers, joint_centers, label_map=None):
        """Joint angles as a flat dict {name: (F,) degrees}.

        ``mode`` per angle:
          * absent or "vector" -> legacy unsigned angle_between (1 channel).
          * "jcs" -> Grood-Suntay/Cardan 3-component angle; emitted as three
            channels ``<name>_FE`` / ``<name>_AB`` / ``<name>_IE`` (signed).

        JCS angles are LEFT/RIGHT SIGN-UNIFIED: the left leg's AB & IE components
        are negated (see ``_left_sign_flip``) so abduction/inversion/internal-
        rotation read POSITIVE on both legs.
        """
        segs = self.compute_segments(markers, joint_centers, label_map)
        frames = self.compute_frames(markers, joint_centers, label_map)
        out = {}
        for a in self.angles:
            mode = a.get("mode", "vector")
            if mode == "jcs":
                Ra = frames.get(a["segment_a"])
                Rb = frames.get(a["segment_b"])
                if Ra is None or Rb is None:
                    continue
                seq = a.get("sequence", "xyz")
                comp = jcs_angles(Ra, Rb, sequence=seq)
                comp = self._left_sign_flip(comp, self._angle_side(a), seq)
                # Per-joint FE flexion-sign so knee flexion reads positive (the
                # knee's flexion is geometrically opposite the hip/elbow Cardan
                # convention -- see ``_FE_FLEXION_SIGN``). FE is component [0]
                # (suffix "_FE"); AB/IE are untouched.
                fsign = fe_flexion_sign(a["name"])
                if fsign != 1.0:
                    comp = comp.copy()
                    comp[:, 0] *= fsign
                for k, suf in enumerate(self._JCS_SUFFIX):
                    out[a["name"] + suf] = comp[:, k]
            else:
                va = segs.get(a["segment_a"])
                vb = segs.get(a["segment_b"])
                if va is None or vb is None:
                    continue
                out[a["name"]] = angle_between(va, vb)
        return out

    def _pelvis_points(self, markers, label_map=None):
        """Virtual pelvis landmarks (mid-ASIS / mid-PSIS) per frame, so the PELVIS
        segment is the pelvic midline AP axis (ISB/Plug-in-Gait standard) rather
        than a single-side vector. Empty when there is no hip joint."""
        data = markers["data"]
        for j in self.joints:
            if j.get("method") != "hip":
                continue
            try:
                def traj(lab):
                    return data[self._index(markers, lab, label_map)]
                mid_asis = (traj(j["asis_r"]) + traj(j["asis_l"])) / 2.0
                if j.get("psis_r") and j.get("psis_l"):
                    mid_post = (traj(j["psis_r"]) + traj(j["psis_l"])) / 2.0
                elif j.get("sacrum"):
                    mid_post = traj(j["sacrum"])
                else:
                    continue
                return {"PELVIS_ANT": mid_asis, "PELVIS_POST": mid_post}
            except KeyError:
                continue
        return {}

    def apply(self, markers, label_map=None, offsets=None,
              body_mass=None, sex=None):
        """Run the full pipeline (reconstruct -> segments -> angles -> COM).

        ``offsets`` (optional): a dict {angle_channel_name: degrees}. When given,
        each angle channel has its offset subtracted
        (``angles[name] -= offsets.get(name, 0.0)``), zero-referencing the
        dynamic curves to a neutral/static posture. Omitting ``offsets`` returns
        raw angles -- identical to the previous behaviour (backward compatible).
        Channels absent from ``offsets`` are left unchanged.

        ``body_mass`` (kg) / ``sex`` ("F"/"M"/None) feed the de Leva (1996) COM
        (``core.com.body_com``) added under ``result["com"]``. The COM *position*
        is computed even with ``body_mass=None`` / ``sex=None`` (sex-neutral
        average BSPs); the mass only fills ``mass_used_kg``. The COM block is
        purely additive -- the joint-centre/segment/angle outputs are unchanged
        (backward compatible).
        """
        jcs = self.reconstruct(markers, label_map)
        jcs.update(self._pelvis_points(markers, label_map))
        segs = self.compute_segments(markers, jcs, label_map)
        angles = self.compute_angles(markers, jcs, label_map)
        if offsets:
            for name in angles:
                off = offsets.get(name)
                if off is not None and np.isfinite(off):
                    angles[name] = angles[name] - off
        result = {"joint_centers": jcs, "segments": segs, "angles": angles,
                  "time": markers["time"]}
        # Centre of mass (de Leva 1996 BSPs). Additive channel: position needs no
        # body mass / sex, so we always attempt it. Wrapped so a COM failure never
        # breaks the (backward-compatible) joint-centre/segment/angle outputs.
        try:
            from core import com as _com
            resolver = _com.point_traj_for(self, markers, jcs, label_map)
            result["com"] = _com.body_com(self, resolver, body_mass=body_mass, sex=sex)
        except Exception:
            # COM is an optional additive channel; a failure must never break the
            # backward-compatible joint-centre/segment/angle outputs, so this stays
            # broad. But leave a breadcrumb (exc_info) so a genuine COM bug isn't
            # silently invisible — mirrors core.metrics.compute_metrics.
            log.debug("apply: COM block failed; skipping 'com' channel",
                      exc_info=True)
        return result


# --------------------------------------------------------------------------
# Per-channel reliability metadata (which angle components are trustworthy)
# --------------------------------------------------------------------------
#
# Not every component of every joint angle is equally trustworthy from a given
# marker set. The dominant case is the ANKLE: with only a HEEL and a TOE marker
# (no dedicated MEDIAL/LATERAL foot markers) the foot's FRONTAL plane is
# near-degenerate. Heel/toe define the foot's sagittal (FE) axis well, but the
# frontal plane -- which carries inversion/eversion (AB) and internal/external
# rotation (IE) -- is fixed only by a single proximal plane point (the lateral
# malleolus). A few millimetres of medio-lateral heel-marker misplacement then
# leak straight into inversion/eversion. This is a known Plug-in-Gait / Visual3D
# limitation: dorsi/plantar-flexion is reliable, inv/ev & rotation are not,
# unless a medial+lateral foot-marker pair is present (Oxford Foot Model style).
#
# So we tag dorsi/plantar-flexion (the ``_FE`` channel) "high" and the ankle's
# ``_AB`` (inv/ev) and ``_IE`` (rotation) channels "low". Every other joint
# (knee/hip/shoulder/elbow/wrist) stays "high": its frontal-plane / rotation
# axes are fixed by a genuine medial+lateral marker pair (knee/ankle epicondyles
# & malleoli, styloids), so all three components are anatomically supported.

_RELIABILITY_LOW = "low"
_RELIABILITY_MODERATE = "moderate"
_RELIABILITY_HIGH = "high"

# Joint base names whose AB/IE (frontal + transverse) channels are unreliable
# unless a dedicated medial/lateral marker pair fixes the distal frontal plane.
# The ankle is the only such joint with the default lower-limb marker set.
_LOW_FRONTAL_JOINTS = ("ANKLE",)


def _segment_has_foot_ml(model, seg_name):
    """True if the segment's frame is fixed by a dedicated medial+lateral foot
    marker pair (which would promote the ankle frontal/rotation channels to
    "high"). The default heel/toe foot frame uses a single lateral malleolus
    plane point, so this is False; a future Oxford-Foot-Model-style builder can
    set ``frame["foot_ml"] = True`` to opt into the promotion."""
    for s in model.segments:
        if s.get("name") == seg_name:
            fr = s.get("frame") or {}
            return bool(fr.get("foot_ml"))
    return False


def _segment_is_cluster_ml(model, seg_name):
    """True if the named segment's frame uses a cluster-embedded (CAST) ML axis
    (``frame["ml_source"] == "cluster"``). Used to grade the residual knee
    transverse cross-talk: CAST removes most of the soft-tissue-driven inflation,
    but a measurable FE<->IE correlation remains (YA01/YA02 |r| ~ 0.3-0.7), so the
    knee internal/external-rotation channel is honestly tagged "moderate" rather
    than "high" when CAST is in use."""
    for s in model.segments:
        if s.get("name") == seg_name:
            fr = s.get("frame") or {}
            return fr.get("ml_source") == "cluster"
    return False


# Joint bases whose TRANSVERSE (_IE) channel keeps a residual FE<->IE cross-talk
# even after the cluster-embedded (CAST) ML fix, so it is graded "moderate".
# The KNEE is the documented case (knee axial rotation is small and rides on a
# large flexion arc; transepicondylar-line obliquity leaks some flexion into it).
_MODERATE_IE_JOINTS = ("KNEE",)


def angle_reliability(model):
    """Per-channel reliability of a model's joint-angle outputs (pure, no data).

    Returns a dict keyed by the SAME channel names that
    ``MarkerModel.compute_angles`` emits, mapping each to::

        {"level": "high" | "low", "reason": <str>}

    Channel-name rules (must match ``compute_angles`` exactly):
      * JCS angles (``mode="jcs"``) expand into three channels per joint:
        ``<ANGLE>_FE`` (sagittal: dorsi/plantar-flexion, flex/ext),
        ``<ANGLE>_AB`` (frontal: ab/adduction, inversion/eversion) and
        ``<ANGLE>_IE`` (transverse: internal/external rotation).
      * Vector-mode angles (no ``mode``/"vector") emit a SINGLE channel
        ``<ANGLE>`` whose meaning is sagittal (FE) -- so it is treated as the
        FE channel for reliability and tagged "high".

    Reliability policy:
      * ANKLE ``_AB`` / ``_IE`` -> "low" (no medial/lateral foot marker; the foot
        frontal plane is near-degenerate, so inv/ev & rotation are untrustworthy),
        UNLESS the FOOT frame declares a medial/lateral foot-marker pair
        (``frame["foot_ml"]``), which promotes them to "high".
      * KNEE ``_IE`` -> "moderate" WHEN the knee's distal (SHANK) frame uses the
        cluster-embedded (CAST) ML axis: CAST removes the soft-tissue cross-talk
        that inflated knee axial rotation, but a residual FE<->IE coupling remains
        (knee internal/external rotation is small and rides on a large flexion
        arc). Legacy single-marker knee frames keep the previous "high" tag (no
        silent re-grading of already-saved models).
      * Every ANKLE ``_FE`` and EVERY remaining channel of all other joints
        -> "high".
      * Vector-mode (frame-less) ankle: a single ``<ANGLE>`` channel exists and
        means FE only -> "high"; there is NO ``_AB``/``_IE`` channel at all, so
        the unreliable components simply do not appear (consistent behaviour).

    How the UI reads this: call ``angle_reliability(model)`` once after a model
    is built, then for each plotted/listed angle channel look up
    ``rel.get(channel, {"level": "high"})``. A ``level == "low"`` channel should
    be flagged (e.g. a warning glyph / muted styling / tooltip showing
    ``reason``). Channels absent from the dict are "high" by default. The dict is
    static for a given model (independent of the trial data), so it can be cached
    alongside the model.
    """
    out = {}
    for a in model.angles:
        name = a["name"]
        base = name.upper()
        is_low_joint = any(j in base for j in _LOW_FRONTAL_JOINTS)
        is_mod_ie_joint = any(j in base for j in _MODERATE_IE_JOINTS)
        if a.get("mode") == "jcs":
            for suf in MarkerModel._JCS_SUFFIX:
                chan = name + suf
                if is_low_joint and suf in ("_AB", "_IE") \
                        and not _segment_has_foot_ml(model, a.get("segment_b", "")):
                    out[chan] = {
                        "level": _RELIABILITY_LOW,
                        "reason": "no medial/lateral foot marker; "
                                  "frontal plane unreliable",
                    }
                elif is_mod_ie_joint and suf == "_IE" \
                        and _segment_is_cluster_ml(model, a.get("segment_b", "")):
                    out[chan] = {
                        "level": _RELIABILITY_MODERATE,
                        "reason": "residual flexion<->rotation cross-talk after "
                                  "cluster-embedded (CAST) ML correction",
                    }
                else:
                    out[chan] = {"level": _RELIABILITY_HIGH, "reason": ""}
        else:
            # Vector mode: one channel, sagittal (FE) meaning -> reliable.
            out[name] = {"level": _RELIABILITY_HIGH, "reason": ""}
    return out


def static_angle_offsets(model, static_markers, label_map=None):
    """Neutral-posture joint-angle offsets from a STATIC calibration trial.

    Runs ``model.apply`` on the static trial and returns, per angle channel, the
    NaN-safe mean angle over its frames: ``{channel_name: nanmean(degrees)}``.
    These are the subject's neutral standing angles; subtracting them from a
    dynamic trial (via ``apply(offsets=...)``) zero-references the curves to the
    subject's own neutral -- the opt-in static-offset convention (NOT a Visual3D
    default, but a common gait-lab practice).

    ``model`` must already be calibrated (so its joint centres reconstruct on the
    static trial). NaN-safe: an all-NaN channel yields a NaN offset, which
    ``apply`` then ignores (leaving that channel raw).
    """
    res = model.apply(static_markers, label_map=label_map)
    offsets = {}
    for name, series in res["angles"].items():
        series = np.asarray(series, float)
        if np.isfinite(series).any():
            offsets[name] = float(np.nanmean(series))
        else:
            offsets[name] = np.nan
    return offsets


def static_angle_offsets_from_window(model, markers, t0, t1, label_map=None):
    """Like ``static_angle_offsets`` but averages a TIME WINDOW [t0, t1] (seconds,
    inclusive) of a dynamic trial -- for when no separate static trial exists and
    the subject holds a neutral posture for part of the recording.

    The window is selected on ``markers["time"]``; an empty or out-of-range
    window yields all-NaN offsets (then ignored by ``apply``). Policy on which
    window counts as "neutral" is left to the caller (UI/user).
    """
    res = model.apply(markers, label_map=label_map)
    t = np.asarray(res["time"], float)
    lo, hi = (t0, t1) if t0 <= t1 else (t1, t0)
    sel = (t >= lo) & (t <= hi)
    offsets = {}
    for name, series in res["angles"].items():
        series = np.asarray(series, float)
        win = series[sel] if sel.any() else series[:0]
        if win.size and np.isfinite(win).any():
            offsets[name] = float(np.nanmean(win))
        else:
            offsets[name] = np.nan
    return offsets


# --------------------------------------------------------------------------
# Cross-talk diagnostic (kinematic cross-talk, Piazza & Cavanagh 2000)
# --------------------------------------------------------------------------
#
# "Kinematic cross-talk" is the leakage of one rotation component into another
# caused by a mis-oriented joint axis. The classic signature (Piazza & Cavanagh
# 2000; Baudet 2014) is a strong CORRELATION between the flexion/extension (FE)
# waveform and the transverse rotation (IE) or frontal (AB) waveform across a
# cycle: a frontal/transverse axis tilted away from the true flexion axis turns
# part of the (large) flexion arc into a spurious ab/adduction or rotation swing.
# A second, ROM-based flag is that the secondary-plane range becomes an
# implausibly large fraction of the flexion range. We expose a PURE diagnostic
# (it takes already-computed angle arrays, no markers) so a UI/QC step can warn
# when a joint's frontal/transverse channels look cross-talk-dominated.

# Default warning thresholds (conservative; tune per lab if needed):
#   |r(FE,IE)| or |r(FE,AB)| above this flags a correlation cross-talk warning.
_CROSSTALK_CORR_WARN = 0.7
#   secondary-plane ROM / FE ROM above this flags a ROM-ratio warning.
_CROSSTALK_ROMRATIO_WARN = 1.0


def _safe_corr(a, b):
    """|Pearson r| between two (F,) arrays over their jointly-finite samples;
    NaN when fewer than 5 valid pairs or either is constant. Pure, NaN-safe."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 5:
        return np.nan
    aa, bb = a[m], b[m]
    if np.std(aa) == 0 or np.std(bb) == 0:
        return np.nan
    return float(abs(np.corrcoef(aa, bb)[0, 1]))


def _ci_rom(x):
    """Robust range = 97.5th - 2.5th percentile (deg), ignoring NaNs; clips the
    odd marker-dropout spike. NaN when no finite samples. Pure."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return np.nan
    return float(np.nanpercentile(x, 97.5) - np.nanpercentile(x, 2.5))


def crosstalk_diagnosis(fe, ab, ie,
                        corr_warn=_CROSSTALK_CORR_WARN,
                        rom_ratio_warn=_CROSSTALK_ROMRATIO_WARN):
    """Kinematic cross-talk diagnostic for one joint over a segment of frames.

    Given the three JCS component waveforms of a joint -- ``fe`` (sagittal,
    flexion/extension), ``ab`` (frontal, ab/adduction or inv/ev) and ``ie``
    (transverse, internal/external rotation), each a (F,) degrees array -- returns
    data-driven cross-talk indicators (Piazza & Cavanagh 2000):

      * ``corr_fe_ie`` / ``corr_fe_ab`` : |Pearson r| between FE and IE / AB. A
        well-aligned axis decorrelates flexion from the secondary planes; a high
        |r| means flexion is bleeding into that plane (the hallmark of a tilted
        frontal/transverse axis).
      * ``fe_rom`` / ``ab_rom`` / ``ie_rom`` : robust ranges (97.5-2.5 pct, deg).
      * ``ie_fe_ratio`` / ``ab_fe_ratio`` : secondary-plane ROM as a fraction of
        the flexion ROM. A small physiological rotation/ab-adduction arc riding on
        a large flexion arc should be << 1; a ratio near or above 1 is suspicious.
      * ``warn`` : True if ANY indicator exceeds its threshold.
      * ``flags`` : the list of triggered indicator names (for messaging).

    Pure & NaN-safe: all-NaN / constant inputs yield NaN indicators and no flag.
    This takes already-computed angle arrays (e.g. from ``model.apply``), so it is
    independent of the marker pipeline and reusable by any QC/UI layer.
    """
    fe = np.asarray(fe, float)
    ab = np.asarray(ab, float)
    ie = np.asarray(ie, float)
    c_fe_ie = _safe_corr(fe, ie)
    c_fe_ab = _safe_corr(fe, ab)
    fe_rom = _ci_rom(fe)
    ab_rom = _ci_rom(ab)
    ie_rom = _ci_rom(ie)
    ie_ratio = (ie_rom / fe_rom) if (np.isfinite(fe_rom) and fe_rom > 0) else np.nan
    ab_ratio = (ab_rom / fe_rom) if (np.isfinite(fe_rom) and fe_rom > 0) else np.nan

    flags = []
    if np.isfinite(c_fe_ie) and c_fe_ie > corr_warn:
        flags.append("corr_fe_ie")
    if np.isfinite(c_fe_ab) and c_fe_ab > corr_warn:
        flags.append("corr_fe_ab")
    if np.isfinite(ie_ratio) and ie_ratio > rom_ratio_warn:
        flags.append("ie_fe_ratio")
    if np.isfinite(ab_ratio) and ab_ratio > rom_ratio_warn:
        flags.append("ab_fe_ratio")

    return {
        "corr_fe_ie": c_fe_ie, "corr_fe_ab": c_fe_ab,
        "fe_rom": fe_rom, "ab_rom": ab_rom, "ie_rom": ie_rom,
        "ie_fe_ratio": ie_ratio, "ab_fe_ratio": ab_ratio,
        "warn": bool(flags), "flags": flags,
        "corr_warn": float(corr_warn), "rom_ratio_warn": float(rom_ratio_warn),
    }


# --------------------------------------------------------------------------
# Angle sign convention (declarative table; pure data, no UI)
# --------------------------------------------------------------------------
#
# A single source of truth for what each JCS angle component MEANS: its positive
# direction, its zero reference, and whether a "peak flexion" style preset op
# (op=max / op=min meaning peak flexion / peak extension) may be pinned onto it.
#
# Sign policy (left/right UNIFIED -- see ``MarkerModel._left_sign_flip``):
#   * FE (sagittal, about ML): flexion +, extension -.  Same sign on both legs
#     (intrinsic to the side-flipped ML axis).  ANKLE FE = dorsiflexion +,
#     plantarflexion -.
#   * AB (frontal, about AP): abduction +, adduction -; ANKLE = inversion +,
#     eversion -.  Left negated so both legs read +.
#   * IE (transverse, about long): internal rotation +, external rotation -.
#     Left negated so both legs read +.
#   * 0 deg = anatomical neutral (the JCS axes aligned); gait/run additionally
#     subtract a static standing offset (``static_angle_offsets``).
#
# ``op_max_means`` / ``op_min_means`` name the clinical extremum each preset op
# selects on that channel, and ``allow_peak_flex_op`` flags whether a generic
# "peak flexion" max/min op is meaningful there. Only the SAGITTAL (FE) channel
# carries a clinical peak-flexion extremum: AB and IE oscillate around neutral,
# so a bare max/min on them is "peak abduction"/"peak internal rotation", NOT
# peak flexion -- the UI must label them per-component, never as "peak flexion".
# VECTOR-mode angles are UNSIGNED (0..180), so even their max is not a signed
# flexion peak -> peak-flexion op disallowed there too.
#
# ``left_negated`` records whether the left side's sign was flipped to unify it
# with the right FOR THE LOWER-LIMB "xyz"/"xzy" orders (FE kept, AB & IE
# negated). The flip is actually SEQUENCE-DEPENDENT (it negates the components
# whose Cardan axis is not ML); for the shoulder "zxz"/"yxy" orders use
# ``left_negated_components(sequence)`` for the exact per-component truth.
#
# Keyed by component suffix ("_FE"/"_AB"/"_IE") and, for the ankle whose frontal
# plane is inversion/eversion (not ab/adduction), by joint base. ``vector``
# is the entry for a frame-less single-channel angle.

_CONV_FE = {
    "positive": "flexion", "negative": "extension", "zero": "neutral",
    "op_max_means": "peak_flexion", "op_min_means": "peak_extension",
    "allow_peak_flex_op": True, "left_negated": False,
}
_CONV_FE_ANKLE = {
    "positive": "dorsiflexion", "negative": "plantarflexion", "zero": "neutral",
    "op_max_means": "peak_dorsiflexion", "op_min_means": "peak_plantarflexion",
    "allow_peak_flex_op": True, "left_negated": False,
}
_CONV_AB = {
    "positive": "abduction", "negative": "adduction", "zero": "neutral",
    "op_max_means": "peak_abduction", "op_min_means": "peak_adduction",
    "allow_peak_flex_op": False, "left_negated": True,
}
_CONV_AB_ANKLE = {
    "positive": "inversion", "negative": "eversion", "zero": "neutral",
    "op_max_means": "peak_inversion", "op_min_means": "peak_eversion",
    "allow_peak_flex_op": False, "left_negated": True,
}
_CONV_IE = {
    "positive": "internal_rotation", "negative": "external_rotation",
    "zero": "neutral", "op_max_means": "peak_internal_rotation",
    "op_min_means": "peak_external_rotation",
    "allow_peak_flex_op": False, "left_negated": True,
}
_CONV_VECTOR = {
    "positive": "unsigned_angle", "negative": "", "zero": "0_deg_aligned",
    "op_max_means": "max_angle", "op_min_means": "min_angle",
    "allow_peak_flex_op": False, "left_negated": False,
}

# ANGLE_CONVENTION[suffix][base] -> convention dict. ``base`` is the joint base
# name (HIP/KNEE/ANKLE/...) so the ankle's frontal plane reads inversion/eversion
# while the hip/knee read ab/adduction. ``"_DEFAULT"`` is the fallback base.
ANGLE_CONVENTION = {
    "_FE": {"ANKLE": _CONV_FE_ANKLE, "_DEFAULT": _CONV_FE},
    "_AB": {"ANKLE": _CONV_AB_ANKLE, "_DEFAULT": _CONV_AB},
    "_IE": {"_DEFAULT": _CONV_IE},
    "vector": {"_DEFAULT": _CONV_VECTOR},
}

_JCS_BASES = ("HIP", "KNEE", "ANKLE", "SHOULDER", "ELBOW", "WRIST")


def _channel_base(channel):
    """Joint base (HIP/KNEE/ANKLE/...) of an angle channel name, else ""."""
    up = str(channel).upper()
    for base in _JCS_BASES:
        if base in up:
            return base
    return ""


# Per-joint SAGITTAL (FE) flexion-sign correction.
#
# Both segment frames are built with z = distal->proximal (pointing proximally),
# so the raw Cardan x-rotation that ``jcs_angles`` returns is positive when the
# distal segment's distal end swings ANTERIOR. For the HIP/SHOULDER/ELBOW that
# coincides with anatomical flexion (thigh/arm/forearm forward), so FE is already
# flexion-positive. The KNEE is the lone exception: knee flexion swings the shank
# POSTERIOR (heel toward buttock), i.e. the geometrically OPPOSITE rotation, so
# the raw FE comes out negative for true flexion. We negate the knee FE so that
# flexion reads POSITIVE on both legs -- matching the ANGLE_CONVENTION table
# (positive == "flexion") and Visual3D/ISB knee reporting. Verified on synthetic
# anatomical flexion (ankle swung posterior -> +FE) for both legs.
_FE_FLEXION_SIGN = {"KNEE": -1.0}


def fe_flexion_sign(channel_or_name):
    """+1.0 / -1.0 sign applied to a joint's FE channel so flexion reads positive
    (see ``_FE_FLEXION_SIGN``). Keyed by joint base; +1 for unlisted joints."""
    return _FE_FLEXION_SIGN.get(_channel_base(channel_or_name), 1.0)


def angle_convention(channel):
    """Sign convention for one angle channel (pure lookup; no data).

    ``channel`` is a channel name as emitted by ``compute_angles`` -- a JCS
    component ``<ANGLE>_FE``/``_AB``/``_IE`` or a vector-mode ``<ANGLE>``.
    Returns the convention dict (positive/negative direction, zero, the clinical
    meaning of a max/min op, and ``allow_peak_flex_op``). A name with no
    ``_FE``/``_AB``/``_IE`` suffix is treated as a vector (unsigned) angle.
    """
    up = str(channel).upper()
    base = _channel_base(channel)
    for suf in ("_FE", "_AB", "_IE"):
        if up.endswith(suf):
            table = ANGLE_CONVENTION[suf]
            return table.get(base, table["_DEFAULT"])
    return ANGLE_CONVENTION["vector"]["_DEFAULT"]


# Short DISPLAY abbreviation of a JCS plane, by component suffix and joint base.
# This is the human-facing label only -- the internal channel name (R_KNEE_FE,
# L_ANKLE_AB, ...) is UNCHANGED, so saved projects/metrics keep working. The
# abbreviations are the clinical plane shorthands the user asked for:
#   _FE -> "F/E"  (flex/extension); ankle -> "Dorsi/Plantar"
#   _AB -> "AB/ADD" (ab/adduction); ankle -> "Inv/Ever" (inversion/eversion)
#   _IE -> "IR/ER" (internal/external rotation)
# Keyed like ANGLE_CONVENTION (suffix -> {base: abbr, "_DEFAULT": abbr}) so the
# ankle's frontal/sagittal planes read inv-ev / dorsi-plantar while hip & knee
# read the generic shorthand. Stays in lockstep with ANGLE_CONVENTION.
_PLANE_ABBR = {
    "_FE": {"ANKLE": "Dorsi/Plantar", "_DEFAULT": "F/E"},
    "_AB": {"ANKLE": "Inv/Ever", "_DEFAULT": "AB/ADD"},
    "_IE": {"_DEFAULT": "IR/ER"},
}

# Title-case display name for the joint base. The internal name is upper-case
# (KNEE); the label shows "Knee". UPPERARM/FOREARM never appear as a joint base.
_BASE_DISPLAY = {
    "HIP": "Hip", "KNEE": "Knee", "ANKLE": "Ankle",
    "SHOULDER": "Shoulder", "ELBOW": "Elbow", "WRIST": "Wrist",
}


def angle_label(name):
    """Human DISPLAY label for a joint-angle channel ``name`` -- abbreviated.

    ``name`` is a channel name as emitted by ``compute_angles``: a JCS component
    ``<SIDE>_<JOINT>_angle_<FE|AB|IE>`` (e.g. ``R_KNEE_angle_FE``,
    ``L_ANKLE_angle_AB``) or a frame-less vector angle.

    Returns the compact clinical label the user reads, e.g.::

        R_KNEE_angle_FE   -> "R Knee F/E"
        L_ANKLE_angle_AB  -> "L Ankle Inv/Ever"
        R_HIP_angle_IE    -> "R Hip IR/ER"
        L_ANKLE_angle_FE  -> "L Ankle Dorsi/Plantar"

    The side token (L/R) is kept as a single letter (it is self-evident, per the
    user's request), the joint is title-cased, and the plane is the shorthand
    from :data:`_PLANE_ABBR`. A name that does not match the JCS pattern (no
    L/R prefix, no FE/AB/IE suffix, or an unknown joint) falls back to the name
    itself so nothing crashes -- the caller (``signals.label_for``) then renders
    it verbatim. Pure; this is purely cosmetic and never touches the data.
    """
    raw = str(name)
    up = raw.upper()

    # Plane shorthand from the trailing component suffix (and joint base for the
    # ankle). No suffix -> not a JCS component; leave the name as-is.
    base = _channel_base(raw)
    abbr = None
    for suf in ("_FE", "_AB", "_IE"):
        if up.endswith(suf):
            table = _PLANE_ABBR[suf]
            abbr = table.get(base, table["_DEFAULT"])
            break
    if abbr is None:
        return raw

    # Side token: a leading "R_"/"L_" (or a bare R/L). Self-evident, so kept as
    # one letter; absent -> no side shown.
    side = ""
    if up[:2] in ("R_", "L_"):
        side = up[0]
    elif up[:1] in ("R", "L") and (len(up) == 1 or not up[1].isalpha()):
        side = up[0]

    joint = _BASE_DISPLAY.get(base, base.title() if base else "")
    parts = [p for p in (side, joint, abbr) if p]
    return " ".join(parts) if parts else raw


def left_negated_components(sequence="xyz"):
    """Per-component bool: was the left side's sign flipped to unify it with the
    right, for a given Cardan/Euler ``sequence``? True where the component's axis
    is not ML (x). Aligned with the decomposition's [0,1,2] = [_FE,_AB,_IE]
    channels. Lower-limb "xyz" -> (False, True, True); shoulder "zxz" ->
    (True, False, True). Pure; the exact counterpart of the static
    ``left_negated`` table field (which records only the "xyz" default)."""
    return tuple(c != "x" for c in str(sequence).lower())


def allow_peak_flexion_op(channel):
    """Gate: may a "peak flexion" preset op (op=max/min meaning peak flexion /
    extension) be pinned onto ``channel``? True ONLY for the sagittal FE channel
    of a JCS joint; False for AB/IE (which read ab/adduction or inv/ev or
    rotation, not flexion) and for vector-mode unsigned angles.

    Use this before stamping a generic ``op=max``/``op=min`` with a "peak
    flexion" label; for AB/IE/vector channels the UI must instead use the
    per-component label from ``angle_convention(channel)["op_max_means"]`` /
    ``["op_min_means"]`` (e.g. "peak abduction", "peak internal rotation").
    """
    return bool(angle_convention(channel).get("allow_peak_flex_op", False))


def standing_zero_selfcheck(model, static_markers, label_map=None,
                            tol_deg=10.0):
    """Self-check that the SAGITTAL (FE) joint angles are ~0 in a neutral static
    trial, i.e. the JCS zero reference is anatomically sound.

    Mirrors ``MarkerModel.calibration_selfcheck`` (which checks joint-CENTRE
    reconstruction error): this checks the FE ANGLE zero instead. In a neutral
    standing static the hip/knee/ankle flexion-extension angles should sit near
    0 deg; a large |FE| means the segment frames are mis-built or the subject was
    not neutral. AB/IE are NOT checked (they carry real neutral offsets -- shank
    torsion, foot inversion -- and the ankle frontal plane is low-reliability).

    Returns ``{"ok": bool, "tol_deg": float, "channels": {fe_channel: mean_deg},
    "worst": (channel, abs_mean_deg) | None, "violations": [channel, ...]}``.
    A channel that is all-NaN (missing markers) is skipped, not failed. ``ok`` is
    True when every checked FE channel's |mean| <= ``tol_deg`` (vacuously True
    when there is nothing to check). Pure read of ``model.apply`` -- no mutation.
    """
    res = model.apply(static_markers, label_map=label_map)
    angles = res["angles"]
    channels = {}
    violations = []
    worst = None
    for name, series in angles.items():
        if not str(name).upper().endswith("_FE"):
            continue
        series = np.asarray(series, float)
        if not np.isfinite(series).any():
            continue
        m = float(np.nanmean(series))
        channels[name] = m
        if worst is None or abs(m) > worst[1]:
            worst = (name, abs(m))
        if abs(m) > tol_deg:
            violations.append(name)
    return {"ok": not violations, "tol_deg": float(tol_deg),
            "channels": channels, "worst": worst, "violations": violations}


# --------------------------------------------------------------------------
# Task presets: per-task Cardan rotation order + static-offset default
# --------------------------------------------------------------------------
#
# A beginner picks a TASK ("walk"/"run"/...), not a rotation sequence. Each
# preset maps the joint base name (HIP/KNEE/ANKLE) to the Cardan/Euler order
# fed to ``jcs_angles`` and whether a static-offset subtraction is on by default.
#
# Rationale (Visual3D Joint Angle doc; Vicon Plug-in-Gait FAQ; ISB Wu 2002):
#   * Visual3D lets you choose the rotation order per joint; its default for all
#     joints is x-y-z = JCS (Grood-Suntay).
#   * HIP & KNEE: "xyz" is the Grood-Suntay/ISB standard and matches our SCS
#     (x=ML, y=AP, z=long) -> FE -> AB/AD -> IE. Used for every task.
#   * ANKLE: the clinical gait standard (Plug-in-Gait) decomposes the ankle in a
#     different order; in our SCS that maps to "xzy" (FE about ML -> IE about long
#     -> inv/eversion about AP). This keeps dorsi/plantar-flexion as the primary
#     (first-extracted) axis, which is the clinically dominant ankle motion in
#     walking. We apply "xzy" to the ankle for walk/run only.
#   * static offset: NOT a Visual3D default -- it is an opt-in convention where a
#     subject's neutral standing (static) joint angles are subtracted so the
#     dynamic curves are zero-referenced to the subject's own neutral. We default
#     it ON for gait (walk/run), where a subject-relative zero is conventional,
#     and OFF elsewhere.
#
# UNCERTAIN / conservative choices (do not over-claim):
#   * run ANKLE order: running ankle kinematics are usually reported with the same
#     PiG-style decomposition as walking, so we reuse "xzy". Literature is less
#     explicit for running than walking -- flagged here, easy to revert per-task.
#   * jump/balance/generic: no single field convention -> kept fully "xyz" (the
#     Visual3D default) with offset OFF. We deliberately do NOT impose an ankle
#     reorder for jump (no established standard).
#
# Keys are ENGLISH only (UI owns any Korean labels). Available task keys:
#   "walk", "run", "jump", "balance", "generic" (default).
TASK_PRESETS = {
    "walk":    {"sequence": {"HIP": "xyz", "KNEE": "xyz", "ANKLE": "xzy"},
                "static_offset": True},
    "run":     {"sequence": {"HIP": "xyz", "KNEE": "xyz", "ANKLE": "xzy"},
                "static_offset": True},
    "jump":    {"sequence": {"HIP": "xyz", "KNEE": "xyz", "ANKLE": "xyz"},
                "static_offset": False},
    "balance": {"sequence": {"HIP": "xyz", "KNEE": "xyz", "ANKLE": "xyz"},
                "static_offset": False},
    "generic": {"sequence": {"HIP": "xyz", "KNEE": "xyz", "ANKLE": "xyz"},
                "static_offset": False},
}

# Map a joint angle name (e.g. "R_ANKLE_angle") to its preset base key.
_PRESET_JOINT_BASES = ("HIP", "KNEE", "ANKLE")


def task_preset(task):
    """Return the preset dict for ``task`` (falls back to "generic" for unknown
    or None). Keys: ``sequence`` ({base: cardan order}) and ``static_offset``
    (bool default). Pure lookup, no side effects."""
    return TASK_PRESETS.get(task or "generic", TASK_PRESETS["generic"])


def _sequence_for_angle(name, preset):
    """Pick the Cardan sequence for a joint-angle name from a task preset, by
    matching the joint base (HIP/KNEE/ANKLE) in the name. Defaults to "xyz"."""
    upper = name.upper()
    seqmap = preset.get("sequence", {})
    for base in _PRESET_JOINT_BASES:
        if base in upper:
            return seqmap.get(base, "xyz")
    return "xyz"


# --------------------------------------------------------------------------
# Label normalisation + capability-based role aliases (researcher design)
# --------------------------------------------------------------------------
#
# Real C3D label streams vary a lot between marker sets (Plug-in-Gait, CGM2,
# Helen Hayes, CODA, Rab upper limb) and labs. Two failure modes hit real data:
#
#   1. MEDIAL markers as a SUFFIX. PiG/CGM2 label the knee/ankle medial markers
#      as e.g. ``RKNM`` / ``RANM`` (side + base + trailing 'M'), or sometimes as
#      ``LMED`` (a bare 'MED' core). The legacy ``_parse_joint_label`` only knew
#      the *prefix* form (``RMKNEE``), so suffix-medial labels were never paired
#      and the joint centre could not be built.
#   2. Subject PREFIX. Vicon multi-subject trials prefix every label with the
#      subject name and a colon, e.g. ``Subject:RASI``. Reading the side from the
#      FIRST character then breaks (the side letter is buried after the colon).
#
# ``normalize_label`` fixes both by (a) dropping any ``...:`` subject prefix and
# (b) extracting a leading L/R (or LEFT/RIGHT) side with an optional separator,
# leaving an upper-cased, separator-free CORE for alias matching. A SIDE SUFFIX
# rule (``...R`` / ``...L``) is intentionally left OFF by default: a trailing
# letter is a very common part of real core names (e.g. ``SACR`` ends in 'R',
# ``WRA`` in 'A'... ``HEE`` etc.) so a suffix-side rule produces false positives.


def normalize_label(raw, side_suffix=False):
    """Normalise one raw marker label into ``{raw, side, core}`` (pure function).

    Steps:
      * Drop any subject prefix: text up to and including the LAST ``:`` is
        removed (``Subject:RASI`` -> ``RASI``).
      * Extract a leading side: ``L``/``R`` or ``LEFT``/``RIGHT`` (case-insensitive),
        optionally followed by a single separator in ``[ _.-]``. ``side`` becomes
        ``"R"``/``"L"`` (or ``""`` if none).
      * The remaining text is upper-cased with all ``[ _.-]`` separators removed
        to give ``core`` (e.g. ``R_KNE`` -> core ``KNE`` side ``R``;
        ``Subject:LANK_MED`` -> core ``ANKMED`` side ``L``).

    ``side_suffix`` (default False, OFF on purpose -- high false-positive risk):
      when True, a trailing single ``R``/``L`` on the core is also accepted as the
      side if no leading side was found. Left as an opt-in only.

    Returns a dict ``{"raw": raw, "side": side, "core": core}``.
    """
    raw = "" if raw is None else str(raw)
    s = raw.strip()
    if ":" in s:                       # drop subject prefix (last colon wins)
        s = s.rsplit(":", 1)[-1]
    s = s.strip()

    side = ""
    body = s
    up = s.upper()
    # leading LEFT/RIGHT word (optionally with a separator)
    for word, sd in (("RIGHT", "R"), ("LEFT", "L")):
        if up.startswith(word):
            rest = s[len(word):]
            if rest[:1] in (" ", "_", ".", "-"):
                rest = rest[1:]
            side, body = sd, rest
            break
    else:
        # leading single R/L, only when followed by a separator OR more letters
        # (so a lone "R" marker isn't swallowed into an empty core).
        if up[:1] in ("R", "L") and len(s) > 1:
            sep = s[1:2]
            if sep in (" ", "_", ".", "-"):
                side, body = up[0], s[2:]
            else:
                side, body = up[0], s[1:]

    core = "".join(ch for ch in body.upper() if ch not in " _.-")

    if not side and side_suffix and core[-1:] in ("R", "L"):
        side, core = core[-1], core[:-1]

    if not core:                       # a bare "R"/"L" label: keep it as the core
        side, core = "", s.upper().replace(" ", "").replace("_", "")
    return {"raw": raw, "side": side, "core": core}


# Role -> (exact-match cores, substring cores). Exact matches are tried FIRST so
# short ambiguous codes (e.g. "ANK") don't get shadowed by a substring rule; the
# substring set then catches longer/compound cores. Cores are the separator-free
# upper-case form from ``normalize_label`` (the side is already stripped).
#
# Sourcing: ASIS/PSIS/SACR and the medial/lateral knee&ankle codes are 1st-party
# confirmed (Plug-in-Gait, CGM2, CODA IAS/IPS, ISB). Items marked 'unverified'
# below could NOT be confirmed from a primary marker-set document by the
# researcher and are best-effort guesses -- keep them, but do not over-trust.
ROLE_ALIASES = {
    # ----- pelvis -----
    "asis":     ({"ASI", "ASIS", "IAS"}, {"ASIS", "ASI"}),
    "psis":     ({"PSI", "PSIS", "IPS"}, {"PSIS", "PSI"}),
    "sacrum":   ({"SACR", "SACRUM", "SACR0", "S2"}, {"SACR"}),
    # ----- knee -----
    # KNE (lat) / KNM (med) are PiG/CGM2-confirmed. LFC/MFC are the anatomical
    # condyle names (lat./med. femoral condyle); the 3-letter ABBREVIATIONS could
    # NOT be tied to a primary marker-set doc -> kept but 'still unverified'.
    "knee_lat": ({"KNE", "LKNE", "KNEE", "LFC"},          # LFC still unverified
                 {"LKNEE", "LATKNEE", "KNEELAT", "LFC"}),
    "knee_med": ({"KNM", "MKNE", "MED", "MFC"},           # MFC still unverified
                 {"MKNEE", "MEDKNEE", "KNEEMED", "KNM", "MFC"}),
    # ----- ankle -----
    # Side prefixes are STRIPPED by normalize_label, so cores must be side-less:
    #   ANK = lateral malleolus (PiG/OFM). Bare ANK -> lateral.
    # (Old LANK/LM here were dead/harmful: 'L' is taken as the side, leaving the
    #  empty/ambiguous cores ANK/'M'.)
    "ankle_lat": ({"ANK", "ANKLE"},
                  {"LANKLE", "LATANK", "ANKLAT", "LMAL"}),
    # Medial malleolus, side-less cores: MMA (OFM), MM (Helen Hayes), ANM (PiG
    # condensed). MED kept but 'still unverified' (also used by knee_med).
    # (Old MANK removed: collides with lateral once normalised.)
    "ankle_med": ({"ANM", "MM", "MMA", "MED"},            # MED still unverified
                  {"MANKLE", "MEDANK", "ANKMED", "ANM", "MMAL"}),
    # ----- foot -----
    # CAL/CALC = calcaneus; bare 'CA' removed (too short -> false positives).
    "heel":     ({"HEE", "HEEL", "CAL"}, {"HEEL", "HEE", "CALC"}),
    # TOE/MET = toe (2nd-MT / forefoot long axis). SMH = IOR 2nd-MT head (on the
    # foot long axis, correct for toe). Removed: FMH (IOR 1st-MT head, MEDIAL --
    # different landmark) and TOE1 (not in any standard marker set).
    "toe":      ({"TOE", "MET", "SMH"}, {"TOE", "MET"}),
}

# Side-less trunk landmark aliases (no L/R). Used by the upper-limb detector.
TRUNK_ALIASES = {
    "c7":  ({"C7", "CV7"}, {"C7"}),
    "t8":  ({"T8", "TV8"}, {"T8"}),
    "ij":  ({"IJ", "SJN", "STRN", "CLAV"}, {"CLAV", "STERN"}),   # suprasternal notch
    "px":  ({"PX", "PXI", "STRNPX"}, {"XIPH"}),                  # xiphoid process
}


def _match_role(core, aliases):
    """Return the first role in ``aliases`` matching ``core`` (exact set first,
    then substring set), else ``None``. Pure lookup."""
    for role, (exact, _) in aliases.items():
        if core in exact:
            return role
    for role, (_, subs) in aliases.items():
        if any(sub in core for sub in subs):
            return role
    return None


# --------------------------------------------------------------------------
# Auto-build (naming-convention suggestions; user reviews/edits in the dialog)
# --------------------------------------------------------------------------

# Proximal -> distal joint ordering used to chain segments per side.
_JOINT_ORDER = ["HIP", "KNEE", "ANKLE", "MTP",
                "SHOULDER", "ELBOW", "WRIST", "TRUNK", "PELVIS"]
_FOOT_KEYS = ("MET", "TOE", "HEEL")


def _parse_joint_label(label):
    """Return (side, m_or_l, base) for a side+(M|L)+joint label like 'RMKNEE',
    else None. side in {R,L}; m_or_l in {M,L}.

    Legacy PREFIX form only (``RMKNEE``/``RLKNEE``). Suffix-medial labels
    (``RKNM``) and subject-prefixed labels are handled by ``detect_roles`` /
    ``normalize_label`` instead; this helper is retained for backward
    compatibility and as the fast path for the canonical PiG prefix style.
    """
    if len(label) < 3:
        return None
    side = label[0].upper()
    ml = label[1].upper()
    if side in ("R", "L") and ml in ("M", "L") and label[2:].strip():
        return side, ml, label[2:].upper()
    return None


def detect_roles(labels, side_suffix=False):
    """Capability-based marker-role detection (researcher Step C).

    Normalises every label (subject-prefix stripped, side extracted) and maps it
    to a standard ROLE via :data:`ROLE_ALIASES` (lower-limb + pelvis) and
    :data:`TRUNK_ALIASES` (side-less trunk). Returns::

        {role: {side: raw_label}}

    where ``side`` is ``"R"``/``"L"`` for sided roles and ``"_"`` for trunk
    landmarks. Only roles whose markers exist appear (missing -> absent).

    This is the single consumer of the alias tables for the LOWER limb + pelvis;
    it catches BOTH the prefix-medial (``RMKNEE``) and suffix-medial (``RKNM``)
    forms, and is subject-prefix safe. The first label to claim a (role, side)
    wins (stable, input order); duplicates are ignored.
    """
    out = {}
    for lab in labels:
        norm = normalize_label(lab, side_suffix=side_suffix)
        core, side = norm["core"], norm["side"]
        role = _match_role(core, ROLE_ALIASES)
        if role is not None and side in ("R", "L"):
            out.setdefault(role, {}).setdefault(side, lab)
            continue
        # sacrum has no side; allow a side-less (or sided) sacrum to map to "_"
        if role == "sacrum":
            out.setdefault("sacrum", {}).setdefault(side or "_", lab)
            continue
        trole = _match_role(core, TRUNK_ALIASES)
        if trole is not None:
            out.setdefault(trole, {}).setdefault("_", lab)
    return out


# --------------------------------------------------------------------------
# Upper-limb (ISB; Wu et al. 2005) capability detection + role aliases
# --------------------------------------------------------------------------
#
# Labs label upper-limb markers very differently. We map any such label to a
# standard ROLE by substring, with an R/L prefix giving the side. Roles:
#   acromion        -> SHOULDER JC (single-landmark surface estimate)
#   epi_m / epi_l   -> medial / lateral humeral epicondyle (ELBOW JC = midpoint)
#   styloid_u / _r  -> ulnar / radial styloid (WRIST JC = midpoint; ulnar = ML)
#   hand            -> a distal hand/finger marker (optional HAND segment)
# and the (side-less) trunk landmarks: ij (suprasternal notch/CLAV), c7, px
# (xiphoid), t8.
#
# Cardan/Euler sequences are chosen per ISB and mapped to THIS module's SCS
# (columns x=ML right, y=AP anterior, z=long up):
#   * SHOULDER: ISB recommends a Y-X-Y *proper-Euler* order (plane of elevation
#     / elevation / axial rotation) about the humeral long axis. Our long axis
#     is z, so that maps to "zxz" (long -> ML -> long). The "_FE/_AB/_IE"
#     channels then read as (plane-of-elevation / elevation / axial-rotation);
#     the generic FE/AB/IE labels are kept for a uniform channel schema.
#   * ELBOW: ISB Z(flex/ext)-X(carrying)-Y(pro/supination). Flexion is our
#     dominant motion about ML (x) and pro/supination is about the long axis
#     (z), so we use "xyz": FE(flex/ext) -> AB(carrying/varus-valgus) ->
#     IE(pronation+/supination-).
#   * WRIST: ISB Z(flex/ext)-X(radial/ulnar dev)-Y. -> "xyz": FE(flex/ext) ->
#     AB(radial+/ulnar- deviation) -> IE(forearm axial residual).
# These are task-independent (unlike the gait TASK_PRESETS).
_UPPER_SEQUENCE = {"SHOULDER": "zxz", "ELBOW": "xyz", "WRIST": "xyz"}


def _detect_upper(labels):
    """Detect upper-limb marker roles by substring (ISB landmark names + common
    lab aliases). Returns ``{side: {role: label}}`` for sides "R"/"L" plus a
    side-less ``{"TRUNK": {role: label}}`` for thorax landmarks. Only roles whose
    markers exist are present (capability-based; missing -> simply absent)."""
    out = {"R": {}, "L": {}, "TRUNK": {}}

    for lab in labels:
        # normalize_label drops any subject prefix (``Subject:RELB``) and pulls
        # off the leading R/L side, returning a separator-free upper-case core --
        # so the substring rules below are both side-correct and prefix-safe.
        norm = normalize_label(lab)
        side = norm["side"]
        core = norm["core"]

        # --- trunk / thorax landmarks (side-less) ---
        if core in ("C7", "CV7") or core.startswith("C7"):
            out["TRUNK"]["c7"] = lab; continue
        if core in ("T8", "TV8") or core.startswith("T8"):
            out["TRUNK"]["t8"] = lab; continue
        if "CLAV" in core or core in ("IJ", "SJN", "STRN") or "STERN" in core:
            # IJ / suprasternal notch (CLAV is the Plug-in-Gait clavicle/IJ marker)
            out["TRUNK"].setdefault("ij", lab); continue
        if core in ("PX", "PXI") or "XIPH" in core or core == "STRNPX":
            out["TRUNK"]["px"] = lab; continue

        # --- arm landmarks (need a side) ---
        if not side:
            continue
        # medial / lateral epicondyle: prefix M/L + epicondyle name
        if any(t in core for t in ("MEPI", "MEL", "MHE", "MEPC", "MEPL")) or core.startswith("MEP"):
            out[side]["epi_m"] = lab; continue
        if any(t in core for t in ("LEPI", "LEL", "LHE", "LEPC", "LEPL")) or core.startswith("LEP"):
            out[side]["epi_l"] = lab; continue
        # styloids: ulnar (medial, ML-side) vs radial (lateral). The PiG wrist-bar
        # codes WRA/WRB are CONFIRMED (Plug-in-Gait Marker Placement; Visual3D PiG
        # full-body): WRA sits on the THUMB/RADIAL (lateral) side -> radial styloid,
        # WRB on the PINKY/ULNAR (medial) side -> ulnar styloid.
        if any(t in core for t in ("USP", "ULN", "WRB", "STYU")) or core.startswith("US"):
            out[side]["styloid_u"] = lab; continue   # WRB = ulnar (pinky side)
        if any(t in core for t in ("RSP", "RAD", "WRA", "STYR")) or core.startswith("RS"):
            out[side]["styloid_r"] = lab; continue   # WRA = radial (thumb side)
        # acromion / shoulder (avoid SACRum / ACETabulum false matches)
        if (any(t in core for t in ("ACR", "SHO", "ACROM")) or core == "AC") \
                and not any(bad in core for bad in ("SACR", "ACET")):
            out[side].setdefault("acromion", lab); continue
        # hand / finger marker (optional)
        if any(t in core for t in ("HAND", "FIN", "MCP", "MC3", "MH3")):
            out[side].setdefault("hand", lab); continue

    return out


def _detect_pelvis(labels):
    """Find pelvis landmark markers (ASIS/PSIS/sacrum) via the normalised alias
    layer, so it is subject-prefix safe (``Subject:RASI``) and accepts the CODA
    variants (``LIAS``/``RIAS`` -> ASIS, ``LIPS``/``RIPS`` -> PSIS) as well as
    the Plug-in-Gait names. Returns ``{asis_l, asis_r, psis_l, psis_r, sacrum}``
    (only present keys)."""
    roles = detect_roles(labels)
    res = {}
    for role, key in (("asis", "asis"), ("psis", "psis")):
        sided = roles.get(role, {})
        if sided.get("R"):
            res[f"{key}_r"] = sided["R"]
        if sided.get("L"):
            res[f"{key}_l"] = sided["L"]
        if sided.get(""):                      # side-less ASIS/PSIS (rare)
            res[key] = sided[""]
    sac = roles.get("sacrum", {})
    if sac:
        res["sacrum"] = next(iter(sac.values()))
    return res


# Condensed cores of SEGMENT/cluster names (side already stripped, separators
# removed, upper-cased). A marker whose core CONTAINS one of these is a tracking-
# cluster marker named after the segment, never a joint landmark. Kept as whole
# words so they only fire on real segment names -- e.g. "SHANK" (-> guards
# Shank_F/Shank_B, whose core "SHANKF"/"SHANKB" embeds the ankle token "ANK")
# and "THIGH"/"THI" (thigh clusters). Joint-landmark cores (KNEE/ANKLE/LMAL/...)
# never contain these, so genuine landmarks are unaffected.
_SEGMENT_CLUSTER_CORES = ("SHANK", "THIGH", "SHIN", "TIBIA", "FEMUR", "TRUNK")


def detect_knee_ankle(labels, exclude=None):
    """Detect medial/lateral KNEE & ANKLE markers, prefix- AND suffix-medial.

    Returns ``{(side, base): {"M": label, "L": label}}`` for base in
    ``{"KNEE","ANKLE"}`` and side in ``{"R","L"}``, including only the medial/
    lateral keys that exist. ``exclude`` is a set of labels already claimed by
    another role (e.g. the upper limb) to skip.

    This is the bug-fix for suffix-medial labels. Determination of medial vs
    lateral from the side-stripped, separator-free ``core``:

      * core STARTS with 'M' (prefix-medial: ``MKNE``/``MANK``)   -> medial
      * core STARTS with 'L' (prefix-lateral: ``LKNE``/``LANK``)  -> lateral
      * core ENDS  with 'M' (suffix-medial:  ``KNM``/``ANM``)     -> medial
      * core ENDS  with 'L' (suffix-lateral: rare, ``KNL``)       -> lateral
      * a bare base (``KNE``/``ANK``)                             -> LATERAL

    The bare-base = LATERAL rule follows Plug-in-Gait, where the single
    permanent marker (``RKNE``/``RANK``) sits over the lateral epicondyle /
    lateral malleolus and the medial marker (``RKNM``/``RMED``/``RANM``) is an
    extra calibration marker. Condyle/malleolus codes (LFC/MFC, LM/MM) are also
    recognised. The first label to claim a (side, base, M|L) slot wins.
    """
    exclude = set(exclude or ())
    out = {}
    for lab in labels:
        if lab in exclude:
            continue
        norm = normalize_label(lab)
        core, side = norm["core"], norm["side"]
        if side not in ("R", "L"):
            continue
        # Reject SEGMENT-named tracking-cluster markers before any joint match.
        # Cluster markers are named after the SEGMENT (Thigh_F, Shank_B, ...) and
        # their condensed cores embed a joint abbreviation by accident -- most
        # notably "SHANK" contains "ANK", so the substring test below would mis-
        # read "RShank_F" as the lateral malleolus. A marker named for a segment
        # is never a joint medial/lateral landmark, so skip it outright.
        if any(seg in core for seg in _SEGMENT_CLUSTER_CORES):
            continue
        # identify the joint base from the core. NB: the condensed PiG medial
        # codes drop a letter -- ``KNM`` (knee medial) has no "KNE", ``ANM``
        # (ankle medial) has no "ANK" -- so they are matched explicitly.
        if "KNE" in core or core in ("LFC", "MFC", "KNM"):
            base = "KNEE"
        elif "ANK" in core or core in ("LM", "MM", "MMA", "LMAL", "MMAL",
                                       "ANM", "MED", "MMAL"):
            # bare MED / MM = medial MALLEOLUS (ankle) in Plug-in-Gait
            # convention (unverified for knee-medial labs; ankle is the PiG norm).
            base = "ANKLE"
        else:
            continue
        # medial / lateral disambiguation (explicit condensed codes, then prefix,
        # then suffix, then condyle code, then bare base = lateral).
        ml = None
        if core in ("MFC", "MM", "MMA", "MMAL", "KNM", "ANM", "MED"):
            ml = "M"
        elif core in ("LFC", "LM", "LMAL"):
            ml = "L"
        elif core[:1] == "M":
            ml = "M"
        elif core[:1] == "L":
            ml = "L"
        elif core[-1:] == "M":
            ml = "M"
        elif core[-1:] == "L":
            ml = "L"
        else:
            ml = "L"                      # bare KNE/ANK -> lateral (Plug-in-Gait)
        out.setdefault((side, base), {}).setdefault(ml, lab)
    return out


def auto_build_model(static_markers, name="auto", task="generic"):
    """Suggest an anatomical MarkerModel from a static trial's labels (Visual3D
    style segments). Joints: hip (pelvis regression) + knee/ankle (medial/lateral
    midpoint). Segments: PELVIS / THIGH / SHANK / FOOT, each carrying a segment
    coordinate system (``frame``). Angles: HIP/KNEE/ANKLE as signed JCS (Cardan)
    3-component angles (``mode="jcs"``); each is emitted as ``<name>_FE`` /
    ``<name>_AB`` / ``<name>_IE`` channels. All editable.

    ``task`` selects per-joint Cardan rotation orders from ``TASK_PRESETS``
    (English keys: "walk"/"run"/"jump"/"balance"/"generic"). The default
    "generic" keeps every joint at sequence "xyz" -- identical to the previous
    behaviour (backward compatible). "walk"/"run" set the ANKLE to "xzy" (the
    clinical Plug-in-Gait decomposition order in our SCS); HIP/KNEE stay "xyz".

    Sequence "xyz": with our SCS (x=ML, y=AP, z=long) this equals the
    Grood-Suntay / ISB JCS ordering flexion-extension -> ab/adduction ->
    internal/external rotation (Visual3D "XYZ = JCS"). The static-offset default
    in the preset is advisory metadata only; auto-build does not subtract
    offsets (that is opt-in via ``MarkerModel.apply(offsets=...)``).
    """
    preset = task_preset(task)
    labels = list(static_markers["labels"])

    def is_foot(lab):
        u = lab.upper()
        return any(k in u for k in _FOOT_KEYS)

    def find_tib_tuberosity(side):
        """Detect a tibial-tuberosity / anterior-tibia marker (TT/TTC/TIB/TUB).

        NOTE: this is detected but intentionally NOT used as the SHANK plane
        point. ``segment_frame`` expects a LATERAL (ML-direction) plane marker to
        fix the frontal plane; a tibial tuberosity is an ANTERIOR landmark, so
        feeding it to ``segment_frame`` would rotate the SCS ~90 deg about the
        long axis and leak into internal/external rotation. We therefore keep the
        conservative lateral-ankle (malleolus) plane point. Kept here so a future
        AP-based foot/shank frame builder can use it without re-detecting.
        """
        for lab in labels:
            norm = normalize_label(lab)
            if norm["side"] != side:
                continue
            core = norm["core"]
            if any(p in core for p in ("TT", "TTC", "TIB", "TUB")):
                return lab
        return None

    # --- upper-limb capability detection (so its markers are excluded from the
    # lower-limb medial/lateral pairing and tracking clusters below) ---
    upper = _detect_upper(labels)
    upper_set = {lab for grp in upper.values() for lab in grp.values()}

    # --- pelvis landmarks + hip joints (regression) ---
    pel = _detect_pelvis(labels)
    pelvis_markers = [pel[k] for k in ("asis_l", "asis_r", "psis_l", "psis_r", "sacrum") if pel.get(k)]
    pelvis_set = set(pelvis_markers)
    has_hip = bool(pel.get("asis_l") and pel.get("asis_r")
                   and (pel.get("sacrum") or (pel.get("psis_l") and pel.get("psis_r")))
                   and len(pelvis_markers) >= 3)

    joints = []
    jc_marker_labels = set()
    if has_hip:
        for side in ("R", "L"):
            hip = {"name": f"{side}_HIP", "method": "hip", "side": side,
                   "asis_l": pel["asis_l"], "asis_r": pel["asis_r"],
                   "cluster": list(pelvis_markers)}
            if pel.get("psis_l") and pel.get("psis_r"):
                hip["psis_l"], hip["psis_r"] = pel["psis_l"], pel["psis_r"]
            if pel.get("sacrum"):
                hip["sacrum"] = pel["sacrum"]
            joints.append(hip)

    # --- knee/ankle joints: pair medial(M)/lateral(L) by (side, base) ---
    # detect_knee_ankle handles BOTH prefix-medial (RMKNEE) and suffix-medial
    # (RKNM/RMED/RANM) labels and is subject-prefix safe (the real-data bug fix).
    # The pelvis markers must be excluded so the bare 'MED'/'ANK' rules can't
    # claim a pelvis label.
    by_key = detect_knee_ankle(labels, exclude=upper_set | pelvis_set)

    # Trans-epicondylar / trans-malleolar MEDIAL+LATERAL pairs for the
    # cluster-embedded (CAST) ML axis. We re-run detect_knee_ankle with the thigh/
    # shank TRACKING markers excluded, because a tracking label like ``RShank_F``
    # normalises to core ``SHANKF`` which incidentally CONTAINS "ANK" and would
    # otherwise be mis-claimed as the lateral malleolus (a latent first-wins
    # collision in detect_knee_ankle). Excluding tracking markers here yields the
    # TRUE medial/lateral malleolus & epicondyle pair for the anatomical ML line.
    def _is_track_marker(lab):
        core = normalize_label(lab)["core"]
        return any(t in core for t in ("THIGH", "SHANK", "THI", "TIB"))
    track_set = {l for l in labels if _is_track_marker(l)}
    ml_pairs = detect_knee_ankle(labels, exclude=upper_set | pelvis_set | track_set)

    # Map each label to its normalised side once (subject-prefix safe), so the
    # tracking-cluster side test below survives ``Subject:RTHI`` style labels.
    side_of_label = {l: normalize_label(l)["side"] for l in labels}

    # lateral_marker[(side, "KNEE"|"ANKLE")] -> the body-surface lateral marker,
    # reused as the frontal-plane point for THIGH (lateral knee) and FOOT
    # (lateral malleolus) so segment frames are non-collinear.
    lateral_marker = {}
    for (side, base), d in by_key.items():
        if "M" in d and "L" in d:
            joints.append({"name": f"{side}_{base}", "method": "midpoint",
                           "medial": d["M"], "lateral": d["L"], "cluster": []})
            jc_marker_labels.update([d["M"], d["L"]])
            lateral_marker[(side, base)] = d["L"]

    # tracking cluster for midpoint joints = same-side limb markers (excl. JC,
    # foot and pelvis markers), plus the lateral marker itself.
    for j in joints:
        if j.get("method") == "hip":
            continue
        side = j["name"][0]
        track = [l for l in labels if side_of_label.get(l) == side
                 and l not in jc_marker_labels and l not in pelvis_set
                 and l not in upper_set and not is_foot(l)]
        j["cluster"] = list(dict.fromkeys(track + [j["lateral"]]))

    have = {j["name"] for j in joints}
    segments, angles = [], []

    # --- PELVIS segment: pelvic midline AP axis (mid-PSIS -> mid-ASIS virtual
    # points computed in apply()), per ISB / Plug-in Gait. Symmetric L/R. The
    # ``frame`` builds the ISB pelvis SCS (ASIS pair + mid-PSIS) for HIP JCS. ---
    if has_hip:
        segments.append({
            "name": "PELVIS", "proximal": "PELVIS_POST", "distal": "PELVIS_ANT",
            "frame": {"type": "pelvis", "rasis": pel["asis_r"],
                      "lasis": pel["asis_l"], "psis": "PELVIS_POST"}})

    def is_heel(lab):
        u = lab.upper()
        return any(k in u for k in ("HEE", "HEEL", "CAL"))

    def is_toe(lab):
        u = lab.upper()
        return any(k in u for k in ("TOE", "MET"))

    # Segment-specific TRACKING-cluster detection for the cluster-embedded (CAST)
    # THIGH/SHANK frames. A thigh cluster is the thigh-mounted tracking markers
    # (e.g. RThigh_F/RThigh_B, RTHI), a shank cluster the shank-mounted ones
    # (RShank_F/RShank_B, RTIB). We add the segment's distal LATERAL marker
    # (lateral knee / lateral malleolus) as a cluster member when present so a
    # 2-marker thigh/shank wand still reaches the >=3 needed for a rigid fit.
    # True anatomical knee/ankle landmark markers (collision-free, from ml_pairs),
    # excluded from tracking clusters so an epicondyle/malleolus is not double-used.
    _landmark_set = {lab for d in ml_pairs.values() for lab in d.values()}

    def _seg_cluster_markers(side, cores):
        out = []
        for lab in labels:
            norm = normalize_label(lab)
            if norm["side"] != side:
                continue
            if (lab in pelvis_set or lab in upper_set or lab in _landmark_set
                    or is_foot(lab)):
                continue
            if any(c in norm["core"] for c in cores):
                out.append(lab)
        return out

    # --- per-side anatomical segments + single joint angles ---
    for side in ("R", "L"):
        def jn(base):
            return f"{side}_{base}" if f"{side}_{base}" in have else None
        hip, knee, ankle = jn("HIP"), jn("KNEE"), jn("ANKLE")
        side_feet = [l for l in labels if side_of_label.get(l) == side and is_foot(l)]
        heel = next((l for l in side_feet if is_heel(l)), None)
        toe = next((l for l in side_feet if is_toe(l)), None)
        lat_knee = lateral_marker.get((side, "KNEE"))
        lat_ankle = lateral_marker.get((side, "ANKLE"))
        # Anatomical ML pair (collision-free; see ml_pairs). The LATERAL member is
        # also the preferred cluster-frame ML lateral marker -- it is the genuine
        # epicondyle/malleolus, not a tracking marker that merely contains "ANK".
        knee_pair = ml_pairs.get((side, "KNEE"), {})
        ankle_pair = ml_pairs.get((side, "ANKLE"), {})
        med_knee, lat_knee_ml = knee_pair.get("M"), knee_pair.get("L")
        med_ankle, lat_ankle_ml = ankle_pair.get("M"), ankle_pair.get("L")
        thigh_cluster = _seg_cluster_markers(side, ("THI",))
        shank_cluster = _seg_cluster_markers(side, ("SHA", "SHANK", "TIB"))
        tib_tub = find_tib_tuberosity(side)
        thigh = shank = foot = None
        if hip and knee:
            thigh = f"{side}_THIGH"
            seg = {"name": thigh, "proximal": hip, "distal": knee}
            # SCS: origin=KNEE(JC), long=HIP(JC). The ML axis comes from a
            # CLUSTER-EMBEDDED (CAST, Cappozzo 1995) anatomical axis when a true
            # medial+lateral knee marker pair + a >=3-marker thigh tracking cluster
            # exist on the static: the trans-epicondylar (knee flexion) line is
            # defined once in the static and transported rigidly by the thigh
            # cluster each frame, so a single lateral marker's soft-tissue wobble
            # can no longer swing the frontal plane (the cause of inflated hip
            # internal/external-rotation cross-talk). The single lateral knee
            # marker is kept as ``plane`` for the LEGACY fallback (old saved models,
            # or trials lacking the medial marker / cluster). If neither is
            # available the frame is omitted (legacy vector angle).
            cluster = list(dict.fromkeys(
                thigh_cluster + ([lat_knee_ml] if lat_knee_ml else [])))
            if med_knee and lat_knee_ml and len(cluster) >= 3:
                seg["frame"] = {"origin": knee, "long": hip,
                                "plane": lat_knee or lat_knee_ml,
                                "side": side, "ml_source": "cluster",
                                "ml_medial": med_knee, "ml_lateral": lat_knee_ml,
                                "cluster": cluster}
            elif lat_knee:
                seg["frame"] = {"origin": knee, "long": hip, "plane": lat_knee,
                                "side": side, "ml_source": "marker"}
            segments.append(seg)
        if knee and ankle:
            shank = f"{side}_SHANK"
            seg = {"name": shank, "proximal": knee, "distal": ankle}
            # SCS: origin=ANKLE(JC), long=KNEE(JC). Same CLUSTER-EMBEDDED (CAST) ML
            # as the thigh: the trans-malleolar line (medial+lateral malleolus)
            # defines the shank's anatomical ML on the static and is transported by
            # the shank tracking cluster. Legacy fallback = the single lateral
            # malleolus ``plane`` marker (a TRUE ML landmark; a tibial tuberosity,
            # being anterior, would mis-rotate the frame -- see find_tib_tuberosity;
            # tib_tub is detected only for a future AP-frame builder).
            _ = tib_tub
            cluster = list(dict.fromkeys(
                shank_cluster + ([lat_ankle_ml] if lat_ankle_ml else [])))
            if med_ankle and lat_ankle_ml and len(cluster) >= 3:
                seg["frame"] = {"origin": ankle, "long": knee,
                                "plane": lat_ankle or lat_ankle_ml,
                                "side": side, "ml_source": "cluster",
                                "ml_medial": med_ankle, "ml_lateral": lat_ankle_ml,
                                "cluster": cluster}
            elif lat_ankle:
                seg["frame"] = {"origin": ankle, "long": knee, "plane": lat_ankle,
                                "side": side, "ml_source": "marker"}
            segments.append(seg)
        # Foot (Visual3D): heel -> toe long axis. Fall back to ankle -> a foot
        # marker when heel/toe aren't both present. SCS: origin=distal(toe/MET),
        # long=proximal(heel/ankle), plane=lateral malleolus (lateral ankle).
        #
        # NB: Visual3D's "simple foot" nominally uses the ANKLE JOINT CENTRE as
        # the third (plane) point. We tested that here and REJECTED it: the ankle
        # JC = midpoint(med, lat malleolus) sits ON the foot's sagittal plane
        # (ML ~ 0), so heel/toe/ankle-JC become near-coplanar with the FE axis ->
        # the foot frame's frontal plane is near-degenerate. A 10 mm medio-lateral
        # heel-marker shift then swung the ankle inv/ev by ~150 deg (vs ~8 deg
        # with the lateral malleolus). We therefore keep the lateral malleolus as
        # the plane point (numerical stability over nominal standard-matching) and
        # instead flag the ankle inv/ev & rotation channels as low-reliability via
        # ``angle_reliability`` (see Step 2 of the foot/ankle redesign).
        if heel and toe:
            foot = f"{side}_FOOT"
            seg = {"name": foot, "proximal": heel, "distal": toe}
            if lat_ankle:
                seg["frame"] = {"origin": toe, "long": heel, "plane": lat_ankle, "side": side}
            segments.append(seg)
        elif ankle and side_feet:
            foot = f"{side}_FOOT"
            distal_foot = sorted(side_feet)[0]
            seg = {"name": foot, "proximal": ankle, "distal": distal_foot}
            if lat_ankle and lat_ankle != distal_foot:
                seg["frame"] = {"origin": distal_foot, "long": ankle, "plane": lat_ankle, "side": side}
            segments.append(seg)
        # Angles: signed JCS (Cardan, sequence "xyz" = FE -> AB/AD -> IE).
        # A segment uses jcs only when it carries a frame; otherwise fall back to
        # the legacy unsigned vector angle so partial marker sets still work.
        seg_has_frame = {s["name"]: ("frame" in s) for s in segments}

        def add_angle(name, a, b):
            ang = {"name": name, "segment_a": a, "segment_b": b}
            if seg_has_frame.get(a) and seg_has_frame.get(b):
                ang["mode"] = "jcs"
                ang["sequence"] = _sequence_for_angle(name, preset)
            angles.append(ang)

        if any(s["name"] == "PELVIS" for s in segments) and thigh:
            add_angle(f"{side}_HIP_angle", "PELVIS", thigh)
        if thigh and shank:
            add_angle(f"{side}_KNEE_angle", thigh, shank)
        if shank and foot:
            add_angle(f"{side}_ANKLE_angle", shank, foot)

    # --- TRUNK / THORAX segment (ISB; only when the four landmarks exist) ---
    # Built from IJ-C7 (upper) and PX-T8 (lower); fewer markers -> graceful skip.
    trunk_l = upper["TRUNK"]
    has_thorax = all(k in trunk_l for k in ("ij", "c7", "px", "t8"))
    if has_thorax:
        segments.append({
            "name": "TRUNK", "proximal": trunk_l["t8"], "distal": trunk_l["ij"],
            "frame": {"type": "thorax", "ij": trunk_l["ij"], "c7": trunk_l["c7"],
                      "px": trunk_l["px"], "t8": trunk_l["t8"]}})

    # --- upper-limb joints + segments + angles (capability-based, per side) ---
    # Joint centres: SHOULDER = acromion (single-landmark surface estimate),
    # ELBOW = midpoint(medial, lateral epicondyle), WRIST = midpoint(ulnar,
    # radial styloid). Segments: UPPERARM (SHOULDER->ELBOW), FOREARM
    # (ELBOW->WRIST). Plane points are TRUE lateral/ML landmarks (lateral
    # epicondyle for the upper arm; ulnar styloid for the forearm) -- the same
    # rule as the lower limb (never a JC, never an anterior marker).
    upper_jc_labels = set()
    for side in ("R", "L"):
        u = upper[side]
        sh_jc = el_jc = wr_jc = None
        if u.get("acromion"):
            sh_jc = f"{side}_SHOULDER"
            joints.append({"name": sh_jc, "method": "marker", "side": side,
                           "landmark": u["acromion"], "cluster": []})
            upper_jc_labels.add(u["acromion"])
        if u.get("epi_m") and u.get("epi_l"):
            el_jc = f"{side}_ELBOW"
            joints.append({"name": el_jc, "method": "midpoint", "side": side,
                           "medial": u["epi_m"], "lateral": u["epi_l"], "cluster": []})
            upper_jc_labels.update([u["epi_m"], u["epi_l"]])
        if u.get("styloid_u") and u.get("styloid_r"):
            wr_jc = f"{side}_WRIST"
            joints.append({"name": wr_jc, "method": "midpoint", "side": side,
                           "medial": u["styloid_u"], "lateral": u["styloid_r"], "cluster": []})
            upper_jc_labels.update([u["styloid_u"], u["styloid_r"]])

    # Tracking clusters for the upper-limb joints: same-side upper-limb markers
    # (>=3 needed for the rigid-body reconstruction). Built after all upper JCs
    # are known so the medial markers can serve as cluster members on the static.
    for side in ("R", "L"):
        u = upper[side]
        arm_markers = [lab for lab in (u.get("acromion"), u.get("epi_m"),
                                       u.get("epi_l"), u.get("styloid_u"),
                                       u.get("styloid_r"), u.get("hand")) if lab]
        for j in joints:
            if j.get("side") != side or not j["name"].split("_")[-1] in (
                    "SHOULDER", "ELBOW", "WRIST"):
                continue
            lat = j.get("lateral")
            cl = list(dict.fromkeys(arm_markers + ([lat] if lat else [])))
            j["cluster"] = cl

    have = {j["name"] for j in joints}
    for side in ("R", "L"):
        u = upper[side]
        def jn2(base):
            return f"{side}_{base}" if f"{side}_{base}" in have else None
        sh, el, wr = jn2("SHOULDER"), jn2("ELBOW"), jn2("WRIST")
        lat_elbow = u.get("epi_l")          # lateral epicondyle = ML plane point
        # Forearm/hand frontal-plane point = the RADIAL styloid (lateral, thumb
        # side, +x for the right arm). Using the lateral landmark -- matching the
        # lower limb's lateral-knee/lateral-malleolus rule -- keeps the UPPERARM
        # and FOREARM ML axes co-directed, so a straight arm reads ~0 on all
        # three components (an ulnar plane point would add a constant 180 deg
        # axial bias that only a static offset could remove).
        rad_styloid = u.get("styloid_r")
        upperarm = forearm = None
        if sh and el:
            upperarm = f"{side}_UPPERARM"
            seg = {"name": upperarm, "proximal": sh, "distal": el}
            if lat_elbow:
                seg["frame"] = {"origin": el, "long": sh, "plane": lat_elbow, "side": side}
            segments.append(seg)
        if el and wr:
            forearm = f"{side}_FOREARM"
            seg = {"name": forearm, "proximal": el, "distal": wr}
            if rad_styloid:
                seg["frame"] = {"origin": wr, "long": el, "plane": rad_styloid, "side": side}
            segments.append(seg)

        seg_has_frame = {s["name"]: ("frame" in s) for s in segments}

        def add_upper_angle(name, a, b, base):
            ang = {"name": name, "segment_a": a, "segment_b": b}
            if seg_has_frame.get(a) and seg_has_frame.get(b):
                ang["mode"] = "jcs"
                ang["sequence"] = _UPPER_SEQUENCE.get(base, "xyz")
            angles.append(ang)

        if has_thorax and upperarm:
            add_upper_angle(f"{side}_SHOULDER_angle", "TRUNK", upperarm, "SHOULDER")
        if upperarm and forearm:
            add_upper_angle(f"{side}_ELBOW_angle", upperarm, forearm, "ELBOW")
        if forearm and u.get("hand"):
            # optional WRIST angle needs a HAND segment; build it only if a hand
            # marker exists (FOREARM JC long axis -> hand marker, plane = ulnar).
            hand_seg = f"{side}_HAND"
            seg = {"name": hand_seg, "proximal": wr, "distal": u["hand"]}
            if rad_styloid and rad_styloid != u["hand"]:
                seg["frame"] = {"origin": u["hand"], "long": wr,
                                "plane": rad_styloid, "side": side}
            segments.append(seg)
            seg_has_frame[hand_seg] = ("frame" in seg)
            add_upper_angle(f"{side}_WRIST_angle", forearm, hand_seg, "WRIST")

    # --- prune un-trackable joints (cluster < 3) and anything depending on them.
    # A joint reconstructed by a rigid cluster needs >=3 visible markers; an
    # upper-limb joint with too few same-side markers (e.g. a lone acromion) is
    # dropped, together with the segments/angles that reference it -- so a
    # partial arm marker set degrades gracefully instead of raising at
    # calibrate(). Lower-limb joints always have >=3 (pelvis/limb clusters) and
    # are unaffected. ---
    bad_joints = {j["name"] for j in joints if len(j.get("cluster", [])) < 3}
    if bad_joints:
        joints = [j for j in joints if j["name"] not in bad_joints]
        segments = [s for s in segments
                    if s["proximal"] not in bad_joints and s["distal"] not in bad_joints]
        seg_names = {s["name"] for s in segments}
        angles = [a for a in angles
                  if a["segment_a"] in seg_names and a["segment_b"] in seg_names]

    return MarkerModel(joints=joints, segments=segments, angles=angles, name=name)


def suggest_label_map(needed_labels, trial_labels):
    """For each needed label absent from trial_labels, suggest the closest
    available label (fuzzy). Returns {needed: suggested} only for missing ones."""
    have = set(trial_labels)
    out = {}
    for lab in needed_labels:
        if lab in have:
            continue
        match = difflib.get_close_matches(lab, list(trial_labels), n=1, cutoff=0.6)
        if match:
            out[lab] = match[0]
    return out
