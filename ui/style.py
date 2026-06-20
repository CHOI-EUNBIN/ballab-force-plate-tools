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
}


def use_theme(name):
    """Rebind the module-level colour names to the chosen palette so that any
    code reading ``ui.style.<NAME>`` at runtime picks up the active theme."""
    palette = DARK_PALETTE if name == "dark" else LIGHT_PALETTE
    globals().update(palette)
    return palette

