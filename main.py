#!/usr/bin/env python3
import os
import sys

def get_root_directory():
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS 
    else:
        return os.path.dirname(os.path.abspath(__file__))

PROJECT_ROOT = get_root_directory()
os.chdir(PROJECT_ROOT) 
os.makedirs(os.path.join(PROJECT_ROOT, "Resultat"), exist_ok=True)

def run_gui_app():
    print(f"Attempting to launch GUI. PROJECT_ROOT={PROJECT_ROOT}, CWD={os.getcwd()}")
    from PySide6.QtWidgets import QApplication
    try: from gui import MainWindow 
    except ImportError as e: print(f"ERROR: Import gui.MainWindow fail: {e}", file=sys.stderr); sys.exit(1)
    app = QApplication(sys.argv); app.setApplicationName("DumpBehandler")
    window = MainWindow(); window.show(); sys.exit(app.exec())

def run_monitor_app(monitor_cli_args):
    print(f"Attempting to run monitor. Args: {monitor_cli_args}. CWD={os.getcwd()}")
    try: from monitor import main as monitor_main_entry
    except ImportError as e: print(f"ERROR: Import monitor.main fail: {e}", file=sys.stderr); sys.exit(1)
    sys.exit(monitor_main_entry(monitor_cli_args))

def run_dashboard_app(dashboard_cli_args):
    print(f"Attempting to run dashboard. Args: {dashboard_cli_args}. CWD={os.getcwd()}")
    try: from dashboard import main as dashboard_main_entry
    except ImportError as e: print(f"ERROR: Import dashboard.main fail: {e}", file=sys.stderr); sys.exit(1)
    sys.exit(dashboard_main_entry(dashboard_cli_args))

if __name__ == "__main__":
    print(f"DumpBehandler Main. PRJ_ROOT: {PROJECT_ROOT}, CWD: {os.getcwd()}", flush=True)
    # print(f"Original sys.argv: {sys.argv}", flush=True) # For debugging

    if len(sys.argv) >= 2:
        command = sys.argv[1].lower()
        args_for_subcommand = sys.argv[2:]
        if command == "monitor": run_monitor_app(args_for_subcommand)
        elif command == "dashboard": run_dashboard_app(args_for_subcommand)
        elif command == "gui": run_gui_app()
        else: print(f"Unknown command: '{sys.argv[1]}'. Defaulting to GUI.", file=sys.stderr); run_gui_app()
    else: print("No command. Defaulting to GUI."); run_gui_app()