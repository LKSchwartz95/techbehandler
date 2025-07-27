# Filename: tool_manager.py
import os
import sys
import json
import zipfile
from pathlib import Path
import requests

from PySide6.QtCore import QObject, Signal, QThread, Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QLabel, QMessageBox
)

# This allows the script to find the project root, even when imported by another script
PROJECT_ROOT = Path(__file__).resolve().parent
TOOLS_DIR = PROJECT_ROOT / "tools"
TOOLS_MANIFEST_PATH = PROJECT_ROOT / "tools.json"
LEGACY_MAT_PATH = PROJECT_ROOT / "mat"


class DownloadWorker(QObject):
    """
    A QObject worker for handling file downloads and extractions in a separate thread.
    """
    finished = Signal(str)
    error = Signal(str)
    progress = Signal(int)

    def __init__(self, url, save_path, extract_path):
        super().__init__()
        self.url, self.save_path, self.extract_path = url, Path(save_path), Path(extract_path)
        self.is_cancelled = False

    def run(self):
        try:
            self.save_path.parent.mkdir(parents=True, exist_ok=True)
            self.extract_path.mkdir(parents=True, exist_ok=True)
            with requests.get(self.url, stream=True, allow_redirects=True, timeout=30) as r:
                r.raise_for_status()
                total_size = int(r.headers.get('content-length', 0))
                downloaded_size = 0
                with open(self.save_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if self.is_cancelled:
                            self.error.emit("Download cancelled.")
                            return
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        if total_size > 0:
                            self.progress.emit(int((downloaded_size / total_size) * 100))
            
            self.progress.emit(100)
            if self.is_cancelled:
                self.error.emit("Download cancelled before extraction.")
                return
            
            with zipfile.ZipFile(self.save_path, 'r') as zip_ref:
                zip_ref.extractall(self.extract_path)
            
            os.remove(self.save_path)
            self.finished.emit(f"Successfully installed to {self.extract_path}")
        except Exception as e:
            self.error.emit(str(e))


class ToolManagerDialog(QDialog):
    """
    A dialog window for managing the download and installation of external tools.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tool Manager")
        self.setMinimumSize(600, 400)
        self.layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Tool", "Version", "Platform", "Status", "Action"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.layout.addWidget(self.table)
        self.download_thread, self.download_worker = None, None
        self.load_tools()

    def _find_installed_tool_dir(self, tool):
        """Returns a matching installation directory if the tool is already installed."""
        install_path = PROJECT_ROOT / tool.get("install_path")
        if install_path.exists() and any(install_path.iterdir()):
            return install_path

        if tool.get("id") == "wireshark":
            pattern = f"wireshark-*-{tool.get('platform')}"
            for path in TOOLS_DIR.glob(pattern):
                if path.exists() and any(path.iterdir()):
                    return path
        return None

    def load_tools(self):
        """
        Populates the table with tools from the manifest and checks their installation status.
        """
        self.table.setRowCount(0)
        
        # Check for legacy MAT installation
        legacy_mat_found = LEGACY_MAT_PATH.is_dir() and any(LEGACY_MAT_PATH.iterdir())
        if legacy_mat_found:
            self.table.insertRow(0)
            self.table.setItem(0, 0, QTableWidgetItem("Eclipse Memory Analyzer (Legacy)"))
            self.table.setItem(0, 1, QTableWidgetItem("Unknown"))
            self.table.setItem(0, 2, QTableWidgetItem("N/A"))
            status_item = QTableWidgetItem("Installed (Legacy)")
            status_item.setForeground(Qt.GlobalColor.darkGreen)
            self.table.setItem(0, 3, status_item)
            self.table.setCellWidget(0, 4, QLabel("Detected in 'mat' folder"))

        if not TOOLS_MANIFEST_PATH.exists():
            if not legacy_mat_found:
                QMessageBox.warning(self, "Error", f"Tool manifest not found at {TOOLS_MANIFEST_PATH}")
            return

        with open(TOOLS_MANIFEST_PATH, "r") as f:
            manifest = json.load(f)

        for tool in manifest.get("tools", []):
            row_index = self.table.rowCount()
            self.table.insertRow(row_index)
            self.table.setItem(row_index, 0, QTableWidgetItem(tool.get("name")))
            self.table.setItem(row_index, 1, QTableWidgetItem(tool.get("version")))
            self.table.setItem(row_index, 2, QTableWidgetItem(tool.get("platform")))

            install_dir = self._find_installed_tool_dir(tool)
            status_item = QTableWidgetItem()
            action_button = QPushButton()

            if install_dir is not None:
                status_item.setText("Installed")
                status_item.setForeground(Qt.GlobalColor.darkGreen)
                action_button.setText("Re-install")
            else:
                status_item.setText("Not Installed")
                status_item.setForeground(Qt.GlobalColor.red)
                action_button.setText("Download & Install")

            self.table.setItem(row_index, 3, status_item)
            action_button.clicked.connect(lambda checked, t=tool, r=row_index: self.start_download(t, r))
            self.table.setCellWidget(row_index, 4, action_button)

    def start_download(self, tool_info, row_index):
        """
        Initiates the download process for a selected tool in a background thread.
        """
        url = tool_info.get("url")
        install_path = PROJECT_ROOT / tool_info.get("install_path")
        save_path = TOOLS_DIR / f"{tool_info['id']}-{tool_info['platform']}.zip"
        
        self.table.cellWidget(row_index, 4).setEnabled(False)
        status_item = self.table.item(row_index, 3)
        status_item.setText("Downloading (0%)...")
        
        self.download_worker = DownloadWorker(url, save_path, install_path)
        self.download_thread = QThread()
        self.download_worker.moveToThread(self.download_thread)
        
        self.download_worker.progress.connect(lambda p, item=status_item: item.setText(f"Downloading ({p}%)..."))
        self.download_worker.error.connect(self.on_download_error)
        self.download_worker.finished.connect(self.on_download_finished)
        
        self.download_thread.started.connect(self.download_worker.run)
        self.download_thread.start()

    def on_download_error(self, error_msg):
        QMessageBox.critical(self, "Download Error", error_msg)
        self.cleanup_thread()
        self.load_tools()

    def on_download_finished(self, message):
        QMessageBox.information(self, "Success", message)
        self.cleanup_thread()
        self.load_tools()

    def cleanup_thread(self):
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.quit()
            self.download_thread.wait()
        self.download_thread, self.download_worker = None, None

    def closeEvent(self, event):
        """
        Ensures the download is cancelled if the dialog is closed prematurely.
        """
        if self.download_worker:
            self.download_worker.is_cancelled = True
        self.cleanup_thread()
        super().closeEvent(event)