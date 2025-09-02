#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Two-phase queue for Myrient ROM Manager

Phase A: Download all items (N-way parallel)
Phase B: Convert all downloaded items (sequential by default)
Phase C: Cleanup (temp dirs nuked after successful conversion; final sweep)

- Robust, live progress for aria2c/wget via stdout parsing
- Logs tab with per-item verbose output
- Auto-advance from downloads → processing → cleanup (no extra clicks)
- CLEAN SHUTDOWN: QueuePanel.shutdown() stops QThreads to avoid 'QThread: Destroyed...' on exit
"""
from __future__ import annotations
import os
import re
import time
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlparse

import requests
from PySide6 import QtCore, QtWidgets
import queue as pyqueue  # stdlib queue


# --------------------------------------------------------------------------------------
# External tools

class Tooling:
    def __init__(self):
        self.aria2c = self.which("aria2c")
        self.wget   = self.which("wget")
        self.unzip  = self.which("unzip") or self.which("7z")
        self.chdman = self.which("chdman")

    @staticmethod
    def which(cmd: str) -> str | None:
        exts = ["", ".exe", ".bat", ".cmd"] if os.name == "nt" else [""]
        for p in os.environ.get("PATH", "").split(os.pathsep):
            for ext in exts:
                c = Path(p) / f"{cmd}{ext}"
                if c.exists() and os.access(c, os.X_OK):
                    return str(c)
        return None

TOOLS = Tooling()
_session = requests.Session()
_session.headers.update({"User-Agent": "MyrientROMManager/1.0"})


# --------------------------------------------------------------------------------------
# Queue item

class QueueItem(QtCore.QObject):
    progress_changed = QtCore.Signal(float, str, str)   # pct (0..1), speed, eta
    status_changed   = QtCore.Signal(str, str)          # status, step
    log_emitted      = QtCore.Signal(str)               # text line

    def __init__(self, url: str, rel_path: str, profile: dict):
        super().__init__()
        self.url = url
        self.rel_path = rel_path
        self.profile = profile
        self.status = "Queued"
        self.step = ""
        self.progress = 0.0
        self.speed = ""
        self.eta = ""
        self.local_file: str | None = None
        self.temp_dir: Path | None = None
        self.downloaded_ok = False
        self.converted_ok = False

    def emit_progress(self, pct: float, speed: str = "", eta: str = ""):
        self.progress = max(0.0, min(1.0, pct))
        self.speed = speed
        self.eta = eta
        self.progress_changed.emit(self.progress, self.speed, self.eta)

    def emit_status(self, status: str, step: str = ""):
        self.status = status
        self.step = step or self.step
        self.status_changed.emit(self.status, self.step)

    def log(self, text: str):
        self.log_emitted.emit(text.rstrip("\n"))


# --------------------------------------------------------------------------------------
# Workers

class DownloadWorker(QtCore.QThread):
    """Downloads only. Emits progress from stdout parsing."""
    def __init__(self, work_q: pyqueue.Queue):
        super().__init__()
        self.work_q = work_q
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        while not self._stop:
            try:
                item: QueueItem = self.work_q.get(timeout=0.25)
            except pyqueue.Empty:
                continue
            try:
                self._download_item(item)
                item.downloaded_ok = True
            except Exception as e:
                item.emit_status("Error", step=f"Download failed: {e}")
                item.log(f"[ERROR] Download failed: {e}")
            finally:
                self.work_q.task_done()

    def _download_item(self, item: QueueItem):
        prof = item.profile
        job_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", Path(item.rel_path).stem)
        temp_dir = Path(prof["temp_dir"]) / job_name
        temp_dir.mkdir(parents=True, exist_ok=True)
        item.temp_dir = temp_dir

        filename = Path(urlparse(item.url).path).name
        if prof.get("sanitize_names"):
            filename = re.sub(r"[^\w.()\-\ ]+", "_", filename)
        dest = temp_dir / filename
        item.local_file = str(dest)

        item.emit_status("Running", step="Downloading")
        item.emit_progress(0.0, "", "")

        speed_cap = int(prof.get("speed_cap_kib", 0))
        if prof.get("downloader") == "aria2c" and TOOLS.aria2c:
            cmd = [
                TOOLS.aria2c,
                "--console-log-level=notice",
                "--enable-color=false",
                "--show-console-readout=true",
                "--allow-overwrite=true",
                "--continue=true",
                "--max-connection-per-server=16",
                "--split=16",
                "--min-split-size=1M",
                "--summary-interval=1",
                f"--dir={dest.parent}",
                f"--out={dest.name}",
                item.url,
            ]
            if speed_cap > 0:
                cmd.insert(-1, f"--max-overall-download-limit={speed_cap}K")
            item.log(f"[CMD] {' '.join(cmd)}")
            self._run_downloader_and_parse(cmd, item, tool="aria2c")
        elif TOOLS.wget:
            cmd = [TOOLS.wget, "-c", "-O", str(dest), item.url]
            item.log(f"[CMD] {' '.join(cmd)}")
            self._run_downloader_and_parse(cmd, item, tool="wget")
        else:
            item.log("[INFO] Using Python HTTP stream fallback.")
            with _session.get(item.url, stream=True, timeout=30) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length", "0") or 0)
                read = 0
                last_emit = time.time()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 128):
                        if not chunk:
                            continue
                        f.write(chunk)
                        read += len(chunk)
                        now = time.time()
                        if now - last_emit >= 0.3:
                            pct = (read / total) if total else 0.0
                            item.emit_progress(pct, "", "")
                            last_emit = now

        item.emit_progress(1.0, "", "")
        item.emit_status("Downloaded", step="Download complete")
        item.log("[INFO] Download complete.")

    def _run_downloader_and_parse(self, cmd: list[str], item: QueueItem, tool: str):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

        aria_pct       = re.compile(r"\((\d+)%\)")
        aria_speed_eta = re.compile(r"DL:\s*([0-9.]+[KMG]?i?B/s)\s+ETA:\s*([0-9hms:]+)", re.I)
        wget_pct       = re.compile(r"(\d+)%")
        wget_speed_eta = re.compile(r"\s([0-9.]+[KMG]?i?B?/s)\s+eta\s+([0-9hms:]+)", re.I)

        for raw in proc.stdout or []:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            item.log(line)

            if tool == "aria2c":
                m1 = aria_pct.search(line)
                m2 = aria_speed_eta.search(line)
                if m1 or m2:
                    pct = float(m1.group(1)) / 100.0 if m1 else item.progress
                    spd = m2.group(1) if m2 else item.speed
                    eta = m2.group(2) if m2 else item.eta
                    item.emit_progress(pct, spd, eta)
                    continue
            else:
                m1 = wget_pct.search(line)
                m2 = wget_speed_eta.search(line)
                if m1 or m2:
                    pct = float(m1.group(1)) / 100.0 if m1 else item.progress
                    spd = m2.group(1) if m2 else item.speed
                    eta = m2.group(2) if m2 else item.eta
                    item.emit_progress(pct, spd, eta)
                    continue

        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"{tool} exited with code {proc.returncode}")


class ProcessWorker(QtCore.QThread):
    """Converts to CHD and cleans up (no downloading)."""
    def __init__(self, work_q: pyqueue.Queue):
        super().__init__()
        self.work_q = work_q
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        while not self._stop:
            try:
                item: QueueItem = self.work_q.get(timeout=0.25)
            except pyqueue.Empty:
                continue
            try:
                self._process_item(item)
                item.converted_ok = True
            except Exception as e:
                item.emit_status("Error", step=f"Process failed: {e}")
                item.log(f"[ERROR] Process failed: {e}")
            finally:
                self.work_q.task_done()

    def _process_item(self, item: QueueItem):
        prof = item.profile
        temp_dir = Path(item.temp_dir or Path(prof["temp_dir"]) / Path(item.rel_path).stem)

        fn = Path(item.local_file or "")
        if fn.exists() and fn.suffix.lower() == ".zip" and prof.get("extract_zip", True):
            item.emit_status("Running", step="Extracting")
            item.log("[INFO] Extracting archive…")
            self._extract_zip(fn, temp_dir)
            if prof.get("delete_after_extract"):
                try:
                    fn.unlink(missing_ok=True)
                    item.log("[INFO] Deleted archive after extraction.")
                except Exception as e:
                    item.log(f"[WARN] Could not delete archive: {e}")

        if prof.get("convert_to_chd", True):
            cue_candidates = sorted(temp_dir.rglob("*.cue"))
            iso_candidates = sorted(temp_dir.rglob("*.iso"))
            out_dir = Path(prof["output_dir"]) if not prof.get("auto_route_per_system") else self._auto_route(Path(prof["output_dir"]), item.rel_path)
            out_dir.mkdir(parents=True, exist_ok=True)
            if cue_candidates:
                src = cue_candidates[0]
                out_chd = out_dir / (src.stem + ".chd")
                item.emit_status("Running", step="Converting (CUE→CHD)")
                item.log(f"[INFO] chdman createcd -i {src} -o {out_chd}")
                self._chd_from_input(src, out_chd, item)
                if prof.get("delete_after_chd"):
                    try:
                        src.unlink(missing_ok=True)
                        for b in src.parent.glob("*.bin"): b.unlink(missing_ok=True)
                        item.log("[INFO] Deleted BIN/CUE after CHD conversion.")
                    except Exception as e:
                        item.log(f"[WARN] Could not delete BIN/CUE: {e}")
            elif iso_candidates:
                src = iso_candidates[0]
                out_chd = out_dir / (src.stem + ".chd")
                item.emit_status("Running", step="Converting (ISO→CHD)")
                item.log(f"[INFO] chdman createcd -i {src} -o {out_chd}")
                self._chd_from_input(src, out_chd, item)
                if prof.get("delete_after_chd"):
                    try:
                        src.unlink(missing_ok=True)
                        item.log("[INFO] Deleted ISO after CHD conversion.")
                    except Exception as e:
                        item.log(f"[WARN] Could not delete ISO: {e}")
            else:
                item.log("[INFO] No .cue or .iso detected; skipping CHD.")

        item.emit_progress(1.0, "", "")
        item.emit_status("Done", step="Finished")
        item.log("[INFO] Processing finished.")

        try:
            if item.temp_dir and item.temp_dir.exists():
                import shutil
                shutil.rmtree(item.temp_dir)
                item.log("[INFO] Cleaned up temp directory.")
        except Exception as e:
            item.emit_status("Warning", step=f"Cleanup failed: {e}")
            item.log(f"[WARN] Cleanup failed: {e}")

    def _auto_route(self, base: Path, rel_path: str) -> Path:
        parts = list(Path(rel_path).parts)
        return base / parts[0] if parts else base

    def _extract_zip(self, archive: Path, out_dir: Path):
        if TOOLS.unzip and Path(TOOLS.unzip).name.lower().startswith("7z"):
            cmd = [TOOLS.unzip, "x", str(archive), f"-o{out_dir}", "-y"]
        elif TOOLS.unzip:
            cmd = [TOOLS.unzip, "-o", str(archive), "-d", str(out_dir)]
        else:
            raise RuntimeError("No unzip/7z tool found")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout or []:
            if line.strip():
                pass
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError("Extraction failed")

    def _chd_from_input(self, src: Path, out_chd: Path, item: QueueItem):
        if not TOOLS.chdman:
            raise RuntimeError("chdman not found. Install MAME (mame-tools).")
        cmd = [TOOLS.chdman, "createcd", "-i", str(src), "-o", str(out_chd)]
        item.log(f"[CMD] {' '.join(cmd)}")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        last_tick = time.time()
        while proc.poll() is None:
            now = time.time()
            if now - last_tick >= 0.75:
                item.emit_progress(min(max(item.progress, 0.01), 0.99))
                last_tick = now
            line = proc.stdout.readline()
            if not line:
                time.sleep(0.1); continue
            item.log(line.strip())
        if proc.returncode != 0:
            raise RuntimeError("chdman failed")


# --------------------------------------------------------------------------------------
# Queue panel (UI)

class QueuePanel(QtWidgets.QWidget):
    startProcessingRequested = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.items: list[QueueItem] = []
        self._dl_q: pyqueue.Queue = pyqueue.Queue()
        self._proc_q: pyqueue.Queue = pyqueue.Queue()
        self._dl_workers: list[DownloadWorker] = []
        self._proc_workers: list[ProcessWorker] = []
        self._downloads_started = False
        self._processing_started = False

        self._build_ui()
        self.startProcessingRequested.connect(self._start_processing)

    # ---------- CLEAN SHUTDOWN ----------
    def shutdown(self):
        """Stop workers and drain queues to avoid QThread destruction warnings."""
        # stop workers
        for w in self._dl_workers: w.stop()
        for w in self._proc_workers: w.stop()
        # clear queues to unblock any get() timeouts quickly
        try:
            with self._dl_q.mutex: self._dl_q.queue.clear()
            with self._proc_q.mutex: self._proc_q.queue.clear()
        except Exception:
            pass
        # wait a bit for threads to exit
        for w in self._dl_workers: w.wait(3000)
        for w in self._proc_workers: w.wait(3000)

    # --- UI ---
    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs)

        queue_page = QtWidgets.QWidget()
        qv = QtWidgets.QVBoxLayout(queue_page)
        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Filename", "Phase", "Progress", "Speed", "ETA", "Step", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        qv.addWidget(self.table)
        h = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("Start")
        self.btn_clear = QtWidgets.QPushButton("Clear Queue")
        h.addWidget(self.btn_start); h.addWidget(self.btn_clear); h.addStretch(1)
        qv.addLayout(h)
        self.tabs.addTab(queue_page, "Queue")

        logs_page = QtWidgets.QWidget()
        lv = QtWidgets.QVBoxLayout(logs_page)
        self.log_view = QtWidgets.QPlainTextEdit(); self.log_view.setReadOnly(True)
        lv.addWidget(self.log_view)
        self.tabs.addTab(logs_page, "Logs")

        self.btn_start.clicked.connect(self._start_or_advance)
        self.btn_clear.clicked.connect(self.clear)

    # --- Public API used by main.py ---
    def set_parallel(self, n: int) -> None:
        # stop existing DL workers before resizing
        for w in self._dl_workers:
            w.stop(); w.wait(1500)
        self._dl_workers.clear()

        for _ in range(max(1, int(n))):
            w = DownloadWorker(self._dl_q)
            w.start()
            self._dl_workers.append(w)

        # ensure one processing worker
        if not self._proc_workers:
            p = ProcessWorker(self._proc_q)
            p.start()
            self._proc_workers.append(p)

    def add_items(self, files, rel_prefix: str, profile: dict) -> None:
        for name, url in files:
            item = QueueItem(url, str(Path(rel_prefix) / name), profile)
            self.items.append(item)
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(Path(item.rel_path).name))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem("Queued"))
            pb = QtWidgets.QProgressBar(); pb.setRange(0, 100); pb.setValue(0)
            self.table.setCellWidget(r, 2, pb)
            self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(""))
            self.table.setItem(r, 4, QtWidgets.QTableWidgetItem(""))
            self.table.setItem(r, 5, QtWidgets.QTableWidgetItem(""))
            self.table.setItem(r, 6, QtWidgets.QTableWidgetItem(item.status))

            item.progress_changed.connect(lambda pct, spd, eta, row=r, bar=pb: self._on_progress(row, bar, pct, spd, eta))
            item.status_changed.connect(lambda st, step, row=r: self._on_status(row, st, step))
            item.log_emitted.connect(lambda text, row=r, nm=Path(item.rel_path).name: self._append_log(nm, text))

    # --- Phase machine ---
    def _start_or_advance(self):
        if not self._downloads_started and self.items:
            self._start_downloads()
        elif self._downloads_started and not self._processing_started:
            self._start_processing()

    def _start_downloads(self):
        self._downloads_started = True
        for idx, it in enumerate(self.items):
            it.emit_status("Queued", step="Waiting (download)")
            self.table.item(idx, 1).setText("Downloading")
            self._dl_q.put(it)
        self._watch_downloads_completion()

    def _start_processing(self):
        if self._processing_started:
            return
        self._processing_started = True
        for idx, it in enumerate(self.items):
            if it.downloaded_ok:
                it.emit_status("Queued", step="Waiting (process)")
                self.table.item(idx, 1).setText("Processing")
                self._proc_q.put(it)
        self._watch_processing_completion()

    def _watch_downloads_completion(self):
        def _watch():
            while True:
                time.sleep(0.5)
                all_done = all(i.downloaded_ok or i.status.startswith("Error") for i in self.items)
                if all_done:
                    self.startProcessingRequested.emit()
                    break
        threading.Thread(target=_watch, daemon=True).start()

    def _watch_processing_completion(self):
        def _watch():
            while True:
                time.sleep(0.5)
                all_done = all((i.converted_ok or i.status.startswith("Error") or not i.downloaded_ok) for i in self.items)
                if all_done:
                    self._final_cleanup_sweep()
                    break
        threading.Thread(target=_watch, daemon=True).start()

    def _final_cleanup_sweep(self):
        for it in self.items:
            try:
                if it.converted_ok and it.temp_dir and it.temp_dir.exists():
                    import shutil
                    shutil.rmtree(it.temp_dir)
                    it.log("[INFO] Final sweep: cleaned temp directory.")
            except Exception as e:
                it.log(f"[WARN] Final sweep failed: {e}")

    # --- Slots ---
    @QtCore.Slot(int, QtWidgets.QProgressBar, float, str, str)
    def _on_progress(self, row: int, bar: QtWidgets.QProgressBar, pct: float, speed: str, eta: str):
        bar.setValue(int(pct * 100))
        if self.table.item(row, 3): self.table.item(row, 3).setText(speed or "")
        if self.table.item(row, 4): self.table.item(row, 4).setText(eta or "")

    @QtCore.Slot(int, str, str)
    def _on_status(self, row: int, status: str, step: str):
        if self.table.item(row, 5): self.table.item(row, 5).setText(step or "")
        if self.table.item(row, 6): self.table.item(row, 6).setText(status or "")

    # --- Logs ---
    def _append_log(self, name: str, text: str):
        self.log_view.appendPlainText(f"[{name}] {text}")

    # --- Clear ---
    def clear(self) -> None:
        self.items.clear()
        self.table.setRowCount(0)
        try:
            with self._dl_q.mutex: self._dl_q.queue.clear()
            with self._proc_q.mutex: self._proc_q.queue.clear()
        except Exception:
            pass
        self.log_view.clear()
        self._downloads_started = False
        self._processing_started = False
