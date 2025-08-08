import os
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox
import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent))
import tool_manager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _setup_dummy(dialog, tmp_path, monkeypatch):
    tool = {"id": "dummy", "name": "Dummy", "install_path": "dummy_install"}
    install_dir = tmp_path / "dummy_install"
    install_dir.mkdir()
    (install_dir / "file.txt").write_text("data")

    original_find = dialog._find_installed_tool_dir

    def fake_find(t):
        if t.get("id") == "dummy":
            return install_dir
        return original_find(t)

    monkeypatch.setattr(dialog, "_find_installed_tool_dir", fake_find)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok)
    return tool, install_dir


def test_uninstall_tool_removes_directory(tmp_path, monkeypatch):
    dialog = tool_manager.ToolManagerDialog()
    tool, install_dir = _setup_dummy(dialog, tmp_path, monkeypatch)

    dialog.uninstall_tool(tool, 0)

    assert not install_dir.exists()


def test_uninstall_tool_permission_error(tmp_path, monkeypatch):
    dialog = tool_manager.ToolManagerDialog()
    tool, install_dir = _setup_dummy(dialog, tmp_path, monkeypatch)

    def fake_rmtree(path):
        raise PermissionError("denied")

    monkeypatch.setattr(tool_manager.shutil, "rmtree", fake_rmtree)
    warnings = {}

    def record_warning(*a, **k):
        warnings["warned"] = True
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", record_warning)

    dialog.uninstall_tool(tool, 0)

    assert install_dir.exists()
    assert warnings.get("warned")
