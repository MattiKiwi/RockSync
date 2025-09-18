import os
import sqlite3
import time
import random
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QSpinBox, QFileDialog, QMessageBox, QCheckBox, QGroupBox,
    QTableWidget, QTableWidgetItem, QToolButton, QListWidget, QAbstractItemView,
    QScrollArea, QDialog, QDialogButtonBox, QPlainTextEdit
)

from core import CONFIG_PATH
from settings_store import save_settings


def _parse_preset_genres_text(text: str) -> List[str]:
    tokens: List[str] = []
    for chunk in str(text or '').replace(';', ',').replace('\n', ',').split(','):
        val = chunk.strip()
        if val:
            tokens.append(val)
    return list(dict.fromkeys(tokens))


class GenrePresetEditorDialog(QDialog):
    def __init__(self, presets: List[Dict[str, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Genre Presets")
        self.resize(560, 360)
        self._presets: List[Dict[str, str]] = [
            {"name": str(p.get("name", "")).strip(), "genres": str(p.get("genres", "")).strip()}
            for p in (presets or [])
        ]

        layout = QVBoxLayout(self)

        main = QHBoxLayout()
        layout.addLayout(main, 1)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        main.addWidget(self.list, 0)

        form = QVBoxLayout()
        main.addLayout(form, 1)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit()
        name_row.addWidget(self.name_edit, 1)
        form.addLayout(name_row)

        form.addWidget(QLabel("Allowed genres (comma-separated):"))
        self.genres_edit = QPlainTextEdit()
        self.genres_edit.setPlaceholderText("pop, europop, dance-pop")
        form.addWidget(self.genres_edit, 1)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.add_btn.clicked.connect(self._on_add)
        btn_row.addWidget(self.add_btn)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._on_remove)
        btn_row.addWidget(self.remove_btn)
        btn_row.addStretch(1)
        form.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.list.currentRowChanged.connect(self._on_selection_changed)
        self.name_edit.textChanged.connect(self._on_name_changed)
        self.genres_edit.textChanged.connect(self._on_genres_changed)

        self._reload_list()
        if self.list.count():
            self.list.setCurrentRow(0)
        self._update_form_enabled()

    def _reload_list(self):
        self.list.blockSignals(True)
        self.list.clear()
        for preset in self._presets:
            name = preset.get("name") or "Preset"
            self.list.addItem(name)
        self.list.blockSignals(False)

    def _on_selection_changed(self, row: int):
        if row is None or row < 0 or row >= len(self._presets):
            self.name_edit.blockSignals(True)
            self.genres_edit.blockSignals(True)
            self.name_edit.clear()
            self.genres_edit.clear()
            self.name_edit.blockSignals(False)
            self.genres_edit.blockSignals(False)
        else:
            preset = self._presets[row]
            self.name_edit.blockSignals(True)
            self.genres_edit.blockSignals(True)
            self.name_edit.setText(preset.get("name", ""))
            self.genres_edit.setPlainText(preset.get("genres", ""))
            self.name_edit.blockSignals(False)
            self.genres_edit.blockSignals(False)
        self._update_form_enabled()

    def _on_name_changed(self, text: str):
        row = self.list.currentRow()
        if row < 0 or row >= len(self._presets):
            return
        self._presets[row]["name"] = text.strip()
        item = self.list.item(row)
        if item:
            item.setText(self._presets[row]["name"] or "Preset")

    def _on_genres_changed(self):
        row = self.list.currentRow()
        if row < 0 or row >= len(self._presets):
            return
        self._presets[row]["genres"] = self.genres_edit.toPlainText().strip()

    def _on_add(self):
        self._presets.append({"name": "New Preset", "genres": ""})
        self._reload_list()
        self.list.setCurrentRow(self.list.count() - 1)

    def _on_remove(self):
        row = self.list.currentRow()
        if row < 0 or row >= len(self._presets):
            return
        self._presets.pop(row)
        self._reload_list()
        if self.list.count():
            self.list.setCurrentRow(min(row, self.list.count() - 1))
        else:
            self._on_selection_changed(-1)

    def _update_form_enabled(self):
        has_selection = self.list.currentRow() >= 0
        self.name_edit.setEnabled(has_selection)
        self.genres_edit.setEnabled(has_selection)
        self.remove_btn.setEnabled(has_selection)

    def result_presets(self) -> List[Dict[str, str]]:
        cleaned: List[Dict[str, str]] = []
        for preset in self._presets:
            name = (preset.get("name") or "").strip()
            genres_text = preset.get("genres") or ""
            if not name:
                continue
            tokens = _parse_preset_genres_text(genres_text)
            cleaned.append({
                "name": name,
                "genres": ", ".join(tokens),
            })
        return cleaned

from rockbox_utils import list_rockbox_devices


class DailyMixPane(QWidget):
    """Create Daily Mix playlists using the indexed DB (Library or Device)."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._genres: List[str] = []
        self._genre_presets: List[Dict[str, str]] = []
        self._loading_presets = False
        self._build_ui()
        self._load_genre_presets()
        self._refresh_sources()
        self._on_source_changed()

    # ---------- UI ----------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)

        # Shared source row (used for auto and default output)
        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("Source:"))
        self.source_combo = QComboBox(); self.source_combo.currentIndexChanged.connect(lambda _: self._on_source_changed())
        src_row.addWidget(self.source_combo, 1)
        b_refresh_src = QPushButton("Refresh"); b_refresh_src.clicked.connect(self._refresh_sources)
        src_row.addWidget(b_refresh_src)
        root.addLayout(src_row)

        # Shared output row
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Save to:"))
        self.out_dir = QLineEdit("")
        out_row.addWidget(self.out_dir, 1)
        b_browse = QPushButton("Browse"); b_browse.clicked.connect(self._browse_out_dir)
        out_row.addWidget(b_browse)
        self.use_src_default = QCheckBox("Use source default (Playlists/Mood Mixes)")
        self.use_src_default.setChecked(True)
        self.use_src_default.toggled.connect(lambda _: self._apply_default_out_dir())
        out_row.addWidget(self.use_src_default)
        root.addLayout(out_row)

        # Auto Generator group
        self.auto_toggle = QToolButton()
        self.auto_toggle.setText("Auto Generator")
        self.auto_toggle.setCheckable(True)
        self.auto_toggle.setChecked(True)
        self.auto_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.auto_toggle.setArrowType(Qt.DownArrow)
        root.addWidget(self.auto_toggle)

        self.auto_group = QGroupBox()
        self.auto_group.setTitle("")
        auto_v = QVBoxLayout(self.auto_group)
        # Mix options row 1
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Mix name:"))
        self.mix_name = QLineEdit("Daily Mix")
        row1.addWidget(self.mix_name, 1)
        row1.addWidget(QLabel("Target (min):"))
        self.target_min = QSpinBox(); self.target_min.setRange(10, 300); self.target_min.setValue(75)
        row1.addWidget(self.target_min)
        row1.addWidget(QLabel("Count:"))
        self.mix_count = QSpinBox(); self.mix_count.setRange(1, 20); self.mix_count.setValue(1)
        row1.addWidget(self.mix_count)
        auto_v.addLayout(row1)

        # Mix options row 2
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Per-artist max:"))
        self.per_artist_max = QSpinBox(); self.per_artist_max.setRange(1, 10); self.per_artist_max.setValue(2)
        row2.addWidget(self.per_artist_max)
        row2.addWidget(QLabel("Fresh days:"))
        self.fresh_days = QSpinBox(); self.fresh_days.setRange(0, 365); self.fresh_days.setValue(0)
        row2.addWidget(self.fresh_days)
        row2.addWidget(QLabel("Genre mode:"))
        self.genre_mode = QComboBox(); self.genre_mode.addItems(["Random", "Pick", "Preset"]) 
        self.genre_mode.currentIndexChanged.connect(self._on_genre_mode_changed)
        row2.addWidget(self.genre_mode)
        self.anchor_label = QLabel("Anchors:")
        row2.addWidget(self.anchor_label)
        self.anchor_count = QSpinBox(); self.anchor_count.setRange(1, 6); self.anchor_count.setValue(3)
        row2.addWidget(self.anchor_count)
        auto_v.addLayout(row2)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Genre preset:"))
        self.genre_preset_combo = QComboBox()
        self.genre_preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_row.addWidget(self.genre_preset_combo, 1)
        self.manage_presets_btn = QPushButton("Manage Presets")
        self.manage_presets_btn.clicked.connect(self._on_manage_presets)
        preset_row.addWidget(self.manage_presets_btn)
        auto_v.addLayout(preset_row)

        self.genre_controls = QWidget()
        genre_layout = QHBoxLayout(self.genre_controls)
        genre_layout.setContentsMargins(0, 0, 0, 0)

        avail_layout = QVBoxLayout()
        avail_layout.addWidget(QLabel("Available genres:"))
        self.genre_available = QListWidget()
        self.genre_available.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.genre_available.setMinimumHeight(150)
        self.genre_available.itemDoubleClicked.connect(self._on_available_genre_double_clicked)
        avail_layout.addWidget(self.genre_available)
        genre_layout.addLayout(avail_layout, 2)

        btn_layout = QVBoxLayout()
        self.btn_anchor_add = QPushButton("→ Anchors")
        self.btn_anchor_add.clicked.connect(self._add_selected_anchors)
        btn_layout.addWidget(self.btn_anchor_add)
        self.btn_blacklist_add = QPushButton("→ Blacklist")
        self.btn_blacklist_add.clicked.connect(self._add_selected_blacklist)
        btn_layout.addWidget(self.btn_blacklist_add)
        btn_layout.addStretch(1)
        genre_layout.addLayout(btn_layout)

        self.anchor_container = QWidget()
        anchor_layout = QVBoxLayout(self.anchor_container)
        anchor_layout.addWidget(QLabel("Selected anchors:"))
        self.genre_anchor = QListWidget()
        self.genre_anchor.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.genre_anchor.setMinimumHeight(150)
        self.genre_anchor.itemDoubleClicked.connect(lambda _: self._remove_selected_from_list(self.genre_anchor))
        anchor_layout.addWidget(self.genre_anchor)
        anchor_btns = QHBoxLayout()
        self.btn_anchor_remove = QPushButton("Remove")
        self.btn_anchor_remove.clicked.connect(lambda: self._remove_selected_from_list(self.genre_anchor))
        anchor_btns.addWidget(self.btn_anchor_remove)
        self.btn_anchor_clear = QPushButton("Clear")
        self.btn_anchor_clear.clicked.connect(lambda: self.genre_anchor.clear())
        anchor_btns.addWidget(self.btn_anchor_clear)
        anchor_btns.addStretch(1)
        anchor_layout.addLayout(anchor_btns)
        genre_layout.addWidget(self.anchor_container, 1)

        self.blacklist_container = QWidget()
        blacklist_layout = QVBoxLayout(self.blacklist_container)
        blacklist_layout.addWidget(QLabel("Blacklisted genres:"))
        self.genre_blacklist = QListWidget()
        self.genre_blacklist.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.genre_blacklist.setMinimumHeight(150)
        self.genre_blacklist.itemDoubleClicked.connect(lambda _: self._remove_selected_from_list(self.genre_blacklist))
        blacklist_layout.addWidget(self.genre_blacklist)
        blacklist_btns = QHBoxLayout()
        self.btn_blacklist_remove = QPushButton("Remove")
        self.btn_blacklist_remove.clicked.connect(lambda: self._remove_selected_from_list(self.genre_blacklist))
        blacklist_btns.addWidget(self.btn_blacklist_remove)
        self.btn_blacklist_clear = QPushButton("Clear")
        self.btn_blacklist_clear.clicked.connect(lambda: self.genre_blacklist.clear())
        blacklist_btns.addWidget(self.btn_blacklist_clear)
        blacklist_btns.addStretch(1)
        blacklist_layout.addLayout(blacklist_btns)
        genre_layout.addWidget(self.blacklist_container, 1)

        auto_v.addWidget(self.genre_controls)

        # Actions row
        act_row = QHBoxLayout()
        self.run_btn = QPushButton("Generate Mix")
        self.run_btn.clicked.connect(self._on_generate)
        act_row.addWidget(self.run_btn)
        self.status = QLineEdit(""); self.status.setReadOnly(True)
        act_row.addWidget(self.status, 1)
        auto_v.addLayout(act_row)

        root.addWidget(self.auto_group)

        # Manual Playlists group
        self.manual_toggle = QToolButton()
        self.manual_toggle.setText("Manual Playlists")
        self.manual_toggle.setCheckable(True)
        self.manual_toggle.setChecked(False)
        self.manual_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.manual_toggle.setArrowType(Qt.RightArrow)
        root.addWidget(self.manual_toggle)

        self.manual_group = QGroupBox()
        self.manual_group.setTitle("")
        man_v = QVBoxLayout(self.manual_group)

        # Manual source row
        man_src = QHBoxLayout()
        man_src.addWidget(QLabel("Source:"))
        self.manual_source_combo = QComboBox(); self.manual_source_combo.currentIndexChanged.connect(lambda _: self._manual_perform_search())
        man_src.addWidget(self.manual_source_combo, 1)
        b_man_refresh = QPushButton("Refresh"); b_man_refresh.clicked.connect(self._refresh_manual_sources)
        man_src.addWidget(b_man_refresh)
        b_reload = QPushButton("Reload DB"); b_reload.clicked.connect(self._manual_perform_search)
        man_src.addWidget(b_reload)
        man_v.addLayout(man_src)

        # Search controls
        man_search = QHBoxLayout()
        man_search.addWidget(QLabel("Search:"))
        self.manual_query = QLineEdit(); self.manual_query.setPlaceholderText("Type to search…")
        man_search.addWidget(self.manual_query, 1)
        self.manual_query.textChanged.connect(lambda _: self._manual_trigger_search())
        man_search.addWidget(QLabel("Field:"))
        self.manual_field = QComboBox(); self.manual_field.addItems(["Any", "Title", "Artist", "Album", "Genre"]) 
        self.manual_field.currentIndexChanged.connect(lambda _: self._manual_trigger_search())
        man_search.addWidget(self.manual_field)
        man_v.addLayout(man_search)

        # Results table
        self._manual_search_timer = QTimer(self)
        self._manual_search_timer.setInterval(250)
        self._manual_search_timer.setSingleShot(True)
        self._manual_search_timer.timeout.connect(self._manual_perform_search)

        self.manual_cols = ("artist", "album", "title", "genre", "duration", "path")
        self.manual_results = QTableWidget(0, len(self.manual_cols))
        self.manual_results.setHorizontalHeaderLabels([c.title() for c in self.manual_cols])
        self.manual_results.setAlternatingRowColors(True)
        self.manual_results.setSelectionBehavior(QTableWidget.SelectRows)
        self.manual_results.setSelectionMode(QTableWidget.ExtendedSelection)
        self.manual_results.horizontalHeader().setStretchLastSection(True)
        self.manual_results.verticalHeader().setDefaultSectionSize(30)
        self.manual_results.verticalHeader().setMinimumSectionSize(26)
        man_v.addWidget(self.manual_results, 1)
        # Give more vertical space to the results list
        man_v.setStretchFactor(self.manual_results, 2)

        # Selected playlist table + buttons
        sel_row = QHBoxLayout()
        b_add = QPushButton("Add Selected →"); b_add.clicked.connect(self._manual_add_selected)
        b_remove = QPushButton("Remove Selected"); b_remove.clicked.connect(self._manual_remove_selected)
        b_clear = QPushButton("Clear"); b_clear.clicked.connect(self._manual_clear_selected)
        sel_row.addWidget(b_add); sel_row.addWidget(b_remove); sel_row.addWidget(b_clear)
        sel_row.addStretch(1)
        man_v.addLayout(sel_row)

        self.manual_selected = QTableWidget(0, len(self.manual_cols))
        self.manual_selected.setHorizontalHeaderLabels([c.title() for c in self.manual_cols])
        self.manual_selected.setAlternatingRowColors(True)
        self.manual_selected.setSelectionBehavior(QTableWidget.SelectRows)
        self.manual_selected.setSelectionMode(QTableWidget.ExtendedSelection)
        self.manual_selected.horizontalHeader().setStretchLastSection(True)
        self.manual_selected.verticalHeader().setDefaultSectionSize(30)
        self.manual_selected.verticalHeader().setMinimumSectionSize(26)
        man_v.addWidget(self.manual_selected, 1)
        man_v.setStretchFactor(self.manual_selected, 1)

        # Footer: name + save
        man_row1 = QHBoxLayout()
        man_row1.addWidget(QLabel("Name:"))
        self.manual_name = QLineEdit("")
        self.manual_name.setPlaceholderText("New Playlist")
        man_row1.addWidget(self.manual_name, 1)
        b_create = QPushButton("Save Playlist"); b_create.clicked.connect(self._on_create_manual_playlist)
        man_row1.addWidget(b_create)
        man_v.addLayout(man_row1)

        root.addWidget(self.manual_group, 1)

        self._on_genre_mode_changed()

        self.auto_toggle.toggled.connect(self._toggle_auto_section)
        self.manual_toggle.toggled.connect(self._toggle_manual_section)
        self._toggle_auto_section(self.auto_toggle.isChecked())
        self._toggle_manual_section(self.manual_toggle.isChecked())

        # Storage for manual selection
        self._manual_files: List[str] = []
        self._manual_selected_paths: List[str] = []
        # Populate manual sources
        self._refresh_manual_sources()

    # ---------- Helpers ----------
    def _toggle_auto_section(self, expanded: bool):
        self._set_section_visible(self.auto_group, self.auto_toggle, expanded)

    def _toggle_manual_section(self, expanded: bool):
        self._set_section_visible(self.manual_group, self.manual_toggle, expanded)

    @staticmethod
    def _set_section_visible(container: QWidget, toggle: QToolButton, expanded: bool):
        if container is not None:
            container.setVisible(bool(expanded))
        if toggle is not None:
            toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

    def _load_genre_presets(self, preferred: Optional[str] = None):
        presets = self.controller.settings.get('daily_mix_genre_presets', []) if hasattr(self.controller, 'settings') else []
        if not isinstance(presets, list):
            presets = []
        self._genre_presets = [
            {"name": str(p.get('name', '')).strip(), "genres": str(p.get('genres', '')).strip()}
            for p in presets
            if isinstance(p, dict)
        ]

        target = preferred if preferred is not None else str(self.controller.settings.get('daily_mix_last_preset', '') if hasattr(self.controller, 'settings') else '')

        self._loading_presets = True
        self.genre_preset_combo.blockSignals(True)
        self.genre_preset_combo.clear()
        self.genre_preset_combo.addItem("All genres", None)
        for preset in self._genre_presets:
            self.genre_preset_combo.addItem(preset.get('name') or 'Preset', dict(preset))
        index = 0
        if target:
            for i in range(1, self.genre_preset_combo.count()):
                data = self.genre_preset_combo.itemData(i)
                if isinstance(data, dict) and (data.get('name') or '') == target:
                    index = i
                    break
        self.genre_preset_combo.blockSignals(False)
        self.genre_preset_combo.setCurrentIndex(index)
        self._loading_presets = False
        self._on_preset_changed()

    def _current_preset_name(self) -> str:
        data = self.genre_preset_combo.currentData()
        if isinstance(data, dict):
            return str(data.get('name') or '').strip()
        return ''

    def _current_allowed_genres(self) -> Optional[List[str]]:
        data = self.genre_preset_combo.currentData()
        if isinstance(data, dict):
            return _parse_preset_genres_text(data.get('genres', ''))
        return None

    def _current_allowed_genres_set(self) -> Optional[Set[str]]:
        allowed = self._current_allowed_genres()
        if allowed is None:
            return None
        return {g.strip().lower() for g in allowed if g.strip()}

    def _apply_preset_filter_to_lists(
        self,
        previous_anchors: Optional[List[str]] = None,
        previous_blacklist: Optional[List[str]] = None,
    ) -> None:
        mode = (self.genre_mode.currentText() or '').strip().lower() if hasattr(self, 'genre_mode') else None
        preset_ui_mode = (mode == 'preset')
        allowed_list = self._current_allowed_genres()
        preset_mode = preset_ui_mode and (allowed_list is not None)
        allowed_set: Optional[Set[str]] = None
        if allowed_list is not None:
            allowed_set = {g.strip().lower() for g in allowed_list if g.strip()}

        if preset_mode:
            if allowed_set is not None and not allowed_set:
                filtered_genres: List[str] = []
            elif allowed_set is None:
                filtered_genres = list(self._genres)
            else:
                filtered_genres = [g for g in self._genres if g.strip().lower() in allowed_set]
        else:
            filtered_genres = list(self._genres)

        self.genre_available.blockSignals(True)
        self.genre_available.clear()
        for g in filtered_genres:
            self.genre_available.addItem(g)
        self.genre_available.sortItems()
        self.genre_available.blockSignals(False)

        if preset_mode:
            anchors_target = allowed_list or []
            if allowed_set is None:
                blacklist_target = []
            else:
                blacklist_target = [g for g in self._genres if g.strip().lower() not in allowed_set]
                blacklist_target = list(dict.fromkeys(sorted(blacklist_target, key=lambda s: s.lower())))
        else:
            anchors_src = previous_anchors if previous_anchors is not None else self._current_anchor_genres()
            blacklist_src = previous_blacklist if previous_blacklist is not None else self._current_blacklist_genres()
            anchors_target = [g for g in anchors_src if g in filtered_genres]
            blacklist_target = [g for g in blacklist_src if g in filtered_genres]

        self._set_list_items(self.genre_anchor, anchors_target)
        self._set_list_items(self.genre_blacklist, blacklist_target)

        enable_controls = bool(filtered_genres)

        if mode == 'pick':
            self.btn_anchor_add.setEnabled(enable_controls)
            self.btn_anchor_remove.setEnabled(self.genre_anchor.count() > 0)
            self.btn_anchor_clear.setEnabled(self.genre_anchor.count() > 0)
        else:
            self.btn_anchor_add.setEnabled(False)
            self.btn_anchor_remove.setEnabled(False)
            self.btn_anchor_clear.setEnabled(False)

        if not preset_ui_mode:
            self.btn_blacklist_add.setEnabled(enable_controls)
            self.btn_blacklist_remove.setEnabled(self.genre_blacklist.count() > 0)
            self.btn_blacklist_clear.setEnabled(self.genre_blacklist.count() > 0)
        else:
            self.btn_blacklist_add.setEnabled(False)
            self.btn_blacklist_remove.setEnabled(False)
            self.btn_blacklist_clear.setEnabled(False)

    def _persist_last_preset(self, name: str):
        current = ''
        if hasattr(self.controller, 'settings'):
            current = str(self.controller.settings.get('daily_mix_last_preset', '') or '')
            self.controller.settings['daily_mix_last_preset'] = name
        if current != name:
            save_settings({'daily_mix_last_preset': name})

    def _on_preset_changed(self):
        if self._loading_presets:
            return
        self._apply_preset_filter_to_lists()
        name = self._current_preset_name()
        self._persist_last_preset(name)

    def _on_manage_presets(self):
        current_name = self._current_preset_name()
        dlg = GenrePresetEditorDialog(self._genre_presets, self)
        if dlg.exec():
            presets = dlg.result_presets()
            if hasattr(self.controller, 'settings'):
                self.controller.settings['daily_mix_genre_presets'] = presets
            save_settings({'daily_mix_genre_presets': presets})
            self._load_genre_presets(preferred=current_name)


    @staticmethod
    def _set_list_items(widget: QListWidget, items: List[str]):
        widget.blockSignals(True)
        widget.clear()
        for g in dict.fromkeys(items):
            widget.addItem(g)
        widget.blockSignals(False)

    @staticmethod
    def _selected_genres(widget: QListWidget) -> List[str]:
        return [it.text().strip() for it in widget.selectedItems() if (it.text() or '').strip()]

    @staticmethod
    def _list_contains(widget: QListWidget, genre: str) -> bool:
        return bool(widget.findItems(genre, Qt.MatchFixedString))

    def _add_genres_to_list(self, widget: QListWidget, genres: Iterable[str]) -> List[str]:
        added: List[str] = []
        for g in genres:
            if not g:
                continue
            if not self._list_contains(widget, g):
                widget.addItem(g)
                added.append(g)
        return added

    @staticmethod
    def _remove_genres_from_list(widget: QListWidget, genres: Iterable[str]) -> List[str]:
        removed: List[str] = []
        for g in genres:
            if not g:
                continue
            items = widget.findItems(g, Qt.MatchFixedString)
            for it in items:
                row = widget.row(it)
                widget.takeItem(row)
                removed.append(g)
        return removed

    def _remove_selected_from_list(self, widget: QListWidget) -> List[str]:
        genres = self._selected_genres(widget)
        return self._remove_genres_from_list(widget, genres)

    def _current_anchor_genres(self) -> List[str]:
        return [self.genre_anchor.item(i).text().strip() for i in range(self.genre_anchor.count()) if self.genre_anchor.item(i) and self.genre_anchor.item(i).text().strip()]

    def _current_blacklist_genres(self) -> List[str]:
        return [self.genre_blacklist.item(i).text().strip() for i in range(self.genre_blacklist.count()) if self.genre_blacklist.item(i) and self.genre_blacklist.item(i).text().strip()]

    def _add_selected_anchors(self):
        if self.genre_mode.currentText().lower() != 'pick':
            return
        selected = self._selected_genres(self.genre_available)
        added = self._add_genres_to_list(self.genre_anchor, selected)
        if added:
            self._remove_genres_from_list(self.genre_blacklist, added)

    def _add_selected_blacklist(self):
        selected = self._selected_genres(self.genre_available)
        added = self._add_genres_to_list(self.genre_blacklist, selected)
        if added:
            self._remove_genres_from_list(self.genre_anchor, added)

    def _on_available_genre_double_clicked(self, item):
        if not item:
            return
        genre = (item.text() or '').strip()
        if not genre:
            return
        if self.genre_mode.currentText().lower() == 'pick':
            added = self._add_genres_to_list(self.genre_anchor, [genre])
            if added:
                self._remove_genres_from_list(self.genre_blacklist, added)
        else:
            added = self._add_genres_to_list(self.genre_blacklist, [genre])
            if added:
                self._remove_genres_from_list(self.genre_anchor, added)

    @staticmethod
    def _filter_blacklisted_tracks(rows: List[Dict], blacklist: Iterable[str]) -> List[Dict]:
        banned = { (b or '').strip().lower() for b in (blacklist or []) if (b or '').strip() }
        if not banned:
            return list(rows)
        filtered: List[Dict] = []
        for r in rows:
            tokens = {t.strip().lower() for t in DailyMixPane._split_genre_tokens(r.get('genre', '')) if t.strip()}
            if tokens & banned:
                continue
            filtered.append(r)
        return filtered

    @staticmethod
    def _filter_allowed_tracks(rows: List[Dict], allowed: Optional[Iterable[str]]) -> List[Dict]:
        if allowed is None:
            return list(rows)
        allowed_set = {(g or '').strip().lower() for g in allowed if (g or '').strip()}
        if not allowed_set:
            return []
        filtered: List[Dict] = []
        for r in rows:
            tokens = {t.strip().lower() for t in DailyMixPane._split_genre_tokens(r.get('genre', '')) if t.strip()}
            if not tokens:
                continue
            if tokens & allowed_set:
                filtered.append(r)
        return filtered

    def _refresh_sources(self):
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItem("Library", { 'type': 'library' })
        try:
            devices = list_rockbox_devices()
        except Exception:
            devices = []
        for d in devices:
            label = d.get('name') or d.get('label') or d.get('mountpoint')
            mp = d.get('mountpoint')
            if not mp:
                continue
            self.source_combo.addItem(f"Device: {label} ({mp})", { 'type': 'device', 'mount': mp })
        self.source_combo.blockSignals(False)

    def _selected_base_folder(self) -> str:
        data = self.source_combo.currentData()
        if not isinstance(data, dict):
            return ''
        if data.get('type') == 'library':
            return (self.controller.settings.get('music_root') or '').strip()
        if data.get('type') == 'device':
            mp = (data.get('mount') or '').rstrip('/\\')
            return mp
        return ''

    def _current_db_path(self) -> str:
        data = self.source_combo.currentData()
        if isinstance(data, dict) and data.get('type') == 'device':
            mp = (data.get('mount') or '').rstrip('/\\')
            if mp:
                return str(Path(mp) / '.rocksync' / 'music_index.sqlite3')
        return str(CONFIG_PATH.with_name('music_index.sqlite3'))

    def _apply_default_out_dir(self):
        if not self.use_src_default.isChecked():
            return
        base = self._selected_base_folder()
        if not base:
            self.out_dir.setText("")
            return
        data = self.source_combo.currentData()
        if isinstance(data, dict) and data.get('type') == 'device':
            # Device default: <mount>/Music/Playlists/Mood Mixes
            self.out_dir.setText(str(Path(base) / 'Music' / 'Playlists' / 'Mood Mixes'))
        else:
            # Library default: <music_root>/Playlists/Mood Mixes
            music_root_str = (self.controller.settings.get('music_root') or base)
            music_root = Path(music_root_str)
            self.out_dir.setText(str(music_root / 'Playlists' / 'Mood Mixes'))

    def _on_source_changed(self):
        self._apply_default_out_dir()
        self._load_genres()

    def _on_genre_mode_changed(self):
        mode = (self.genre_mode.currentText() or '').strip().lower()
        pick = (mode == 'pick')
        preset_mode = (mode == 'preset')

        self.genre_controls.setVisible(not preset_mode)

        self.anchor_container.setVisible(pick)
        self.btn_anchor_add.setVisible(pick)
        self.btn_anchor_remove.setVisible(pick)
        self.btn_anchor_clear.setVisible(pick)

        blacklist_visible = not preset_mode
        self.blacklist_container.setVisible(blacklist_visible)
        self.btn_blacklist_add.setVisible(blacklist_visible)
        self.btn_blacklist_remove.setVisible(blacklist_visible)
        self.btn_blacklist_clear.setVisible(blacklist_visible)

        show_anchor_count = (mode == 'random')
        self.anchor_label.setVisible(show_anchor_count)
        self.anchor_count.setVisible(show_anchor_count)
        self.anchor_count.setEnabled(show_anchor_count)

        if not pick:
            self.genre_anchor.clearSelection()

        if preset_mode:
            self.genre_blacklist.clearSelection()

        self._apply_preset_filter_to_lists()

    def _browse_out_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select output folder", self.out_dir.text() or self._selected_base_folder() or "")
        if path:
            self.out_dir.setText(path)
            self.use_src_default.setChecked(False)

    def _manual_trigger_search(self):
        self._manual_search_timer.start()

    def _manual_perform_search(self):
        db_path = self._manual_current_db_path()
        self.manual_results.setRowCount(0)
        if not db_path or not os.path.isfile(db_path):
            return
        query = (self.manual_query.text() or '').strip()
        field = (self.manual_field.currentText() or 'Any').lower()
        try:
            with sqlite3.connect(db_path) as conn:
                if not query:
                    sql = "SELECT artist, album, title, genre, duration_seconds, path FROM tracks ORDER BY artist, album, track, title LIMIT 1000"
                    cur = conn.execute(sql)
                else:
                    like = f"%{query}%"
                    if field == 'any':
                        where = "(IFNULL(title,'') LIKE ? OR IFNULL(artist,'') LIKE ? OR IFNULL(album,'') LIKE ? OR IFNULL(genre,'') LIKE ?)"
                        params = [like, like, like, like]
                    else:
                        col = {'title':'title','artist':'artist','album':'album','genre':'genre'}.get(field, 'title')
                        where = f"IFNULL({col},'') LIKE ?"
                        params = [like]
                    sql = f"SELECT artist, album, title, genre, duration_seconds, path FROM tracks WHERE {where} ORDER BY artist, album, track, title LIMIT 1000"
                    cur = conn.execute(sql, params)
                rows = cur.fetchall()
        except Exception:
            rows = []
        for (artist, album, title, genre, dur, path) in rows:
            info = {
                'artist': artist or '',
                'album': album or '',
                'title': title or '',
                'genre': genre or '',
                'duration': self._fmt_duration(dur or 0),
                'path': path or '',
            }
            self._manual_insert_row(self.manual_results, info)

    # ---------- DB ops ----------
    def _load_genres(self):
        db_path = self._current_db_path()
        genres: List[str] = []
        if db_path and os.path.isfile(db_path):
            try:
                with sqlite3.connect(db_path) as conn:
                    cur = conn.execute("SELECT DISTINCT IFNULL(genre,'') FROM tracks")
                    for (g,) in cur.fetchall():
                        gs = str(g or '')
                        # Split combined genres into individual tokens
                        tokens = self._split_genre_tokens(gs)
                        for t in tokens:
                            if self._is_valid_genre(t):
                                genres.append(t)
            except Exception:
                pass
        genres = sorted(set(genres), key=lambda s: s.lower())
        previous_anchors = self._current_anchor_genres()
        previous_blacklist = self._current_blacklist_genres()

        self._genres = genres
        self._apply_preset_filter_to_lists(previous_anchors, previous_blacklist)

    @staticmethod
    def _fmt_duration(secs):
        try:
            secs = int(secs)
            return f"{secs//60}:{secs%60:02d}"
        except Exception:
            return ''

    @staticmethod
    def _is_valid_genre(g: str) -> bool:
        bad = {"", "unknown", "(unknown)", "undef", "undefined", "n/a", "none", "genre:"}
        return (g or '').strip().lower() not in bad

    @staticmethod
    def _split_genre_tokens(genre: str) -> List[str]:
        if not genre:
            return []
        raw = [genre]
        seps = [';', '|', '/', ',']
        for sep in seps:
            tmp = []
            for item in raw:
                tmp.extend(item.split(sep))
            raw = tmp
        return [t.strip() for t in raw if t.strip()]

    def _load_tracks(self) -> List[Dict]:
        db_path = self._current_db_path()
        rows: List[Dict] = []
        if not db_path or not os.path.isfile(db_path):
            return rows
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.execute(
                    "SELECT path, IFNULL(artist,''), IFNULL(album,''), IFNULL(title,''), IFNULL(genre,''), IFNULL(duration_seconds,0), IFNULL(mtime,0) FROM tracks"
                )
                for (path, artist, album, title, genre, dur, mtime) in cur.fetchall():
                    if not self._is_valid_genre(genre):
                        continue
                    rows.append({
                        'path': path,
                        'artist': artist,
                        'album': album,
                        'title': title or Path(path).stem,
                        'genre': genre,
                        'seconds': int(dur) if dur else 0,
                        'mtime': int(mtime) if mtime else 0,
                    })
        except Exception:
            return []
        return rows

    # ---------- Generate ----------
    def _on_generate(self):
        out_dir = (self.out_dir.text() or '').strip()
        if not out_dir:
            QMessageBox.warning(self, "Daily Mix", "Please choose an output folder.")
            return
        tracks = self._load_tracks()
        if not tracks:
            QMessageBox.warning(self, "Daily Mix", "No tracks found in the index for the selected source.")
            return

        allowed_list = self._current_allowed_genres()
        mode = (self.genre_mode.currentText() or '').strip().lower()
        preset_ui_mode = (mode == 'preset')
        if preset_ui_mode and allowed_list is None:
            QMessageBox.warning(self, "Daily Mix", "Select a genre preset before using Preset mode.")
            return
        preset_mode = preset_ui_mode and (allowed_list is not None)
        if allowed_list is not None:
            if not allowed_list:
                QMessageBox.warning(self, "Daily Mix", "The selected genre preset does not contain any genres.")
                return
            tracks = self._filter_allowed_tracks(tracks, allowed_list)
            if not tracks:
                QMessageBox.warning(self, "Daily Mix", "No tracks match the selected genre preset.")
                return

        blacklist = self._current_blacklist_genres()
        usable_tracks = self._filter_blacklisted_tracks(tracks, blacklist)
        if not usable_tracks:
            QMessageBox.warning(self, "Daily Mix", "All tracks were excluded by the blacklist.")
            return

        # Determine anchors
        anchors: List[str] = []
        pick_mode = (mode == 'pick')
        if preset_mode:
            anchors = list(dict.fromkeys(allowed_list))
            if not anchors:
                QMessageBox.warning(self, "Daily Mix", "Preset contains no usable genres.")
                return
        elif pick_mode:
            anchors = self._current_anchor_genres()
            if not anchors:
                QMessageBox.warning(self, "Daily Mix", "Please add at least one anchor genre or use Random mode.")
                return
        else:
            anchors = self._choose_anchor_genres(usable_tracks, self.anchor_count.value(), blacklist)
            if not anchors:
                anchors = self._choose_anchor_genres(usable_tracks, max(1, self.anchor_count.value()))

        per_artist_max = self.per_artist_max.value()
        fresh_days = self.fresh_days.value() or None
        total_min = self.target_min.value()
        mix_count = self.mix_count.value()
        name = self.mix_name.text().strip() or "Daily Mix"

        base = Path(out_dir)
        base.mkdir(parents=True, exist_ok=True)

        wrote = 0
        for i in range(mix_count):
            mix = self._build_mix(usable_tracks, anchors, total_min, per_artist_max, fresh_days)
            if not mix:
                break
            mix_name = name if mix_count == 1 else f"{name} #{i+1}"
            out = self._write_m3u8(base, mix_name, mix)
            wrote += 1
            self.status.setText(f"Wrote {out}")
        if wrote == 0:
            QMessageBox.warning(self, "Daily Mix", "Could not build a mix. Try adjusting options.")
        else:
            QMessageBox.information(self, "Daily Mix", f"Created {wrote} playlist(s).")

    # ---------- Manual playlist ----------
    def _manual_insert_row(self, table: QTableWidget, info: Dict):
        row = table.rowCount()
        table.insertRow(row)
        vals = [info.get('artist',''), info.get('album',''), info.get('title',''), info.get('genre',''), info.get('duration',''), info.get('path','')]
        for col, val in enumerate(vals):
            table.setItem(row, col, QTableWidgetItem(str(val)))

    def _manual_add_selected(self):
        rows = sorted(set([i.row() for i in self.manual_results.selectedIndexes()]))
        for r in rows:
            path_item = self.manual_results.item(r, 5)
            if not path_item:
                continue
            path = path_item.text()
            if path in self._manual_selected_paths:
                continue
            # Build info dict from results row
            info = { c: (self.manual_results.item(r, idx).text() if self.manual_results.item(r, idx) else '')
                     for idx, c in enumerate(self.manual_cols) }
            self._manual_insert_row(self.manual_selected, info)
            self._manual_selected_paths.append(path)

    def _manual_remove_selected(self):
        rows = sorted(set([i.row() for i in self.manual_selected.selectedIndexes()]), reverse=True)
        for r in rows:
            path_item = self.manual_selected.item(r, 5)
            path = path_item.text() if path_item else ''
            if 0 <= r < self.manual_selected.rowCount():
                self.manual_selected.removeRow(r)
            if path in self._manual_selected_paths:
                try:
                    self._manual_selected_paths.remove(path)
                except ValueError:
                    pass

    def _manual_clear_selected(self):
        self.manual_selected.setRowCount(0)
        self._manual_selected_paths.clear()
    def _on_create_manual_playlist(self):
        out_dir = (self.out_dir.text() or '').strip()
        if not out_dir:
            QMessageBox.warning(self, "Playlists", "Please choose an output folder.")
            return
        name = (self.manual_name.text() or '').strip()
        if not name:
            QMessageBox.warning(self, "Playlists", "Please enter a playlist name.")
            return
        if not self._manual_selected_paths:
            QMessageBox.warning(self, "Playlists", "Please add one or more tracks.")
            return
        try:
            out = self._write_manual_m3u8(Path(out_dir), name, self._manual_selected_paths)
            self.status.setText(f"Wrote {out}")
            QMessageBox.information(self, "Playlists", f"Created playlist: {out}")
        except Exception as e:
            QMessageBox.critical(self, "Playlists", f"Failed to write playlist: {e}")
    
    def _refresh_manual_sources(self):
        self.manual_source_combo.blockSignals(True)
        self.manual_source_combo.clear()
        self.manual_source_combo.addItem("Library", { 'type': 'library' })
        try:
            devices = list_rockbox_devices()
        except Exception:
            devices = []
        for d in devices:
            label = d.get('name') or d.get('label') or d.get('mountpoint')
            mp = d.get('mountpoint')
            if not mp:
                continue
            self.manual_source_combo.addItem(f"{label}", { 'type': 'device', 'mount': mp })
        self.manual_source_combo.blockSignals(False)
        self._manual_perform_search()

    def _manual_current_db_path(self) -> str:
        data = self.manual_source_combo.currentData()
        if not isinstance(data, dict):
            return ''
        if data.get('type') == 'device':
            mp = (data.get('mount') or '').rstrip('/\\')
            if mp:
                return str(Path(mp) / '.rocksync' / 'music_index.sqlite3')
            return ''
        return str(CONFIG_PATH.with_name('music_index.sqlite3'))

    # ---------- Mix utilities (local) ----------
    @staticmethod
    def _choose_anchor_genres(rows: List[Dict], n: int, blacklist: Optional[Iterable[str]] = None) -> List[str]:
        banned = { (b or '').strip().lower() for b in (blacklist or []) if (b or '').strip() }
        freq: Dict[str, int] = {}
        for r in rows:
            g = (r.get('genre') or '').strip()
            toks = DailyMixPane._split_genre_tokens(g)
            for t in toks:
                if not DailyMixPane._is_valid_genre(t):
                    continue
                if (t or '').strip().lower() in banned:
                    continue
                freq[t] = freq.get(t, 0) + 1
        ranked = sorted(freq.items(), key=lambda kv: kv[1], reverse=True)
        top = [g for g, _ in ranked[:max(2, n + 2)]]
        random.shuffle(top)
        return list(dict.fromkeys(top[:n]))

    @staticmethod
    def _weight_rows(rows: List[Dict], anchors: List[str], fresh_days: Optional[int]) -> List[Tuple[Dict, float]]:
        now = time.time()
        window = (fresh_days or 0) * 86400
        anchors_lc = {a.strip().lower() for a in anchors}
        out: List[Tuple[Dict, float]] = []
        for r in rows:
            w = 1.0
            toks = DailyMixPane._split_genre_tokens(r.get('genre',''))
            if any(t.strip().lower() in anchors_lc for t in toks):
                w += 1.0
            if fresh_days and (now - float(r.get('mtime') or 0)) <= window:
                w += 0.5
            out.append((r, w))
        return out

    @staticmethod
    def _pick_next(pool: List[Tuple[Dict, float]], used: set, last_artist: Optional[str], per_artist: Dict[str, int], cap: int) -> Optional[Dict]:
        filtered = [(r, w) for (r, w) in pool
                    if r.get('path') not in used
                    and per_artist.get(r.get('artist',''), 0) < cap
                    and (last_artist is None or r.get('artist','') != last_artist)]
        if not filtered:
            filtered = [(r, w) for (r, w) in pool
                        if r.get('path') not in used
                        and per_artist.get(r.get('artist',''), 0) < cap]
        if not filtered:
            return None
        weights = [w for _, w in filtered]
        return random.choices(filtered, weights=weights, k=1)[0][0]

    def _build_mix(self, rows: List[Dict], anchors: List[str], target_min: int, per_artist_max: int, fresh_days: Optional[int]) -> List[Dict]:
        pool = self._weight_rows(rows, anchors, fresh_days)
        target_sec = target_min * 60
        used = set()
        per_artist: Dict[str, int] = {}
        out: List[Dict] = []
        last_artist: Optional[str] = None
        total = 0
        approx_count = max(10, int(target_min * 0.24)) if not any(r.get('seconds') for r, _w in pool) else None

        while True:
            nxt = self._pick_next(pool, used, last_artist, per_artist, per_artist_max)
            if not nxt:
                break
            dur = int(nxt.get('seconds') or 240)
            if any(r.get('seconds') for r, _w in pool):
                if total > 0 and total + dur > target_sec + 120:
                    break
                total += dur
            else:
                if approx_count is not None and len(out) >= approx_count:
                    break
            out.append(nxt)
            used.add(nxt.get('path'))
            art = nxt.get('artist','')
            per_artist[art] = per_artist.get(art, 0) + 1
            last_artist = art
            if len(out) >= 200:
                break
        return out

    @staticmethod
    def _write_m3u8(out_dir: Path, name: str, rows: List[Dict]) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in name if c not in r'<>:"/\\|?*').strip() or "Daily Mix"
        ts = time.strftime("%Y-%m-%d")
        fp = out_dir / f"{safe} - {ts}.m3u8"
        lines = ["#EXTM3U"]
        for r in rows:
            secs = int(r.get('seconds') or 0)
            if secs:
                lines.append(f"#EXTINF:{secs},{r.get('artist','')} - {r.get('title','')}")
            try:
                rp = os.path.relpath(str(Path(r.get('path')).resolve()), str(out_dir.resolve())).replace("\\", "/")
            except Exception:
                rp = r.get('path')
            lines.append(rp)
        fp.write_text("\n".join(lines), encoding="utf-8")
        return fp

    @staticmethod
    def _write_manual_m3u8(out_dir: Path, name: str, files: List[str]) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in name if c not in r'<>:"/\\|?*').strip() or "New Playlist"
        fp = out_dir / f"{safe}.m3u8"
        lines = ["#EXTM3U"]
        for p in files:
            try:
                rp = os.path.relpath(str(Path(p).resolve()), str(out_dir.resolve())).replace("\\", "/")
            except Exception:
                rp = p
            lines.append(rp)
        fp.write_text("\n".join(lines), encoding="utf-8")
        return fp
