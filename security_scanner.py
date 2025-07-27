diff --git a//dev/null b/security_scanner.py
index 0000000000000000000000000000000000000000..adae6f9fe8f4f93288cff857109f1dd1a957c149 100644
--- a//dev/null
+++ b/security_scanner.py
@@ -0,0 +1,41 @@
+import os
+import subprocess
+from pathlib import Path
+
+PROJECT_ROOT = Path(__file__).resolve().parent
+RESULTAT_DIR = PROJECT_ROOT / "Resultat"
+
+
+def run_lynis_scan(run_dir: Path) -> str:
+    """Run a lynis security audit if available."""
+    output_file = run_dir / "lynis_report.txt"
+    cmd = ["lynis", "audit", "system", "--quiet", "--quick"]
+    try:
+        with open(output_file, "w", encoding="utf-8") as f:
+            subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=False)
+    except FileNotFoundError:
+        with open(output_file, "w", encoding="utf-8") as f:
+            f.write("lynis not installed or not found in PATH\n")
+    return str(output_file)
+
+
+def run_osquery_scan(run_dir: Path) -> str:
+    """Run a basic osquery info query if available."""
+    output_file = run_dir / "osquery_info.txt"
+    cmd = ["osqueryi", "--json", "SELECT version, build_platform FROM osquery_info;"]
+    try:
+        with open(output_file, "w", encoding="utf-8") as f:
+            subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=False)
+    except FileNotFoundError:
+        with open(output_file, "w", encoding="utf-8") as f:
+            f.write("osqueryi not installed or not found in PATH\n")
+    return str(output_file)
+
+
+def run_all_scans(run_name: str):
+    run_dir = RESULTAT_DIR / run_name
+    os.makedirs(run_dir, exist_ok=True)
+    return {
+        "lynis": run_lynis_scan(run_dir),
+        "osquery": run_osquery_scan(run_dir),
+    }
