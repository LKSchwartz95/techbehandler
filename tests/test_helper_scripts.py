import importlib.util
from pathlib import Path
import sys
import types

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

qtcore = types.ModuleType('PySide6.QtCore')

class QStandardPaths:
    class StandardLocation:
        HomeLocation = 0

    @staticmethod
    def writableLocation(_):
        return str(ROOT_DIR)

qtcore.QStandardPaths = QStandardPaths
pyside6 = types.ModuleType('PySide6')
pyside6.QtCore = qtcore
sys.modules.setdefault('PySide6', pyside6)
sys.modules.setdefault('PySide6.QtCore', qtcore)

# Load modules
spec_ns = importlib.util.spec_from_file_location("network_scanner", ROOT_DIR / "network_scanner.py")
network_scanner = importlib.util.module_from_spec(spec_ns)
spec_ns.loader.exec_module(network_scanner)

spec_ss = importlib.util.spec_from_file_location("security_scanner", ROOT_DIR / "security_scanner.py")
security_scanner = importlib.util.module_from_spec(spec_ss)
spec_ss.loader.exec_module(security_scanner)

spec_la = importlib.util.spec_from_file_location("log_aggregator", ROOT_DIR / "log_aggregator.py")
log_aggregator = importlib.util.module_from_spec(spec_la)
spec_la.loader.exec_module(log_aggregator)


def test_network_scan_and_cleanup(tmp_path: Path):
    run_dir = tmp_path
    out_path = network_scanner.run_nmap_scan("127.0.0.1", run_dir, ["-Pn"])
    assert Path(out_path).exists()


def test_security_scans(tmp_path: Path):
    lynis_path = security_scanner.run_lynis_scan(tmp_path)
    osq_path = security_scanner.run_osquery_scan(tmp_path)
    assert Path(lynis_path).exists()
    assert Path(osq_path).exists()


def test_yara_scan(tmp_path: Path):
    rule_file = tmp_path / "rule.yar"
    rule_file.write_text("rule dummy { strings: $a = \"dummy\" condition: $a }")
    target_file = tmp_path / "sample.txt"
    target_file.write_text("dummy")
    out_path = security_scanner.run_yara_scan(rule_file, target_file, tmp_path)
    assert Path(out_path).exists()


def test_log_aggregation(tmp_path: Path):
    log_file = log_aggregator.gather_system_logs(tmp_path)
    assert Path(log_file).exists()


def test_batch_launcher_contains_setup():
    batch_path = ROOT_DIR / "run_dumpbehandler.bat"
    content = batch_path.read_text()
    assert "venv" in content
    assert "pip install" in content
