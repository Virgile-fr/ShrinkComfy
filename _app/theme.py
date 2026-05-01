"""
Theme Sun Valley (Windows 11) avec detection automatique systeme.
Suit le theme systeme, pas de toggle manuel.
"""

import sys

LIGHT = {
    "bg":             "#fafafa",
    "surface":        "#ffffff",
    "border":         "#e5e5e5",
    "border_strong":  "#d1d1d1",
    "text":           "#1a1a1a",
    "text_secondary": "#5b5b5b",
    "text_muted":     "#8a8a8a",
    "accent":         "#0067c0",
    "accent_subtle":  "#e6f0fb",
    "accent_text":    "#003d7a",
    "danger":         "#c42b1c",
    "sidebar_bg":     "#f3f3f3",
    "sidebar_hover":  "#ebebeb",
    "sidebar_sel":    "#dfdfdf",
    "log_bg":         "#fbfbfb",
}

DARK = {
    "bg":             "#202020",
    "surface":        "#2b2b2b",
    "border":         "#1d1d1d",
    "border_strong":  "#3a3a3a",
    "text":           "#ffffff",
    "text_secondary": "#cccccc",
    "text_muted":     "#9a9a9a",
    "accent":         "#4cc2ff",
    "accent_subtle":  "#1f3a52",
    "accent_text":    "#9ed7ff",
    "danger":         "#ff99a4",
    "sidebar_bg":     "#272727",
    "sidebar_hover":  "#323232",
    "sidebar_sel":    "#3a3a3a",
    "log_bg":         "#1c1c1c",
}


def detect_system_theme():
    try:
        import darkdetect
        t = darkdetect.theme()
        return "dark" if t == "Dark" else "light"
    except Exception:
        return "light"


def palette(mode):
    return DARK if mode == "dark" else LIGHT


def apply_theme(root, mode):
    """Applique sv_ttk + colore la titlebar Windows 11."""
    import sv_ttk
    sv_ttk.set_theme(mode)

    if sys.platform == "win32":
        try:
            import pywinstyles
            ver = sys.getwindowsversion()
            if ver.major == 10 and ver.build >= 22000:
                color = "#1c1c1c" if mode == "dark" else "#fafafa"
                pywinstyles.change_header_color(root, color)
        except Exception:
            pass

    return palette(mode)
