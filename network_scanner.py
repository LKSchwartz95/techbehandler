import json
import os
import re
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
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


def run_nmap_scan(target: str, run_dir: Path) -> str:
    """Run an nmap scan if nmap is available and create a JSON report."""
    output_file = run_dir / f"nmap_{target.replace('/', '_')}.txt"
    cmd = ["nmap", "-A", target]
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=False)
    except FileNotFoundError:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("nmap not installed or not found in PATH\n")

    write_nmap_json(output_file)
    return str(output_file)


def scan_target(target: str, run_name: str):
    run_dir = RESULTAT_DIR / run_name
    os.makedirs(run_dir, exist_ok=True)
    return run_nmap_scan(target, run_dir)


def load_nmap_json(json_file: Path) -> dict:
    """Helper to load nmap JSON results for display in the dashboard."""
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
