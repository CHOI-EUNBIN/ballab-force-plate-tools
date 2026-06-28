"""Whole-body and segmental centre-of-mass (COM) engine (pure numpy, no Qt).

A lightweight Visual3D ``MODEL_COG`` equivalent: each rigid segment carries a
de Leva (1996) body-segment-parameter (BSP) pair {mass fraction, longitudinal
CoM ratio}; the segment CoM is a linear interpolation between its proximal and
distal endpoints, and the whole-body COM is the mass-weighted mean of every
*available* segment's CoM.

Design rules (researcher spec, 2026-06-22):
  * Capability-based & "safe only": never invent missing segments. A model with
    only the legs yields a partial COM (coverage < 1, ``whole_body=False``); the
    missing segments are reported, not estimated.
  * COM *position* needs only mass *ratios*, so it is computed even without a
    body mass (``body_mass=None`` -> position valid, ``mass_used_kg=None``).
  * Anti-double-counting: de Leva's TRUNK already spans the pelvis (shoulder ->
    hip centre). The PELVIS segment is therefore EXCLUDED from BSP mapping; the
    torso is captured once by the TRUNK segment (built from the shoulder-girdle
    and hip/ASIS-PSIS endpoints) — see ``BSP`` and ``body_com``.

Endpoint trajectories (proximal/distal (F,3) arrays) come from the marker model
(``MarkerModel.compute_segments`` resolves the same endpoints via ``_point_traj``).
All functions are vectorised over frames and NaN-safe (an occluded endpoint
yields NaN at that frame for that segment, which the weighted mean ignores).
"""

import numpy as np


# --------------------------------------------------------------------------
# de Leva (1996) body-segment parameters
# --------------------------------------------------------------------------
#
# Source (PRIMARY, re-verified 2026-06-23): de Leva P. (1996) "Adjustments to
# Zatsiorsky-Seluyanov's segment inertia parameters." J Biomech 29(9):1223-1230,
# Table 4 (relative mass) and the longitudinal CoM position (% of segment length
# from the PROXIMAL reference endpoint). These are the adjusted Zatsiorsky-
# Seluyanov values used by Visual3D's MODEL_COG when "Conventional"/de Leva BSPs
# are selected.
#
# Each entry: (mass_frac_female, mass_frac_male, com_ratio_female, com_ratio_male,
#              bilateral). com_ratio = distance of the segment CoM from the
# PROXIMAL endpoint, as a fraction of segment length (proximal->distal). The
# de Leva reference endpoints per segment (so the proximal/distal points the
# caller supplies match the table):
#   HEAD      vertex            -> cervicale (mid-shoulder/C7).  (no head segment
#                                  is built without head markers; ratio kept for
#                                  completeness.)
#   TRUNK     mid-shoulder (cervicale / shoulder-girdle centre) -> mid-hip
#             (midpoint of the two hip joint centres).  ** the WHOLE trunk **
#   UPPERARM  shoulder JC       -> elbow JC                     (bilateral)
#   FOREARM   elbow JC          -> wrist JC (stylion)           (bilateral)
#   HAND      wrist (stylion)   -> 3rd metacarpal/knuckle III   (bilateral)
#   THIGH     hip JC            -> knee JC                       (bilateral)
#   SHANK     knee JC           -> ankle JC (sphyrion/malleolus) (bilateral)
#   FOOT      heel              -> toe tip (acropodion)          (bilateral)
#
# Mass-fraction totals (head + trunk + 2x each bilateral) = 0.9999 (F) / 1.0000
# (M) — de Leva's published rounding, NOT an error (verified by the table-sum
# test in tests/test_com.py).
#
# Verification status: every value below matches de Leva (1996) Table 4 to the
# published precision; none are 'unverified'. (The only open *modelling* choice
# — how to build the TRUNK endpoints from a real marker set — is documented in
# ``trunk_endpoints`` below, not in this table.)
BSP = {
    "HEAD":     (0.0668, 0.0694, 0.4841, 0.5002, False),
    "TRUNK":    (0.4257, 0.4346, 0.4964, 0.5138, False),
    "UPPERARM": (0.0255, 0.0271, 0.5754, 0.5772, True),
    "FOREARM":  (0.0138, 0.0162, 0.4559, 0.4574, True),
    "HAND":     (0.0056, 0.0061, 0.7474, 0.7900, True),
    "THIGH":    (0.1478, 0.1416, 0.3612, 0.4095, True),
    "SHANK":    (0.0481, 0.0433, 0.4352, 0.4395, True),
    "FOOT":     (0.0129, 0.0137, 0.4014, 0.4415, True),
}

# Segment base names deliberately EXCLUDED from BSP mapping to avoid double
# counting. de Leva's TRUNK already includes the pelvis (its distal endpoint is
# the mid-hip), so a separate PELVIS segment must NOT get its own mass — the
# torso is represented once, by TRUNK (see module docstring & ``body_com``).
BSP_EXCLUDE = ("PELVIS",)


def _bsp_for(sex):
    """Return ``{base: (mass_frac, com_ratio, bilateral)}`` for ``sex``.

    ``sex`` in {"F"/"female", "M"/"male"}. ``None`` (or anything else) uses the
    SEX-NEUTRAL average of the female & male values — a deliberate, documented
    fallback (researcher open question): with no subject sex we average rather
    than assume a sex, biasing neither. The averaged mass fractions still sum to
    ~1.0 (mean of two ~1.0 totals).
    """
    s = (str(sex).strip().upper()[:1] if sex is not None else "")
    out = {}
    for base, (mf, mm, cf, cm, bilat) in BSP.items():
        if s == "F":
            out[base] = (mf, cf, bilat)
        elif s == "M":
            out[base] = (mm, cm, bilat)
        else:
            out[base] = ((mf + mm) / 2.0, (cf + cm) / 2.0, bilat)
    return out


def _base_name(seg_name):
    """Strip a leading ``R_``/``L_`` (or ``R``/``L``) side prefix and upper-case,
    so ``R_THIGH`` -> ``THIGH``, ``L_FOOT`` -> ``FOOT``, ``TRUNK`` -> ``TRUNK``.
    Used to look a segment up in the side-less :data:`BSP` table (its values are
    per-side for bilateral segments)."""
    u = str(seg_name).upper()
    for pre in ("R_", "L_", "RIGHT_", "LEFT_"):
        if u.startswith(pre):
            return u[len(pre):]
    if u[:1] in ("R", "L") and len(u) > 1 and not u[1:].isdigit():
        # bare side prefix only when the remainder is a known base (avoid eating
        # the first letter of e.g. "RADIUS" — not a BSP base anyway).
        rest = u[1:]
        if rest in BSP:
            return rest
    return u


# --------------------------------------------------------------------------
# Segment CoM + whole-body / partial COM
# --------------------------------------------------------------------------

def segment_com(prox_xyz, dist_xyz, com_ratio):
    """Segment centre of mass per frame: ``prox + com_ratio*(dist - prox)``.

    ``prox_xyz``, ``dist_xyz`` : (F,3) proximal/distal endpoint trajectories.
    ``com_ratio`` : fraction of the segment length from the proximal endpoint
    (de Leva longitudinal CoM ratio). Returns (F,3). NaN-safe: a frame with a
    NaN endpoint yields NaN there (propagates naturally through the arithmetic).
    """
    prox = np.asarray(prox_xyz, dtype=float)
    dist = np.asarray(dist_xyz, dtype=float)
    return prox + float(com_ratio) * (dist - prox)


def trunk_endpoints(model, point_traj):
    """Proximal (shoulder-girdle centre) & distal (mid-hip) TRUNK endpoints.

    de Leva's TRUNK runs mid-shoulder -> mid-hip, so we build those two points
    from whatever the model exposes, reusing the SAME landmarks the kinematic
    model already computes (no new geometry):

      * distal (mid-hip): midpoint of the L/R hip joint centres if the model has
        hip joints; else the pelvis mid-ASIS point (``PELVIS_ANT``) as a fallback.
      * proximal (mid-shoulder): the thorax IJ/C7 mid-point if the model has a
        thorax frame (``compute_frames`` thorax landmarks), else the midpoint of
        the two shoulder joint centres (acromia) if present.

    ``point_traj(name)`` is a callable returning a (F,3) trajectory for a joint-
    centre name or marker label (the model's ``_point_traj`` bound to a trial).

    Returns ``(prox (F,3), dist (F,3))`` or ``None`` when either end cannot be
    built (then TRUNK is skipped — the "safe only" rule). NaN-safe.
    """
    # --- distal: mid-hip ---
    hip_names = [j["name"] for j in model.joints if j.get("method") == "hip"]
    dist = None
    if len(hip_names) >= 2:
        r = next((n for n in hip_names if n.upper().startswith(("R", "RIGHT"))), None)
        l = next((n for n in hip_names if n.upper().startswith(("L", "LEFT"))), None)
        if r and l:
            dist = (point_traj(r) + point_traj(l)) / 2.0
    if dist is None:
        # fallback: pelvis anterior midpoint (mid-ASIS), if available
        try:
            dist = point_traj("PELVIS_ANT")
        except Exception:
            dist = None

    # --- proximal: mid-shoulder (thorax upper or shoulder JCs) ---
    prox = None
    # thorax landmarks live on segments with a frame {"type":"thorax", ...}
    thorax = next((s.get("frame") for s in model.segments
                   if (s.get("frame") or {}).get("type") == "thorax"), None)
    if thorax:
        try:
            prox = (point_traj(thorax["ij"]) + point_traj(thorax["c7"])) / 2.0
        except Exception:
            prox = None
    if prox is None:
        sh = [j["name"] for j in model.joints
              if j.get("name", "").upper().endswith("SHOULDER")]
        rs = next((n for n in sh if n.upper().startswith(("R", "RIGHT"))), None)
        ls = next((n for n in sh if n.upper().startswith(("L", "LEFT"))), None)
        if rs and ls:
            try:
                prox = (point_traj(rs) + point_traj(ls)) / 2.0
            except Exception:
                prox = None

    if prox is None or dist is None:
        return None
    return np.asarray(prox, float), np.asarray(dist, float)


def body_com(model, point_traj, body_mass=None, sex=None):
    """Mass-weighted whole-body / partial COM from a model's available segments.

    ``model``      : a ``MarkerModel`` (its ``segments`` list names the proximal/
                     distal endpoints; bilateral L/R segments are each weighted).
    ``point_traj`` : callable ``name -> (F,3)`` resolving a joint-centre name or
                     marker label to a world trajectory (typically the model's
                     ``_point_traj`` bound to a trial; see :func:`point_traj_for`).
    ``body_mass``  : subject mass in kg, or ``None``. The COM POSITION never needs
                     it (it cancels in the weighted mean); when given, per-segment
                     and total masses in kg are also reported.
    ``sex``        : "F"/"M" (or None for the sex-neutral average; see ``_bsp_for``).

    Returns a dict::

        {
          "com":          (F,3) whole-body / partial COM (world frame),
          "segment_coms": {seg_name: (F,3)},   # one per mass-bearing segment
          "coverage":     float 0..1,          # summed mass fraction included
          "missing":      [base, ...],         # de Leva bases NOT represented
          "whole_body":   bool,                # coverage > ~0.97
          "mass_used_kg": float | None,        # = body_mass (echoed) or None
        }

    Anti-double-counting: PELVIS (and any :data:`BSP_EXCLUDE` base) is ignored —
    the torso is carried once by TRUNK. Capability-based: only segments that
    exist in the model AND have a BSP entry contribute; the rest go to
    ``missing`` and lower ``coverage``. NaN-safe & vectorised over frames.
    """
    bsp = _bsp_for(sex)
    seg_defs = {s["name"]: s for s in model.segments}

    # Frame count from the first resolvable endpoint.
    F = None
    weighted = None         # (F,3) running sum of mass_frac * seg_com
    weight_tot = None       # (F,)  running sum of included mass_frac (per frame,
                            #       so an occluded segment drops out that frame)
    segment_coms = {}
    included_bases = {}     # base -> count of sides included (for coverage)

    # --- iterate the model's own segments (capability-based) ---
    for name, sdef in seg_defs.items():
        base = _base_name(name)
        if base in BSP_EXCLUDE or base not in bsp:
            continue
        if base == "TRUNK":
            ends = trunk_endpoints(model, point_traj)
            if ends is None:
                continue
            prox, dist = ends
        else:
            try:
                prox = np.asarray(point_traj(sdef["proximal"]), float)
                dist = np.asarray(point_traj(sdef["distal"]), float)
            except Exception:
                continue
        mass_frac, com_ratio, _bilat = bsp[base]
        com = segment_com(prox, dist, com_ratio)        # (F,3)
        if F is None:
            F = com.shape[0]
            weighted = np.zeros((F, 3), dtype=float)
            weight_tot = np.zeros(F, dtype=float)
        segment_coms[name] = com
        ok = np.isfinite(com).all(axis=1)               # frames with a valid CoM
        contrib = np.where(ok[:, None], mass_frac * com, 0.0)
        weighted += contrib
        weight_tot += np.where(ok, mass_frac, 0.0)
        included_bases[base] = included_bases.get(base, 0) + 1

    if F is None:
        # nothing mass-bearing in the model
        return {"com": np.zeros((0, 3)), "segment_coms": {}, "coverage": 0.0,
                "missing": [b for b in BSP if b not in BSP_EXCLUDE],
                "whole_body": False, "mass_used_kg": None}

    with np.errstate(invalid="ignore", divide="ignore"):
        com = weighted / weight_tot[:, None]
    com[weight_tot == 0] = np.nan

    # --- coverage: total de Leva mass fraction represented by the model ---
    # (uses the NOMINAL table fractions, not the per-frame weight, so coverage is
    # a property of the model's segment set — what fraction of body mass it can
    # account for — independent of momentary occlusions.)
    coverage = 0.0
    for base, n_sides in included_bases.items():
        mass_frac, _ratio, bilat = bsp[base]
        coverage += mass_frac * (2 if (bilat and n_sides >= 2) else n_sides if not bilat else n_sides)
    # clamp/round guard
    coverage = float(min(coverage, 1.0))

    missing = []
    for base in BSP:
        if base in BSP_EXCLUDE:
            continue
        if base not in included_bases:
            missing.append(base)

    # whole-body when essentially all mass is accounted for. de Leva mass sums to
    # ~1.0; a full-body marker set covers head+trunk+arms+legs. We treat coverage
    # > 0.97 as whole-body (tolerates the head being absent only if something
    # else fills in — in practice "whole body" needs head+trunk+limbs).
    whole_body = coverage > 0.97

    return {
        "com": com,
        "segment_coms": segment_coms,
        "coverage": coverage,
        "missing": missing,
        "whole_body": whole_body,
        "mass_used_kg": (float(body_mass) if body_mass is not None else None),
    }


def point_traj_for(model, markers, joint_centers, label_map=None):
    """A ``name -> (F,3)`` resolver bound to one trial, reusing the model's own
    endpoint resolution (``MarkerModel._point_traj``).

    ``joint_centers`` must already include the reconstructed joint centres AND
    the virtual pelvis points (``model.apply`` adds them via ``_pelvis_points``),
    so TRUNK's mid-hip / PELVIS_ANT endpoints resolve. Returns a closure so
    :func:`body_com` (and ``trunk_endpoints``) stay UI- and model-agnostic.
    """
    def resolve(name):
        return model._point_traj(name, markers, joint_centers, label_map)
    return resolve


# --------------------------------------------------------------------------
# Body mass from ground reaction force (static / quiet-standing trial only)
# --------------------------------------------------------------------------

def mass_from_grf(fz, g=9.81, plate_axis=0):
    """Estimate body mass (kg) from the mean vertical GRF of a STATIC trial.

    Newton's first law in quiet standing: with the body at rest the mean vertical
    ground reaction force equals body weight, so ``mass = mean(Fz) / g``. Fz is in
    NEWTONS (the C3D force convention); the sign convention varies, so the
    magnitude ``|mean(Fz)|`` is used. For a single plate pass the (N,) Fz; for
    multiple plates pass a list/2-D array of per-plate Fz and they are SUMMED
    frame-wise before averaging (the subject's weight is split across plates).

    ``g`` defaults to 9.81 m/s^2. NaN samples are ignored. Returns the mass in kg,
    or ``None`` when there is no finite force (no force channel / all-NaN).

    *** STATIC TRIALS ONLY. *** During a dynamic trial (gait, jump) the mean
    vertical GRF still averages to body weight over whole gait cycles, but any
    partial window, acceleration phase, or single-leg stance biases it badly —
    this function makes no stationarity check, so the caller must apply it only to
    a quiet-standing recording (or a quiet window thereof).
    """
    arr = np.asarray(fz, dtype=float)
    if arr.ndim == 0:
        arr = arr[None]
    # multi-plate: sum across the plate axis frame-wise (NaN-safe).
    if arr.ndim >= 2:
        arr = np.nansum(arr, axis=plate_axis)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return None
    mean_fz = float(np.abs(np.mean(finite)))
    if mean_fz <= 0 or g <= 0:
        return None
    return mean_fz / float(g)
