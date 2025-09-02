#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Browser widgets and directory scraping for Myrient ROM Manager.

Exports
- list_directory(url, cache_dir=None)
- BrowserTree(base_url)
- FileTable()
"""
from __future__ import annotations
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from PySide6 import QtCore, QtWidgets

# ---- HTTP (polite) ---------------------------------------------------------
_session = requests.Session()
_session.headers.update({"User-Agent": "MyrientROMManager/1.0"})
_lock = QtCore.QMutex()


def _http_get(url: str) -> str:
    # Use a mutex to serialize requests slightly to be gentle
    locker = QtCore.QMutexLocker(_lock)
    try:
        QtCore.QThread.msleep(250)
        r = _session.get(url, timeout=30)
        r.raise_for_status()
        return r.text
    finally:
        del locker


# ---- Directory listing -----------------------------------------------------

def list_directory(url: str, cache_dir: Path | None = None):
    """Return (subdirs, files) parsed from Myrient directory index.

    Each entry is a dict: {name, url, size, date}
    """
    html: str
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", url)
        cache_file = cache_dir / f"{safe}.html"
        if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < 120:
            html = cache_file.read_text(encoding="utf-8", errors="ignore")
        else:
            html = _http_get(url)
            cache_file.write_text(html, encoding="utf-8")
    else:
        html = _http_get(url)

    soup = BeautifulSoup(html, "html.parser")

    subdirs, files = [], []

    def push(name: str, href: str, size: str, date: str):
        full = urljoin(url, href)
        (subdirs if href.endswith("/") else files).append({
            "name": name.strip("/"),
            "url": full,
            "size": size.strip(),
            "date": date.strip(),
        })

    # Accept both SI and IEC units (KiB, MiB, GiB, TiB) + plain B
    SIZE_RE = re.compile(r"(\d+(?:[.,]\d+)?\s*(?:[KMGT]i?B|B))", re.IGNORECASE)
    DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2}[^ ]*)")

    table = soup.find("table")
    if table:
        # Table-style: parse each row
        for tr in table.find_all("tr"):
            a = tr.find("a")
            if not a:
                continue
            name = (a.text or "").strip()
            href = a.get("href")
            if not href or name == "Parent Directory":
                continue

            # Collect all cell text for a robust regex scan
            cells_text = " ".join(td.get_text(" ", strip=True) for td in tr.find_all("td"))
            m_size = SIZE_RE.search(cells_text)
            m_date = DATE_RE.search(cells_text)

            push(name, href,
                 m_size.group(1) if m_size else "",
                 m_date.group(1) if m_date else "")
    else:
        # Plain listing: link lines contain name, then size/date text
        for a in soup.find_all("a"):
            href = a.get("href")
            name = (a.text or "").strip()
            if not href or href.startswith("?") or name == "Parent Directory":
                continue
            row = a.find_parent("tr") or a.parent
            size = date = ""
            if row is not None:
                text = row.get_text(" ", strip=True)
                # Examples:
                # "Some Game.zip 175.9 MiB 02-Apr-2022 04:55"
                # "FolderName/ - 31-Aug-2025 12:59"
                m_size = SIZE_RE.search(text)
                m_date = DATE_RE.search(text)
                if m_size:
                    size = m_size.group(1)
                # Directories often show "-" for size; we just leave it blank
                if m_date:
                    date = m_date.group(1)
            push(name, href, size, date)

    return subdirs, files


# ---- Widgets ---------------------------------------------------------------

class BrowserTree(QtWidgets.QTreeWidget):
    pathSelected = QtCore.Signal(str, str)  # (url, rel_path)

    def __init__(self, base_url: str, cache_dir: Path | None = None):
        super().__init__()
        self.base_url = base_url
        self.cache_dir = cache_dir
        self.setHeaderHidden(True)
        self.setIconSize(QtCore.QSize(18, 18))
        self.setAnimated(True)
        root = QtWidgets.QTreeWidgetItem(["Myrient"])
        root.setData(0, QtCore.Qt.UserRole, base_url)
        root.setData(0, QtCore.Qt.UserRole + 1, "")
        root.setExpanded(True)
        self.addTopLevelItem(root)
        self.populate_node(root, base_url, rel_prefix="")
        self.itemExpanded.connect(self.on_expand)
        self.itemClicked.connect(self.on_click)

    def populate_node(self, node: QtWidgets.QTreeWidgetItem, url: str, rel_prefix: str) -> None:
        try:
            subdirs, _ = list_directory(url, self.cache_dir)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Myrient", f"Failed to load {url}: {e}")
            return
        node.takeChildren()
        for sd in subdirs:
            it = QtWidgets.QTreeWidgetItem([sd["name"]])
            it.setData(0, QtCore.Qt.UserRole, sd["url"])
            it.setData(0, QtCore.Qt.UserRole + 1, str(Path(rel_prefix) / sd["name"]))
            node.addChild(it)

    def on_expand(self, item: QtWidgets.QTreeWidgetItem) -> None:
        url = item.data(0, QtCore.Qt.UserRole)
        rel = item.data(0, QtCore.Qt.UserRole + 1) or ""
        self.populate_node(item, url, rel)

    def on_click(self, item: QtWidgets.QTreeWidgetItem, _column: int) -> None:
        url = item.data(0, QtCore.Qt.UserRole)
        rel = item.data(0, QtCore.Qt.UserRole + 1) or ""
        self.pathSelected.emit(url, rel)

    def select_child_by_name(self, child_name: str) -> None:
        cur = self.currentItem() or self.topLevelItem(0)
        self.on_expand(cur)
        for i in range(cur.childCount()):
            ch = cur.child(i)
            if ch.text(0) == child_name:
                self.setCurrentItem(ch)
                self.pathSelected.emit(
                    ch.data(0, QtCore.Qt.UserRole),
                    ch.data(0, QtCore.Qt.UserRole + 1) or "",
                )
                break


class FileTable(QtWidgets.QTableWidget):
    navigateTo = QtCore.Signal(str, str)  # (child_url, child_rel_name)

    def __init__(self, cache_dir: Path | None = None):
        super().__init__(0, 4)
        self.cache_dir = cache_dir
        self.setHorizontalHeaderLabels(["", "Name", "Size", "Date"])
        self.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.itemDoubleClicked.connect(self._on_activated)

    def load(self, url: str) -> None:
        try:
            subdirs, files = list_directory(url, self.cache_dir)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Myrient", f"Failed to list files: {e}")
            return
        self.setRowCount(0)
        # Folders
        for sd in subdirs:
            row = self.rowCount()
            self.insertRow(row)
            folder_icon = self.style().standardIcon(QtWidgets.QStyle.SP_DirIcon)
            icon_item = QtWidgets.QTableWidgetItem()
            icon_item.setIcon(folder_icon)
            icon_item.setData(QtCore.Qt.UserRole, sd["url"])
            icon_item.setData(QtCore.Qt.UserRole + 1, True)
            icon_item.setFlags(icon_item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.setItem(row, 0, icon_item)
            name_it = QtWidgets.QTableWidgetItem(sd["name"])  # show folder name
            name_it.setData(QtCore.Qt.UserRole, sd["url"])
            name_it.setData(QtCore.Qt.UserRole + 1, True)
            self.setItem(row, 1, name_it)
            self.setItem(row, 2, QtWidgets.QTableWidgetItem(""))
            self.setItem(row, 3, QtWidgets.QTableWidgetItem(sd.get("date", "")))
        # Files
        for f in files:
            row = self.rowCount()
            self.insertRow(row)
            file_icon = self.style().standardIcon(QtWidgets.QStyle.SP_FileIcon)
            icon_item = QtWidgets.QTableWidgetItem()
            icon_item.setIcon(file_icon)
            icon_item.setData(QtCore.Qt.UserRole, f["url"])
            icon_item.setData(QtCore.Qt.UserRole + 1, False)
            icon_item.setFlags(icon_item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.setItem(row, 0, icon_item)
            name_it = QtWidgets.QTableWidgetItem(f["name"])  # filename
            name_it.setData(QtCore.Qt.UserRole, f["url"])
            name_it.setData(QtCore.Qt.UserRole + 1, False)
            self.setItem(row, 1, name_it)
            self.setItem(row, 2, QtWidgets.QTableWidgetItem(f.get("size", "")))
            self.setItem(row, 3, QtWidgets.QTableWidgetItem(f.get("date", "")))

    def selected_files(self):
        out = []
        for r in range(self.rowCount()):
            name_item = self.item(r, 1)
            if name_item and name_item.isSelected():
                is_dir = bool(name_item.data(QtCore.Qt.UserRole + 1))
                if not is_dir:
                    out.append((name_item.text(), name_item.data(QtCore.Qt.UserRole)))
        return out

    # Navigation when double-clicking folders in the center view
    def _on_activated(self, item: QtWidgets.QTableWidgetItem):
        r = item.row()
        name_item = self.item(r, 1)
        is_dir = bool(name_item.data(QtCore.Qt.UserRole + 1))
        url = name_item.data(QtCore.Qt.UserRole)
        if is_dir and url:
            self.navigateTo.emit(url, name_item.text())
