#!/usr/bin/env python3
# Filename: monitor.py
import os
import sys
import subprocess
import re
import zipfile
import shutil
import time
from datetime import datetime, timezone
import argparse
import json 
import traceback 
import ollama_client 
from bs4 import BeautifulSoup

PROJECT_ROOT_MONITOR = os.path.dirname(os.path.abspath(__file__))
# RESULTAT_DIR_MONITOR is no longer the authority, run_dir passed by arg is.
LOG_FILE_MONITOR = os.path.join(os.getcwd(), "monitor_log.txt") 

def log_monitor_error(msg):
    try:
        if os.path.exists(LOG_FILE_MONITOR) and os.path.getsize(LOG_FILE_MONITOR) > 10 * 1024 * 1024:
            with open(LOG_FILE_MONITOR, "w", encoding="utf-8") as f: f.write(f"[{datetime.now()}] Log truncated.\n")
    except OSError: pass
    with open(LOG_FILE_MONITOR, "a", encoding="utf-8") as f: f.write(f"[{datetime.now()}] {msg}\n{traceback.format_exc()}\n")

def check_ollama_model_availability(model_name, ollama_cmd_path, timeout=30):
    if not os.path.isfile(ollama_cmd_path): print(f"ERROR: Ollama cmd FNF: '{ollama_cmd_path}'.", flush=True); log_monitor_error(f"Ollama cmd FNF: '{ollama_cmd_path}'."); return False
    list_cmd = [ollama_cmd_path, "list"]; process = None
    try:
        current_env = os.environ.copy()
        process = subprocess.Popen(list_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=current_env)
        stdout_data, stderr_data = process.communicate(timeout=timeout)
        if process.returncode == 0:
            if model_name.lower() in stdout_data.lower(): return True
            else: print(f"Model '{model_name}' NOT in `ollama list`.", flush=True); log_monitor_error(f"Model '{model_name}' not in list.\nOut:{stdout_data}\nErr:{stderr_data}"); return False
        else: print(f"`ollama list` failed: {process.returncode}", flush=True); log_monitor_error(f"`ollama list` fail {process.returncode}.\nOut:{stdout_data}\nErr:{stderr_data}"); return False
    except subprocess.TimeoutExpired: 
        print(f"Ollama `list` command timed out after {timeout}s.", flush=True)
        log_monitor_error(f"Ollama `list` for model {model_name} timed out after {timeout}s")
        if process: process.kill()
        return False
    except Exception as e: print(f"Err in `ollama list`: {e}", flush=True); log_monitor_error(f"Err `ollama list` for {model_name}: {e}"); return False

def generate_mat_report(hprof_path, current_run_dir, base_name, mat_jar_to_use, mat_memory_mb, mat_report_argument): 
    if not mat_jar_to_use or not os.path.isfile(mat_jar_to_use): raise ValueError(f"MAT_JAR invalid: '{mat_jar_to_use}'.")
    abs_hprof = os.path.abspath(hprof_path)
    
    # current_run_dir is already created by the GUI, so no need for os.makedirs
    
    cmd = [ "java", "--add-opens=java.base/java.lang=ALL-UNNAMED", "--add-exports=java.base/jdk.internal.org.objectweb.asm=ALL-UNNAMED",
        f"-Xmx{mat_memory_mb}m", "-jar", mat_jar_to_use, "-consoleLog", "-application"]
    if mat_report_argument and mat_report_argument != "org.eclipse.mat.api.parse":
        cmd.extend(["org.eclipse.mat.api.parse", abs_hprof, mat_report_argument])
    else: 
        cmd.extend(["org.eclipse.mat.api.parse", abs_hprof])
    log_monitor_error(f"MAT Command: {' '.join(cmd)}"); print(f"Generating MAT report with argument: {mat_report_argument}", flush=True)
    
    # MAT generates output in its CWD, so we run it from the run_dir to keep files contained
    p = subprocess.Popen(cmd, cwd=current_run_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    for line in p.stdout: print(line, end="", flush=True)
    p.wait()
    if p.returncode != 0: log_monitor_error(f"MAT fail {p.returncode} for {hprof_path} with arg {mat_report_argument}"); raise subprocess.CalledProcessError(p.returncode, cmd)

    # MAT files should now be in current_run_dir.
    print("MAT process finished. Checking for output in run directory.")


def unzip_mat_zip(current_run_dir, base_name, mat_report_argument_used):
    zip_to_extract = None
    # MAT sometimes creates unpredictable zip names, so we find any relevant zip
    if "suspects" in mat_report_argument_used.lower():
        zip_pattern = "_Leak_Suspects.zip"
    elif "dominator" in mat_report_argument_used.lower():
        zip_pattern = "_dominator_tree.zip"
    elif "consumers" in mat_report_argument_used.lower():
        zip_pattern = "_Top_Consumers.zip"
    else:
        print(f"Skipping unzip for MAT report type: {mat_report_argument_used}", flush=True)
        return

    for f in os.listdir(current_run_dir):
        if f.endswith(zip_pattern):
            zip_to_extract = os.path.join(current_run_dir, f)
            break
            
    if zip_to_extract and os.path.isfile(zip_to_extract):
        try:
            with zipfile.ZipFile(zip_to_extract, "r") as z: z.extractall(current_run_dir)
            print(f"Unzipped MAT report: {zip_to_extract}", flush=True)
            os.remove(zip_to_extract) # Clean up the zip file after extraction
        except zipfile.BadZipFile: print(f"ERROR: Bad zip: {zip_to_extract}", flush=True); log_monitor_error(f"Bad MAT zip: {zip_to_extract}")
        except Exception as e: print(f"ERROR: Unzip fail {zip_to_extract}: {e}", flush=True); log_monitor_error(f"Unzip fail {zip_to_extract}: {e}")
    else: print(f"MAT report zip not found with pattern *{zip_pattern}", flush=True)

def extract_mat_suspect_text(run_dir):
    # Find index.html, which might be in a subdirectory after extraction
    for root, _, files in os.walk(run_dir):
        if "index.html" in files:
            html_report_path = os.path.join(root, "index.html")
            try:
                with open(html_report_path, "r", encoding="utf-8", errors="ignore") as f:
                    soup = BeautifulSoup(f.read(), "lxml")
                header = soup.find(lambda tag: tag.name in ("h2", "h3") and "Problem Suspect" in tag.get_text())
                if not header: return "Could not find 'Problem Suspect' section in the MAT report."
                details_element = header.find_next_sibling("div", class_="details") or header.find_next_sibling("table")
                if details_element: return details_element.get_text(separator='\n', strip=True)
                return "Found 'Problem Suspect' header, but no details section followed it."
            except Exception as e:
                log_monitor_error(f"Failed to extract text from MAT HTML report: {html_report_path} - {e}"); return f"Error parsing MAT report HTML: {e}"

    log_monitor_error(f"Could not find index.html in {run_dir} for summary extraction.")
    return "MAT report summary file (index.html) not found."


def extract_threads_file_content(threads_filepath):
    # This function is used for both .txt files and .threads files from MAT
    if not os.path.isfile(threads_filepath):
        log_monitor_error(f"Threads file not found for content extraction: {threads_filepath}"); return None
    try:
        with open(threads_filepath, "r", encoding="utf-8", errors="ignore") as f_threads: return f_threads.read()
    except Exception as e:
        log_monitor_error(f"Error reading content from {threads_filepath}: {e}"); return None

def run_tshark_task(pcap_path, tshark_exe_path, task_id):
    if not os.path.isfile(tshark_exe_path):
        raise FileNotFoundError(f"tshark executable not found at: {tshark_exe_path}")

    TSHARK_TASKS = {
        "tcp_conv":   {"cmd": ["-q", "-z", "conv,tcp"], "title": "TCP Conversation Summary"},
        "ip_conv":    {"cmd": ["-q", "-z", "conv,ip"], "title": "IP Conversation Summary"},
        "dns_stats":  {"cmd": ["-q", "-z", "dns,tree"], "title": "DNS Statistics"},
        "http_reqs":  {"cmd": ["-Y", "http.request", "-T", "fields", "-e", "http.host", "-e", "http.request.method", "-e", "http.request.uri"], "title": "HTTP Requests"},
        "tls_alerts": {"cmd": ["-Y", "tls.alert_message", "-T", "fields", "-e", "frame.number", "-e", "ip.src", "-e", "ip.dst", "-e", "tls.alert_message.desc"], "title": "TLS/SSL Alerts"},
        "slow_resps": {"cmd": ["-Y", "tcp.time_delta > 0.2", "-T", "fields", "-e", "frame.number", "-e", "ip.src", "-e", "ip.dst", "-e", "tcp.time_delta"], "title": "Slow TCP Responses (>200ms)"},
        "proto_hier": {"cmd": ["-q", "-z", "io,phs"], "title": "Protocol Hierarchy"},
        "tcp_errors": {"cmd": ["-Y", "tcp.analysis.flags", "-T", "fields", "-e", "frame.number", "-e", "ip.src", "-e", "ip.dst", "-e", "tcp.analysis.flags"], "title": "TCP Errors"}
    }

    task = TSHARK_TASKS.get(task_id)
    if not task:
        raise ValueError(f"Unknown tshark task ID: {task_id}")

    base_cmd = [tshark_exe_path, "-r", pcap_path]
    full_cmd = base_cmd + task["cmd"]
    
    print(f"Running tshark task '{task['title']}': {' '.join(full_cmd)}")
    
    try:
        process = subprocess.run(full_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True, timeout=120)
        return f"--- {task['title']} ---\n{process.stdout}\n"
    except subprocess.TimeoutExpired as e:
        error_output = f"--- {task['title']} (TIMED OUT) ---\n"
        error_output += f"tshark task timed out after 120 seconds.\n"
        log_monitor_error(error_output)
        return error_output
    except subprocess.CalledProcessError as e:
        error_output = f"--- {task['title']} (FAILED) ---\n"
        error_output += f"tshark failed with exit code {e.returncode}.\nStderr: {e.stderr}\n"
        log_monitor_error(error_output)
        return error_output
    except FileNotFoundError:
        log_monitor_error(f"tshark command failed. Is tshark installed and in the PATH or specified correctly?")
        raise

def ask_ollama_model(prompt, model_tag, ollama_cmd_path_ignored, llm_params_dict, timeout=300):
    print(f"Contacting Ollama API via client with model '{model_tag}'...", flush=True)
    text_response, _ = ollama_client.ollama_api_generate(model_tag=model_tag, prompt_text=prompt, llm_parameters=llm_params_dict, timeout=timeout)
    if text_response: print("Ollama API interaction successful.")
    else: print("Ollama API interaction failed.")
    return text_response

def save_run_metadata(current_run_dir, metadata_dict):
    metadata_path = os.path.join(current_run_dir, "run_metadata.json")
    try:
        with open(metadata_path, "w", encoding="utf-8") as f: json.dump(metadata_dict, f, indent=4)
    except Exception as e: print(f"Error saving metadata: {e}", flush=True); log_monitor_error(f"Error saving metadata to {metadata_path}: {e}")

def main(argv_to_parse=None):
    parser = argparse.ArgumentParser(description="Analyze diagnostic files.")
    parser.add_argument("input_file", help="Path to the diagnostic file (should be inside the run_dir).")
    parser.add_argument("--run-dir", required=True, help="Path to the dedicated directory for this analysis run.")
    parser.add_argument("--prompt", help="LLM prompt template.")
    parser.add_argument("--model", required=True, help="Ollama model tag.")
    parser.add_argument("--ollama-cmd", required=True, help="Path to Ollama CLI.")
    parser.add_argument("--llm-params", type=str, default="{}", help="JSON string of LLM parameters.")
    parser.add_argument("--mat-memory", type=int, help="Memory for MAT in MB (HPROF only).")
    parser.add_argument("--mat-report-arg", help="MAT API argument for report type (HPROF only).")
    parser.add_argument("--mat-launcher-path", help="Path to the MAT launcher JAR (HPROF only).")
    parser.add_argument("--tshark-path", help="Path to tshark executable (pcap only).")
    parser.add_argument("--pcap-tasks", help="Comma-separated list of tshark tasks to run (pcap only).")
    args = parser.parse_args(argv_to_parse)

    input_file_lower = args.input_file.lower()
    is_hprof, is_txt, is_pcap = input_file_lower.endswith('.hprof'), input_file_lower.endswith('.txt'), input_file_lower.endswith(('.pcap', '.pcapng'))
    
    # The run directory is now passed as an argument
    run_dir = args.run_dir
    os.makedirs(run_dir, exist_ok=True) # Ensure it exists, though GUI should have created it

    if is_hprof and not args.mat_launcher_path: print("ERROR: --mat-launcher-path is required for .hprof analysis.", file=sys.stderr); sys.exit(1)
    if is_pcap and not args.tshark_path: print("ERROR: --tshark-path is required for pcap analysis.", file=sys.stderr); sys.exit(1)

    try: llm_parameters = json.loads(args.llm_params)
    except (json.JSONDecodeError, ValueError) as e: print(f"ERROR: Invalid JSON for --llm-params: {e}", flush=True); llm_parameters = {}

    log_monitor_error(f"Monitor run. CWD:{os.getcwd()}. Args:{args}")
    
    if not check_ollama_model_availability(args.model, args.ollama_cmd): print(f"Model '{args.model}' unavailable. Aborting.", flush=True); sys.exit(1)
    if not os.path.isfile(args.input_file): print(f"Input file not found: '{args.input_file}'.", flush=True); log_monitor_error(f"Input file FNF: {args.input_file}"); sys.exit(1)

    base_name = os.path.splitext(os.path.basename(args.input_file))[0]
    
    metadata = { 
        "input_file": os.path.basename(args.input_file),
        "analysis_type": "hprof" if is_hprof else "threaddump" if is_txt else "pcap" if is_pcap else "unknown",
        "analysis_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model_used": args.model, "ollama_executable_used": args.ollama_cmd, 
        "mat_memory_mb_used": args.mat_memory if is_hprof else "N/A", 
        "mat_report_arg_used": args.mat_report_arg if is_hprof else "N/A", 
        "prompt_template_used": args.prompt or "Default", "llm_parameters_used": llm_parameters, 
        "status": "started", "user_status": "pending",
        "llm_generated_tags": []
    }
    save_run_metadata(run_dir, metadata)

    mat_summary, thread_dump, tshark_summary, md_content_header = "N/A", "N/A", "N/A", ""

    if is_hprof:
        print("--- Starting HPROF Analysis ---")
        try: 
            generate_mat_report(args.input_file, run_dir, base_name, args.mat_launcher_path, args.mat_memory, args.mat_report_arg)
            unzip_mat_zip(run_dir, base_name, args.mat_report_arg)
            
            # Find the .threads file which might be in a subdirectory after unzipping
            threads_path = next((os.path.join(root, f) for root, _, files in os.walk(run_dir) for f in files if f.lower().endswith((".threads", "_threads.txt"))), None)

            if threads_path:
                thread_dump = extract_threads_file_content(threads_path)
            else:
                print("Warning: No .threads file found in the MAT output.")

            mat_summary = extract_mat_suspect_text(run_dir)
            md_content_header = f"### Thread Dump Details from HPROF:\n```text\n{thread_dump or 'Not available.'}\n```\n\n"
        except Exception as e: 
            print(f"MAT analysis failed: {e}", flush=True); metadata["status"] = "failed_mat"; save_run_metadata(run_dir, metadata); sys.exit(1)
    
    elif is_txt:
        print("--- Starting Thread Dump Analysis ---")
        try:
            # The .txt file is already in the run_dir, passed as input_file
            thread_dump = extract_threads_file_content(args.input_file)
            md_content_header = f"### Full Thread Dump:\n```text\n{thread_dump or 'Not available.'}\n```\n\n"
        except Exception as e:
            print(f"Failed to read thread dump file: {e}", flush=True); metadata["status"] = "failed_read_input"; save_run_metadata(run_dir, metadata); sys.exit(1)

    elif is_pcap:
        print("--- Starting Wireshark (tshark) Analysis ---")
        task_ids = [task.strip() for task in args.pcap_tasks.split(',')]
        summaries = []
        try:
            # The pcap file is already in the run_dir, passed as input_file
            for task_id in task_ids:
                summary = run_tshark_task(args.input_file, args.tshark_path, task_id)
                summaries.append(summary)
            tshark_summary = "\n".join(summaries)
            with open(os.path.join(run_dir, f"{base_name}_tshark_summary.txt"), "w", encoding="utf-8") as f_out: f_out.write(tshark_summary)
            md_content_header = f"### tshark Analysis Output:\n```text\n{tshark_summary or 'Not available.'}\n```\n\n"
        except Exception as e:
            print(f"tshark analysis failed: {e}", flush=True); metadata["status"] = "failed_tshark"; save_run_metadata(run_dir, metadata); sys.exit(1)

    prompt_txt = (args.prompt or "Default prompt...").format(
        thread_dump_details=thread_dump or "Not available.",
        mat_summary=mat_summary or "Not available.",
        tshark_summary=tshark_summary or "Not available."
    )
    
    llm_result = ask_ollama_model(prompt_txt, args.model, args.ollama_cmd, llm_parameters) 
    
    llm_tags = []
    if llm_result:
        tag_line_match = re.search(r"^TAGS:(.*)$", llm_result, re.MULTILINE | re.IGNORECASE)
        if tag_line_match:
            llm_tags = [tag.strip() for tag in tag_line_match.group(1).split(',') if tag.strip()]
            llm_result = llm_result.replace(tag_line_match.group(0), "").strip()
    
    metadata["llm_generated_tags"] = llm_tags

    if not llm_result:
        print("Ollama analysis failed.", flush=True); metadata["status"] = "failed_ollama_analysis"
        save_run_metadata(run_dir, metadata); sys.exit(1)

    md_name = f"{base_name}_analysis_{args.model.replace(':','_')}.md"; md_path = os.path.join(run_dir, md_name)
    try:
        with open(md_path, "w", encoding="utf-8") as f: 
            f.write(f"# Analysis Report for {os.path.basename(args.input_file)}\n\n")
            f.write(f"* **Model Used:** {args.model}\n")
            if is_hprof: f.write(f"* **MAT Report Type:** {args.mat_report_arg}\n")
            f.write(f"* **Timestamp (UTC):** {metadata['analysis_timestamp_utc']}\n\n")
            f.write(f"## LLM Parameters Used\n```json\n{json.dumps(llm_parameters, indent=2)}\n```\n\n")
            f.write(md_content_header)
            f.write(f"### LLM Analysis:\n{llm_result}")
        metadata.update({"llm_analysis_file": md_name, "status": "completed_ok"})
    except Exception as e: print(f"Err writing MD: {e}", flush=True); metadata["status"] = "failed_writing_analysis"
    
    save_run_metadata(run_dir, metadata)
    print(f"--- Analysis Complete. Results are in {run_dir} ---")
    sys.exit(0 if metadata["status"] == "completed_ok" else 1)

if __name__ == "__main__":
    try: main(None) 
    except SystemExit as e: sys.exit(e.code)
    except Exception: tb_str = traceback.format_exc(); print(f"UNHANDLED MONITOR ERR:\n{tb_str}", flush=True); log_monitor_error(f"UNHANDLED MONITOR ERR:\n{tb_str}"); sys.exit(2)