import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
RESULTAT_DIR = PROJECT_ROOT / "Resultat"


def run_nmap_scan(target: str, run_dir: Path) -> str:
    """Run an nmap scan if nmap is available."""
    output_file = run_dir / f"nmap_{target.replace('/', '_')}.txt"
    cmd = ["nmap", "-A", target]
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=False)
    except FileNotFoundError:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("nmap not installed or not found in PATH\n")
    return str(output_file)


def scan_target(target: str, run_name: str):
    run_dir = RESULTAT_DIR / run_name
    os.makedirs(run_dir, exist_ok=True)
    return run_nmap_scan(target, run_dir)
