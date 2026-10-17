"""Εμφάνιση προγράμματος: φωτεινό (λευκό), σκούρο ή όπως τα Windows.

Χωρίς ρητή επιλογή, το Qt ακολουθεί το σκούρο θέμα των Windows και η εφαρμογή βγαίνει σκούρα.
Η προεπιλογή εδώ είναι «φωτεινό». Το γράφημα και το Link map μένουν πάντα σε λευκό «χαρτί».
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEMES = (("light", "Φωτεινό (λευκό)"), ("dark", "Σκούρο"), ("auto", "Όπως τα Windows"))
DEFAULT_THEME = "light"
SETTINGS_KEY = "appTheme"


def _palette(colors: dict[str, str], disabled_text: str) -> QPalette:
    p = QPalette()
    roles = {
        "window": QPalette.Window, "window_text": QPalette.WindowText, "base": QPalette.Base,
        "alt_base": QPalette.AlternateBase, "text": QPalette.Text, "button": QPalette.Button,
        "button_text": QPalette.ButtonText, "highlight": QPalette.Highlight,
        "highlight_text": QPalette.HighlightedText, "tooltip_base": QPalette.ToolTipBase,
        "tooltip_text": QPalette.ToolTipText, "placeholder": QPalette.PlaceholderText,
        "link": QPalette.Link, "bright_text": QPalette.BrightText,
    }
    for key, role in roles.items():
        p.setColor(role, QColor(colors[key]))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(disabled_text))
    return p


def light_palette() -> QPalette:
    return _palette({
        "window": "#f6f8fa", "window_text": "#1f2328", "base": "#ffffff", "alt_base": "#f3f6f9",
        "text": "#1f2328", "button": "#eef1f4", "button_text": "#1f2328", "highlight": "#0969da",
        "highlight_text": "#ffffff", "tooltip_base": "#ffffe1", "tooltip_text": "#1f2328",
        "placeholder": "#6e7781", "link": "#0969da", "bright_text": "#cf222e",
    }, "#8c959f")


def dark_palette() -> QPalette:
    return _palette({
        "window": "#202328", "window_text": "#e6edf3", "base": "#16181c", "alt_base": "#24282e",
        "text": "#e6edf3", "button": "#2b3036", "button_text": "#e6edf3", "highlight": "#1f6feb",
        "highlight_text": "#ffffff", "tooltip_base": "#2b3036", "tooltip_text": "#e6edf3",
        "placeholder": "#8b949e", "link": "#58a6ff", "bright_text": "#ff7b72",
    }, "#6e7681")


# Χρώματα κειμένου με νόημα (σφάλμα / προειδοποίηση / υπόδειξη), ευανάγνωστα σε κάθε θέμα (αντίθεση ≥ 4.5:1)
SEMANTIC = {
    "light": {"fail": "#cf222e", "warn": "#9a6700", "muted": "#57606a"},
    "dark": {"fail": "#ffa198", "warn": "#d29922", "muted": "#9198a1"},
}


def is_dark(app: QApplication | None = None) -> bool:
    app = app or QApplication.instance()
    return app is not None and app.palette().color(QPalette.Window).lightness() < 128


def color(role: str, app: QApplication | None = None) -> str:
    return SEMANTIC["dark" if is_dark(app) else "light"][role]


def style_label(widget, role: str, extra: str = "") -> None:
    """Χρώμα κειμένου που ακολουθεί το θέμα (ξαναεφαρμόζεται σε κάθε αλλαγή θέματος)."""
    widget.setProperty("themeRole", role)
    widget.setProperty("themeExtra", extra)
    widget.setStyleSheet(f"color: {color(role)}; {extra}")


def normalize(mode) -> str:
    return mode if mode in {m for m, _ in THEMES} else DEFAULT_THEME


def refresh_widgets(app: QApplication) -> None:
    """Μετά από αλλαγή θέματος ενώ τρέχει η εφαρμογή: όλα τα στοιχεία παίρνουν τα νέα χρώματα.

    ΠΡΟΣΟΧΗ: stylesheet σε widget που έχει παιδιά (π.χ. στο QTabWidget των καρτελών εργασίας) «παγώνει»
    την παλέτα όλων των παιδιών και η αλλαγή θέματος εφαρμοζόταν μισή (σκούρο φόντο με σκούρα γράμματα,
    λευκοί πίνακες). Γι' αυτό stylesheets μόνο σε «φύλλα» (ετικέτες, κουμπιά) και όχι σε δοχεία.
    """
    for w in app.allWidgets():
        role = w.property("themeRole")
        if role:                                # χρώμα με νόημα: το νέο χρώμα του θέματος
            style_label(w, role, w.property("themeExtra") or "")
            w.update()
            continue
        sheet = w.styleSheet()
        if sheet:                               # τα widgets με δικό τους στυλ ξαναϋπολογίζονται
            w.setStyleSheet("")
            w.setStyleSheet(sheet)
        else:
            w.style().unpolish(w)
            w.style().polish(w)
        w.update()


_current = {"mode": None, "connected": False}


def current_mode() -> str | None:
    return _current["mode"]


def _os_scheme_changed(scheme=None):
    """«Όπως τα Windows»: όταν αλλάξει το θέμα των Windows ενώ τρέχει η εφαρμογή, ακολουθεί."""
    app = QApplication.instance()
    if app is None or _current["mode"] != "auto":
        return
    if scheme is None:
        scheme = app.styleHints().colorScheme()
    dark = scheme == Qt.ColorScheme.Dark
    app.setPalette(dark_palette() if dark else light_palette())
    refresh_widgets(app)


def apply_theme(app: QApplication, mode: str) -> str:
    """Εφαρμόζει το θέμα σε όλη την εφαρμογή (αμέσως) και επιστρέφει αυτό που εφαρμόστηκε."""
    mode = normalize(mode)
    _current["mode"] = mode
    if not _current["connected"]:
        try:
            app.styleHints().colorSchemeChanged.connect(_os_scheme_changed)
            _current["connected"] = True
        except AttributeError:
            pass
    scheme = {"light": Qt.ColorScheme.Light, "dark": Qt.ColorScheme.Dark}.get(mode, Qt.ColorScheme.Unknown)
    try:
        app.styleHints().setColorScheme(scheme)        # και η μπάρα τίτλου των Windows
    except AttributeError:                             # παλιό Qt χωρίς setColorScheme
        pass
    if mode == "light":
        app.setPalette(light_palette())
    elif mode == "dark":
        app.setPalette(dark_palette())
    else:
        dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
        app.setPalette(dark_palette() if dark else light_palette())
    refresh_widgets(app)
    return mode
