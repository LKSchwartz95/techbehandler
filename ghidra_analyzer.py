"""Utility for running Ghidra in headless mode and summarizing output."""
import json
import subprocess
from pathlib import Path

def run_ghidra_analysis(binary_path, ghidra_headless_path, work_dir):
    """Run Ghidra headless analysis on *binary_path* using *ghidra_headless_path*.
    Returns a text summary of discovered functions and strings.
    """
    work_dir = Path(work_dir)
    script_dir = Path(__file__).parent / "ghidra_scripts"
    script_path = script_dir / "dump_basic_info.py"
    summary_path = work_dir / "ghidra_summary.json"
    cmd = [
        ghidra_headless_path,
        str(work_dir),
        "TempProject",
        "-import",
        str(binary_path),
        "-analysisTimeoutPerFile",
        "60",
        "-scriptPath",
        str(script_dir),
        "-postScript",
        f"{script_path.name} {summary_path}"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Ghidra analysis failed: {result.stderr.strip()}")
    if not summary_path.exists():
        raise FileNotFoundError(f"Expected summary file not created: {summary_path}")
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    parts = []
    funcs = data.get("functions", [])[:50]
    if funcs:
        parts.append("Functions:\n" + "\n".join(funcs))
    strs = data.get("strings", [])[:50]
    if strs:
        parts.append("Strings:\n" + "\n".join(strs))
    return "\n\n".join(parts)
