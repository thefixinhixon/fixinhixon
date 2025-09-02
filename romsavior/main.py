#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main application wiring for Myrient ROM Manager.

Behavior:
- Profiles snapshot the CURRENT browsed folder ONLY when you press Save (or New).
- Switching profiles/browsing does NOT change the saved folder.
- Loading a profile navigates to the folder saved with that profile.

Also:
- Reentrancy-safe profile save/switch
- Clean shutdown of background QThreads on exit
"""

from __future__ import annotations
import json
import copy
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from browser import BrowserTree, FileTable
from download_queue import QueuePanel  # avoid stdlib 'queue' clash

APP_NAME = "Myrient ROM Manager"
BASE_URL = "https://myrient.erista.me/files/"
APP_DIR = Path.home() / ".myrient_manager"; APP_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = APP_DIR / "cache"; CACHE_DIR.mkdir(exist_ok=True)
PROFILES_PATH = APP_DIR / "profiles.json"

DEFAULT_PROFILE = {
    "name": "Default",
    "temp_dir": str((APP_DIR / "tmp").resolve()),
    "downloader": "aria2c",  # aria2c|wget
    "extract_zip": True,
    "convert_to_chd": True,
    "delete_after_extract": False,
    "delete_after_chd": False,
    "output_dir": str((APP_DIR / "output").resolve()),
    "parallel_downloads": 3,
    "speed_cap_kib": 0,  # 0 = unlimited
    "sanitize_names": False,
    "auto_route_per_system": True,
    # Saved browsing state (ONLY set on Save/New)
    "last_url": BASE_URL,
    "last_rel": "",
}


# ---------------- Profiles Panel -----------------
class ProfilePanel(QtWidgets.QWidget):
    aboutToSave    = QtCore.Signal()   # emitted right before Save/New persists a profile
    profileChanged = QtCore.Signal(dict)  # emitted after save/switch (async)

    def __init__(self):
        super().__init__()
        self._suppress_combo_signal = False
        self.profiles = self._load_profiles()
        self.current = self.profiles[0]
        self._build_ui()

    # ---- persistence ----
    def _load_profiles(self):
        try:
            if PROFILES_PATH.exists():
                data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
                if isinstance(data, list) and data:
                    # backfill keys (on upgrades)
                    for p in data:
                        for k, v in DEFAULT_PROFILE.items():
                            p.setdefault(k, v)
                    return data
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, APP_NAME, f"Failed to load profiles:\n{e}")
        # first-time
        Path(DEFAULT_PROFILE["temp_dir"]).mkdir(parents=True, exist_ok=True)
        Path(DEFAULT_PROFILE["output_dir"]).mkdir(parents=True, exist_ok=True)
        data = [copy.deepcopy(DEFAULT_PROFILE)]
        self._write_profiles_safely(data)
        return data

    def _write_profiles_safely(self, data: list[dict]) -> None:
        try:
            PROFILES_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, APP_NAME, f"Failed to save profiles:\n{e}")

    def _save_profiles(self):
        self._write_profiles_safely(self.profiles)

    # ---- ui ----
    def _build_ui(self):
        lay = QtWidgets.QFormLayout(self)
        top = QtWidgets.QHBoxLayout()
        self.combo = QtWidgets.QComboBox(); self.combo.addItems([p['name'] for p in self.profiles])
        btn_save = QtWidgets.QPushButton("Save")
        btn_new = QtWidgets.QPushButton("New")
        top.addWidget(self.combo); top.addWidget(btn_save); top.addWidget(btn_new)
        lay.addRow("Profile:", top)

        self.temp = QtWidgets.QLineEdit(self.current['temp_dir']); btn_t = QtWidgets.QPushButton("Browse")
        row = QtWidgets.QHBoxLayout(); row.addWidget(self.temp); row.addWidget(btn_t)
        lay.addRow("Temporary Folder:", row)

        self.r_aria = QtWidgets.QRadioButton("aria2c"); self.r_wget = QtWidgets.QRadioButton("wget")
        (self.r_wget if self.current['downloader'] == 'wget' else self.r_aria).setChecked(True)
        row = QtWidgets.QHBoxLayout(); row.addWidget(self.r_aria); row.addWidget(self.r_wget)
        lay.addRow("Downloader:", row)

        self.c_ext = QtWidgets.QCheckBox("Extract .zip"); self.c_ext.setChecked(self.current['extract_zip'])
        self.c_chd = QtWidgets.QCheckBox("Convert BIN/CUE or ISO → CHD"); self.c_chd.setChecked(self.current['convert_to_chd'])
        self.c_delx = QtWidgets.QCheckBox("Delete archive after extraction"); self.c_delx.setChecked(self.current['delete_after_extract'])
        self.c_delc = QtWidgets.QCheckBox("Delete sources after CHD"); self.c_delc.setChecked(self.current['delete_after_chd'])
        lay.addRow(self.c_ext); lay.addRow(self.c_chd); lay.addRow(self.c_delx); lay.addRow(self.c_delc)

        self.out = QtWidgets.QLineEdit(self.current['output_dir']); btn_o = QtWidgets.QPushButton("Browse")
        row = QtWidgets.QHBoxLayout(); row.addWidget(self.out); row.addWidget(btn_o)
        lay.addRow("Output Directory:", row)

        self.par = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.par.setRange(1, 8); self.par.setValue(int(self.current['parallel_downloads']))
        lay.addRow("Simultaneous Downloads:", self.par)

        self.cap = QtWidgets.QSpinBox(); self.cap.setRange(0, 10_000_000); self.cap.setSuffix(" KiB/s (0 = unlimited)")
        self.cap.setValue(int(self.current.get('speed_cap_kib', 0)))
        lay.addRow("Speed Cap (aria2c):", self.cap)

        self.c_san = QtWidgets.QCheckBox("Sanitize filenames"); self.c_san.setChecked(self.current.get('sanitize_names', False))
        self.c_route = QtWidgets.QCheckBox("Auto route per system"); self.c_route.setChecked(self.current.get('auto_route_per_system', True))
        lay.addRow(self.c_san); lay.addRow(self.c_route)

        # Display of SAVED folder (not live); updated on Save/Switch
        self.last_label = QtWidgets.QLabel(self.current.get('last_rel', '') or '/')
        lay.addRow("Saved Folder:", self.last_label)

        btn_t.clicked.connect(lambda: self._pick(self.temp))
        btn_o.clicked.connect(lambda: self._pick(self.out))
        btn_save.clicked.connect(self._save_button)
        btn_new.clicked.connect(self._new)
        self.combo.currentIndexChanged.connect(self._switch)

    def _pick(self, edit: QtWidgets.QLineEdit):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Directory", edit.text() or str(Path.home()))
        if d:
            edit.setText(d)

    # ---- profile getters/setters ----
    def current_profile(self) -> dict:
        # Compose from UI + SAVED last_url/last_rel (not live)
        return {
            "name": self.combo.currentText(),
            "temp_dir": self.temp.text(),
            "downloader": 'aria2c' if self.r_aria.isChecked() else 'wget',
            "extract_zip": self.c_ext.isChecked(),
            "convert_to_chd": self.c_chd.isChecked(),
            "delete_after_extract": self.c_delx.isChecked(),
            "delete_after_chd": self.c_delc.isChecked(),
            "output_dir": self.out.text(),
            "parallel_downloads": self.par.value(),
            "speed_cap_kib": self.cap.value(),
            "sanitize_names": self.c_san.isChecked(),
            "auto_route_per_system": self.c_route.isChecked(),
            "last_url": self.current.get("last_url", BASE_URL),
            "last_rel": self.current.get("last_rel", ""),
        }

    def set_saved_path(self, url: str, rel: str):
        """Set the SAVED path (used on Save/New only)."""
        name = self.combo.currentText()
        for i, p in enumerate(self.profiles):
            if p['name'] == name:
                p['last_url'] = url or BASE_URL
                p['last_rel'] = rel or ""
                self.current = p
                break
        # Update label to show the just-saved folder; persistence happens in _save_button/_new
        self.last_label.setText(self.current.get('last_rel', '') or '/')

    def _emit_profile_changed_async(self, data: dict):
        QtCore.QTimer.singleShot(0, lambda: self.profileChanged.emit(copy.deepcopy(data)))

    def _save_button(self):
        # Ask MainWindow to snapshot CURRENT browsing folder into this profile
        self.aboutToSave.emit()

        name = self.combo.currentText()
        data = self.current_profile()

        # Replace or append
        found = False
        for i, p in enumerate(self.profiles):
            if p['name'] == name:
                self.profiles[i] = data
                found = True
                break
        if not found:
            self.profiles.append(data)
            self._suppress_combo_signal = True
            try:
                self.combo.blockSignals(True)
                self.combo.addItem(name)
                self.combo.setCurrentText(name)
            finally:
                self.combo.blockSignals(False)
                self._suppress_combo_signal = False

        self._save_profiles()
        self.current = data
        self._emit_profile_changed_async(self.current)

    def _new(self):
        # Snapshot current folder into the active profile first (so the clone inherits it)
        self.aboutToSave.emit()

        name, ok = QtWidgets.QInputDialog.getText(self, "New Profile", "Name")
        if not ok or not name:
            return
        data = self.current_profile(); data['name'] = name
        self.profiles.append(data)
        self._save_profiles()
        self.current = data
        self._suppress_combo_signal = True
        try:
            self.combo.blockSignals(True)
            self.combo.addItem(name)
            self.combo.setCurrentText(name)
        finally:
            self.combo.blockSignals(False)
            self._suppress_combo_signal = False
        self._emit_profile_changed_async(self.current)

    def _switch(self, idx: int):
        if self._suppress_combo_signal:
            return
        try:
            self.current = self.profiles[idx]
        except Exception:
            return
        # Load UI fields (saved values)
        self.temp.setText(self.current['temp_dir'])
        self.r_aria.setChecked(self.current['downloader'] != 'wget')
        self.r_wget.setChecked(self.current['downloader'] == 'wget')
        self.c_ext.setChecked(self.current['extract_zip'])
        self.c_chd.setChecked(self.current['convert_to_chd'])
        self.c_delx.setChecked(self.current['delete_after_extract'])
        self.c_delc.setChecked(self.current['delete_after_chd'])
        self.out.setText(self.current['output_dir'])
        self.par.setValue(int(self.current['parallel_downloads']))
        self.cap.setValue(int(self.current.get('speed_cap_kib', 0)))
        self.c_san.setChecked(self.current.get('sanitize_names', False))
        self.c_route.setChecked(self.current.get('auto_route_per_system', True))
        self.last_label.setText(self.current.get('last_rel', '') or '/')
        # Notify MainWindow to navigate to the SAVED folder for this profile
        self._emit_profile_changed_async(self.current)


# ---------------- Main Window -----------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 720)

        # Panels
        self.tree = BrowserTree(BASE_URL, CACHE_DIR)
        self.table = FileTable(CACHE_DIR)
        self.profile = ProfilePanel()
        self.queue = QueuePanel()

        splitter = QtWidgets.QSplitter(); splitter.addWidget(self.tree); splitter.addWidget(self.table)
        right = QtWidgets.QTabWidget(); right.addTab(self.profile, "Profiles"); right.addTab(self.queue, "Queue")
        splitter.addWidget(right); splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)

        tb = self.addToolBar("Main"); self.search = QtWidgets.QLineEdit(); self.search.setPlaceholderText("Search in folder…"); btn_add = QtWidgets.QPushButton("Add to Queue")
        tb.addWidget(self.search); tb.addWidget(btn_add)
        self.statusBar().showMessage(f"Connected to {BASE_URL}")

        # Signals
        self.tree.pathSelected.connect(self.on_tree_path)
        self.table.navigateTo.connect(self.on_center_folder)
        btn_add.clicked.connect(self.on_add_to_queue)
        self.search.textChanged.connect(self.apply_filter)

        # Critical: capture current folder into profile ONLY on Save/New
        self.profile.aboutToSave.connect(self._snapshot_current_folder_into_profile)
        self.profile.profileChanged.connect(self.on_profile_changed, QtCore.Qt.QueuedConnection)

        # Initial: navigate to the SAVED folder of the default/active profile
        active = self.profile.current
        self.current_url = active.get("last_url") or BASE_URL
        self.current_rel = active.get("last_rel") or ""
        self.table.load(self.current_url)

        # Parallelism from profile
        self.queue.set_parallel(int(active['parallel_downloads']))

    # Snapshot current folder into profile ONLY when saving/creating
    @QtCore.Slot()
    def _snapshot_current_folder_into_profile(self):
        self.profile.set_saved_path(self.current_url or BASE_URL, self.current_rel or "")

    # Profile changed (save or switch) → navigate to the SAVED folder
    @QtCore.Slot(dict)
    def on_profile_changed(self, prof: dict) -> None:
        self.queue.set_parallel(int(prof['parallel_downloads']))
        self.current_url = prof.get("last_url") or BASE_URL
        self.current_rel = prof.get("last_rel") or ""
        self.table.load(self.current_url)
        self.statusBar().showMessage(f"Loaded profile '{prof.get('name','')}' at {self.current_rel or '/'}")

    # Navigation (tree) — NO saving of path here
    def on_tree_path(self, url: str, rel: str) -> None:
        self.current_url = url
        self.current_rel = rel
        self.table.load(url)

    # Navigation (center) — NO saving of path here
    def on_center_folder(self, child_url: str, child_name: str) -> None:
        self.current_url = child_url
        self.current_rel = str(Path(self.current_rel) / child_name) if self.current_rel else child_name
        self.table.load(child_url)
        self.tree.select_child_by_name(child_name)

    def apply_filter(self, text: str) -> None:
        t = text.lower()
        for r in range(self.table.rowCount()):
            name = self.table.item(r, 1).text().lower()
            self.table.setRowHidden(r, t not in name)

    def on_add_to_queue(self) -> None:
        files = self.table.selected_files()
        if not files:
            QtWidgets.QMessageBox.information(self, APP_NAME, "No files selected.")
            return
        self.queue.add_items(files, self.current_rel, self.profile.current_profile())

    # Clean shutdown of QThreads
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        try:
            self.queue.shutdown()
        except Exception:
            pass
        super().closeEvent(event)


# ---------------- App bootstrap -----------------
def main():
    app = QtWidgets.QApplication([])
    # simple dark theme
    pal = app.palette()
    pal.setColor(QtGui.QPalette.Window, QtGui.QColor(32, 36, 40))
    pal.setColor(QtGui.QPalette.Base, QtGui.QColor(22, 24, 28))
    pal.setColor(QtGui.QPalette.Text, QtGui.QColor(230, 230, 230))
    pal.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(230, 230, 230))
    app.setPalette(pal)
    w = MainWindow(); w.show(); app.exec()


if __name__ == "__main__":
    main()
