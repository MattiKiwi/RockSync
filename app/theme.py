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
    # Default palette
    palette = {
        'bg': '#F0F0F0',
        'surface': '#FFFFFF',
        'text': '#000000',
        'muted': '#555555',
        'accent': '#4F6BED',
        'selection_bg': '#CDE1FF',
        'selection_fg': '#000000',
        'entry_bg': '#FFFFFF',
    }

    if theme_spec and theme_spec != 'system':
        path = THEMES_DIR / theme_spec
        if path.exists():
            try:
                pal = parse_css_palette(path)
                for k in list(palette.keys()):
                    if k in pal:
                        palette[k] = pal[k]
            except Exception:
                pass

    # Build and set QPalette (Fusion-friendly)
    qpal = QPalette()
    bg = _color(palette['bg'])
    surf = _color(palette['surface'])
    text = _color(palette['text'])
    sel_bg = _color(palette['selection_bg'])
    sel_fg = _color(palette['selection_fg'])

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

    # Minimal stylesheet touches for a modern look
    qss = f"""
    QWidget {{
        font-family: -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, 'Noto Sans', Arial;
        font-size: 12px;
    }}
    QGroupBox {{
        border: 1px solid rgba(0,0,0,0.1);
        border-radius: 6px;
        margin-top: 12px;
        padding: 8px 8px 8px 8px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 8px;
        padding: 0 3px;
    }}
    QLineEdit, QComboBox, QTextEdit, QPlainTextEdit {{
        background: {palette['entry_bg']};
        border: 1px solid rgba(0,0,0,0.2);
        border-radius: 6px;
        padding: 6px;
    }}
    QPushButton {{
        padding: 6px 10px;
        border-radius: 6px;
        background: {palette['surface']};
        border: 1px solid rgba(0,0,0,0.15);
    }}
    QPushButton:hover {{
        background: {palette['selection_bg']};
    }}
    QTabWidget::pane {{ border: 0; }}
    QTreeView, QTableView {{
        gridline-color: rgba(0,0,0,0.1);
        selection-background-color: {palette['selection_bg']};
        selection-color: {palette['selection_fg']};
    }}
    """
    app.setStyleSheet(qss)
    return palette
