# Filename: config_handler.py
import json
import os
from pathlib import Path
from PySide6.QtCore import QStandardPaths

# This allows the script to find the project root, even when imported by another script
PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_FILE_PATH = PROJECT_ROOT / "config.json"

DEFAULT_SETTINGS = {
    "default_ollama_model": "gemma3:1b", "ollama_dashboard_port": 5000, "mat_memory_mb": 4096,
    "guard_mode_folder": "", "guard_mode_enabled": False, "guard_mode_interval_minutes": 1,
    "saved_prompts": [
        {"name": "HPROF Comprehensive Analysis", "template": """You are an expert Java performance analyst.
Analyze the following diagnostic information from a Java application's heap dump.

**MAT Leak Suspects Report Summary:**
{mat_summary}

**Thread Dump Details from HPROF:**
{thread_dump_details}

Based on all the provided data, perform the following two tasks:
1.  **Generate Tags:** In a single line, provide a comma-separated list of 3-5 tags that categorize the main problem(s). Use tags from this list if applicable: MemoryLeak, HighThreadCount, GC_Overhead, FinalizerAbuse, LargeAllocation, ClassLoaderLeak, DuplicateStrings. The line MUST start with "TAGS:".
2.  **Provide Analysis:** Write a detailed analysis in Markdown format covering the primary memory-related problem(s), a root cause hypothesis, and clear, actionable recommendations.

Your response:
"""},
        {"name": "Thread Dump (jstack) Analysis", "template": """You are an expert Java performance analyst specializing in thread-related issues.
Analyze the following Java thread dump (from jstack).

**Full Thread Dump:**
{thread_dump_details}

Based on the provided thread dump, perform the following two tasks:
1.  **Generate Tags:** In a single line, provide a comma-separated list of 3-5 tags that categorize the main problem(s). Use tags from this list if applicable: Deadlock, ThreadContention, BlockedThreads, HighThreadCount, SlowRequest, IdleApplication. The line MUST start with "TAGS:".
2.  **Provide Analysis:** Write a detailed analysis in Markdown format covering any deadlocks, significant thread contention, a summary of the application state, and actionable recommendations.

Your response:
"""},
        {"name": "Wireshark Multi-Tool Analysis", "template": """You are an expert network analyst.
Analyze the following summaries generated by tshark from a packet capture. Each section represents a different analysis task.

**tshark Analysis Output:**
{tshark_summary}

Based on all the provided data, perform the following two tasks:
1.  **Generate Tags:** In a single line, provide a comma-separated list of 3-5 tags that categorize the main observations. Use tags from this list if applicable: HighLatency, HighTraffic, ChattyProtocol, DNS_Error, TLS_Alert, ManyConnections, LongLivedConnection, UnencryptedHTTP. The line MUST start with "TAGS:".
2.  **Provide Analysis:** Write a detailed, holistic analysis in Markdown format. Synthesize findings from all sections to:
    - Identify the top 3 "chattiest" conversations by total bytes or packets.
    - Point out any conversations with unusually long durations or high latency that may indicate performance bottlenecks.
    - Report any DNS errors or unusual query patterns.
    - Report any TLS/SSL security alerts or handshake failures.
    - Summarize the overall network behavior and provide clear, actionable recommendations for investigation.

Your response:
"""}
    ],
    "default_prompt_name": "HPROF Comprehensive Analysis", 
    "last_hprof_dir": str(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.HomeLocation)),
    "default_mat_report_type_id": "leak_suspects", 
    "mat_report_options": [ 
        {"name": "Leak Suspects", "id": "leak_suspects", "mat_arg": "org.eclipse.mat.api:suspects"},
        {"name": "Dominator Tree", "id": "dominator_tree", "mat_arg": "org.eclipse.mat.api:dominator_tree"},
        {"name": "Top Consumers (Retained Size)", "id": "top_consumers", "mat_arg": "org.eclipse.mat.api:top_consumers_html"},
        {"name": "System Overview (Basic Parse + Threads)", "id": "system_overview", "mat_arg": "org.eclipse.mat.api.parse"}
    ],
    "llm_parameters": { 
        "temperature": 0.7, "num_ctx": 4096, "top_k": 40, "top_p": 0.9, "seed": 0, "stop": [],
        "num_predict": 1024 
    },
    "llm_params_group_checked": False,
    "wireshark_tasks": {
        "tcp_conv": True, "ip_conv": False, "dns_stats": True, 
        "http_reqs": True, "tls_alerts": True, "slow_resps": False
    }
}

def load_settings():
    """
    Loads settings from config.json, merging with defaults to ensure all keys are present.
    """
    loaded_settings = {}
    try:
        if CONFIG_FILE_PATH.exists():
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                loaded_settings = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Could not load config file at {CONFIG_FILE_PATH}: {e}")
        # Return defaults if the file is corrupted or unreadable
        return DEFAULT_SETTINGS.copy()

    # Merge loaded settings with defaults to ensure all keys exist
    # This makes the program resilient to manually edited/old config files
    final_settings = DEFAULT_SETTINGS.copy()
    
    # Special handling for lists like prompts to merge intelligently
    if 'saved_prompts' in loaded_settings:
        existing_prompt_names = {p['name'] for p in loaded_settings['saved_prompts']}
        for default_prompt in DEFAULT_SETTINGS['saved_prompts']:
            if default_prompt['name'] not in existing_prompt_names:
                loaded_settings['saved_prompts'].append(default_prompt)
    
    final_settings.update(loaded_settings)
    return final_settings

def save_settings(settings_dict):
    """
    Saves the provided settings dictionary to config.json.
    """
    try:
        with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(settings_dict, f, indent=4)
        return True
    except (OSError, TypeError) as e:
        print(f"Error: Could not save settings to {CONFIG_FILE_PATH}: {e}")
        return False