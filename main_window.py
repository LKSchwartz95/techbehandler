# Filename: main_window.py
import sys
import os
import webbrowser
import time
import json
import subprocess
import glob
from pathlib import Path
import shutil
import requests

from PySide6.QtWidgets import (
    QWidget, QPushButton, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFileDialog, QSpinBox, QLabel, QPlainTextEdit, QInputDialog,
    QLineEdit, QComboBox, QMessageBox, QTextEdit, QProgressBar,
    QCheckBox, QGroupBox, QFormLayout, QDoubleSpinBox, QMenuBar, QTabWidget, QApplication
)
from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QAction

# Import the refactored modules
import config_handler
from tool_manager import ToolManagerDialog
from capture_dialog import LiveCaptureDialog

PROJECT_ROOT = Path(__file__).resolve().parent
RESULTAT_DIR = PROJECT_ROOT / "Resultat"
LEGACY_MAT_PATH = PROJECT_ROOT / "mat"
TOOLS_MANIFEST_PATH = PROJECT_ROOT / "tools.json"

BUNDLED_OLLAMA_DIR = PROJECT_ROOT / "Ollama"
BUNDLED_OLLAMA_EXE_PATH = BUNDLED_OLLAMA_DIR / ("ollama.exe" if sys.platform == "win32" else "ollama")
BUNDLED_OLLAMA_MODELS_DIR = PROJECT_ROOT / "models" / "models"


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DumpBehandler Control Panel")
        self.resize(950, 800) 
        self.setAcceptDrops(True) 
        
        self.settings = {}
        self.current_prompts_list = []
        self.mat_report_definitions = []
        
        self.ollama_server_proc = None
        self.analysis_proc = None
        self.dashboard_proc = None
        self.pull_model_proc = None
        
        self.ollama_available = False
        self.health_check_timer = None 
        
        self.batch_queue = []
        self.is_batch_running = False
        self.current_batch_total_files = 0
        self.current_batch_processed_files = 0
        
        self.guard_mode_timer = QTimer(self)
        self.processed_in_guard_mode = set()
        self.guard_mode_file_mod_times = {} 
        
        self.wireshark_task_checkboxes = {}
        
        self._init_ui() 
        self.load_settings_from_handler() 
        self._check_bundled_resources()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setMenuBar(self._create_menu_bar())

        self.main_tabs = QTabWidget()
        main_layout.addWidget(self.main_tabs)

        analysis_control_tab = self._create_analysis_control_tab()
        dashboard_tab = self._create_dashboard_tab()
        console_tab = self._create_console_tab()

        self.main_tabs.addTab(analysis_control_tab, "Analysis Control")
        self.main_tabs.addTab(dashboard_tab, "Dashboard & Guard Mode")
        self.main_tabs.addTab(console_tab, "Console Output")

        # Connect signals to slots
        self.run_btn.clicked.connect(self.on_select_and_run_analysis)
        self.analyze_batch_btn.clicked.connect(self.on_start_batch_analysis)
        self.pull_model_btn.clicked.connect(self.on_pull_model_clicked)
        self.prompt_selector_combo.currentIndexChanged.connect(self.on_prompt_selected)
        self.edit_current_prompt_btn.clicked.connect(self.on_edit_selected_prompt)
        self.save_prompt_as_btn.clicked.connect(self.on_save_prompt_as)
        self.delete_prompt_btn.clicked.connect(self.on_delete_selected_prompt)
        self.dashboard_btn.clicked.connect(self.on_toggle_dashboard)
        self.open_browser_btn.clicked.connect(self.on_open_browser)
        self.open_resultat_btn.clicked.connect(self.on_open_resultat_folder)
        self.export_pdf_btn.clicked.connect(self.on_export_pdf)
        self.guard_folder_select_btn.clicked.connect(self.on_select_guard_folder)
        self.guard_enable_checkbox.toggled.connect(self.on_toggle_guard_mode)
        self.guard_interval_spinbox.valueChanged.connect(self.on_guard_interval_changed)
        self.clear_console_btn.clicked.connect(self.console.clear)

    def _create_analysis_control_tab(self):
        tab_widget = QWidget()
        main_layout = QVBoxLayout(tab_widget)

        top_section_widget = QWidget()
        analysis_label = QLabel("<b>1. Select Diagnostic File(s):</b>")
        self.run_btn = QPushButton("Analyze Single File...")
        self.analyze_batch_btn = QPushButton("Analyze Batch/Folder...")
        analysis_group_layout = QGridLayout() 
        analysis_group_layout.addWidget(analysis_label, 0, 0, 1, 2)
        analysis_group_layout.addWidget(self.run_btn, 1, 0)
        analysis_group_layout.addWidget(self.analyze_batch_btn, 1, 1)
        self.batch_status_label = QLabel("Batch Status: Idle")
        self.batch_progress_bar = QProgressBar()
        self.batch_progress_bar.setVisible(False)
        analysis_group_layout.addWidget(self.batch_status_label, 2,0)
        analysis_group_layout.addWidget(self.batch_progress_bar, 2,1)
        
        ollama_model_group_layout = QGridLayout()
        ollama_model_group_layout.addWidget(QLabel("<b>2. Configure Model & Prompts:</b>"), 0, 0, 1, 2)
        self.model_label = QLabel("Ollama Model:")
        self.model_selector_combo = QComboBox()
        self.model_selector_combo.setEditable(True)
        self.model_selector_combo.setToolTip("Select an Ollama model or type a custom one.")
        ollama_model_group_layout.addWidget(self.model_label, 1, 0)
        ollama_model_group_layout.addWidget(self.model_selector_combo, 1, 1)
        self.pull_model_name_input = QLineEdit()
        self.pull_model_name_input.setPlaceholderText("e.g., llama3:8b or mistral:latest")
        self.pull_model_btn = QPushButton("Pull New Model")
        ollama_model_group_layout.addWidget(QLabel("Pull Model:"), 2, 0)
        ollama_model_group_layout.addWidget(self.pull_model_name_input, 2, 1)
        ollama_model_group_layout.addWidget(self.pull_model_btn, 3, 1)

        prompt_label = QLabel("<b>Prompt Template:</b>")
        self.prompt_selector_combo = QComboBox()
        self.prompt_selector_combo.setToolTip("Select a saved prompt template.")
        self.prompt_template_display = QTextEdit()
        self.prompt_template_display.setPlaceholderText("Prompt content will appear here.")
        self.edit_current_prompt_btn = QPushButton("Update Selected Prompt")
        self.save_prompt_as_btn = QPushButton("Save as New...")
        self.delete_prompt_btn = QPushButton("Delete Prompt")
        prompt_controls_layout = QVBoxLayout()
        prompt_controls_layout.addWidget(prompt_label)
        prompt_controls_layout.addWidget(self.prompt_selector_combo)
        prompt_controls_layout.addWidget(self.prompt_template_display, 1) 
        prompt_buttons_layout = QHBoxLayout()
        prompt_buttons_layout.addWidget(self.edit_current_prompt_btn)
        prompt_buttons_layout.addWidget(self.save_prompt_as_btn)
        prompt_buttons_layout.addWidget(self.delete_prompt_btn)
        prompt_controls_layout.addLayout(prompt_buttons_layout)

        top_left_layout = QVBoxLayout()
        top_left_layout.addLayout(analysis_group_layout)
        top_left_layout.addLayout(ollama_model_group_layout)
        top_left_layout.addStretch()
        top_right_layout = prompt_controls_layout
        top_section_layout = QHBoxLayout(top_section_widget)
        top_section_layout.addLayout(top_left_layout, 1)
        top_section_layout.addLayout(top_right_layout, 1)
        
        middle_label = QLabel("<b>3. Configure Analysis-Specific Settings:</b>")
        self.settings_tabs = QTabWidget()
        self.hprof_tab = QWidget()
        self.wireshark_tab = QWidget()
        self.settings_tabs.addTab(self.hprof_tab, "HPROF / Thread Dump")
        self.settings_tabs.addTab(self.wireshark_tab, "Wireshark")
        self.hprof_tab.setLayout(self._create_hprof_tab_layout())
        self.wireshark_tab.setLayout(self._create_wireshark_tab_layout())
        
        main_layout.addWidget(top_section_widget)
        main_layout.addWidget(middle_label)
        main_layout.addWidget(self.settings_tabs)
        main_layout.addStretch()

        return tab_widget

    def _create_dashboard_tab(self):
        tab_widget = QWidget()
        main_layout = QVBoxLayout(tab_widget)

        dashboard_group = QGroupBox("Dashboard Utilities")
        dashboard_utils_layout = QHBoxLayout()
        self.dashboard_btn = QPushButton("Launch Dashboard")
        self.open_browser_btn = QPushButton("Open Dashboard in Browser")
        self.open_resultat_btn = QPushButton("Open Results Folder")
        self.export_pdf_btn = QPushButton("Export PDF")
        self.port_label = QLabel("Port:")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        dashboard_utils_layout.addWidget(self.dashboard_btn)
        dashboard_utils_layout.addWidget(self.open_browser_btn)
        dashboard_utils_layout.addWidget(self.open_resultat_btn)
        dashboard_utils_layout.addWidget(self.export_pdf_btn)
        dashboard_utils_layout.addStretch()
        dashboard_utils_layout.addWidget(self.port_label)
        dashboard_utils_layout.addWidget(self.port_spin)
        dashboard_group.setLayout(dashboard_utils_layout)

        guard_mode_group = QGroupBox("Guard Mode (Auto-Process Folder)")
        guard_mode_layout = QVBoxLayout()
        self.guard_folder_input = QLineEdit()
        self.guard_folder_input.setPlaceholderText("Enter folder path to monitor...")
        self.guard_folder_select_btn = QPushButton("Browse Folder...")
        self.guard_enable_checkbox = QCheckBox("Enable Guard Mode")
        self.guard_interval_label = QLabel("Check Interval (min):")
        self.guard_interval_spinbox = QSpinBox()
        self.guard_interval_spinbox.setRange(1, 1440)
        self.guard_interval_spinbox.setToolTip("How often to check the folder (in minutes).")
        self.guard_status_label = QLabel("Guard Mode: Inactive")
        guard_folder_layout = QHBoxLayout()
        guard_folder_layout.addWidget(QLabel("Folder to Watch:"))
        guard_folder_layout.addWidget(self.guard_folder_input, 1)
        guard_folder_layout.addWidget(self.guard_folder_select_btn)
        guard_options_layout = QHBoxLayout()
        guard_options_layout.addWidget(self.guard_enable_checkbox)
        guard_options_layout.addStretch()
        guard_options_layout.addWidget(self.guard_interval_label)
        guard_options_layout.addWidget(self.guard_interval_spinbox)
        guard_mode_layout.addLayout(guard_folder_layout)
        guard_mode_layout.addLayout(guard_options_layout)
        guard_mode_layout.addWidget(self.guard_status_label)
        guard_mode_group.setLayout(guard_mode_layout)

        main_layout.addWidget(dashboard_group)
        main_layout.addWidget(guard_mode_group)
        main_layout.addStretch()
        return tab_widget

    def _create_console_tab(self):
        tab_widget = QWidget()
        main_layout = QVBoxLayout(tab_widget)
        console_header_layout = QHBoxLayout()
        console_header_layout.addStretch()
        self.clear_console_btn = QPushButton("Clear Console")
        console_header_layout.addWidget(self.clear_console_btn)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet("background-color: #2d2d2d; color: #f0f0f0; font-family: Consolas, 'Courier New', monospace;")
        main_layout.addLayout(console_header_layout)
        main_layout.addWidget(self.console)
        return tab_widget

    def _create_hprof_tab_layout(self):
        layout = QVBoxLayout()
        hprof_group = QGroupBox("HPROF Settings")
        hprof_form_layout = QFormLayout()
        self.mat_memory_spinbox = QSpinBox()
        self.mat_memory_spinbox.setRange(1024, 32768)
        self.mat_memory_spinbox.setSingleStep(512)
        self.mat_memory_spinbox.setToolTip("Memory for MAT.")
        self.mat_report_type_combo = QComboBox()
        self.mat_report_type_combo.setToolTip("Select MAT report type.")
        hprof_form_layout.addRow("MAT Memory (MB):", self.mat_memory_spinbox)
        hprof_form_layout.addRow("MAT Report Type:", self.mat_report_type_combo)
        hprof_group.setLayout(hprof_form_layout)
        
        self.llm_params_group = QGroupBox("LLM Parameters (Advanced)")
        self.llm_params_group.setCheckable(True)
        self.llm_params_group.setChecked(False) 
        llm_params_layout = QFormLayout()
        self.llm_temp_spin = QDoubleSpinBox()
        self.llm_temp_spin.setRange(0.0, 2.0)
        self.llm_temp_spin.setSingleStep(0.1)
        self.llm_num_ctx_spin = QSpinBox()
        self.llm_num_ctx_spin.setRange(512, 32768)
        self.llm_num_ctx_spin.setSingleStep(512)
        self.llm_top_k_spin = QSpinBox()
        self.llm_top_k_spin.setRange(0, 100)
        self.llm_top_p_spin = QDoubleSpinBox()
        self.llm_top_p_spin.setRange(0.0, 1.0)
        self.llm_top_p_spin.setSingleStep(0.05)
        self.llm_seed_spin = QSpinBox()
        self.llm_seed_spin.setRange(0, 2147483647)
        self.llm_num_predict_spin = QSpinBox()
        self.llm_num_predict_spin.setRange(-1, 8192)
        self.llm_num_predict_spin.setSingleStep(128)
        self.llm_stop_input = QLineEdit()
        self.llm_stop_input.setPlaceholderText("e.g., \\nUser:, Observation:")
        llm_params_layout.addRow("Temperature:", self.llm_temp_spin)
        llm_params_layout.addRow("Context Size (num_ctx):", self.llm_num_ctx_spin)
        llm_params_layout.addRow("Top K:", self.llm_top_k_spin)
        llm_params_layout.addRow("Top P:", self.llm_top_p_spin)
        llm_params_layout.addRow("Seed (0=random):", self.llm_seed_spin)
        llm_params_layout.addRow("Max New Tokens:", self.llm_num_predict_spin)
        llm_params_layout.addRow("Stop Sequences (CSV):", self.llm_stop_input)
        self.llm_params_group.setLayout(llm_params_layout)
        self.llm_params_group.toggled.connect(self.on_llm_params_group_toggled)

        layout.addWidget(hprof_group)
        layout.addWidget(self.llm_params_group)
        layout.addStretch()
        return layout

    def _create_wireshark_tab_layout(self):
        main_layout = QVBoxLayout()
        group_box = QGroupBox("Select Wireshark (tshark) Analysis Tasks to Run")
        grid_layout = QGridLayout()

        tasks = [
            {"id": "tcp_conv", "name": "TCP Conversations", "desc": "High-level summary of all TCP connections."},
            {"id": "ip_conv", "name": "IP Conversations", "desc": "Summary of all IP-level connections."},
            {"id": "dns_stats", "name": "DNS Statistics", "desc": "Analyze DNS queries and responses for errors."},
            {"id": "http_reqs", "name": "HTTP Requests", "desc": "Extract all HTTP/1.x requests (host, method, URI)."},
            {"id": "tls_alerts", "name": "TLS/SSL Alerts", "desc": "Scan for secure connection failures and warnings."},
            {"id": "slow_resps", "name": "Slow TCP Responses", "desc": "Find TCP packets with a response time > 200ms."}
        ]

        row, col = 0, 0
        for task in tasks:
            cb = QCheckBox(task["name"])
            cb.setToolTip(task["desc"])
            cb.setProperty("task_id", task["id"])
            cb.toggled.connect(self.on_wireshark_task_toggled)
            self.wireshark_task_checkboxes[task["id"]] = cb
            grid_layout.addWidget(cb, row, col)
            col += 1
            if col > 1:
                col = 0
                row += 1
        
        group_box.setLayout(grid_layout)
        main_layout.addWidget(group_box)
        main_layout.addStretch()
        return main_layout
    
    def on_wireshark_task_toggled(self):
        self.settings["wireshark_tasks"] = {
            task_id: cb.isChecked() for task_id, cb in self.wireshark_task_checkboxes.items()
        }

    def _create_menu_bar(self):
        menu_bar = QMenuBar()
        tools_menu = menu_bar.addMenu("&Tools")
        tool_manager_action = QAction("Tool Manager...", self)
        tool_manager_action.triggered.connect(self.open_tool_manager)
        tools_menu.addAction(tool_manager_action)
        live_capture_action = QAction("Live Network Capture...", self)
        live_capture_action.triggered.connect(self.open_live_capture)
        tools_menu.addAction(live_capture_action)
        return menu_bar

    def open_tool_manager(self):
        dialog = ToolManagerDialog(self)
        dialog.exec()

    def open_live_capture(self):
        tshark_path = self.get_tool_launcher_path("wireshark")
        if not tshark_path:
            QMessageBox.warning(self, "Wireshark (tshark) Not Found", 
                                  "Wireshark is required for live capture.\n"
                                  "Please open the Tool Manager to install it or ensure 'tshark' is in your system's PATH.",
                                  QMessageBox.StandardButton.Ok)
            return
        
        dialog = LiveCaptureDialog(tshark_path, self)
        dialog.captureFinished.connect(self.on_live_capture_completed)
        dialog.exec()

    def on_live_capture_completed(self, pcap_path):
        self.append_console(f"Live capture complete. Analyzing file: {pcap_path}")
        self.trigger_analysis_for_file(pcap_path)

    def get_tool_launcher_path(self, tool_id):
        if tool_id == "wireshark":
            if TOOLS_MANIFEST_PATH.exists():
                with open(TOOLS_MANIFEST_PATH, "r") as f: manifest = json.load(f)
                current_platform = "win64" if sys.platform == "win32" else ""
                for tool in manifest.get("tools", []):
                    if tool.get("id") == "wireshark" and tool.get("platform") == current_platform:
                        install_path = PROJECT_ROOT / tool.get("install_path")
                        launcher_path = install_path / tool.get("launcher_relative_path")
                        if launcher_path.is_file():
                            self.append_console(f"Using managed Wireshark (tshark) found at: {launcher_path}")
                            return str(launcher_path)
            tshark_path = shutil.which("tshark")
            if tshark_path:
                self.append_console(f"Using system tshark found at: {tshark_path}")
                return tshark_path
            return None

        if tool_id == "mat":
            legacy_plugins_path = LEGACY_MAT_PATH / "plugins"
            if legacy_plugins_path.is_dir():
                legacy_launchers = list(legacy_plugins_path.glob("org.eclipse.equinox.launcher_*.jar"))
                if legacy_launchers:
                    self.append_console(f"Using legacy MAT installation found at: {LEGACY_MAT_PATH}")
                    return str(legacy_launchers[0])

            if not TOOLS_MANIFEST_PATH.exists(): return None
            with open(TOOLS_MANIFEST_PATH, "r") as f: manifest = json.load(f)
            current_platform = "win64" if sys.platform == "win32" else "macos-aarch64" if sys.platform == "darwin" else "linux-x86_64"
            for tool in manifest.get("tools", []):
                if tool.get("id") == "mat" and tool.get("platform") == current_platform:
                    install_path = PROJECT_ROOT / tool.get("install_path")
                    if not install_path.is_dir(): continue
                    launcher_pattern = str(install_path / tool.get("launcher_relative_path"))
                    found_launchers = glob.glob(launcher_pattern)
                    if found_launchers:
                        self.append_console(f"Using managed MAT installation found at: {install_path}")
                        return found_launchers[0]
        return None

    def on_llm_params_group_toggled(self, checked):
        self.settings["llm_params_group_checked"] = checked

    def _set_analysis_buttons_enabled(self, enabled_state):
        self.run_btn.setEnabled(enabled_state)
        self.analyze_batch_btn.setEnabled(enabled_state)
        ollama_ready = self.ollama_available and (self.ollama_server_proc and self.ollama_server_proc.state() == QProcess.Running)
        can_toggle_guard = enabled_state and ollama_ready 
        self.guard_enable_checkbox.setEnabled(can_toggle_guard and not self.is_batch_running)
        self.pull_model_btn.setEnabled(ollama_ready and enabled_state) 

    def _check_bundled_resources(self):
        self.ollama_available = os.path.isfile(BUNDLED_OLLAMA_EXE_PATH)
        if not self.ollama_available: self.append_console(f"ERROR: Ollama exe FNF: {BUNDLED_OLLAMA_EXE_PATH}. Analysis disabled.")
        elif not os.path.isdir(BUNDLED_OLLAMA_MODELS_DIR): self.append_console(f"ERROR: Ollama models dir FNF: {BUNDLED_OLLAMA_MODELS_DIR}. Analysis disabled."); self.ollama_available = False
        elif not any((BUNDLED_OLLAMA_MODELS_DIR / item).is_dir() for item in ["manifests", "blobs"]): self.append_console(f"WARN: Ollama models dir '{BUNDLED_OLLAMA_MODELS_DIR}' missing manifests/blobs.")
        if not self.ollama_available: self._set_analysis_buttons_enabled(False); self.model_selector_combo.setEnabled(False)
        else: self.start_bundled_ollama_server()

    def load_settings_from_handler(self):
        """
        Loads settings using the config_handler and applies them to the UI.
        """
        self.settings = config_handler.load_settings()
        self.append_console(f"Settings loaded from {config_handler.CONFIG_FILE_PATH}")
        
        self.port_spin.setValue(self.settings["ollama_dashboard_port"])
        self.mat_memory_spinbox.setValue(self.settings["mat_memory_mb"])
        
        self.current_prompts_list = self.settings["saved_prompts"][:]
        self._populate_prompt_selector()
        
        self.model_selector_combo.setCurrentText(self.settings["default_ollama_model"])
        
        self.mat_report_definitions = self.settings.get("mat_report_options", config_handler.DEFAULT_SETTINGS["mat_report_options"][:])
        self.mat_report_type_combo.clear()
        for report_option in self.mat_report_definitions:
            self.mat_report_type_combo.addItem(report_option["name"], userData=report_option["id"])
        default_mat_report_id = self.settings.get("default_mat_report_type_id", config_handler.DEFAULT_SETTINGS["default_mat_report_type_id"])
        mat_report_idx = self.mat_report_type_combo.findData(default_mat_report_id)
        if mat_report_idx != -1:
            self.mat_report_type_combo.setCurrentIndex(mat_report_idx)
        elif self.mat_report_type_combo.count() > 0:
            self.mat_report_type_combo.setCurrentIndex(0)
        
        llm_params = self.settings.get("llm_parameters", config_handler.DEFAULT_SETTINGS["llm_parameters"].copy())
        self.llm_temp_spin.setValue(llm_params.get("temperature"))
        self.llm_num_ctx_spin.setValue(llm_params.get("num_ctx"))
        self.llm_top_k_spin.setValue(llm_params.get("top_k"))
        self.llm_top_p_spin.setValue(llm_params.get("top_p"))
        self.llm_seed_spin.setValue(llm_params.get("seed"))
        self.llm_num_predict_spin.setValue(llm_params.get("num_predict"))
        self.llm_stop_input.setText(",".join(map(str, llm_params.get("stop", []))))
        self.llm_params_group.setChecked(self.settings.get("llm_params_group_checked", False))

        self.guard_folder_input.setText(self.settings.get("guard_mode_folder", ""))
        self.guard_interval_spinbox.setValue(self.settings.get("guard_mode_interval_minutes", 1))
        
        # Disconnect signal before setting check state to prevent premature trigger
        try: self.guard_enable_checkbox.toggled.disconnect(self.on_toggle_guard_mode)
        except RuntimeError: pass 
        self.guard_enable_checkbox.setChecked(self.settings.get("guard_mode_enabled", False))
        self.guard_enable_checkbox.toggled.connect(self.on_toggle_guard_mode)
        
        saved_tasks = self.settings.get("wireshark_tasks", config_handler.DEFAULT_SETTINGS["wireshark_tasks"])
        for task_id, cb in self.wireshark_task_checkboxes.items():
            cb.setChecked(saved_tasks.get(task_id, False))

    def save_settings_to_handler(self):
        """
        Gathers current UI settings and uses the config_handler to save them.
        """
        if not hasattr(self, 'settings') or not self.settings:
            return
            
        self.settings["default_ollama_model"] = self.model_selector_combo.currentText()
        self.settings["ollama_dashboard_port"] = self.port_spin.value()
        self.settings["mat_memory_mb"] = self.mat_memory_spinbox.value()
        self.settings["saved_prompts"] = self.current_prompts_list
        
        current_prompt_name = self.prompt_selector_combo.currentText()
        if any(p["name"] == current_prompt_name for p in self.current_prompts_list):
            self.settings["default_prompt_name"] = current_prompt_name
        
        selected_mat_id = self.mat_report_type_combo.currentData()
        if selected_mat_id:
            self.settings["default_mat_report_type_id"] = selected_mat_id
        
        self.settings["llm_parameters"] = {
            "temperature": self.llm_temp_spin.value(),
            "num_ctx": self.llm_num_ctx_spin.value(),
            "top_k": self.llm_top_k_spin.value(),
            "top_p": self.llm_top_p_spin.value(),
            "seed": self.llm_seed_spin.value(),
            "stop": [s.strip() for s in self.llm_stop_input.text().split(',') if s.strip()],
            "num_predict": self.llm_num_predict_spin.value()
        }
        self.settings["llm_params_group_checked"] = self.llm_params_group.isChecked()
        self.settings["guard_mode_folder"] = self.guard_folder_input.text()
        self.settings["guard_mode_enabled"] = self.guard_enable_checkbox.isChecked()
        self.settings["guard_mode_interval_minutes"] = self.guard_interval_spinbox.value()
        self.settings["wireshark_tasks"] = {task_id: cb.isChecked() for task_id, cb in self.wireshark_task_checkboxes.items()}
        
        if not config_handler.save_settings(self.settings):
            QMessageBox.warning(self, "Save Settings Error", "Could not save settings to config.json.")

    def _populate_prompt_selector(self): 
        current_text = self.prompt_selector_combo.currentText()
        self.prompt_selector_combo.clear()
        for item in self.current_prompts_list:
            self.prompt_selector_combo.addItem(item["name"])
        idx = self.prompt_selector_combo.findText(current_text)
        if idx != -1:
            self.prompt_selector_combo.setCurrentIndex(idx)
        elif self.prompt_selector_combo.count() > 0:
            self.prompt_selector_combo.setCurrentIndex(0)
        self.on_prompt_selected()

    def on_prompt_selected(self): 
        name = self.prompt_selector_combo.currentText()
        self.prompt_template_display.setPlainText(next((p["template"] for p in self.current_prompts_list if p["name"] == name), ""))

    def on_edit_selected_prompt(self): 
        name = self.prompt_selector_combo.currentText()
        new_text = self.prompt_template_display.toPlainText()
        if not name:
            QMessageBox.information(self, "No Prompt Selected", "Please select a prompt from the list to update.")
            return
        for i, p_item in enumerate(self.current_prompts_list):
            if p_item["name"] == name:
                if p_item["template"] != new_text:
                    self.current_prompts_list[i]["template"] = new_text
                    self.append_console(f"Prompt '{name}' updated in this session.")
                    self.save_settings_to_handler()
                else:
                    self.append_console(f"Prompt '{name}' content is unchanged.")
                return

    def on_save_prompt_as(self): 
        template = self.prompt_template_display.toPlainText()
        if not template.strip():
            QMessageBox.warning(self, "Empty Prompt", "Cannot save an empty prompt template.")
            return
        name, ok = QInputDialog.getText(self, "Save Prompt As", "Enter a new name for this prompt:")
        if ok and name.strip():
            name = name.strip()
            if any(p["name"] == name for p in self.current_prompts_list):
                QMessageBox.warning(self, "Name Exists", f"A prompt named '{name}' already exists. Please choose a different name.")
                return
            
            self.current_prompts_list.append({"name": name, "template": template})
            self._populate_prompt_selector()
            self.prompt_selector_combo.setCurrentText(name) 
            self.append_console(f"Prompt '{name}' saved.")
            self.save_settings_to_handler()
        elif ok:
            QMessageBox.warning(self, "Invalid Name", "The prompt name cannot be empty.")

    def on_delete_selected_prompt(self): 
        name = self.prompt_selector_combo.currentText()
        if not name:
            QMessageBox.information(self, "No Prompt Selected", "Please select a prompt from the list to delete.")
            return
        if len(self.current_prompts_list) <= 1:
            QMessageBox.warning(self, "Cannot Delete", "You cannot delete the last remaining prompt.")
            return
        
        reply = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete the prompt '{name}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.current_prompts_list = [p for p in self.current_prompts_list if p["name"] != name]
            self._populate_prompt_selector()
            self.append_console(f"Prompt '{name}' deleted.")
            self.save_settings_to_handler()

    def on_open_resultat_folder(self):
        path = PROJECT_ROOT / "Resultat"
        path.mkdir(exist_ok=True)
        try:
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                if sys.platform == "win32": os.startfile(path)
                elif sys.platform == "darwin": subprocess.call(["open", str(path)])
                else: subprocess.call(["xdg-open", str(path)])
            self.append_console(f"Attempted to open results folder: {path}")
        except Exception as e:
            self.append_console(f"Error opening results folder: {e}")
            QMessageBox.warning(self, "Error", f"Could not open folder: {path}\n{e}")

    def on_export_pdf(self):
        run_dir = QFileDialog.getExistingDirectory(self, "Select Run Folder", str(RESULTAT_DIR))
        if not run_dir:
            return
        run_name = os.path.basename(run_dir.rstrip(os.sep))
        port = self.port_spin.value()
        url = f"http://localhost:{port}/api/run/{run_name}/export_pdf"
        self.append_console(f"Requesting PDF from {url}")
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
        except Exception as e:
            self.append_console(f"PDF export request failed: {e}")
            QMessageBox.warning(self, "Export Failed", f"Could not download PDF:\n{e}")
            return

        default_save = os.path.join(run_dir, f"{run_name}_report.pdf")
        save_path, _ = QFileDialog.getSaveFileName(self, "Save PDF As", default_save, "PDF Files (*.pdf)")
        if not save_path:
            self.append_console("PDF export cancelled by user (no save path).")
            return

        try:
            with open(save_path, "wb") as f:
                f.write(response.content)
            self.append_console(f"PDF saved to {save_path}")
            QMessageBox.information(self, "Export Complete", f"PDF saved to:\n{save_path}")
        except Exception as e:
            self.append_console(f"Failed to save PDF: {e}")
            QMessageBox.warning(self, "Save Error", f"Could not save PDF:\n{e}")
    
    def dragEnterEvent(self, event): 
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith((".hprof", ".txt", ".pcap", ".pcapng")):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event): 
        if event.mimeData().hasUrls():
            file_paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            valid_files = [fp for fp in file_paths if fp.lower().endswith((".hprof", ".txt", ".pcap", ".pcapng"))]
            
            if len(valid_files) == 1:
                self.append_console(f"File dropped: {valid_files[0]}")
                self.settings["last_hprof_dir"] = os.path.dirname(valid_files[0])
                self.trigger_analysis_for_file(valid_files[0])
            elif len(valid_files) > 1:
                self.append_console(f"{len(valid_files)} files dropped. Starting batch analysis.")
                self.batch_queue = valid_files
                self.current_batch_total_files = len(self.batch_queue)
                self.current_batch_processed_files = 0
                self.is_batch_running = True
                self.batch_status_label.setText("Batch processing starting...")
                self.batch_progress_bar.setMaximum(self.current_batch_total_files)
                self.batch_progress_bar.setValue(0)
                self.batch_progress_bar.setVisible(True)
                self._set_analysis_buttons_enabled(False)
                self.process_next_in_batch()
            
            event.acceptProposedAction()
        else:
            event.ignore()

    def on_select_and_run_analysis(self):
        if self.is_batch_running or (self.analysis_proc and self.analysis_proc.state() != QProcess.NotRunning):
            QMessageBox.information(self, "Busy", "An analysis or batch process is already in progress.")
            return
            
        last_dir = self.settings.get("last_hprof_dir", str(PROJECT_ROOT))
        
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Diagnostic File", last_dir, "Diagnostic Files (*.hprof *.txt *.pcap *.pcapng);;All Files (*)")
        if file_path:
            self.settings["last_hprof_dir"] = os.path.dirname(file_path)
            self.trigger_analysis_for_file(file_path)

    def on_start_batch_analysis(self):
        if self.is_batch_running or (self.analysis_proc and self.analysis_proc.state() != QProcess.NotRunning):
            QMessageBox.information(self, "Busy", "An analysis or batch process is already in progress.")
            return

        last_dir = self.settings.get("last_hprof_dir", str(PROJECT_ROOT))
        
        dialog = QFileDialog(self, "Select Diagnostic Files for Batch Analysis", last_dir, "Diagnostic Files (*.hprof *.txt *.pcap *.pcapng)")
        dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        
        if dialog.exec():
            selected_files = dialog.selectedFiles()
            if selected_files:
                self.batch_queue = selected_files
                self.current_batch_total_files = len(self.batch_queue)
                self.current_batch_processed_files = 0
                self.is_batch_running = True
                self.batch_status_label.setText("Batch processing starting...")
                self.batch_progress_bar.setMaximum(self.current_batch_total_files)
                self.batch_progress_bar.setValue(0)
                self.batch_progress_bar.setVisible(True)
                self._set_analysis_buttons_enabled(False) 
                self.append_console(f"Batch analysis started for {self.current_batch_total_files} file(s).")
                self.process_next_in_batch()

    def process_next_in_batch(self):
        if not self.is_batch_running or not self.batch_queue:
            completion_status = "Complete" if self.current_batch_total_files > 0 and self.current_batch_processed_files == self.current_batch_total_files else "Idle (or ended)"
            self.batch_status_label.setText(f"Batch Status: {completion_status}")
            self.batch_progress_bar.setVisible(False)
            self.is_batch_running = False
            self.current_batch_total_files = 0
            self.current_batch_processed_files = 0
            self._set_analysis_buttons_enabled(True) 
            if self.batch_queue: self.append_console("Warning: Batch queue had remaining items but processing stopped.") 
            self.batch_queue = [] 
            return
            
        file_path = self.batch_queue.pop(0) 
        self.batch_status_label.setText(f"Batch: Preparing {self.current_batch_processed_files + 1}/{self.current_batch_total_files}: {os.path.basename(file_path)}")
        self.batch_progress_bar.setValue(self.current_batch_processed_files) 
        self.settings["last_hprof_dir"] = os.path.dirname(file_path) 
        self.trigger_analysis_for_file(file_path) 
    
    def trigger_analysis_for_file(self, source_file_path):
        run_dir = ""
        analysis_file = ""

        try:
            source_path = Path(source_file_path)
            is_in_run_folder = source_path.parent.parent.resolve() == RESULTAT_DIR.resolve()
        except Exception:
            is_in_run_folder = False

        if is_in_run_folder:
            self.append_console(f"File '{os.path.basename(source_file_path)}' is already in a run folder.")
            run_dir = os.path.dirname(source_file_path)
            analysis_file = source_file_path
        else:
            self.append_console(f"Creating new run folder for '{os.path.basename(source_file_path)}'.")
            try:
                base_name = os.path.splitext(os.path.basename(source_file_path))[0]
                ts = time.strftime("%Y%m%d-%H%M%S")
                run_name = f"{base_name}_{ts}"
                run_dir = RESULTAT_DIR / run_name
                run_dir.mkdir(parents=True, exist_ok=True)
                
                analysis_file = run_dir / os.path.basename(source_file_path)
                shutil.copy(source_file_path, analysis_file)
                self.append_console(f"Copied file to run folder: {analysis_file}")
            except Exception as e:
                QMessageBox.critical(self, "File Error", f"Could not create run folder or copy file: {e}")
                self._analysis_ended_or_failed(); return
        
        lower_analysis_file = str(analysis_file).lower()
        is_hprof = lower_analysis_file.endswith(".hprof")
        is_txt = lower_analysis_file.endswith(".txt")
        is_pcap = lower_analysis_file.endswith((".pcap", ".pcapng"))
        
        tool_launcher = None
        prompt_name = None
        extra_args = []
        
        if is_hprof:
            self.settings_tabs.setCurrentWidget(self.hprof_tab)
            tool_launcher = self.get_tool_launcher_path("mat")
            if not tool_launcher:
                QMessageBox.warning(self, "MAT Not Found", "Eclipse MAT is required for HPROF analysis.\nPlease use the Tool Manager to install it.", QMessageBox.StandardButton.Ok)
                self._analysis_ended_or_failed(); return
            prompt_name = "HPROF Comprehensive Analysis"
            extra_args.extend(["--mat-memory", str(self.mat_memory_spinbox.value()), "--mat-report-arg", self.mat_report_type_combo.currentData(), "--mat-launcher-path", tool_launcher])
        
        elif is_txt:
            self.settings_tabs.setCurrentWidget(self.hprof_tab)
            prompt_name = "Thread Dump (jstack) Analysis"

        elif is_pcap:
            self.settings_tabs.setCurrentWidget(self.wireshark_tab)
            tool_launcher = self.get_tool_launcher_path("wireshark")
            if not tool_launcher:
                QMessageBox.warning(self, "Wireshark (tshark) Not Found", "Wireshark (tshark) is required for packet capture analysis.\nPlease use the Tool Manager to install it or ensure 'tshark' is in your system's PATH.", QMessageBox.StandardButton.Ok)
                self._analysis_ended_or_failed(); return
            prompt_name = "Wireshark Multi-Tool Analysis"
            
            selected_tasks = [task_id for task_id, cb in self.wireshark_task_checkboxes.items() if cb.isChecked()]
            if not selected_tasks:
                QMessageBox.warning(self, "No Tasks Selected", "Please select at least one Wireshark analysis task to run.")
                self._analysis_ended_or_failed(); return
            extra_args.extend(["--tshark-path", tool_launcher, "--pcap-tasks", ",".join(selected_tasks)])

        else:
            QMessageBox.warning(self, "Unsupported File", f"The file type for '{os.path.basename(str(analysis_file))}' is not supported.");
            self._analysis_ended_or_failed(); return

        prompt_index = self.prompt_selector_combo.findText(prompt_name)
        if prompt_index == -1:
            QMessageBox.warning(self, "Prompt Not Found", f"The required '{prompt_name}' prompt is missing.")
            self._analysis_ended_or_failed(); return
        self.prompt_selector_combo.setCurrentIndex(prompt_index)

        ollama_ready = self.ollama_available and (self.ollama_server_proc and self.ollama_server_proc.state() == QProcess.Running)
        if not ollama_ready: QMessageBox.warning(self, "Ollama Not Ready", "Ollama server not running or model not verified."); self._analysis_ended_or_failed(); return
        
        selected_model = self.model_selector_combo.currentText().strip()
        if not selected_model: QMessageBox.warning(self, "Model Not Specified", "Select/enter Ollama model name."); self._analysis_ended_or_failed(); return
        
        current_prompt_template = self.prompt_template_display.toPlainText().strip()
            
        if self.llm_params_group.isChecked():
            llm_params_to_use = { "temperature": self.llm_temp_spin.value(), "num_ctx": self.llm_num_ctx_spin.value(),
                "top_k": self.llm_top_k_spin.value(), "top_p": self.llm_top_p_spin.value(), "seed": self.llm_seed_spin.value(), 
                "stop": [s.strip() for s in self.llm_stop_input.text().split(',') if s.strip()], "num_predict": self.llm_num_predict_spin.value() }
            self.append_console("Using custom LLM parameters from GUI.")
        else:
            llm_params_to_use = self.settings.get("llm_parameters", config_handler.DEFAULT_SETTINGS["llm_parameters"].copy())
            self.append_console("Using default/saved LLM parameters from config.")
        llm_params_json = json.dumps(llm_params_to_use)

        self.append_console(f"Running analysis on '{analysis_file}' in run dir '{run_dir}'")
        if self.analysis_proc and self.analysis_proc.state() != QProcess.NotRunning: self.append_console("Terminating previous analysis..."); self.analysis_proc.kill(); self.analysis_proc.waitForFinished(5000)
        if not self.is_batch_running: self._set_analysis_buttons_enabled(False)
        
        self.analysis_proc = QProcess(self); self.analysis_proc.setProgram(sys.executable) 
        
        direct_monitor_args = [ str(PROJECT_ROOT / "monitor.py"), 
            "--prompt", current_prompt_template, "--model", selected_model,
            "--ollama-cmd", str(BUNDLED_OLLAMA_EXE_PATH),
            "--llm-params", llm_params_json,
            "--run-dir", str(run_dir),
            str(analysis_file)
        ]
        
        direct_monitor_args.extend(extra_args)

        self.append_console(f"Executing: {sys.executable} {' '.join(direct_monitor_args)}")
        env = QProcessEnvironment.systemEnvironment(); env.insert("OLLAMA_MODELS", str(BUNDLED_OLLAMA_MODELS_DIR))
        self.analysis_proc.setProcessEnvironment(env); self.analysis_proc.setArguments(direct_monitor_args); self.analysis_proc.setWorkingDirectory(str(PROJECT_ROOT))
        self.analysis_proc.setProcessChannelMode(QProcess.MergedChannels)
        self.analysis_proc.readyReadStandardOutput.connect(self._on_analysis_output); self.analysis_proc.finished.connect(self._on_analysis_finished); self.analysis_proc.errorOccurred.connect(self._on_analysis_error)
        self.analysis_proc.start()
        if not self.analysis_proc.waitForStarted(5000): self.append_console(f"ERROR: Failed to start monitor.py: {self.analysis_proc.errorString()}"); self._analysis_ended_or_failed()
        elif self.is_batch_running: self.current_batch_processed_files += 1 
    
    def _analysis_ended_or_failed(self): 
        if self.is_batch_running:
            if self.analysis_proc and not self.analysis_proc.waitForStarted(0) and \
               self.current_batch_processed_files < self.current_batch_total_files : 
                self.current_batch_processed_files +=1 
                self.batch_progress_bar.setValue(self.current_batch_processed_files)
            QTimer.singleShot(0, self.process_next_in_batch) 
        else:
            self._set_analysis_buttons_enabled(True)

    def start_bundled_ollama_server(self):
        if not self.ollama_available: self.append_console("Cannot start Ollama: resources missing."); return
        if self.ollama_server_proc and self.ollama_server_proc.state() != QProcess.NotRunning: self.append_console("Ollama server already running/starting."); return
        self.append_console(f"Starting Ollama: {BUNDLED_OLLAMA_EXE_PATH} with models: {BUNDLED_OLLAMA_MODELS_DIR}")
        self.ollama_server_proc = QProcess(self); self.ollama_server_proc.setProgram(str(BUNDLED_OLLAMA_EXE_PATH)); self.ollama_server_proc.setArguments(["serve"])
        env = QProcessEnvironment.systemEnvironment(); env.insert("OLLAMA_MODELS", str(BUNDLED_OLLAMA_MODELS_DIR))
        self.ollama_server_proc.setProcessEnvironment(env)
        self.ollama_server_proc.readyReadStandardOutput.connect(self._on_ollama_server_output); self.ollama_server_proc.readyReadStandardError.connect(self._on_ollama_server_error_output)
        self.ollama_server_proc.finished.connect(self._on_ollama_server_finished); self.ollama_server_proc.errorOccurred.connect(self._on_ollama_server_error_occurred)
        self.ollama_server_proc.start()
        if not self.ollama_server_proc.waitForStarted(5000): 
            err_str = self.ollama_server_proc.errorString() if self.ollama_server_proc else "Process object is None"
            self.append_console(f"ERROR: Ollama server failed to start: {err_str}")
            self.ollama_server_proc = None; self._set_analysis_buttons_enabled(False); self.model_selector_combo.setEnabled(False); return
        self.append_console("Ollama server initiated. Verifying models..."); self.health_check_attempts = 0
        if not self.health_check_timer: self.health_check_timer = QTimer(self); self.health_check_timer.timeout.connect(self.check_ollama_server_health)
        self.health_check_timer.start(3000)
    def check_ollama_server_health(self):
        self.health_check_attempts += 1; max_attempts = 15
        if self.health_check_attempts > max_attempts: 
            self.append_console(f"ERROR: Ollama health check timeout. Analysis disabled."); self.health_check_timer.stop()
            self._set_analysis_buttons_enabled(False); self.model_selector_combo.setEnabled(False); return
        self.append_console(f"Checking Ollama health ({self.health_check_attempts}/{max_attempts})...")
        list_proc = QProcess(self); list_proc.setProgram(str(BUNDLED_OLLAMA_EXE_PATH)); list_proc.setArguments(["list"])
        env = QProcessEnvironment.systemEnvironment(); env.insert("OLLAMA_MODELS", str(BUNDLED_OLLAMA_MODELS_DIR)); list_proc.setProcessEnvironment(env)
        list_proc.start(); 
        if not list_proc.waitForStarted(2000): self.append_console("Failed to start `ollama list`."); return
        if not list_proc.waitForFinished(10000): self.append_console("`ollama list` timed out."); list_proc.kill(); return
        out_bytes, err_bytes = list_proc.readAllStandardOutput(), list_proc.readAllStandardError()
        try: out_str = out_bytes.data().decode('utf-8', errors='surrogateescape').lower()
        except: out_str = out_bytes.data().decode(sys.stdout.encoding or 'utf-8', errors='replace').lower()
        try: err_str = err_bytes.data().decode('utf-8', errors='surrogateescape').lower()
        except: err_str = err_bytes.data().decode(sys.stderr.encoding or 'utf-8', errors='replace').lower()
        if list_proc.exitCode() == 0:
            model_names = [line.split()[0] for line in out_str.splitlines() if line and not line.startswith("name")]
            current_sel = self.model_selector_combo.currentText(); self.model_selector_combo.clear()
            if model_names: self.model_selector_combo.addItems(model_names); self.append_console(f"Available models: {', '.join(model_names)}")
            else: self.append_console("No models found by `ollama list`.")
            idx_current = self.model_selector_combo.findText(current_sel, Qt.MatchFlag.MatchFixedString | Qt.MatchFlag.MatchCaseSensitive)
            idx_default = self.model_selector_combo.findText(self.settings.get("default_ollama_model",""), Qt.MatchFlag.MatchFixedString | Qt.MatchFlag.MatchCaseSensitive)
            if idx_current != -1: self.model_selector_combo.setCurrentIndex(idx_current)
            elif idx_default != -1: self.model_selector_combo.setCurrentIndex(idx_default)
            elif self.model_selector_combo.count() > 0 : self.model_selector_combo.setCurrentIndex(0)
            else: self.model_selector_combo.setCurrentText(current_sel if current_sel else config_handler.DEFAULT_SETTINGS["default_ollama_model"]) 
            self.append_console("Ollama server responsive."); self.health_check_timer.stop(); 
            self._set_analysis_buttons_enabled(True); self.model_selector_combo.setEnabled(True)
            if self.settings.get("guard_mode_enabled", False) and self.guard_enable_checkbox.isEnabled() and not self.guard_mode_timer.isActive():
                 self.append_console("Attempting to enable Guard Mode based on saved settings as Ollama is now ready.")
                 if not self.guard_enable_checkbox.isChecked(): self.guard_enable_checkbox.setChecked(True) 
                 else: self.on_toggle_guard_mode(True)
        else: self.append_console(f"Health check: `ollama list` failed (Exit: {list_proc.exitCode()}).\nOut: {out_str}\nErr: {err_str}")
    def stop_ollama_server(self):
        if self.health_check_timer and self.health_check_timer.isActive(): self.health_check_timer.stop()
        if self.ollama_server_proc and self.ollama_server_proc.state() != QProcess.NotRunning:
            self.append_console("Stopping Ollama server..."); self.ollama_server_proc.kill() 
            if self.ollama_server_proc.waitForFinished(5000): self.append_console("Ollama server stopped.")
            else: self.append_console("Ollama server kill timeout.")
        self.ollama_server_proc = None
    def _on_ollama_server_output(self):
        if not self.ollama_server_proc: return
        data_bytes = self.ollama_server_proc.readAllStandardOutput()
        console_encoding = sys.stdout.encoding or "utf-8"
        try: data_str = data_bytes.data().decode('utf-8', errors='surrogateescape')
        except UnicodeDecodeError: data_str = data_bytes.data().decode(console_encoding, errors='replace')
        for line in data_str.splitlines(): 
            safe_line = line.encode(console_encoding, errors='replace').decode(console_encoding)
            self.append_console(f"[OllamaServe] {safe_line}")
    def _on_ollama_server_error_output(self):
        if not self.ollama_server_proc: return
        data_bytes = self.ollama_server_proc.readAllStandardError()
        console_encoding = sys.stderr.encoding or "utf-8"
        try: data_str = data_bytes.data().decode('utf-8', errors='surrogateescape')
        except UnicodeDecodeError: data_str = data_bytes.data().decode(console_encoding, errors='replace')
        for line in data_str.splitlines(): 
            safe_line = line.encode(console_encoding, errors='replace').decode(console_encoding)
            self.append_console(f"[OllamaServe ERR] {safe_line}")
    def _on_ollama_server_finished(self, exit_code, exit_status):
        status = "normally" if exit_status == QProcess.NormalExit else "crashed"; self.append_console(f"Ollama server finished ({status}) code {exit_code}.")
        self._set_analysis_buttons_enabled(False); self.model_selector_combo.setEnabled(False)
        if self.health_check_timer and self.health_check_timer.isActive(): self.health_check_timer.stop()
    def _on_ollama_server_error_occurred(self, error):
        err_str = self.ollama_server_proc.errorString() if self.ollama_server_proc else "Process is None"
        self.append_console(f"ERROR Ollama server: {err_str} (Code: {error})")
        self._set_analysis_buttons_enabled(False); self.model_selector_combo.setEnabled(False)
        if self.health_check_timer and self.health_check_timer.isActive(): self.health_check_timer.stop()

    def on_select_guard_folder(self):
        current_folder = self.settings.get("guard_mode_folder", "")
        if not os.path.isdir(current_folder): current_folder = self.settings.get("last_hprof_dir", "")
        if not os.path.isdir(current_folder): current_folder = str(PROJECT_ROOT)
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Monitor", current_folder)
        if folder: self.guard_folder_input.setText(folder); self.settings["guard_mode_folder"] = folder; self.append_console(f"Guard Mode folder set: {folder}")
    
    def on_toggle_guard_mode(self, checked):
        current_folder_text = self.guard_folder_input.text().strip()
        self.settings["guard_mode_enabled"] = checked 
        if checked:
            if not current_folder_text or not os.path.isdir(current_folder_text): QMessageBox.warning(self, "Invalid Folder", "Select a valid folder for Guard Mode."); self.guard_enable_checkbox.setChecked(False); return
            if not self.ollama_available or (self.ollama_server_proc and self.ollama_server_proc.state() != QProcess.Running): QMessageBox.warning(self, "Ollama Not Ready", "Ollama server not running. Guard Mode cannot be enabled."); self.guard_enable_checkbox.setChecked(False); return
            interval_minutes = self.guard_interval_spinbox.value()
            if not self.guard_mode_timer.isActive(): 
                try: self.guard_mode_timer.timeout.disconnect(self.scan_guard_folder) 
                except RuntimeError: pass 
                self.guard_mode_timer.timeout.connect(self.scan_guard_folder)
            self.guard_mode_timer.start(interval_minutes * 60 * 1000) 
            self.guard_status_label.setText(f"Guard Mode: Active - Watching '{os.path.basename(current_folder_text)}' every {interval_minutes} min(s).")
            self.append_console(f"Guard Mode enabled: '{current_folder_text}', interval: {interval_minutes} min(s).")
            self.guard_folder_input.setEnabled(False); self.guard_folder_select_btn.setEnabled(False); self.guard_interval_spinbox.setEnabled(False)
            self.processed_in_guard_mode.clear(); self.guard_mode_file_mod_times.clear() 
            QTimer.singleShot(1000, self.scan_guard_folder) 
        else: 
            self.guard_mode_timer.stop()
            self.guard_status_label.setText("Guard Mode: Inactive"); self.append_console("Guard Mode disabled.")
            self.guard_folder_input.setEnabled(True); self.guard_folder_select_btn.setEnabled(True); self.guard_interval_spinbox.setEnabled(True)
            
    def on_guard_interval_changed(self, new_interval_minutes):
        self.settings["guard_mode_interval_minutes"] = new_interval_minutes
        if self.guard_enable_checkbox.isChecked() and self.guard_mode_timer.isActive():
            self.guard_mode_timer.stop(); self.guard_mode_timer.start(new_interval_minutes * 60 * 1000)
            self.append_console(f"Guard Mode: Interval updated to {new_interval_minutes} min(s).")
            folder_name = os.path.basename(self.guard_folder_input.text().strip()) if self.guard_folder_input.text().strip() else "selected folder"
            self.guard_status_label.setText(f"Guard Mode: Active - Interval {new_interval_minutes} min(s). Watching '{folder_name}'.")

    def is_file_stable(self, filepath, stability_check_interval_sec=2, stability_checks=2):
        try:
            if not os.path.isfile(filepath): return False 
            last_size = os.path.getsize(filepath); last_mtime = os.path.getmtime(filepath)
            for i in range(stability_checks):
                time.sleep(stability_check_interval_sec) 
                if not os.path.isfile(filepath): return False 
                current_size = os.path.getsize(filepath); current_mtime = os.path.getmtime(filepath)
                if current_size != last_size or current_mtime != last_mtime : self.append_console(f"Guard Mode: File '{os.path.basename(filepath)}' unstable. Check {i+1}/{stability_checks}"); return False 
                last_size, last_mtime = current_size, current_mtime
            self.append_console(f"Guard Mode: File '{os.path.basename(filepath)}' appears stable (size: {last_size})."); return True
        except FileNotFoundError: self.append_console(f"Guard Mode: File '{os.path.basename(filepath)}' FNF during stability check."); return False
        except Exception as e: self.append_console(f"Guard Mode: Error checking file stability for '{os.path.basename(filepath)}': {e}"); return False

    def scan_guard_folder(self): 
        if not self.guard_enable_checkbox.isChecked(): self.guard_mode_timer.stop(); return
        if self.is_batch_running or (self.analysis_proc and self.analysis_proc.state() != QProcess.NotRunning): self.append_console("Guard Mode: Analysis/Batch in progress, scan deferred."); return
        folder_to_watch = self.guard_folder_input.text().strip()
        if not folder_to_watch or not os.path.isdir(folder_to_watch): self.append_console("Guard Mode: Invalid folder, stopping guard."); self.guard_enable_checkbox.setChecked(False); return
        self.append_console(f"Guard Mode: Scanning '{folder_to_watch}'...")
        new_files_to_process = []
        try:
            for filename in os.listdir(folder_to_watch):
                if filename.lower().endswith((".hprof", ".txt", ".pcap", ".pcapng")):
                    filepath = os.path.join(folder_to_watch, filename)
                    try:
                        if not os.path.isfile(filepath): continue
                        current_mod_time = os.path.getmtime(filepath)
                        if (filepath not in self.guard_mode_file_mod_times or self.guard_mode_file_mod_times.get(filepath) != current_mod_time):
                            if self.is_file_stable(filepath):
                                self.append_console(f"Guard Mode: Adding stable file to queue: {filepath}")
                                new_files_to_process.append(filepath)
                    except FileNotFoundError: 
                        if filepath in self.processed_in_guard_mode: self.processed_in_guard_mode.remove(filepath) 
                        if filepath in self.guard_mode_file_mod_times: del self.guard_mode_file_mod_times[filepath]
                        continue 
        except Exception as e: self.append_console(f"Guard Mode: Error scanning folder '{folder_to_watch}': {e}"); return
        if new_files_to_process:
            self.append_console(f"Guard Mode: Adding {len(new_files_to_process)} file(s) to analysis queue.")
            for fp in new_files_to_process: 
                self.processed_in_guard_mode.add(fp) 
                try:
                    self.guard_mode_file_mod_times[fp] = os.path.getmtime(fp) if os.path.exists(fp) else 0
                except FileNotFoundError:
                    self.guard_mode_file_mod_times[fp] = 0
            self.batch_queue.extend(new_files_to_process) 
            if not self.is_batch_running: 
                self.current_batch_total_files = len(self.batch_queue); self.current_batch_processed_files = 0; self.is_batch_running = True
                self._set_analysis_buttons_enabled(False)
                self.batch_progress_bar.setMaximum(self.current_batch_total_files); self.batch_progress_bar.setVisible(True)
                self.process_next_in_batch()
        else: self.append_console(f"Guard Mode: No new or modified files found requiring processing.")
        self.guard_status_label.setText(f"Guard Mode: Last scan {time.strftime('%H:%M:%S')}. Watching '{os.path.basename(folder_to_watch)}'.")

    def on_pull_model_clicked(self):
        model_name_to_pull = self.pull_model_name_input.text().strip()
        if not model_name_to_pull: QMessageBox.warning(self, "No Model Name", "Enter model name to pull."); return
        if not self.ollama_available or not (self.ollama_server_proc and self.ollama_server_proc.state() == QProcess.Running):
            QMessageBox.warning(self, "Ollama Not Ready", "Ollama server not running."); return
        if self.pull_model_proc and self.pull_model_proc.state() != QProcess.NotRunning:
            QMessageBox.information(self, "Busy", "Model pull already in progress."); return
        self.append_console(f"Attempting to pull Ollama model: {model_name_to_pull}...")
        self._set_analysis_buttons_enabled(False) 
        self.pull_model_proc = QProcess(self); self.pull_model_proc.setProgram(str(BUNDLED_OLLAMA_EXE_PATH))
        self.pull_model_proc.setArguments(["pull", model_name_to_pull])
        env = QProcessEnvironment.systemEnvironment(); env.insert("OLLAMA_MODELS", str(BUNDLED_OLLAMA_MODELS_DIR))
        self.pull_model_proc.setProcessEnvironment(env)
        self.pull_model_proc.readyReadStandardOutput.connect(self._on_pull_model_output)
        self.pull_model_proc.readyReadStandardError.connect(self._on_pull_model_output) 
        self.pull_model_proc.finished.connect(self._on_pull_model_finished)
        self.pull_model_proc.start()
        if not self.pull_model_proc.waitForStarted(3000):
            self.append_console(f"ERROR: Failed to start 'ollama pull' for {model_name_to_pull}.")
            self._set_analysis_buttons_enabled(True); self.pull_model_proc = None
    def _on_pull_model_output(self):
        if not self.pull_model_proc: return
        console_encoding = sys.stdout.encoding or "utf-8"
        output_bytes = self.pull_model_proc.readAllStandardOutput(); err_bytes = self.pull_model_proc.readAllStandardError()
        if output_bytes: self.append_console(f"[Ollama Pull] {output_bytes.data().decode(console_encoding, errors='replace').strip()}")
        if err_bytes: self.append_console(f"[Ollama Pull] {err_bytes.data().decode(console_encoding, errors='replace').strip()}")
    def _on_pull_model_finished(self, exit_code, exit_status):
        model_name = self.pull_model_name_input.text().strip() 
        if exit_status == QProcess.NormalExit and exit_code == 0:
            self.append_console(f"Successfully pulled Ollama model: {model_name}. Refreshing list...")
            if self.health_check_timer and self.health_check_timer.isActive(): self.health_check_timer.stop()
            self.check_ollama_server_health() 
            idx = self.model_selector_combo.findText(model_name, Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchCaseSensitive)
            if idx != -1: self.model_selector_combo.setCurrentIndex(idx)
        else: self.append_console(f"Failed to pull Ollama model: {model_name}. Exit: {exit_code}, Status: {exit_status}")
        self._set_analysis_buttons_enabled(True); self.pull_model_name_input.clear(); self.pull_model_proc = None

    def _on_analysis_output(self): 
        if not self.analysis_proc: return
        out_bytes = self.analysis_proc.readAllStandardOutput()
        try: 
            console_encoding = sys.stdout.encoding or "utf-8"
            try: out_str = out_bytes.data().decode('utf-8', errors='surrogateescape')
            except UnicodeDecodeError: out_str = out_bytes.data().decode(console_encoding, errors='replace')
            for line in out_str.splitlines(): 
                safe_line = line.encode(console_encoding, errors='replace').decode(console_encoding)
                self.append_console(safe_line)
        except Exception as e: self.append_console(f"Error decoding analysis output: {e}")
            
    def _on_analysis_finished(self, exit_code, exit_status):
        status = "normally" if exit_status == QProcess.NormalExit else "crashed"
        self.append_console(f"\nAnalysis finished ({status}) code {exit_code}")
        if self.is_batch_running:
            if not self.batch_queue: self.append_console("Batch processing complete.")
            QTimer.singleShot(100, self.process_next_in_batch) 
        else: self._set_analysis_buttons_enabled(True)
            
    def _on_analysis_error(self, error):
        proc_error_string = self.analysis_proc.errorString() if self.analysis_proc else "N/A"
        self.append_console(f"ERROR in analysis process execution (QProcess error type {error}): {proc_error_string}")
        if self.is_batch_running:
            self.append_console("Error during batch item. Moving to next file if any.")
            QTimer.singleShot(100, self.process_next_in_batch) 
        else: self._set_analysis_buttons_enabled(True)

    def on_toggle_dashboard(self): 
        port = self.port_spin.value()
        if self.dashboard_proc and self.dashboard_proc.state() != QProcess.NotRunning:
            self.append_console("Stopping dashboard..."); self.dashboard_proc.terminate() 
            if not self.dashboard_proc.waitForFinished(5000): self.dashboard_proc.kill(); self.dashboard_proc.waitForFinished(3000)
            self.dashboard_btn.setText("Launch Dashboard"); self.append_console("Dashboard stopped."); self.dashboard_proc = None
        else:
            self.append_console(f"Starting dashboard on port {port}…"); self.dashboard_proc = QProcess(self)
            self.dashboard_proc.setProgram(sys.executable)
            args_dashboard = [str(PROJECT_ROOT / "dashboard.py"), f"--port={port}"]
            self.dashboard_proc.setArguments(args_dashboard); self.dashboard_proc.setWorkingDirectory(str(PROJECT_ROOT)) 
            self.dashboard_proc.readyReadStandardOutput.connect(self._on_dashboard_output); self.dashboard_proc.readyReadStandardError.connect(self._on_dashboard_error_output)
            self.dashboard_proc.finished.connect(self._on_dashboard_finished); self.dashboard_proc.errorOccurred.connect(self._on_dashboard_error)
            self.dashboard_proc.start()
            if self.dashboard_proc.waitForStarted(5000): self.dashboard_btn.setText("Stop Dashboard"); self.append_console("Dashboard started.")
            else: self.append_console(f"ERROR starting dashboard: {self.dashboard_proc.errorString()}"); self.dashboard_proc = None
    
    def _on_dashboard_output(self): 
        if not self.dashboard_proc: return
        data = self.dashboard_proc.readAllStandardOutput().data().decode(sys.stdout.encoding or "utf-8", errors="replace")
        for line in data.splitlines(): self.append_console(line.rstrip('\r\n'))
    
    def _on_dashboard_error_output(self): 
        if not self.dashboard_proc: return
        data = self.dashboard_proc.readAllStandardError().data().decode(sys.stderr.encoding or "utf-8", errors="replace")
        for line in data.splitlines():
            self.append_console("DASHBOARD_ERR: " + line.rstrip("\r\n"))
    
    def _on_dashboard_finished(self, exit_code, exit_status): 
        status = "normally" if exit_status == QProcess.NormalExit else "crashed"; self.append_console(f"Dashboard finished ({status}) code {exit_code}"); self.dashboard_btn.setText("Launch Dashboard")
    
    def _on_dashboard_error(self, error): 
        proc_error_string = self.dashboard_proc.errorString() if self.dashboard_proc else "N/A"
        self.append_console(f"ERROR dashboard process: {error} ({proc_error_string}"); self.dashboard_btn.setText("Launch Dashboard")
    
    def on_open_browser(self): 
        url_string = f"http://localhost:{self.port_spin.value()}/"; 
        if not QDesktopServices.openUrl(QUrl(url_string)):
            try: webbrowser.open(url_string) 
            except Exception as e: self.append_console(f"webbrowser could not open URL: {e}")
        self.append_console(f"Attempted to open browser at {url_string}")
        
    def append_console(self, txt): 
        self.console.appendPlainText(str(txt).rstrip('\r\n')); QApplication.processEvents()
        
    def closeEvent(self, event): 
        self.append_console("Window closing. Saving settings & stopping processes...")
        self.save_settings_to_handler()
        if self.guard_mode_timer.isActive(): self.guard_mode_timer.stop() 
        if self.analysis_proc and self.analysis_proc.state() != QProcess.NotRunning: self.analysis_proc.kill(); self.analysis_proc.waitForFinished(3000)
        if self.dashboard_proc and self.dashboard_proc.state() != QProcess.NotRunning: self.dashboard_proc.kill(); self.dashboard_proc.waitForFinished(3000)
        if self.pull_model_proc and self.pull_model_proc.state() != QProcess.NotRunning: self.pull_model_proc.kill(); self.pull_model_proc.waitForFinished(3000)
        self.stop_ollama_server()
        super().closeEvent(event)