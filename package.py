import os
import zipfile
from datetime import datetime

# --- Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__)) # Assumes this script is in the project root
OUTPUT_ZIP_FILENAME_BASE = "DumpBehandler_App_Files"

# Files and folders to ALWAYS include (relative to PROJECT_ROOT)
# These are your core application logic and assets.
INCLUDE_ITEMS = [
    "main.py",
    "gui.py",
    "monitor.py",
    "dashboard.py",
    "ollama_client.py",
    "config.json",          # Include current config as a starting point for user
    "requirements.txt",     # Essential for setting up the environment
    "run_dumpbehandler.bat", # Your launcher script
    "templates",            # Folder
    "static"                # Folder (if you have one, otherwise it will be skipped if not found)
]

# Patterns of files and folders to ALWAYS exclude (relative to PROJECT_ROOT)
# These are large dependencies, virtual environments, generated output, logs, etc.
EXCLUDE_PATTERNS = [
    ".venv",                # Virtual environment
    "Ollama",               # Bundled Ollama executable and its libs
    "MAT",                  # MAT tool
    "models",               # LLM models (can be very large)
    "Resultat",             # Output directory
    "__pycache__",          # Python bytecode cache
    ".git",                 # Git repository folder
    ".vscode",              # VSCode settings
    ".idea",                # PyCharm/IntelliJ settings
    "*.log",                # Log files (e.g., monitor_log.txt)
    "*.zip",                # Don't include previous zip files (including itself)
    "package_app.py",       # This script itself
    "ollama_client_log.txt", # Specific log file
    "dashboard_log.txt",    # Specific log file
    "monitor_log.txt"       # Specific log file
    # Add any other files/folders you want to exclude
]

def should_exclude(filepath, root_dir):
    """Checks if a file/folder should be excluded based on EXCLUDE_PATTERNS."""
    relative_path = os.path.relpath(filepath, root_dir)
    
    # Check for exact matches or directory prefixes first
    for pattern in EXCLUDE_PATTERNS:
        if relative_path == pattern or relative_path.startswith(pattern + os.sep):
            return True
        # For wildcard file patterns like *.log
        if pattern.startswith("*.") and relative_path.endswith(pattern[1:]):
            return True
            
    # Check if it's a directory name match (e.g. __pycache__) anywhere in the path
    path_parts = relative_path.split(os.sep)
    for part in path_parts:
        if part in EXCLUDE_PATTERNS: # e.g. if "__pycache__" is in EXCLUDE_PATTERNS
            return True
            
    return False

def create_app_zip():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_zip_filename = f"{OUTPUT_ZIP_FILENAME_BASE}_{timestamp}.zip"
    output_zip_path = os.path.join(PROJECT_ROOT, output_zip_filename)

    included_count = 0
    excluded_count = 0

    print(f"Creating application package: {output_zip_path}")
    print(f"Project root: {PROJECT_ROOT}")

    with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # First, explicitly add items from INCLUDE_ITEMS
        for item_name in INCLUDE_ITEMS:
            item_path_abs = os.path.join(PROJECT_ROOT, item_name)
            if os.path.exists(item_path_abs):
                if os.path.isfile(item_path_abs):
                    arcname = item_name # Store with relative path from root
                    zipf.write(item_path_abs, arcname)
                    print(f"  Including file: {arcname}")
                    included_count += 1
                elif os.path.isdir(item_path_abs):
                    print(f"  Including directory: {item_name}")
                    for foldername, subfolders, filenames in os.walk(item_path_abs):
                        # Exclude __pycache__ within included directories like 'templates'
                        if "__pycache__" in subfolders:
                            subfolders.remove("__pycache__") 
                            
                        for filename in filenames:
                            file_to_zip_abs = os.path.join(foldername, filename)
                            # arcname should be relative to PROJECT_ROOT
                            arcname = os.path.relpath(file_to_zip_abs, PROJECT_ROOT)
                            zipf.write(file_to_zip_abs, arcname)
                            print(f"    Including file: {arcname}")
                            included_count += 1
            else:
                print(f"  Warning: Specified include item not found: {item_name}")
        
        # Optional: Walk through the rest of PROJECT_ROOT for anything not explicitly included/excluded
        # For a more controlled package, you might skip this general walk and *only* include INCLUDE_ITEMS.
        # If you want to walk everything else:
        # print("\nScanning for other project files (excluding specified patterns)...")
        # for folderName, subfolders, filenames in os.walk(PROJECT_ROOT):
        #     # Prune excluded directories from further traversal
        #     subfolders[:] = [d for d in subfolders if not should_exclude(os.path.join(folderName, d), PROJECT_ROOT)]
            
        #     for filename in filenames:
        #         filePath_abs = os.path.join(folderName, filename)
        #         arcname = os.path.relpath(filePath_abs, PROJECT_ROOT)

        #         # Check if already included or if it should be excluded
        #         if arcname in INCLUDE_ITEMS or any(filePath_abs == os.path.join(PROJECT_ROOT, inc_item) for inc_item in INCLUDE_ITEMS if os.path.isfile(os.path.join(PROJECT_ROOT, inc_item))):
        #             continue # Already handled by explicit includes

        #         if not should_exclude(filePath_abs, PROJECT_ROOT) and filename != output_zip_filename:
        #             zipf.write(filePath_abs, arcname)
        #             print(f"  Including additional file: {arcname}")
        #             included_count += 1
        #         elif filename != output_zip_filename: # Don't count the zip itself as excluded if not yet created
        #             # print(f"  Excluding: {arcname}") # Can be very verbose
        #             excluded_count +=1


    print(f"\nSuccessfully created {output_zip_filename}")
    print(f"Total files and folders explicitly included: {included_count}")
    # print(f"Total other items scanned and excluded: {excluded_count}")

if __name__ == "__main__":
    create_app_zip()
    input("Press Enter to exit...")