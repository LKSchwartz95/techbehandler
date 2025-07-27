import json
import os
import time
from pathlib import Path

import psutil

PROJECT_ROOT = Path(__file__).resolve().parent
RESULTAT_DIR = PROJECT_ROOT / "Resultat"


def collect_metrics(output_file: str | os.PathLike):
    """Collect basic system metrics and append as a JSON line."""
    metrics = {
        "timestamp": time.time(),
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage("/").percent,
        "net_bytes_sent": psutil.net_io_counters().bytes_sent,
        "net_bytes_recv": psutil.net_io_counters().bytes_recv,
    }
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(metrics) + "\n")
    return metrics


def collect_once_in_resultat(run_name: str):
    """Convenience wrapper to collect metrics to a run subdirectory."""
    run_dir = RESULTAT_DIR / run_name
    os.makedirs(run_dir, exist_ok=True)
    out_path = run_dir / "system_metrics.jsonl"
    return collect_metrics(str(out_path))


def collect_metrics_periodically(
    output_file: str | os.PathLike,
    iterations: int,
    interval_seconds: float = 1.0,
) -> list[dict]:
    """Collect metrics repeatedly for a number of iterations.

    Parameters
    ----------
    output_file:
        File path to append metrics JSON lines to.
    iterations:
        How many samples to collect.
    interval_seconds:
        Delay between samples. The first sample is collected immediately.

    Returns
    -------
    list of dict
        A list of metrics dictionaries in the order they were collected.
    """

    results = []
    for i in range(iterations):
        results.append(collect_metrics(output_file))
        if i < iterations - 1:
            time.sleep(max(0.0, interval_seconds))
    return results

