from pathlib import Path
import importlib.util
import json
import os

PROJECT_ROOT = Path(__file__).resolve().parent
RESULTAT_DIR = PROJECT_ROOT / "Resultat"
PLUGIN_DIR = PROJECT_ROOT / "remediation_plugins"

TAG_TO_REMEDIATION = {
    "OutdatedPackages": "Run system package updates to apply latest security patches.",
    "MemoryLeak": "Investigate heap usage with profiling tools and fix leaking objects.",
    "HighCPU": "Identify processes with high CPU utilization and optimize or restart them.",
    "HighThreadCount": "Check for thread leaks or misconfigured thread pools.",
}


def _load_plugin_mappings():
    """Load tag-to-remediation mappings from all plugin modules."""
    if not PLUGIN_DIR.exists():
        return
    for plugin_path in PLUGIN_DIR.glob("*.py"):
        if plugin_path.name == "__init__.py":
            continue
        spec = importlib.util.spec_from_file_location(plugin_path.stem, plugin_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            mapping = getattr(module, "TAG_TO_REMEDIATION", None)
            if isinstance(mapping, dict):
                TAG_TO_REMEDIATION.update(mapping)


_load_plugin_mappings()


def generate_remediation(tags: list[str], output_file: str | os.PathLike):
    suggestions = [TAG_TO_REMEDIATION[tag] for tag in tags if tag in TAG_TO_REMEDIATION]
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({"tags": tags, "suggestions": suggestions}, f, indent=2)
    return suggestions


def generate_for_run(run_name: str, tags: list[str]):
    run_dir = RESULTAT_DIR / run_name
    os.makedirs(run_dir, exist_ok=True)
    out_file = run_dir / "remediation.json"
    return generate_remediation(tags, str(out_file))
