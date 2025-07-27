#!/usr/bin/env python3
# Filename: gui.py
# This is the main entry point for the GUI application.

import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication

# This is important to ensure other modules find files correctly from the project root
PROJECT_ROOT = Path(__file__).resolve().parent

# We import the main window class *after* setting up the project root
try:
    from main_window import MainWindow
except ImportError as e:
    print(f"FATAL: Could not import MainWindow. Ensure main_window.py exists. Error: {e}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("DumpBehandler")
    
    # Ensure the main "Resultat" directory exists at startup
    (PROJECT_ROOT / "Resultat").mkdir(exist_ok=True)
    
    # Create and show the main application window
    window = MainWindow()
    window.show()
    
    # Start the application's event loop
    sys.exit(app.exec())