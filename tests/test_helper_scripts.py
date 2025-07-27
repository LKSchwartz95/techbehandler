import importlib.util
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

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
    out_path = network_scanner.run_nmap_scan("127.0.0.1", run_dir)
    assert Path(out_path).exists()


def test_security_scans(tmp_path: Path):
    lynis_path = security_scanner.run_lynis_scan(tmp_path)
    osq_path = security_scanner.run_osquery_scan(tmp_path)
    assert Path(lynis_path).exists()
    assert Path(osq_path).exists()


def test_log_aggregation(tmp_path: Path):
    log_file = log_aggregator.gather_system_logs(tmp_path)
    assert Path(log_file).exists()


def test_batch_launcher_contains_setup():
    batch_path = ROOT_DIR / "run_dumpbehandler.bat"
    content = batch_path.read_text()
    assert "venv" in content
    assert "pip install" in content
