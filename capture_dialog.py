# Filename: capture_dialog.py
import os
import time
import asyncio
from pathlib import Path
import pyshark
from pyshark.tshark.tshark import get_tshark_interfaces

from PySide6.QtCore import QObject, Signal, QThread
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox, QSpinBox,
    QPushButton, QLabel, QMessageBox, QApplication, QLineEdit,
    QFileDialog, QHBoxLayout
)

# This allows the script to find the project root, even when imported by another script
PROJECT_ROOT = Path(__file__).resolve().parent
RESULTAT_DIR = PROJECT_ROOT / "Resultat"


class CaptureWorker(QObject):
    """
    A QObject worker for handling the tshark capture process in a separate thread.
    """
    finished = Signal(str)
    error = Signal(str)
    progress = Signal(str)
    countdown = Signal(int)

    def __init__(self, interface, duration, output_file, tshark_path,
                 bpf_filter=None, packet_limit=None, filesize_limit=None):
        super().__init__()
        self.interface = interface
        self.duration = duration
        self.output_file = output_file
        self.tshark_path = tshark_path
        self.bpf_filter = bpf_filter
        self.packet_limit = packet_limit
        self.filesize_limit = filesize_limit
        self.is_cancelled = False
    
    def run(self):
        # Each thread needs its own asyncio event loop.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            self.progress.emit(f"Starting capture on '{self.interface}' for {self.duration} seconds...")
            
            # Ensure the output directory exists
            os.makedirs(os.path.dirname(self.output_file), exist_ok=True)

            # ### DEFINITIVE BUG FIX ###
            # We no longer use the 'output_file' parameter of pyshark as it can be unreliable.
            # Instead, we pass the -w argument directly to tshark for maximum reliability.
            custom_params = ['-w', self.output_file]
            if self.packet_limit:
                custom_params.extend(['-c', str(self.packet_limit)])
            if self.filesize_limit:
                custom_params.extend(['-a', f'filesize:{self.filesize_limit}'])

            capture = pyshark.LiveCapture(
                interface=self.interface,
                tshark_path=self.tshark_path,
                bpf_filter=self.bpf_filter,
                custom_parameters=custom_params
            )

            # The sniff process starts in the background. We wait for the duration.
            for i in range(self.duration):
                if self.is_cancelled:
                    self.progress.emit("Capture cancelled by user.")
                    break
                self.countdown.emit(self.duration - i)
                time.sleep(1)

            capture.close()
            
            if self.is_cancelled:
                # Attempt to delete the partially saved file if capture was cancelled
                if os.path.exists(self.output_file):
                    try: os.remove(self.output_file)
                    except OSError as e: self.progress.emit(f"Could not delete partial capture file: {e}")
                self.error.emit("Capture was cancelled.")
            else:
                self.countdown.emit(0)
                self.progress.emit("Finalizing capture file...")
                
                # Use a polling loop to robustly wait for the file to be written.
                timeout_seconds = 10
                poll_interval = 0.2
                elapsed_time = 0
                file_ready = False

                while elapsed_time < timeout_seconds:
                    if os.path.exists(self.output_file) and os.path.getsize(self.output_file) > 24: # pcap files have a 24-byte header
                        file_ready = True
                        break
                    time.sleep(poll_interval)
                    elapsed_time += poll_interval
                    # No need to update the UI on every poll, it can feel spammy.
                
                if file_ready:
                    self.finished.emit(f"Capture complete. File saved to:\n{self.output_file}")
                else:
                    self.error.emit(f"Capture finished, but the output file is missing or empty after waiting {timeout_seconds}s:\n{self.output_file}")

        except Exception as e:
            self.error.emit(f"An error occurred during capture:\n{e}")
        finally:
            loop.close()


class LiveCaptureDialog(QDialog):
    """
    A dialog for setting up and running a live network capture.
    """
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

        self.filter_edit = QLineEdit()
        form_layout.addRow("BPF Filter:", self.filter_edit)

        self.output_edit = QLineEdit()
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse_output_file)
        output_layout = QHBoxLayout()
        output_layout.addWidget(self.output_edit)
        output_layout.addWidget(browse_btn)
        form_layout.addRow("Output File:", output_layout)

        self.packet_spinbox = QSpinBox()
        self.packet_spinbox.setRange(0, 1000000)
        self.packet_spinbox.setSpecialValueText("Unlimited")
        form_layout.addRow("Max Packets:", self.packet_spinbox)

        self.filesize_spinbox = QSpinBox()
        self.filesize_spinbox.setRange(0, 10240)
        self.filesize_spinbox.setSuffix(" MB")
        self.filesize_spinbox.setSpecialValueText("Unlimited")
        form_layout.addRow("Max File Size:", self.filesize_spinbox)
        self.layout.addLayout(form_layout)

        self.start_button = QPushButton("Start Capture")
        self.start_button.clicked.connect(self.start_capture)
        self.layout.addWidget(self.start_button)

        self.capture_thread = None
        self.capture_worker = None
        self.save_path = ""

        self.load_interfaces()

    def browse_output_file(self):
        path, _ = QFileDialog.getSaveFileName(self, "Select Capture File", str(PROJECT_ROOT), "PCAP Files (*.pcapng *.pcap)")
        if path:
            self.output_edit.setText(path)

    def load_interfaces(self):
        self.start_button.setEnabled(False)
        self.status_label.setText("Loading network interfaces...")
        QApplication.processEvents() # Update UI before potentially blocking call
        try:
            # Note: get_tshark_interfaces can be slow. A future improvement could
            # be to run this in a QThread as well.
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

        duration = self.duration_spinbox.value()

        output_path = self.output_edit.text().strip()
        if not output_path:
            try:
                run_name = f"live_capture_{time.strftime('%Y%m%d-%H%M%S')}"
                run_dir = RESULTAT_DIR / run_name
                run_dir.mkdir(parents=True, exist_ok=True)
                output_path = str(run_dir / "capture.pcapng")
            except OSError as e:
                QMessageBox.critical(self, "Directory Error", f"Could not create run directory: {e}")
                return

        self.save_path = output_path
        self.status_label.setText(f"Will save capture to: {self.save_path}")

        self.start_button.setEnabled(False)
        self.interface_combo.setEnabled(False)
        self.duration_spinbox.setEnabled(False)
        self.filter_edit.setEnabled(False)
        self.output_edit.setEnabled(False)
        self.packet_spinbox.setEnabled(False)
        self.filesize_spinbox.setEnabled(False)
        
        bpf_filter = self.filter_edit.text().strip() or None
        packet_limit = self.packet_spinbox.value() or None
        filesize_limit = self.filesize_spinbox.value() or None

        self.capture_worker = CaptureWorker(
            interface,
            duration,
            self.save_path,
            self.tshark_path,
            bpf_filter=bpf_filter,
            packet_limit=packet_limit,
            filesize_limit=filesize_limit,
        )
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
        self.reject() # Close dialog on error

    def on_capture_finished(self, msg):
        QMessageBox.information(self, "Success", msg)
        self.reset_ui()
        self.captureFinished.emit(self.save_path)
        self.accept() # Close dialog on success

    def reset_ui(self):
        self.status_label.setText("Select an interface and duration, then start the capture.")
        self.start_button.setEnabled(True)
        self.interface_combo.setEnabled(True)
        self.duration_spinbox.setEnabled(True)
        self.filter_edit.setEnabled(True)
        self.output_edit.setEnabled(True)
        self.packet_spinbox.setEnabled(True)
        self.filesize_spinbox.setEnabled(True)
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
