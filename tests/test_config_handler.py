import importlib.util
from pathlib import Path
import json
import sys
import types


def load_module(tmp_path):
    qtcore = types.ModuleType('PySide6.QtCore')

    class QStandardPaths:
        class StandardLocation:
            HomeLocation = 0

        @staticmethod
        def writableLocation(_):
            return str(tmp_path)

    qtcore.QStandardPaths = QStandardPaths
    pyside6 = types.ModuleType('PySide6')
    pyside6.QtCore = qtcore
    sys.modules['PySide6'] = pyside6
    sys.modules['PySide6.QtCore'] = qtcore
    if 'config_handler' in sys.modules:
        del sys.modules['config_handler']
    spec = importlib.util.spec_from_file_location(
        'config_handler', Path(__file__).resolve().parents[1] / 'config_handler.py'
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules['config_handler'] = module
    spec.loader.exec_module(module)
    return module


def test_load_settings_missing_file(tmp_path, monkeypatch):
    mod = load_module(tmp_path)
    cfg_path = tmp_path / 'config.json'
    monkeypatch.setattr(mod, 'CONFIG_FILE_PATH', cfg_path)
    settings = mod.load_settings()
    assert settings == mod.DEFAULT_SETTINGS


def test_load_settings_merges_defaults(tmp_path, monkeypatch):
    mod = load_module(tmp_path)
    cfg_path = tmp_path / 'config.json'
    with cfg_path.open('w', encoding='utf-8') as f:
        json.dump({'guard_mode_enabled': True}, f)
    monkeypatch.setattr(mod, 'CONFIG_FILE_PATH', cfg_path)
    settings = mod.load_settings()
    assert settings['guard_mode_enabled'] is True
    for key in mod.DEFAULT_SETTINGS:
        assert key in settings


def test_save_settings(tmp_path, monkeypatch):
    mod = load_module(tmp_path)
    cfg_path = tmp_path / 'config.json'
    monkeypatch.setattr(mod, 'CONFIG_FILE_PATH', cfg_path)
    result = mod.save_settings({'foo': 'bar'})
    assert result is True
    with cfg_path.open(encoding='utf-8') as f:
        data = json.load(f)
    assert data == {'foo': 'bar'}
