from tkinter import ttk
from theme_loader import list_theme_files, parse_css_palette, THEMES_DIR


def available_themes():
    return ["system"] + list_theme_files()


def apply_theme(app, theme_spec: str):
    style = ttk.Style(app)
    # Default palette (system fallback)
    palette = {
        'bg': style.lookup('TFrame', 'background') or '#F0F0F0',
        'surface': '#FFFFFF',
        'text': '#000000',
        'muted': '#555555',
        'accent': '#4F6BED',
        'selection_bg': '#CDE1FF',
        'selection_fg': '#000000',
        'entry_bg': '#FFFFFF',
    }

    # If a CSS file is selected, parse it for palette values
    if theme_spec and theme_spec != 'system':
        path = THEMES_DIR / theme_spec
        if path.exists():
            try:
                pal = parse_css_palette(path)
                # update only known keys
                for k in list(palette.keys()):
                    if k in pal:
                        palette[k] = pal[k]
            except Exception:
                pass
        base = 'clam' if 'clam' in style.theme_names() else style.theme_use()
        style.theme_use(base)
    else:
        # use current system theme
        try:
            style.theme_use(style.theme_use())
        except Exception:
            pass

    # Apply common widget styles
    bg = palette['bg']; fg = palette['text']; surf = palette['surface']
    style.configure('TFrame', background=bg)
    style.configure('TLabel', background=bg, foreground=fg)
    style.configure('TButton', background=surf, foreground=fg)
    style.map('TButton', background=[('active', palette['selection_bg'])])
    style.configure('TNotebook', background=bg)
    style.configure('TNotebook.Tab', background=surf, foreground=fg)
    style.map('TNotebook.Tab', background=[('selected', palette['selection_bg'])])
    style.configure('TEntry', fieldbackground=palette['entry_bg'], foreground=fg)
    style.configure('TCombobox', fieldbackground=palette['entry_bg'], foreground=fg)
    style.configure('TCheckbutton', background=bg, foreground=fg)
    style.configure('Treeview', background=surf, fieldbackground=surf, foreground=fg)
    style.map('Treeview', background=[('selected', palette['selection_bg'])], foreground=[('selected', palette['selection_fg'])])
    style.configure('Treeview.Heading', background=bg, foreground=fg)
    style.configure('TScrollbar', background=bg)

    # Return palette to allow non-ttk widgets (Text) to be themed by caller
    return palette
