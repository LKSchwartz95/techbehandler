import json
import os
import re
import subprocess
from pathlib import Path
import sys
from typing import List, Optional
import config_handler


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))
from utils import sanitize_run_name
RESULTAT_DIR = PROJECT_ROOT / "Resultat"



def parse_nmap_output(output_file: Path) -> dict:
    """Parse nmap's textual output to a structured dict."""
    result = {"host": None, "ip": None, "ports": []}
    try:
        content = output_file.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        return {**result, "error": str(e)}

    if "nmap not installed" in content.lower():
        result["error"] = "nmap not installed or not found in PATH"
        return result

    host_match = re.search(r"Nmap scan report for ([^\s]+)(?: \(([^)]+)\))?", content)
    if host_match:
        result["host"] = host_match.group(1)
        result["ip"] = host_match.group(2)

    port_section = False
    for line in content.splitlines():
        if re.match(r"PORT\s+STATE\s+SERVICE", line):
            port_section = True
            continue
        if port_section:
            if not line.strip() or line.startswith("Nmap done"):
                break
            m = re.match(r"(\d+)/(tcp|udp)\s+(\S+)\s+(\S+)", line.strip())
            if m:
                port, proto, state, service = m.groups()
                result["ports"].append({
                    "port": int(port),
                    "protocol": proto,
                    "state": state,
                    "service": service,
                })
    return result


def write_nmap_json(output_file: Path) -> Path:
    """Write a JSON companion file next to the nmap output."""
    data = parse_nmap_output(output_file)
    json_path = output_file.with_suffix(".json")
    try:
        json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass
    return json_path


def run_nmap_scan(
    target: str,
    run_dir: Path,
    extra_options: Optional[List[str]] = None,
    timeout: int = 60,
) -> str:
    """Run an nmap scan if nmap is available and create a JSON report."""

    output_file = run_dir / f"nmap_{target.replace('/', '_')}.txt"
    cmd = ["nmap", "-A"]
    if extra_options:
        cmd.extend(extra_options)
    cmd.append(target)
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            try:
                result = subprocess.run(
                    cmd,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    check=False,
                    timeout=timeout,
                )
                if result.returncode != 0:
                    f.write(
                        f"\nCommand exited with return code {result.returncode}\n"
                    )
            except subprocess.TimeoutExpired:
                f.write("nmap scan timed out\n")
    except FileNotFoundError:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("nmap not installed or not found in PATH\n")

    write_nmap_json(output_file)
    return str(output_file)


def load_nmap_json(json_path: Path) -> dict:
    """Load the JSON output produced by :func:`write_nmap_json`."""
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {"error": str(e)}


def scan_target(target: str, run_name: str):
    run_name = sanitize_run_name(run_name)
    run_dir = RESULTAT_DIR / run_name
    os.makedirs(run_dir, exist_ok=True)

    settings = config_handler.load_settings()
    extra_opts = settings.get("nmap_options", [])
    return run_nmap_scan(target, run_dir, extra_opts)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run an Nmap scan and save the output.")
    parser.add_argument("target", help="Target to scan")
    parser.add_argument("--run-name", default="run", help="Output directory name")
    parser.add_argument(
        "--options",
        nargs="*",
        help="Extra options for nmap (overrides config file)",
    )
    args = parser.parse_args()

    opts = args.options if args.options is not None else config_handler.load_settings().get("nmap_options", [])
    run_dir = RESULTAT_DIR / args.run_name
    os.makedirs(run_dir, exist_ok=True)
    output_path = run_nmap_scan(args.target, run_dir, opts)
    print(output_path)
