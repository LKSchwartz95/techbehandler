from pathlib import Path
import importlib.util
import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]

spec_utils = importlib.util.spec_from_file_location("utils", ROOT_DIR / "utils.py")
utils = importlib.util.module_from_spec(spec_utils)
spec_utils.loader.exec_module(utils)


def test_sanitize_run_name_normalizes_separators_and_chars():
    assert utils.sanitize_run_name("foo/bar?baz") == "foo_bar_baz"


def test_sanitize_run_name_rejects_traversal():
    with pytest.raises(ValueError):
        utils.sanitize_run_name("../evil")
