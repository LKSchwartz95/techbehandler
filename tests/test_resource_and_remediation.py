import json
from pathlib import Path
import importlib.util

ROOT_DIR = Path(__file__).resolve().parents[1]

spec_rm = importlib.util.spec_from_file_location("resource_monitor", ROOT_DIR / "resource_monitor.py")
resource_monitor = importlib.util.module_from_spec(spec_rm)
spec_rm.loader.exec_module(resource_monitor)

spec_re = importlib.util.spec_from_file_location("remediation_engine", ROOT_DIR / "remediation_engine.py")
remediation_engine = importlib.util.module_from_spec(spec_re)
spec_re.loader.exec_module(remediation_engine)

collect_metrics = resource_monitor.collect_metrics
generate_remediation = remediation_engine.generate_remediation


def test_collect_metrics(tmp_path: Path):
    out_file = tmp_path / "metrics.jsonl"
    metrics = collect_metrics(out_file)
    assert out_file.exists()
    with out_file.open() as f:
        data = json.loads(f.readline())
    assert metrics["cpu_percent"] == data["cpu_percent"]


def test_generate_remediation(tmp_path: Path):
    out_file = tmp_path / "rem.json"
    suggestions = generate_remediation(["OutdatedPackages", "Unknown"], out_file)
    assert suggestions and "Run system package updates" in suggestions[0]
    data = json.loads(out_file.read_text())
    assert data["tags"] == ["OutdatedPackages", "Unknown"]
    assert len(data["suggestions"]) == 1

