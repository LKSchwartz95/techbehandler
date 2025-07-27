# Filename: capture_dialog.py
import os
import time
import asyncio
import sys
import ctypes
import pyshark
from pathlib import Path
from pyshark.tshark.tshark import get_tshark_interfaces

from PySide6.QtCore import QObject, Signal, QThread
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox, QSpinBox,
    QPushButton, QLabel, QMessageBox, QApplication
)

PROJECT_ROOT = Path(__file__).resolve().parent
RESULTAT_DIR = PROJECT_ROOT / "Resultat"


def is_admin() -> bool:
    if os.name == "nt":
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    else:
        return os.geteuid() == 0


class CaptureWorker(QObject):
    finished = Signal(str)
    error = Signal(str)
    progress = Signal(str)
    countdown = Signal(int)

    def __init__(self, interface, duration, output_file, tshark_path):
        super().__init__()
        self.interface = interface
        self.duration = duration
        self.output_file = output_file
        self.tshark_path = tshark_path
        self.is_cancelled = False

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            self.progress.emit(f"Starting capture on '{self.interface}' for {self.duration} seconds...")
            os.makedirs(os.path.dirname(self.output_file), exist_ok=True)

            capture = pyshark.LiveCapture(
                interface=self.interface,
                tshark_path=self.tshark_path,
                custom_parameters=['-w', self.output_file]
            )

            capture.sniff(timeout=self.duration)  # ✅ THE CRITICAL MISSING LINE
            capture.close()

            if self.is_cancelled:
                if os.path.exists(self.output_file):
                    try:
                        os.remove(self.output_file)
                    except OSError as e:
                        self.progress.emit(f"Could not delete partial capture file: {e}")
                self.error.emit("Capture was cancelled.")
                return

            self.countdown.emit(0)
            self.progress.emit("Finalizing capture file...")

            timeout_seconds = 10
            poll_interval = 0.2
            elapsed_time = 0
            file_ready = False

            while elapsed_time < timeout_seconds:
                if os.path.exists(self.output_file) and os.path.getsize(self.output_file) > 100:
                    file_ready = True
                    break
                time.sleep(poll_interval)
                elapsed_time += poll_interval

            if file_ready:
                self.finished.emit(f"Capture complete. File saved to:\n{self.output_file}")
            else:
                self.error.emit(
                    f"Capture finished, but the output file is missing or appears empty after waiting {timeout_seconds}s:\n{self.output_file}"
                )

        except Exception as e:
            self.error.emit(f"An error occurred during capture:\n{e}")
        finally:
            loop.close()


class LiveCaptureDialog(QDialog):
    captureFinished = Signal(str)

    def __init__(self, tshark_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Live Network Capture")
        self.tshark_path = tshark_path
        self.setMinimumWidth(500)
        self.layout = QVBoxLayout(self)

        self.status_label = QLabel("Select an interface and duration, then start the capture.")
        self.layout.addWidget(self.status_label)

        form_layout = QFormLayout()
        self.interface_combo = QComboBox()
        form_layout.addRow("Network Interface:", self.interface_combo)

        self.duration_spinbox = QSpinBox()
        self.duration_spinbox.setRange(5, 300)
        self.duration_spinbox.setValue(30)
        self.duration_spinbox.setSuffix(" seconds")
        form_layout.addRow("Capture Duration:", self.duration_spinbox)
        self.layout.addLayout(form_layout)

        self.start_button = QPushButton("Start Capture")
        self.start_button.clicked.connect(self.start_capture)
        self.layout.addWidget(self.start_button)

        self.capture_thread = None
        self.capture_worker = None
        self.save_path = ""

        self.load_interfaces()

    def load_interfaces(self):
        self.start_button.setEnabled(False)
        self.status_label.setText("Loading network interfaces...")
        QApplication.processEvents()
        try:
            interfaces = get_tshark_interfaces(tshark_path=self.tshark_path)
            self.interface_combo.clear()
            for iface in interfaces:
                self.interface_combo.addItem(iface)
            self.status_label.setText("Select an interface and duration, then start the capture.")
            self.start_button.setEnabled(True)
        except Exception as e:
            self.status_label.setText(f"Error getting interfaces: {e}")
            self.start_button.setEnabled(False)

    def start_capture(self):
        interface = self.interface_combo.currentText()
        if not interface:
            QMessageBox.warning(self, "No Interface", "Please select a network interface to capture from.")
            return

        if not is_admin():
            QMessageBox.warning(
                self,
                "Insufficient Privileges",
                "Live capture requires administrative privileges.\n"
                "Please restart the application with elevated rights."
            )
            return

        duration = self.duration_spinbox.value()
        try:
            run_name = f"live_capture_{time.strftime('%Y%m%d-%H%M%S')}"
            run_dir = RESULTAT_DIR / run_name
            run_dir.mkdir(parents=True, exist_ok=True)
            self.save_path = str(run_dir / "capture.pcapng")
        except OSError as e:
            QMessageBox.critical(self, "Directory Error", f"Could not create run directory: {e}")
            return

        self.status_label.setText(f"Will save capture to: {self.save_path}")
        self.start_button.setEnabled(False)
        self.interface_combo.setEnabled(False)
        self.duration_spinbox.setEnabled(False)

        self.capture_worker = CaptureWorker(interface, duration, self.save_path, self.tshark_path)
        self.capture_thread = QThread()
        self.capture_worker.moveToThread(self.capture_thread)

        self.capture_worker.progress.connect(self.status_label.setText)
        self.capture_worker.countdown.connect(lambda s: self.status_label.setText(f"Capturing... {s} seconds remaining."))
        self.capture_worker.error.connect(self.on_capture_error)
        self.capture_worker.finished.connect(self.on_capture_finished)

        self.capture_thread.started.connect(self.capture_worker.run)
        self.capture_thread.start()

    def on_capture_error(self, msg):
        QMessageBox.critical(self, "Capture Error", msg)
        self.reset_ui()
        self.reject()

    def on_capture_finished(self, msg):
        QMessageBox.information(self, "Success", msg)
        self.reset_ui()
        self.captureFinished.emit(self.save_path)
        self.accept()

    def reset_ui(self):
        self.status_label.setText("Select an interface and duration, then start the capture.")
        self.start_button.setEnabled(True)
        self.interface_combo.setEnabled(True)
        self.duration_spinbox.setEnabled(True)
        if self.capture_thread and self.capture_thread.isRunning():
            self.capture_thread.quit()
            self.capture_thread.wait()
        self.capture_thread = None
        self.capture_worker = None

    def closeEvent(self, event):
        if self.capture_worker:
            self.capture_worker.is_cancelled = True
        self.reset_ui()
        super().closeEvent(event)
