from pathlib import Path
import json
import importlib.util

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]

spec_rm = importlib.util.spec_from_file_location("resource_monitor", ROOT_DIR / "resource_monitor.py")
resource_monitor = importlib.util.module_from_spec(spec_rm)
spec_rm.loader.exec_module(resource_monitor)

spec_re = importlib.util.spec_from_file_location("remediation_engine", ROOT_DIR / "remediation_engine.py")
remediation_engine = importlib.util.module_from_spec(spec_re)
spec_re.loader.exec_module(remediation_engine)

collect_metrics = resource_monitor.collect_metrics
collect_metrics_periodically = resource_monitor.collect_metrics_periodically
generate_remediation = remediation_engine.generate_remediation


def test_collect_metrics(tmp_path: Path, monkeypatch):
    pytest.importorskip("psutil")
    recorded: dict[str, float | None] = {}

    def fake_cpu_percent(*, interval=None):
        recorded["interval"] = interval
        return 12.0

    monkeypatch.setattr(resource_monitor.psutil, "cpu_percent", fake_cpu_percent)
    out_file = tmp_path / "metrics.jsonl"
    metrics = collect_metrics(out_file)
    assert recorded["interval"] is None
    assert out_file.exists()
    with out_file.open() as f:
        data = json.loads(f.readline())
    assert metrics["cpu_percent"] == data["cpu_percent"] == 12.0



def test_collect_metrics_current_directory(tmp_path: Path, monkeypatch):
    """Collect metrics when output path is in the current working directory."""
    pytest.importorskip("psutil")

    recorded: dict[str, float | None] = {}

    def fake_cpu_percent(*, interval=None):
        recorded["interval"] = interval
        return 34.0

    monkeypatch.setattr(resource_monitor.psutil, "cpu_percent", fake_cpu_percent)
    monkeypatch.chdir(tmp_path)
    out_file = Path("metrics.jsonl")
    metrics = collect_metrics(out_file)
    assert recorded["interval"] is None
    assert out_file.exists()
    data = json.loads(out_file.read_text().splitlines()[0])
    assert metrics["cpu_percent"] == data["cpu_percent"] == 34.0


def test_collect_metrics_periodically(tmp_path: Path):
    pytest.importorskip("psutil")
    out_file = tmp_path / "metrics.jsonl"
    results = collect_metrics_periodically(out_file, iterations=3, interval_seconds=0)
    assert len(results) == 3
    lines = out_file.read_text().strip().splitlines()
    assert len(lines) == 3



def test_generate_remediation(tmp_path: Path):
    out_file = tmp_path / "rem.json"
    suggestions = generate_remediation(["OutdatedPackages", "Unknown"], out_file)
    assert suggestions and "Run system package updates" in suggestions[0]
    data = json.loads(out_file.read_text())
    assert data["tags"] == ["OutdatedPackages", "Unknown"]
    assert len(data["suggestions"]) == 1

