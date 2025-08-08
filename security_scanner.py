import os
import subprocess
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))
from utils import sanitize_run_name
RESULTAT_DIR = PROJECT_ROOT / "Resultat"


def run_lynis_scan(run_dir: Path, timeout: int = 60) -> str:
    """Run a lynis security audit if available."""
    output_file = run_dir / "lynis_report.txt"
    cmd = ["lynis", "audit", "system", "--quiet", "--quick"]
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            try:
                result = subprocess.run(
                    cmd, stdout=f, stderr=subprocess.STDOUT, check=False, timeout=timeout
                )
                if result.returncode != 0:
                    f.write(f"\nCommand exited with return code {result.returncode}\n")
            except subprocess.TimeoutExpired:
                f.write("lynis scan timed out\n")
    except FileNotFoundError:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("lynis not installed or not found in PATH\n")
    return str(output_file)


def run_osquery_scan(run_dir: Path, timeout: int = 60) -> str:
    """Run a basic osquery info query if available."""
    output_file = run_dir / "osquery_info.txt"
    cmd = ["osqueryi", "--json", "SELECT version, build_platform FROM osquery_info;"]
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            try:
                result = subprocess.run(
                    cmd, stdout=f, stderr=subprocess.STDOUT, check=False, timeout=timeout
                )
                if result.returncode != 0:
                    f.write(f"\nCommand exited with return code {result.returncode}\n")
            except subprocess.TimeoutExpired:
                f.write("osquery scan timed out\n")
    except FileNotFoundError:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("osqueryi not installed or not found in PATH\n")
    return str(output_file)


def run_yara_scan(rule_file: str | os.PathLike, target: str | os.PathLike, run_dir: Path, timeout: int = 60) -> str:
    """Scan a file or directory with yara rules if available.

    Parameters
    ----------
    rule_file:
        Path to the yara rule file.
    target:
        File or directory to scan.
    run_dir:
        Output directory for the scan results.
    """

    output_file = run_dir / f"yara_{Path(target).name}.txt"
    cmd = ["yara", str(rule_file), str(target)]
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            try:
                result = subprocess.run(
                    cmd, stdout=f, stderr=subprocess.STDOUT, check=False, timeout=timeout
                )
                if result.returncode != 0:
                    f.write(f"\nCommand exited with return code {result.returncode}\n")
            except subprocess.TimeoutExpired:
                f.write("yara scan timed out\n")
    except FileNotFoundError:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("yara not installed or not found in PATH\n")
    return str(output_file)


def run_all_scans(
    run_name: str,
    yara_rule: str | os.PathLike | None = None,
    yara_target: str | os.PathLike | None = None,
):
    run_name = sanitize_run_name(run_name)
    run_dir = RESULTAT_DIR / run_name
    os.makedirs(run_dir, exist_ok=True)
    results = {
        "lynis": run_lynis_scan(run_dir),
        "osquery": run_osquery_scan(run_dir),
    }
    if yara_rule and yara_target:
        results["yara"] = run_yara_scan(yara_rule, yara_target, run_dir)
    return results
