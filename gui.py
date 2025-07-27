#!/usr/bin/env python3
# Filename: gui.py
# This is the main entry point for the GUI application.

import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

# This is important to ensure other modules find files correctly from the project root
PROJECT_ROOT = Path(__file__).resolve().parent

# We import the main window class *after* setting up the project root
try:
    from main_window import MainWindow
except ImportError as e:
    print(f"FATAL: Could not import MainWindow. Ensure main_window.py exists. Error: {e}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    # Enable automatic scaling on high-DPI displays before creating the
    # QApplication instance. This ensures widgets and icons look correct
    # on high resolution screens.
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = QApplication(sys.argv)
    app.setApplicationName("DumpBehandler")
    
    # Ensure the main "Resultat" directory exists at startup
    (PROJECT_ROOT / "Resultat").mkdir(exist_ok=True)
    
    # Create and show the main application window
    window = MainWindow()
    window.show()
    
    # Start the application's event loop
    sys.exit(app.exec())