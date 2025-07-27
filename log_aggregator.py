
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
RESULTAT_DIR = PROJECT_ROOT / "Resultat"


def gather_system_logs(run_dir: Path) -> str:
    """Collect basic system logs into a single file."""
    output_file = run_dir / "system_logs.txt"
    paths = []
    if os.name == "nt":
        # Placeholder: real Windows log collection would require pywin32
        paths.append(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32\\LogFiles\\HTTPERR\\httperr1.log")
    else:
        for candidate in ("/var/log/syslog", "/var/log/messages"):
            if os.path.isfile(candidate):
                paths.append(candidate)
    with open(output_file, "w", encoding="utf-8", errors="ignore") as out_f:
        for p in paths:
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as src:
                    out_f.write(f"--- {p} ---\n")
                    out_f.write(src.read())
                    out_f.write("\n")
            except Exception as e:
                out_f.write(f"Could not read {p}: {e}\n")
    return str(output_file)


def gather_for_run(run_name: str):
    run_dir = RESULTAT_DIR / run_name
    os.makedirs(run_dir, exist_ok=True)
    return gather_system_logs(run_dir)
