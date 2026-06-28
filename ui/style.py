# ============================================================================
# COLOR PALETTE
# ============================================================================
# Backgrounds
BG_DARK   = "#E5EBF2"    # Page/section background
BG_MID    = "#F5F7FA"    # Secondary background
BG_PANEL  = "#FFFFFF"    # Card/panel background
BG_INPUT  = "#F0F3F7"    # Input field background
BG_HOVER  = "#EBEBF0"    # Hover state for buttons
BG_DISABLED = "#F8F9FA"  # Disabled state

# Accent Colors
ACCENT_TEAL   = "#22A26A"  # Primary action/highlight
ACCENT_PURPLE = "#5D85FF"  # Secondary accent
ACCENT_RED    = "#EF5B5B"  # Error/warning/danger
ACCENT_GREEN  = "#2ECC71"  # Success
ACCENT_ORANGE = "#F39C12"  # Info/attention

# Text
TEXT_PRIMARY   = "#12323B"  # Main text
TEXT_SECONDARY = "#4B5B67"  # Secondary text
TEXT_MUTED     = "#7A8591"  # Disabled/placeholder
TEXT_INVERSE   = "#FFFFFF"  # Text on dark backgrounds

# Borders & Dividers
BORDER        = "#D5DEE9"  # Main border
BORDER_LIGHT  = "#E5EBF2"  # Light border
BORDER_FOCUS  = ACCENT_TEAL  # Focus ring

# Graph
GRAPH_BG  = "#FCFDFF"  # Plot background
GRAPH_FG  = "#6B7280"  # Plot foreground/grid

# Selection / checkbox indicator
# The app's selection language is a small green dot. These tokens give every
# checkbox/list indicator one consistent set of states (idle ring · hover ·
# checked dot · partial) so the dot reads the same everywhere.
SEL_GREEN        = "#3FC08D"             # checked text / strong accent
CHECK_DOT        = "rgba(63, 192, 141, 0.90)"  # checked indicator dot
CHECK_DOT_PARTLY = "rgba(63, 192, 141, 0.35)"  # indeterminate dot
CHECK_RING       = "#C4D0DD"             # unchecked indicator ring (faint)
CHECK_RING_HOVER = "#94A7BF"             # unchecked ring on hover

# ============================================================================
# TYPOGRAPHY
# ============================================================================
FONT_FAMILY = "Segoe UI, Arial, sans-serif"
FONT_SIZE_LARGE = "14px"      # Headers, section titles
FONT_SIZE_BASE = "12px"       # Normal text
FONT_SIZE_SMALL = "11px"      # Secondary text, labels
FONT_SIZE_TINY = "10px"       # Footnotes, metadata
FONT_WEIGHT_BOLD = "600"
FONT_WEIGHT_SEMI = "500"
FONT_WEIGHT_NORMAL = "400"

# ============================================================================
# SPACING & SIZING
# ============================================================================
SPACING_XS = "4px"
SPACING_SM = "8px"
SPACING_MD = "12px"
SPACING_LG = "16px"
SPACING_XL = "20px"
SPACING_2XL = "24px"

BORDER_RADIUS_SM = "4px"
BORDER_RADIUS_MD = "6px"
BORDER_RADIUS_LG = "8px"
BORDER_RADIUS_FULL = "12px"

# ============================================================================
# SHADOWS & ELEVATION
# ============================================================================
SHADOW_NONE = "none"
SHADOW_SM = "0 1px 2px rgba(0, 0, 0, 0.05)"
SHADOW_MD = "0 2px 4px rgba(0, 0, 0, 0.08)"
SHADOW_LG = "0 4px 8px rgba(0, 0, 0, 0.12)"

# ============================================================================
# COMPONENT CONSTANTS
# ============================================================================
SIDEBAR_WIDTH = "220px"
BUTTON_HEIGHT = "36px"
BUTTON_HEIGHT_SM = "32px"
CARD_MIN_HEIGHT = "60px"

#: Uniform pixel height for every PIPELINE step row. Single dense line (VSCode
#: explorer rhythm) — name + inline muted summary, no 2-line card. Owned here so
#: the row widget and the list's item size-hint agree on one number.
PIPELINE_ROW_HEIGHT = 26

#: Shared vertical row height for sidebar list items / checkable toggles, so the
#: marker list, RAW-signal toggles and RESULTS lists share one rhythm.
ROW_HEIGHT_LIST = 22

# ============================================================================
# PIPELINE STAGE BADGE COLORS
# ============================================================================
# One colour per analysis stage (core.pipeline.STAGE_ORDER), used by the
# Pipeline section to tint the small stage badge on each step row. Keeping the
# mapping here (instead of inline in analyze_tab) means a single place owns the
# pipeline's visual language. Each entry is (background, foreground-text).
# Only ``derive`` and ``detect`` have concrete step classes today; the other
# three are reserved place-holders (Phase C) and use a muted grey so a future
# step in those stages still reads sensibly.
PIPELINE_STAGE_COLORS = {
    "derive":    ("#E3ECFF", "#3355CC"),   # Compute — blue
    "detect":    ("#E2F3EA", "#1E8A55"),   # Detect Events — green
    "segment":   ("#EEE9F7", "#6A5AA8"),   # Segment — muted violet (placeholder)
    "metric":    ("#F3EDE4", "#9A7B3F"),   # Metric — muted amber (placeholder)
    "normalize": ("#EAEFF3", "#5B6B7A"),   # Normalize — muted slate (placeholder)
}

#: Fallback badge colour when a step's stage is unknown (forward-compat).
PIPELINE_STAGE_FALLBACK = ("#ECECEC", "#5B6B7A")


# ============================================================================
# THEMES
# ============================================================================
# Keys consumed by MainWindow._style(); switching the palette restyles the app
# chrome (menus, sidebars, status bars, buttons, inputs).
LIGHT_PALETTE = {
    "BG_DARK": BG_DARK,
    "BG_MID": BG_MID,
    "BG_PANEL": BG_PANEL,
    "BG_INPUT": BG_INPUT,
    "BG_HOVER": BG_HOVER,
    "BG_DISABLED": BG_DISABLED,
    "ACCENT_TEAL": ACCENT_TEAL,
    "ACCENT_PURPLE": ACCENT_PURPLE,
    "ACCENT_RED": ACCENT_RED,
    "TEXT_PRIMARY": TEXT_PRIMARY,
    "TEXT_SECONDARY": TEXT_SECONDARY,
    "TEXT_MUTED": TEXT_MUTED,
    "BORDER": BORDER,
    "GRAPH_BG": GRAPH_BG,
    "GRAPH_FG": GRAPH_FG,
    "SEL_GREEN": SEL_GREEN,
    "CHECK_DOT": CHECK_DOT,
    "CHECK_DOT_PARTLY": CHECK_DOT_PARTLY,
    "CHECK_RING": CHECK_RING,
    "CHECK_RING_HOVER": CHECK_RING_HOVER,
}

DARK_PALETTE = {
    "BG_DARK": "#15181E",
    "BG_MID": "#1B1F27",
    "BG_PANEL": "#222731",
    "BG_INPUT": "#2B313C",
    "BG_HOVER": "#333A47",
    "BG_DISABLED": "#262B34",
    "ACCENT_TEAL": "#2BB673",
    "ACCENT_PURPLE": "#6D8BFF",
    "ACCENT_RED": "#EF5B5B",
    "TEXT_PRIMARY": "#E8EDF4",
    "TEXT_SECONDARY": "#A7B2C0",
    "TEXT_MUTED": "#6F7B8A",
    "BORDER": "#39414E",
    "GRAPH_BG": "#1E232C",
    "GRAPH_FG": "#8A95A5",
    "SEL_GREEN": "#3FC08D",
    "CHECK_DOT": "rgba(63, 192, 141, 0.95)",
    "CHECK_DOT_PARTLY": "rgba(63, 192, 141, 0.40)",
    "CHECK_RING": "#4A5360",
    "CHECK_RING_HOVER": "#6F7B8A",
}


def use_theme(name):
    """Rebind the module-level colour names to the chosen palette so that any
    code reading ``ui.style.<NAME>`` at runtime picks up the active theme."""
    palette = DARK_PALETTE if name == "dark" else LIGHT_PALETTE
    globals().update(palette)
    return palette


# ============================================================================
# INLINE STYLE HELPERS
# ============================================================================
# Small builders that return a QSS string for ``widget.setStyleSheet(...)``.
# They are *functions* (not constants) so they read the current theme colours at
# call time — important because ``use_theme`` rebinds the palette at runtime.

def label_style(color=None, size=None, weight=None):
    """Build a label stylesheet (colour + optional font-size / weight).

    ``size`` may be an int (px) or a string like ``"11px"``; ``color`` defaults
    to the secondary text colour."""
    color = color or TEXT_SECONDARY
    parts = [f"color:{color};"]
    if size is not None:
        parts.append(f"font-size:{size}px;" if isinstance(size, int) else f"font-size:{size};")
    if weight is not None:
        parts.append(f"font-weight:{weight};")
    return "".join(parts)


def separator_style():
    """Stylesheet for thin divider frames (a coloured 1px line)."""
    return f"color:{BORDER};"


def transparent_bg():
    """Stylesheet for a widget that should be visually transparent."""
    return "background: transparent;"


def page_bg(border=False):
    """Stylesheet for a page-coloured background container, optionally borderless."""
    return f"background:{BG_DARK};border:none;" if border else f"background:{BG_DARK};"


def metric_value_style():
    """Stylesheet for the large primary metric value label."""
    return f"color:{TEXT_PRIMARY};font-size:22px;font-weight:500;"


def region_toggle_style():
    """Stylesheet for the round range-shading toggle button (idle / checked /
    disabled states)."""
    return f"""
            QPushButton {{
                border: 1px solid #94A7BF;
                border-radius: 9px;
                background: {BG_PANEL};
                padding: 0;
            }}
            QPushButton:checked {{
                border: 1px solid #3B82F6;
                background: #3B82F6;
            }}
            QPushButton:disabled {{
                border: 1px solid {BORDER};
                background: {BG_DISABLED};
            }}
        """

