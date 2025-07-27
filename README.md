# TechBehandler

TechBehandler is a GUI application for analyzing Java diagnostics and network captures using local LLM models with Ollama. The project provides utilities for generating reports, managing external tools and viewing results through a small dashboard.

## Features

- Launch a PySide6 desktop application for analysis
- Run a Flask based dashboard to review run results
- Live capture of network traffic using tshark
- Manage optional tools via the built in tool manager
- Configurable prompt templates for LLM based analysis

## Requirements

Python 3.11+ and the dependencies listed in `requirements.txt` are required. You can install them with

```bash
pip install -r requirements.txt
```

Some features require additional third party tools (e.g. Wireshark or Eclipse MAT) which can be downloaded through the Tool Manager dialog.

## Usage

Run the GUI directly:

```bash
python main.py
```

or start the dashboard manually:

```bash
python main.py dashboard
```

The application stores output under the `Resultat` directory.

## Packaging

`package.py` can be used to create a zip archive of the application while excluding large model files and temporary output.

## Testing

Run the unit tests with:

```bash
pytest
```

Tests run automatically on GitHub Actions:

[![Tests](https://github.com/<owner>/techbehandler/actions/workflows/python-app.yml/badge.svg)](https://github.com/<owner>/techbehandler/actions/workflows/python-app.yml)
