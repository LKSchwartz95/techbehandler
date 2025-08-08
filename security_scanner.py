import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
RESULTAT_DIR = PROJECT_ROOT / "Resultat"


def run_lynis_scan(run_dir: Path) -> str:
    """Run a lynis security audit if available."""
    output_file = run_dir / "lynis_report.txt"
    cmd = ["lynis", "audit", "system", "--quiet", "--quick"]
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=False)
    except FileNotFoundError:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("lynis not installed or not found in PATH\n")
    return str(output_file)


def run_osquery_scan(run_dir: Path) -> str:
    """Run a basic osquery info query if available."""
    output_file = run_dir / "osquery_info.txt"
    cmd = ["osqueryi", "--json", "SELECT version, build_platform FROM osquery_info;"]
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=False)
    except FileNotFoundError:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("osqueryi not installed or not found in PATH\n")
    return str(output_file)


def run_yara_scan(rule_file: str | os.PathLike, target: str | os.PathLike, run_dir: Path) -> str:
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
            subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=False)
    except FileNotFoundError:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("yara not installed or not found in PATH\n")
    return str(output_file)


def run_all_scans(run_name: str, yara_rule: str | os.PathLike | None = None, yara_target: str | os.PathLike | None = None):
    run_dir = RESULTAT_DIR / run_name
    os.makedirs(run_dir, exist_ok=True)

    with ThreadPoolExecutor() as executor:
        futures = {
            "lynis": executor.submit(run_lynis_scan, run_dir),
            "osquery": executor.submit(run_osquery_scan, run_dir),
        }

        if yara_rule and yara_target:
            futures["yara"] = executor.submit(run_yara_scan, yara_rule, yara_target, run_dir)

        results = {name: future.result() for name, future in futures.items()}

    return results
