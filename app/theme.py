from theme_loader import list_theme_files, parse_css_palette, THEMES_DIR
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication


def available_themes():
    return ["system"] + list_theme_files()


def _color(hex_str: str) -> QColor:
    try:
        return QColor(hex_str)
    except Exception:
        return QColor("#000000")


def apply_theme(app: QApplication, theme_spec: str):
    """Apply a Material-You-inspired theme using QPalette + QSS.
    Accepts both the previous palette keys and new Material tokens from CSS :root.
    """
    # Baseline palette (Material-ish light)
    palette = {
        # Legacy keys
        'bg': '#F5F6F8',
        'surface': '#FFFFFF',
        'text': '#1C1B1F',
        'muted': '#6B7280',
        'accent': '#6750A4',
        'selection_bg': '#EADDFF',
        'selection_fg': '#1C1B1F',
        'entry_bg': '#FFFFFF',
        # Material tokens (new)
        'primary': '#6750A4',
        'on_primary': '#FFFFFF',
        'secondary': '#625B71',
        'on_secondary': '#FFFFFF',
        'surface_container': '#F2EDF7',
        'on_surface': '#1C1B1F',
        'surface_variant': '#E7E0EC',
        'on_surface_variant': '#49454F',
        'outline': '#79747E',
        'error': '#B3261E',
        'on_error': '#FFFFFF',
    }

    # Load overrides from CSS theme file
    if theme_spec and theme_spec != 'system':
        path = THEMES_DIR / theme_spec
        if path.exists():
            try:
                pal = parse_css_palette(path)
                # Merge any provided keys
                for k, v in pal.items():
                    palette[k] = v
                # Backfill legacy keys from Material tokens if unset in CSS
                palette.setdefault('bg', palette.get('background', palette['surface_container']))
                palette.setdefault('surface', palette.get('surface', '#FFFFFF'))
                palette.setdefault('text', palette.get('on_surface', '#1C1B1F'))
                palette.setdefault('accent', palette.get('primary', '#6750A4'))
                palette.setdefault('selection_bg', palette.get('surface_variant', '#E7E0EC'))
                palette.setdefault('selection_fg', palette.get('on_surface', '#1C1B1F'))
                palette.setdefault('entry_bg', palette.get('surface', '#FFFFFF'))
            except Exception:
                pass

    # Build and set QPalette (Fusion-friendly)
    qpal = QPalette()
    bg = _color(palette.get('bg', '#F5F6F8'))
    surf = _color(palette.get('surface', '#FFFFFF'))
    text = _color(palette.get('text', '#1C1B1F'))
    sel_bg = _color(palette.get('selection_bg', '#EADDFF'))
    sel_fg = _color(palette.get('selection_fg', '#1C1B1F'))

    qpal.setColor(QPalette.Window, bg)
    qpal.setColor(QPalette.WindowText, text)
    qpal.setColor(QPalette.Base, surf)
    qpal.setColor(QPalette.AlternateBase, bg)
    qpal.setColor(QPalette.ToolTipBase, surf)
    qpal.setColor(QPalette.ToolTipText, text)
    qpal.setColor(QPalette.Text, text)
    qpal.setColor(QPalette.Button, surf)
    qpal.setColor(QPalette.ButtonText, text)
    qpal.setColor(QPalette.Highlight, sel_bg)
    qpal.setColor(QPalette.HighlightedText, sel_fg)

    app.setPalette(qpal)

    # Derived colors for QSS
    primary = palette.get('primary', palette.get('accent', '#6750A4'))
    on_primary = palette.get('on_primary', '#FFFFFF')
    secondary = palette.get('secondary', '#625B71')
    on_secondary = palette.get('on_secondary', '#FFFFFF')
    surface_container = palette.get('surface_container', '#F2EDF7')
    on_surface = palette.get('on_surface', palette.get('text', '#1C1B1F'))
    surface_variant = palette.get('surface_variant', '#E7E0EC')
    on_surface_variant = palette.get('on_surface_variant', '#49454F')
    outline = palette.get('outline', '#79747E')

    # Material-ish metrics
    radius = 10
    padding = 8

    # Application stylesheet
    qss = f"""
    QWidget {{
        font-family: -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, 'Noto Sans', Arial;
        font-size: 13px;
        color: {on_surface};
    }}

    /* Top App Bar */
    QWidget#TopAppBar {{
        background: {surf.name() if hasattr(surf, 'name') else palette['surface']};
        border-bottom: 1px solid {outline};
        padding: 8px 12px;
    }}
    QLabel#TopAppTitle {{
        font-weight: 600;
        font-size: 15px;
    }}

    /* Cards and groups */
    QGroupBox {{
        border: 1px solid {surface_variant};
        border-radius: {radius}px;
        margin-top: 12px;
        padding: 8px 8px 8px 8px;
        background: {surf.name() if hasattr(surf, 'name') else palette['surface']};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 8px;
        padding: 0 3px;
        color: {on_surface_variant};
    }}

    /* Inputs */
    QLineEdit, QComboBox, QTextEdit, QPlainTextEdit {{
        background: {palette['entry_bg']};
        border: 1px solid {surface_variant};
        border-radius: {radius}px;
        padding: {padding}px;
    }}
    QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border: 2px solid {primary};
    }}

    /* Buttons */
    QPushButton {{
        padding: 6px 12px;
        border-radius: {radius}px;
        background: {surface_variant};
        border: 1px solid {surface_variant};
        color: {on_surface};
    }}
    QPushButton:hover {{
        background: {palette['selection_bg']};
    }}
    QPushButton[accent="true"] {{
        background: {primary};
        color: {on_primary};
        border: none;
    }}
    QPushButton[accent="true"]:hover {{
        background: {secondary};
        color: {on_secondary};
    }}

    /* Navigation (rail) */
    QListWidget#NavList {{
        background: {bg.name() if hasattr(bg, 'name') else palette['bg']};
        border-right: 1px solid {outline};
        padding: 8px 0;
    }}
    QListWidget#NavList::item {{
        padding: 10px 14px;
        margin: 4px 8px;
        border-radius: {radius}px;
    }}
    QListWidget#NavList::item:selected {{
        background: {palette['selection_bg']};
        color: {palette['selection_fg']};
    }}
    QListWidget#NavList::item:!enabled {{
        color: {palette['muted']};
        margin-top: 14px;
    }}

    /* Tables / Trees */
    QTreeView, QTableView {{
        gridline-color: {surface_variant};
        selection-background-color: {palette['selection_bg']};
        selection-color: {palette['selection_fg']};
        border: 1px solid {surface_variant};
        border-radius: {radius}px;
        background: {surf.name() if hasattr(surf, 'name') else palette['surface']};
    }}
    """
    app.setStyleSheet(qss)
    return palette
