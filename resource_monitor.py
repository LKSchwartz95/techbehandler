import json
import os
import time
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover - handled by graceful fallback
    psutil = None

PROJECT_ROOT = Path(__file__).resolve().parent
RESULTAT_DIR = PROJECT_ROOT / "Resultat"


def collect_metrics(output_file: str | os.PathLike):
    """Collect basic system metrics and append as a JSON line.

    Parameters
    ----------
    output_file:
        Destination file for the metrics. If the path points to the current
        working directory (i.e. has no parent folder), the directory creation
        step is skipped.
    """

    output_path = Path(output_file)
    # ``Path.output_path.parent`` resolves to ``'.'`` when no directory
    # component is provided. ``mkdir`` on ``'.'`` is a no-op, which allows
    # callers to write metrics directly to the current working directory.
    output_path.parent.mkdir(parents=True, exist_ok=True)

    metrics = {"timestamp": time.time()}
    if psutil is None:
        metrics.update(
            {
                "cpu_percent": None,
                "memory_percent": None,
                "disk_percent": None,
                "net_bytes_sent": None,
                "net_bytes_recv": None,
            }
        )
    else:
        metrics.update(
            {
                "cpu_percent": psutil.cpu_percent(interval=None),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage("/").percent,
                "net_bytes_sent": psutil.net_io_counters().bytes_sent,
                "net_bytes_recv": psutil.net_io_counters().bytes_recv,
            }
        )

    with output_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(metrics) + "\n")
    return metrics


def collect_once_in_resultat(run_name: str):
    """Convenience wrapper to collect metrics to a run subdirectory."""
    run_dir = RESULTAT_DIR / run_name
    os.makedirs(run_dir, exist_ok=True)
    out_path = run_dir / "system_metrics.jsonl"
    return collect_metrics(out_path)


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

    if psutil is not None:
        # Warm up CPU percent to avoid a blocking first measurement
        psutil.cpu_percent(interval=None)

    for i in range(iterations):
        start = time.perf_counter()
        results.append(collect_metrics(output_file))
        if i < iterations - 1:
            elapsed = time.perf_counter() - start
            sleep_duration = max(0.0, interval_seconds - elapsed)
            time.sleep(sleep_duration)
    return results

