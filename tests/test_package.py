import importlib.util
from pathlib import Path

# Load the local package.py module explicitly to avoid name clashes
spec = importlib.util.spec_from_file_location(
    'package_local', Path(__file__).resolve().parents[1] / 'package.py'
)
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def test_should_exclude(tmp_path):
    root_dir = tmp_path
    file_in_cache = root_dir / '__pycache__' / 'x.pyc'
    file_in_cache.parent.mkdir()
    file_in_cache.touch()
    assert package.should_exclude(str(file_in_cache), str(root_dir)) is True

    log_file = root_dir / 'debug.log'
    log_file.touch()
    assert package.should_exclude(str(log_file), str(root_dir)) is True

    normal_file = root_dir / 'data' / 'file.txt'
    normal_file.parent.mkdir()
    normal_file.touch()
    assert package.should_exclude(str(normal_file), str(root_dir)) is False
