#!/usr/bin/env python3
# Filename: dashboard.py
from flask import (Flask, render_template, send_from_directory, abort, url_for,
                   jsonify, request, Response, session, redirect)
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import run_simple
from werkzeug.wrappers import Response as WsgiResponse
from xhtml2pdf import pisa
from io import BytesIO
from bs4 import BeautifulSoup
import os
import markdown
import re
import traceback
from datetime import datetime, timezone 
import sys
import json 
import shutil 
import requests
from pathlib import Path
import threading
import time

import ollama_client

app = Flask(__name__)
app.secret_key = os.getenv("DASHBOARD_SECRET_KEY", "change_me")

AUTH_USERNAME = os.getenv("DASHBOARD_USERNAME")
AUTH_PASSWORD = os.getenv("DASHBOARD_PASSWORD")

OLLAMA_MODEL_DISPLAY_FALLBACK = "Unknown Model"
USER_STATUS_PENDING = "pending"
USER_STATUS_RESOLVED = "resolved"

DASHBOARD_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__)) 
CONFIG_FILE_PATH_DASHBOARD = os.path.join(DASHBOARD_PROJECT_ROOT, "config.json")
RESULTAT_DIR_DASHBOARD = os.path.join(os.getcwd(), "Resultat") 
DASHBOARD_LOG_FILE = os.path.join(os.getcwd(), "dashboard_log.txt")
app.config["TOKEN_AUTH"] = False
app.config["READ_ONLY_MODE"] = False

capture_thread = None
capture_stop_event = threading.Event()
capture_state = {
    "status": "idle",
    "message": "Idle",
    "run_name": None,
    "output_file": None,
    "duration": 0,
    "start_time": 0,
}
capture_obj = None


@app.before_request
def require_login():
    """Require login if credentials are set via environment variables."""
    if app.config.get("TOKEN_AUTH"):
        return
    if AUTH_USERNAME and AUTH_PASSWORD:
        if request.endpoint not in {"login", "static"} and not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))


@app.before_request
def enforce_read_only():
    if app.config.get("READ_ONLY_MODE") and request.method not in {"GET", "HEAD"}:
        abort(405)


@app.route("/login", methods=["GET", "POST"])
def login():
    if not (AUTH_USERNAME and AUTH_PASSWORD):
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        if (request.form.get("username") == AUTH_USERNAME and
                request.form.get("password") == AUTH_PASSWORD):
            session["logged_in"] = True
            next_url = request.args.get("next") or url_for("index")
            return redirect(next_url)
        error = "Invalid credentials"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))

def get_config():
    """Loads the entire config file."""
    try:
        with open(CONFIG_FILE_PATH_DASHBOARD, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log_dashboard_error(f"Could not load config.json: {e}")
        return {}

def get_llm_parameters_from_config():
    ultimate_default_llm_params = { 
        "temperature": 0.7, "num_ctx": 4096, "top_k": 40, "top_p": 0.9, "seed": 0, "stop": [],
        "num_predict": 1536 
    }
    ultimate_default_model = "gemma3:1b" 

    params_to_return = ultimate_default_llm_params.copy()
    params_to_return["default_ollama_model_for_dashboard"] = ultimate_default_model

    config_settings = get_config()
    if config_settings:
        params_to_return["default_ollama_model_for_dashboard"] = config_settings.get("default_ollama_model", ultimate_default_model)
        loaded_llm_specific_params = config_settings.get("llm_parameters", {})
        params_to_return.update(loaded_llm_specific_params)

    return params_to_return


def ensure_resultat_dir():
    if not os.path.isdir(RESULTAT_DIR_DASHBOARD):
        try: os.makedirs(RESULTAT_DIR_DASHBOARD)
        except OSError as e: print(f"ERROR: Create Resultat dir fail: {e}.", file=sys.stderr, flush=True); sys.exit(1)

def _hexdump(buf: bytes, width: int = 16) -> str:
    lines = []
    for i in range(0, len(buf), width):
        chunk = buf[i:i+width]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:08x}  {hex_part:<{width*3}} {ascii_part}")
    return "\n".join(lines)

def log_dashboard_error(message):
    print(f"DASHBOARD_ERR: [{datetime.now()}] {message}", file=sys.stderr, flush=True)
    try:
        with open(DASHBOARD_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
            exc_type, exc_value, exc_tb = sys.exc_info()
            if exc_type is not None: f.write(traceback.format_exc() + "\n")
    except Exception as e: print(f"CRIT_DASHBOARD_LOG_FAIL: {e}", file=sys.stderr, flush=True)


def list_runs_with_status():
    """Yield basic information for each run in the Resultat directory."""
    ensure_resultat_dir()
    try:
        with os.scandir(RESULTAT_DIR_DASHBOARD) as it:
            run_dirs = [entry for entry in it if entry.is_dir()]

        for entry in sorted(run_dirs, key=lambda e: e.stat().st_mtime, reverse=True):
            status = USER_STATUS_PENDING
            tags = []
            metadata_path = os.path.join(entry.path, "run_metadata.json")
            if os.path.isfile(metadata_path):
                try:
                    with open(metadata_path, "r", encoding="utf-8") as f_meta:
                        metadata = json.load(f_meta)
                    status = metadata.get("user_status", USER_STATUS_PENDING)
                    tags = metadata.get("llm_generated_tags", [])
                except Exception:
                    pass
            yield {"name": entry.name, "user_status": status, "tags": tags}
    except Exception as e:
        log_dashboard_error(f"Error reading Resultat dir or metadata: {e}")
        raise

@app.route("/")
def index():
    try:
        runs_with_status = list(list_runs_with_status())
    except Exception as e:
        log_dashboard_error(f"Index: {e}")
        runs_with_status = []
    return render_template("index.html", runs_with_status=runs_with_status)


@app.route("/api/runs")
def get_runs_api():
    try:
        runs_with_status = list(list_runs_with_status())
    except Exception as e:
        log_dashboard_error(f"API Err read Resultat: {e}")
        return jsonify({"error": str(e)}), 500
    return jsonify(runs_with_status)




def _capture_worker(interface, duration):
    """Background worker that performs packet capture using pyshark."""
    global capture_obj, capture_thread, capture_state
    import pyshark  # Imported lazily to avoid import overhead when unused
    ensure_resultat_dir()
    run_name = f"capture_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    run_dir = os.path.join(RESULTAT_DIR_DASHBOARD, run_name)
    os.makedirs(run_dir, exist_ok=True)
    output_file = os.path.join(run_dir, "capture.pcapng")
    capture_state.update({
        "status": "running",
        "message": "Capture in progress",
        "run_name": run_name,
        "output_file": output_file,
        "duration": duration,
        "start_time": time.time(),
    })
    try:
        capture_obj = pyshark.LiveCapture(
            interface=interface,
            custom_parameters=['-w', output_file]
        )
        capture_obj.sniff(timeout=duration)
        capture_obj.close()
        if capture_stop_event.is_set():
            capture_state.update({"status": "stopped", "message": "Capture stopped"})
            if os.path.exists(output_file):
                try:
                    os.remove(output_file)
                except OSError:
                    pass
        else:
            capture_state.update({"status": "finished", "message": f"Capture saved to {output_file}"})
    except Exception as e:  # pragma: no cover - capture errors not under test
        capture_state.update({"status": "error", "message": str(e)})
    finally:
        capture_obj = None
        capture_stop_event.clear()
        capture_thread = None


@app.route("/api/capture", methods=["GET", "POST"])
def api_capture():
    """API endpoint to control live packet captures."""
    global capture_thread, capture_obj
    if request.method == "POST":
        if app.config.get("READ_ONLY_MODE"):
            return jsonify({"status": "error", "message": "Read-only mode"}), 405
        data = request.get_json() or {}
        action = data.get("action")
        if action == "start":
            if capture_thread and capture_thread.is_alive():
                return jsonify({"status": "error", "message": "Capture already running"}), 400
            interface = data.get("interface", "any")
            duration = int(data.get("duration", 30))
            capture_stop_event.clear()
            capture_thread = threading.Thread(
                target=_capture_worker,
                args=(interface, duration),
                daemon=True,
            )
            capture_thread.start()
            return jsonify({"status": "started"})
        elif action == "stop":
            if capture_thread and capture_thread.is_alive():
                capture_stop_event.set()
                if capture_obj:
                    try:
                        capture_obj.close()
                    except Exception:
                        pass
                return jsonify({"status": "stopping"})
            return jsonify({"status": "error", "message": "No capture running"}), 400
        return jsonify({"status": "error", "message": "Invalid action"}), 400

    # GET: return capture status
    state = capture_state.copy()
    if state.get("status") == "running":
        elapsed = time.time() - state.get("start_time", 0)
        remaining = max(0, int(state.get("duration", 0) - elapsed))
        state["remaining"] = remaining
    return jsonify(state)


@app.route("/capture")
def capture_page():
    """Serve simple page to control live packet captures."""
    return render_template("capture.html")


def _load_run_data_common(run_dir_path, run_name_for_log):
    data = {
        "name": run_name_for_log,
        "model_used": OLLAMA_MODEL_DISPLAY_FALLBACK,
        "timestamp": "N/A",
        "analysis_type": "unknown",
        "hprof_source": "N/A",
        "mat_memory_setting": "N/A",
        "mat_report_type": "N/A",
        "llm_analysis_html": "<p><em>Analysis N/A</em></p>",
        "metadata_error": None,
        "md_error": None,
        "raw_md_snippet_on_load": "N/A",
        "md_filename_processed": None,
        "user_status": USER_STATUS_PENDING,
        "raw_llm_analysis_text": None,
        "raw_diagnostic_text": None,
        "raw_oom_trace_text": None,
        "llm_generated_tags": [],
        "llm_params_json": "{}",
        "user_notes": "",
        "mat_report_entry_file": None,
        "mat_problem_suspect_html": "<p><em>MAT report not available or not applicable.</em></p>",
        "mat_overview_pie_chart_url": None,
    }
    metadata_path = os.path.join(run_dir_path, "run_metadata.json")
    if os.path.isfile(metadata_path):
        try:
            with open(metadata_path, "r", encoding="utf-8") as f_meta:
                metadata = json.loads(f_meta.read()) 
            data["model_used"] = metadata.get("model_used", OLLAMA_MODEL_DISPLAY_FALLBACK)
            ts_iso = metadata.get("analysis_timestamp_utc", "N/A")
            if ts_iso != "N/A" and ts_iso: 
                 try: data["timestamp"] = datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S UTC")
                 except ValueError: data["timestamp"] = ts_iso 
            data["hprof_source"] = metadata.get("input_file", "N/A")
            data["analysis_type"] = metadata.get("analysis_type", "unknown")
            data["mat_memory_setting"] = metadata.get("mat_memory_mb_used", "N/A") 
            data["mat_report_type"] = metadata.get("mat_report_arg_used", "N/A")
            data["user_status"] = metadata.get("user_status", USER_STATUS_PENDING)
            data["llm_generated_tags"] = metadata.get("llm_generated_tags", [])
            data["llm_params_json"] = json.dumps(metadata.get("llm_parameters_used", {}), indent=4)
            data["user_notes"] = metadata.get("user_notes", "")
        except Exception as e: log_dashboard_error(f"Err parsing metadata.json for {run_name_for_log}: {e}"); data["metadata_error"] = f"Error parsing: {e}"
    else: data["metadata_error"] = "run_metadata.json not found"

    temp_md_fn = None
    try: 
        files_in_run_dir = os.listdir(run_dir_path)

        # Attempt to locate MAT report entry (index.html)
        for root_dir, _, files in os.walk(run_dir_path):
            if 'index.html' in files:
                rel_path = os.path.relpath(os.path.join(root_dir, 'index.html'), run_dir_path).replace('\\', '/')
                data['mat_report_entry_file'] = rel_path
                break

        if data['mat_report_entry_file']:
            try:
                mat_full_path = os.path.join(run_dir_path, data['mat_report_entry_file'])
                with open(mat_full_path, 'r', encoding='utf-8', errors='ignore') as f_mat:
                    soup = BeautifulSoup(f_mat.read(), 'lxml')

                report_type = data.get('mat_report_type', '').lower()
                if 'suspects' in report_type:
                    h_suspect = soup.find(lambda t: t.name in ('h2', 'h3') and 'Problem Suspect 1' in t.get_text())
                    if h_suspect:
                        detail_div = h_suspect.find_next_sibling('div', class_='details') or h_suspect.find_next_sibling()
                        if detail_div:
                            for tag in detail_div.find_all(('a', 'img')):
                                attr = 'href' if tag.name == 'a' else 'src'
                                if tag.has_attr(attr) and not tag[attr].startswith(('http', '//', 'data:')):
                                    asset_path = Path(os.path.dirname(data['mat_report_entry_file'])) / tag[attr]
                                    clean_fn = os.path.normpath(asset_path).replace('\\', '/')
                                    tag[attr] = f"/run/{run_name_for_log}/{clean_fn}" if not clean_fn.startswith('../') else '#'
                            data['mat_problem_suspect_html'] = detail_div.prettify()
                else:
                    data['mat_problem_suspect_html'] = (
                        f"<p><em>Displaying '{report_type}' MAT report. "
                        f"<a href='/run/{run_name_for_log}/{data['mat_report_entry_file']}' target='_blank'>Open full report.</a></em></p>"
                    )

                pie_img = soup.find('img', src=lambda s: s and 'chart' in s.lower() and s.lower().endswith('.png'))
                if pie_img and pie_img.has_attr('src'):
                    pie_path = Path(os.path.dirname(data['mat_report_entry_file'])) / pie_img['src']
                    pie_fn = os.path.normpath(pie_path).replace('\\', '/')
                    if os.path.isfile(os.path.join(run_dir_path, pie_fn)):
                        data['mat_overview_pie_chart_url'] = f"/run/{run_name_for_log}/{pie_fn}"
            except Exception as e_mat:
                log_dashboard_error(f"Err parsing MAT HTML for {run_name_for_log}: {e_mat}")

        # Prioritize .md files that contain 'analysis'
        md_files = [f for f in files_in_run_dir if f.lower().endswith(".md")]
        analysis_md_files = [f for f in md_files if 'analysis' in f.lower()]
        
        if analysis_md_files:
            temp_md_fn = sorted(analysis_md_files)[0]
        elif md_files:
            temp_md_fn = sorted(md_files)[0]
            
        if temp_md_fn:
            data["md_filename_processed"] = temp_md_fn
            md_file_path = os.path.join(run_dir_path, temp_md_fn)
            if os.path.isfile(md_file_path):
                with open(md_file_path, "r", encoding="utf-8") as f_md: md_content = f_md.read()
                
                main_analysis_content = md_content
                analysis_section_match = re.search(r"(### LLM Analysis:.*)", md_content, re.DOTALL)
                if analysis_section_match:
                    analysis_text = analysis_section_match.group(1).split("### LLM Analysis:",1)[1].strip()
                    data["raw_llm_analysis_text"] = analysis_text
                    data["llm_analysis_html"] = markdown.markdown(analysis_text, extensions=['fenced_code','tables', 'nl2br'])
                else:
                    data["raw_llm_analysis_text"] = main_analysis_content
                    data["llm_analysis_html"] = markdown.markdown(main_analysis_content, extensions=['fenced_code','tables', 'nl2br'])

                diag_data_match = re.search(r"### (?:Full Thread Dump|Thread Dump Details from HPROF|tshark Analysis Output):\n```text\n(.*?)\n```", md_content, re.DOTALL)
                if diag_data_match:
                    data["raw_diagnostic_text"] = diag_data_match.group(1).strip()

                oom_match = re.search(r"###\s*Detected OutOfMemoryError Trace.*?(?:```.*?\n(.*?)\n```|\n(.*?)(?=\n###|$))", md_content, re.DOTALL | re.IGNORECASE)
                if oom_match:
                    data["raw_oom_trace_text"] = (oom_match.group(1) or oom_match.group(2)).strip()
                    if not data["raw_diagnostic_text"]:
                        data["raw_diagnostic_text"] = data["raw_oom_trace_text"]
            else: data["llm_analysis_html"] = "<p><em>MD file path invalid.</em></p>"
        else: data["llm_analysis_html"] = "<p><em>No analysis MD file found.</em></p>"
    except Exception as e: log_dashboard_error(f"Err processing MD for {run_name_for_log}: {e}"); data["md_error"] = f"Err MD: {e}"; data["llm_analysis_html"] = f"<p><em>Err loading MD: {e}</em></p>"
    
    # Fallback to find OOM trace if not in markdown
    if not data["raw_oom_trace_text"]:
        try:
            trace_fn = next(
                (
                    f
                    for f in os.listdir(run_dir_path)
                    if f.lower().endswith('.threads')
                    or f.lower() == 'trace_used.txt'
                    or f.lower().endswith('_llm_failed.txt')
                ),
                None,
            )
            if trace_fn:
                with open(os.path.join(run_dir_path, trace_fn), 'r', encoding='utf-8', errors='ignore') as f_trace:
                    data['raw_oom_trace_text'] = f_trace.read().strip()
        except Exception as e_trace:
            log_dashboard_error(f"Fallback: Error reading OOM trace for {run_name_for_log}: {e_trace}")

    if data["raw_oom_trace_text"] and not data["raw_diagnostic_text"]:
        data["raw_diagnostic_text"] = data["raw_oom_trace_text"]

    # Fallback to find general diagnostic data if still missing
    if not data["raw_diagnostic_text"]:
        try:
            trace_fn = next(
                (
                    f
                    for f in os.listdir(run_dir_path)
                    if f.lower().endswith('_tshark_summary.txt')
                    or f.lower().endswith('.txt')
                ),
                None,
            )
            if trace_fn:
                with open(os.path.join(run_dir_path, trace_fn), 'r', encoding='utf-8', errors='ignore') as f_trace:
                    data["raw_diagnostic_text"] = f_trace.read().strip()
        except Exception as e_trace:
            log_dashboard_error(f"Fallback: Error reading diagnostic file for {run_name_for_log}: {e_trace}")
    # Provide a small preview of packet capture data for pcap analyses
    if data["analysis_type"] == "pcap":
        try:
            pcap_fn = next((f for f in os.listdir(run_dir_path) if f.lower().endswith((".pcap", ".pcapng"))), None)
            if pcap_fn:
                sample_path = os.path.join(run_dir_path, pcap_fn)
                with open(sample_path, "rb") as f_pcap:
                    sample_bytes = f_pcap.read(256)

                data["pcap_sample"] = _hexdump(sample_bytes)
        except Exception as e_pcap:
            log_dashboard_error(f"Error extracting pcap preview for {run_name_for_log}: {e_pcap}")

    if not data.get("raw_thread_dump_text"):
        data["raw_thread_dump_text"] = data.get("raw_oom_trace_text") or data.get("raw_diagnostic_text")

    return data


@app.route("/run/<run>/")
def view_run(run):
    ensure_resultat_dir(); 
    if ".." in run or "/" in run or "\\" in run: log_dashboard_error(f"Path traversal: {run}"); abort(403)
    run_dir_path = os.path.join(RESULTAT_DIR_DASHBOARD, run)
    if not os.path.isdir(run_dir_path): log_dashboard_error(f"Run dir FNF: {run_dir_path}"); abort(404)
    run_info = _load_run_data_common(run_dir_path, run)

    mat_report_entry_file = run_info.get("mat_report_entry_file")
    mat_suspect_html = run_info.get("mat_problem_suspect_html")
    mat_pie_src = run_info.get("mat_overview_pie_chart_url")

    mat_idx_link_txt = "MAT Report (Not Found)"
    mat_toc_link_txt = "MAT TOC (Not Found)"
    mat_toc_entries = []
    toc_relpaths = set()
    mat_extra_index_entries = []

    if mat_report_entry_file:
        mat_report_full_path = os.path.join(run_dir_path, mat_report_entry_file)
        mat_idx_link_txt = f"MAT Report ({os.path.basename(mat_report_entry_file)})"

        mat_toc_path = os.path.join(os.path.dirname(mat_report_full_path), "toc.html")
        if os.path.isfile(mat_toc_path):
            mat_toc_link_txt = "MAT Table of Contents"
            try:
                with open(mat_toc_path, "r", encoding="utf-8", errors="ignore") as f_toc:
                    toc_soup = BeautifulSoup(f_toc.read(), "lxml")
                for a in toc_soup.find_all("a", href=True):
                    href = a["href"]
                    text = a.get_text(strip=True) or href
                    if href.startswith(("#", "javascript:")):
                        continue
                    asset_path_from_toc = Path(os.path.dirname(mat_report_entry_file)) / href
                    clean_fn = os.path.normpath(asset_path_from_toc).replace("\\", "/")
                    if clean_fn.startswith("../"):
                        continue
                    mat_toc_entries.append({
                        "text": text,
                        "url": url_for("get_file_from_run", run=run, filename=clean_fn)
                    })

                    toc_relpaths.add(clean_fn)
            except Exception as e:
                log_dashboard_error(f"Err parsing MAT TOC for {run}: {e}")

        # Gather additional MAT index files not referenced in toc.html
        try:
            mat_root = os.path.dirname(mat_report_entry_file)
            for root_dir, _, files in os.walk(os.path.join(run_dir_path, mat_root)):
                for fname in files:
                    lower = fname.lower()
                    if lower.startswith("index") and lower.endswith((".html", ".htm")):
                        rel_path = os.path.relpath(os.path.join(root_dir, fname), run_dir_path).replace("\\", "/")
                        if (rel_path == mat_report_entry_file or rel_path.endswith("toc.html") or rel_path in toc_relpaths):
                            continue
                        mat_extra_index_entries.append({
                            "text": rel_path,
                            "url": url_for("get_file_from_run", run=run, filename=rel_path)
                        })
        except Exception as e:
            log_dashboard_error(f"Err listing MAT index files for {run}: {e}")

    other_files = []
    viewable_files = []
    try:
        md_name_only = os.path.basename(run_info["md_filename_processed"]) if run_info.get("md_filename_processed") else ""

        excluded_files = {"run_metadata.json", md_name_only}
        if mat_report_entry_file:
            excluded_files.add(mat_report_entry_file)
            excluded_files.add(mat_report_entry_file.replace("index.html", "toc.html"))
        excluded_files.update(toc_relpaths)
        excluded_files.update(entry["text"] for entry in mat_extra_index_entries)

        for root_dir, _, files in os.walk(run_dir_path):
            for f in files:
                rel_path = os.path.relpath(os.path.join(root_dir, f), run_dir_path).replace("\\", "/")
                if rel_path in excluded_files or f in excluded_files:
                    continue
                other_files.append(rel_path)

        other_files = sorted(other_files)
        viewable_files = list(other_files)

    except Exception as e:
        log_dashboard_error(f"Err listing files for {run}: {e}")
        traceback.print_exc(file=sys.stderr)

    config_data = get_config()
    prompts_for_template = config_data.get("saved_prompts", [])
    ollama_models_available = []
    try:
        # Fetch available ollama models for the re-evaluate modal
        api_url = ollama_client.get_ollama_api_base_url() + "/api/tags"
        response = requests.get(api_url, timeout=5)
        response.raise_for_status()
        ollama_models_available = [m.get('name') for m in response.json().get('models', [])]
    except Exception as e:
        log_dashboard_error(f"Could not fetch ollama models for re-evaluation: {e}")

    return render_template("view_run.html", 
        run_name=run, 
        hprof_source=run_info.get("hprof_source"),
        run_time=run_info.get("timestamp"), 
        mat_memory_setting=run_info.get("mat_memory_setting"),
        model_used=run_info.get("model_used"),
        llm_analysis_html=run_info.get("llm_analysis_html"),
        oom_trace_details=run_info.get("raw_oom_trace_text", "N/A"),
        pcap_sample=run_info.get("pcap_sample"),
        mat_problem_suspect_html=mat_suspect_html,
        mat_overview_pie_chart_url=mat_pie_src,
        mat_report_index_link_text=mat_idx_link_txt,
        mat_report_toc_link_text=mat_toc_link_txt,
        mat_report_entry_file=mat_report_entry_file,
        mat_toc_entries=mat_toc_entries,

        mat_index_files=mat_extra_index_entries,
        other_run_files=other_files,
        viewable_run_files=viewable_files,
        mat_report_type_used=run_info.get("mat_report_type"),
        user_status=run_info.get("user_status"),

        llm_tags=run_info.get("llm_generated_tags", []),
        llm_params_json=run_info.get("llm_params_json", "{}"),
        user_notes=run_info.get("user_notes", ""),
        default_llm_params=get_llm_parameters_from_config(),
        initial_llm_analysis_text_for_chat=run_info.get("raw_llm_analysis_text", None),
        initial_diagnostic_text_for_chat=run_info.get("raw_oom_trace_text", run_info.get("raw_diagnostic_text", None)),
        saved_prompts=prompts_for_template,
        available_models=ollama_models_available
    )

@app.route("/api/run/<run>/export_pdf")
def export_run_pdf(run):
    if ".." in run or "/" in run or "\\" in run: abort(403)
    run_dir_path = os.path.join(RESULTAT_DIR_DASHBOARD, run)
    if not os.path.isdir(run_dir_path): abort(404)

    run_info = _load_run_data_common(run_dir_path, run)
    
    html_string = render_template("report_template.html", 
        run_name=run,
        hprof_source=run_info.get("hprof_source"),
        run_time=run_info.get("timestamp"),
        model_used=run_info.get("model_used"),
        llm_analysis_html=run_info.get("llm_analysis_html"),
        thread_dump_details=run_info.get("raw_oom_trace_text", run_info.get("raw_diagnostic_text", "N/A")),
        tags=run_info.get("llm_generated_tags", [])
    )
    
    pdf_buffer = BytesIO()
    pisa_status = pisa.CreatePDF(
        src=BytesIO(html_string.encode("UTF-8")),
        dest=pdf_buffer,
        encoding='UTF-8'
    )

    if pisa_status.err:
        log_dashboard_error(f"PDF generation failed for run {run}: {pisa_status.err}")
        return "PDF generation failed.", 500

    pdf_bytes = pdf_buffer.getvalue()
    pdf_buffer.close()
    
    return Response(pdf_bytes,
                   mimetype="application/pdf",
                   headers={"Content-disposition": f"attachment; filename={run}_report.pdf"})

@app.route("/run/<run>/<path:filename>")
def get_file_from_run(run, filename):
    ensure_resultat_dir();
    run_dir_abs = os.path.abspath(os.path.join(RESULTAT_DIR_DASHBOARD, run));
    file_abs = os.path.abspath(os.path.join(run_dir_abs, filename))
    
    # Security check to prevent path traversal
    if not file_abs.startswith(run_dir_abs):
        log_dashboard_error(f"Path traversal attempt blocked: Run='{run}', Filename='{filename}'")
        abort(403)
    
    if not os.path.exists(file_abs) or not os.path.isfile(file_abs):
        abort(404)
        
    return send_from_directory(run_dir_abs, filename)

@app.route("/run/<run>/preview/<path:filename>")
def preview_file_from_run(run, filename):
    ensure_resultat_dir()
    run_dir_abs = os.path.abspath(os.path.join(RESULTAT_DIR_DASHBOARD, run))
    file_abs = os.path.abspath(os.path.join(run_dir_abs, filename))

    if not file_abs.startswith(run_dir_abs):
        log_dashboard_error(f"Path traversal attempt blocked: Run='{run}', Filename='{filename}'")
        abort(403)

    if not os.path.exists(file_abs) or not os.path.isfile(file_abs):
        abort(404)

    text_exts = {".txt", ".log", ".html", ".htm", ".json", ".md", ".csv"}
    ext = os.path.splitext(filename.lower())[1]
    if ext in text_exts:
        return send_from_directory(run_dir_abs, filename)

    try:
        with open(file_abs, "rb") as f:
            content = f.read(64 * 1024)
        hexdumped = _hexdump(content)
        if os.path.getsize(file_abs) > len(content):
            hexdumped += f"\n... (truncated, total {os.path.getsize(file_abs)} bytes)"
        return Response(hexdumped, mimetype="text/plain")
    except Exception as e:
        log_dashboard_error(f"Error previewing file '{filename}' for run '{run}': {e}")
        abort(500)

@app.route("/compare")
def compare_runs():
    ensure_resultat_dir(); selected_run_names = request.args.getlist('run') 
    if not selected_run_names or len(selected_run_names) < 1: log_dashboard_error("Compare attempt with too few runs selected."); return "Please select at least one run to compare. <a href='/'>Back</a>", 400
    runs_data = []
    for run_name in selected_run_names:
        if ".." in run_name or "/" in run_name or "\\" in run_name: log_dashboard_error(f"Invalid run name in compare: {run_name}"); continue
        run_dir_path = os.path.join(RESULTAT_DIR_DASHBOARD, run_name)
        if not os.path.isdir(run_dir_path): log_dashboard_error(f"Compare: Run dir FNF: {run_dir_path}"); runs_data.append({"name": run_name, "error": f"Dir not found: {run_dir_path}"}); continue
        current_run_details = _load_run_data_common(run_dir_path, run_name)
        runs_data.append(current_run_details)
    return render_template("compare_runs.html", runs_to_compare=runs_data)

@app.route("/api/run/<run_name>/set_status", methods=["POST"])
def set_run_status(run_name):
    ensure_resultat_dir();
    if ".." in run_name or "/" in run_name or "\\" in run_name: abort(403)
    new_status = request.json.get("status")
    if new_status not in [USER_STATUS_PENDING, USER_STATUS_RESOLVED]: return jsonify({"success": False, "error": "Invalid status value"}), 400
    run_dir_path = os.path.join(RESULTAT_DIR_DASHBOARD, run_name); metadata_path = os.path.join(run_dir_path, "run_metadata.json")
    if not os.path.isdir(run_dir_path) or not os.path.isfile(metadata_path): return jsonify({"success": False, "error": "Run or metadata not found"}), 404
    try:
        with open(metadata_path, "r+", encoding="utf-8") as f:
            metadata = json.load(f); metadata["user_status"] = new_status; metadata["user_status_updated_utc"] = datetime.now(timezone.utc).isoformat()
            f.seek(0); json.dump(metadata, f, indent=4); f.truncate()
        log_dashboard_error(f"Run '{run_name}' status updated to '{new_status}'.")
        return jsonify({"success": True, "new_status": new_status})
    except Exception as e: log_dashboard_error(f"Error updating status for run '{run_name}': {e}"); return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/run/<run_name>/set_notes", methods=["POST"])
def set_run_notes(run_name):
    """Update user notes for a run."""
    ensure_resultat_dir()
    if ".." in run_name or "/" in run_name or "\\" in run_name:
        abort(403)
    notes = request.json.get("notes", "")
    run_dir_path = os.path.join(RESULTAT_DIR_DASHBOARD, run_name)
    metadata_path = os.path.join(run_dir_path, "run_metadata.json")
    if not os.path.isdir(run_dir_path) or not os.path.isfile(metadata_path):
        return jsonify({"success": False, "error": "Run or metadata not found"}), 404
    try:
        with open(metadata_path, "r+", encoding="utf-8") as f:
            metadata = json.load(f)
            metadata["user_notes"] = notes
            metadata["user_notes_updated_utc"] = datetime.now(timezone.utc).isoformat()
            f.seek(0)
            json.dump(metadata, f, indent=4)
            f.truncate()
        return jsonify({"success": True})
    except Exception as e:
        log_dashboard_error(f"Error updating notes for run '{run_name}': {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/run/<run_name>/delete", methods=["POST"])
def delete_run_folder(run_name):
    ensure_resultat_dir();
    if ".." in run_name or "/" in run_name or "\\" in run_name: abort(403)
    run_dir_path = os.path.join(RESULTAT_DIR_DASHBOARD, run_name)
    if not os.path.abspath(run_dir_path).startswith(os.path.abspath(RESULTAT_DIR_DASHBOARD) + os.sep): log_dashboard_error(f"CRITICAL: Delete folder outside Resultat: {run_dir_path}"); return jsonify({"success": False, "error": "Invalid path"}), 403
    if not os.path.isdir(run_dir_path): return jsonify({"success": False, "error": "Run directory not found"}), 404
    try: shutil.rmtree(run_dir_path); log_dashboard_error(f"Run '{run_name}' directory deleted: {run_dir_path}"); return jsonify({"success": True, "message": f"Run '{run_name}' deleted."})
    except Exception as e: log_dashboard_error(f"Error deleting run directory '{run_dir_path}': {e}"); return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/run/<run_name>/chat_interaction", methods=["POST"])
def chat_interaction(run_name):
    ensure_resultat_dir()
    if ".." in run_name or "/" in run_name or "\\" in run_name: abort(403)
    data = request.json; messages_history = data.get("history", []) 
    if not messages_history or messages_history[-1].get("role") != "user": return jsonify({"error": "Last message in history must be from user."}), 400
    
    global_llm_params_dict = get_llm_parameters_from_config() 
    model_to_use = global_llm_params_dict.get("default_ollama_model_for_dashboard", "gemma3:1b")
    
    # Check if a model was specified in the run's metadata and use it
    run_dir_path = os.path.join(RESULTAT_DIR_DASHBOARD, run_name)
    if os.path.isdir(run_dir_path):
        run_data = _load_run_data_common(run_dir_path, run_name) 
        if run_data.get("model_used") and run_data.get("model_used") != OLLAMA_MODEL_DISPLAY_FALLBACK:
            model_to_use = run_data.get("model_used")
            
    valid_ollama_options = {k: v for k, v in global_llm_params_dict.items() if k != "default_ollama_model_for_dashboard"}
    
    assistant_response_content, full_response_dict = ollama_client.ollama_api_chat(model_tag=model_to_use, messages_history=messages_history, llm_parameters=valid_ollama_options)
    if assistant_response_content is not None: return jsonify({"success": True, "response": assistant_response_content})
    else: error_detail = full_response_dict.get("error", "Unknown error from Ollama client during chat."); log_dashboard_error(f"Chat API error for {run_name} with model {model_to_use}: {error_detail} - Full Resp: {full_response_dict}"); return jsonify({"success": False, "error": error_detail}), 500

@app.route("/api/llm_compare_runs", methods=["POST"])
def llm_compare_runs_api():
    ensure_resultat_dir(); data = request.json
    runs_for_comparison = data.get("runs", []) 
    custom_question = data.get("custom_question", None)
    if not runs_for_comparison or len(runs_for_comparison) < 1 : 
        if not (custom_question and len(runs_for_comparison) == 1):
             return jsonify({"success": False, "error": "Not enough run data provided."}), 400
    context_parts = []; valid_runs_for_context = 0
    for i, run_detail in enumerate(runs_for_comparison):
        run_dir_path = os.path.join(RESULTAT_DIR_DASHBOARD, run_detail.get("name"))
        if not os.path.isdir(run_dir_path): log_dashboard_error(f"LLM Compare: Dir FNF for run {run_detail.get('name')}"); continue
        loaded_run_data = _load_run_data_common(run_dir_path, run_detail.get("name"))
        llm_analysis_text = loaded_run_data.get('raw_llm_analysis_text')
        diagnostic_text = loaded_run_data.get('raw_diagnostic_text')
        if (llm_analysis_text and llm_analysis_text.strip()) or (diagnostic_text and diagnostic_text.strip()):
            context_parts.append(f"\n--- Analysis for Run: {loaded_run_data.get('name', 'Unknown Run ' + str(i+1))} ---")
            context_parts.append(f"Input File: {loaded_run_data.get('hprof_source', 'N/A')}")
            context_parts.append(f"Model Used (original analysis): {loaded_run_data.get('model_used', 'N/A')}")
            context_parts.append(f"Analysis Type: {loaded_run_data.get('mat_report_type', 'N/A')}")
            if diagnostic_text and diagnostic_text.strip(): context_parts.append("Raw Diagnostic Data for this run:"); context_parts.append(f"```text\n{diagnostic_text}\n```")
            if llm_analysis_text and llm_analysis_text.strip(): context_parts.append("LLM Summary for this specific run:"); context_parts.append(llm_analysis_text)
            context_parts.append("--- End of Analysis for this Run ---\n"); valid_runs_for_context += 1
        else: log_dashboard_error(f"LLM Compare API: Skipping run '{run_detail.get('name')}' due to missing analysis and diagnostic text.")
    if valid_runs_for_context == 0: return jsonify({"success": False, "error": "No valid run data with analysis/trace text found."}), 400
    if not custom_question and valid_runs_for_context < 2: return jsonify({"success": False, "error": "Need at least two runs with content for default comparison."}), 400
    context_str = "\n".join(context_parts)
    if custom_question:
        final_prompt = f"You are an expert performance analyst. Given the following context from one or more analyses, please answer the user's question.\n\nContext:\n{context_str}\n\nUser's Question: {custom_question}\n\nYour Answer (use Markdown for formatting):"
    else:
        final_prompt = f"You are an expert performance analyst. Based on the following diagnostic data and LLM summaries from different analyses, please identify and list key similarities, differences, and recurring patterns. Focus on factual correlations in the provided data. Be concise and use Markdown for formatting.\n\nContext:\n{context_str}\n\nComparison Analysis (similarities, differences, patterns):"
    llm_params_from_config_file = get_llm_parameters_from_config()
    api_call_options = {k: v for k, v in llm_params_from_config_file.items() if k != "default_ollama_model_for_dashboard"}
    api_call_options["num_predict"] = api_call_options.get("num_predict", 1024); 
    if api_call_options["num_predict"] < 1024 : api_call_options["num_predict"] = 1024
    comparison_model = llm_params_from_config_file.get("default_ollama_model_for_dashboard", "gemma3:1b") 
    llm_comparison_text, response_details = ollama_client.ollama_api_generate(model_tag=comparison_model, prompt_text=final_prompt, llm_parameters=api_call_options )
    if llm_comparison_text: return jsonify({"success": True, "comparison_analysis": llm_comparison_text})
    else:
        error_msg = response_details.get("error", "LLM failed to generate comparison."); error_detail_content = response_details.get("message", "") 
        log_dashboard_error(f"LLM Comparison API error: {error_msg} - Details: {error_detail_content} - Full Resp: {response_details}")
        return jsonify({"success": False, "error": f"{error_msg} - {error_detail_content}"}), 500


@app.route("/api/run/<run_name>/re-evaluate-data", methods=["GET"])
def get_reevaluate_data(run_name):
    """Gathers all necessary data from a run folder for re-evaluation."""
    if ".." in run_name or "/" in run_name or "\\" in run_name: abort(403)
    run_dir = os.path.join(RESULTAT_DIR_DASHBOARD, run_name)
    if not os.path.isdir(run_dir):
        return jsonify({"success": False, "error": "Run directory not found."}), 404

    run_data = _load_run_data_common(run_dir, run_name)
    
    mat_summary = ""
    if "hprof" in run_data.get("analysis_type", ""):
        try:
            # Reuse the same logic from monitor.py to extract summary
            from monitor import extract_mat_suspect_text
            mat_summary = extract_mat_suspect_text(run_dir)
        except Exception as e:
            log_dashboard_error(f"Re-eval Data: Error parsing MAT summary for {run_name}: {e}")
            mat_summary = f"Error extracting MAT summary: {e}"

    diagnostic_text = run_data.get("raw_diagnostic_text", "")
    
    return jsonify({
        "success": True,
        "mat_summary": mat_summary or "Not available.",
        "diagnostic_text": diagnostic_text or "Not available.",
        "current_model": run_data.get("model_used", OLLAMA_MODEL_DISPLAY_FALLBACK)
    })

@app.route("/api/run/<run_name>/re-evaluate", methods=["POST"])
def reevaluate_run(run_name):
    if ".." in run_name or "/" in run_name or "\\" in run_name: abort(403)
    
    data = request.json
    new_prompt_name = data.get("prompt_name")
    new_prompt_template = data.get("prompt_template")
    model_to_use = data.get("model")
    override_params = data.get("llm_params", {})

    if not new_prompt_template or not model_to_use or not new_prompt_name:
        return jsonify({"success": False, "error": "A new prompt, template, and model are required."}), 400

    run_dir = os.path.join(RESULTAT_DIR_DASHBOARD, run_name)
    if not os.path.isdir(run_dir):
        return jsonify({"success": False, "error": "Run directory not found."}), 404

    # Gather all evidence from the run folder using the dedicated endpoint's logic
    run_data_response = get_reevaluate_data(run_name)
    if not run_data_response.is_json or not run_data_response.json.get("success"):
        return jsonify({"success": False, "error": "Failed to gather data for re-evaluation."}), 500
    
    run_context = run_data_response.json
    
    # Construct the final prompt
    final_prompt = new_prompt_template.format(
        mat_summary=run_context.get("mat_summary", "Not available."),
        thread_dump_details=run_context.get("diagnostic_text", "Not available."),
        tshark_summary=run_context.get("diagnostic_text", "Not available.")
    )
    
    # Call the LLM
    llm_params = get_llm_parameters_from_config()
    api_call_options = {k: v for k, v in llm_params.items() if k != "default_ollama_model_for_dashboard"}
    if isinstance(override_params, dict):
        api_call_options.update({k: v for k, v in override_params.items() if v is not None})
    new_analysis_text, response_details = ollama_client.ollama_api_generate(model_tag=model_to_use, prompt_text=final_prompt, llm_parameters=api_call_options)

    if not new_analysis_text:
        error = response_details.get("error", "LLM failed to generate a new analysis.")
        log_dashboard_error(f"Re-eval failed for {run_name}: {error}")
        return jsonify({"success": False, "error": error}), 500

    try:
        # Separate tags from the main body
        analysis_body = new_analysis_text
        new_tags = []
        tag_match = re.search(r"^TAGS:(.*)$", new_analysis_text, re.MULTILINE | re.IGNORECASE)
        if tag_match:
            new_tags = [tag.strip() for tag in tag_match.group(1).split(',') if tag.strip()]
            analysis_body = analysis_body.replace(tag_match.group(0), "").strip()

        # Update metadata.json
        metadata_path = os.path.join(run_dir, "run_metadata.json")
        with open(metadata_path, "r+") as f:
            metadata = json.load(f)
            metadata["llm_generated_tags"] = new_tags
            metadata["model_used"] = model_to_use
            metadata["prompt_template_used"] = new_prompt_template # Save the template used
            metadata["llm_parameters_used"] = api_call_options
            metadata["last_reevaluation_utc"] = datetime.now(timezone.utc).isoformat()
            
            f.seek(0)
            json.dump(metadata, f, indent=4)
            f.truncate()

        # Find and update analysis.md
        run_data_for_files = _load_run_data_common(run_dir, run_name)
        md_filename = run_data_for_files.get("md_filename_processed")
        if not md_filename:
            # If no MD file exists, create a new one
            base_name = metadata.get("input_file", "reeval").split('.')[0]
            md_filename = f"{base_name}_analysis_{model_to_use.replace(':','_')}.md"
            metadata["llm_analysis_file"] = md_filename
            save_run_metadata(run_dir, metadata)

        md_path = os.path.join(run_dir, md_filename)
        
        # Read the original MD content to preserve headers
        original_md_content = ""
        if os.path.exists(md_path):
            with open(md_path, "r", encoding="utf-8") as f_md:
                original_md_content = f_md.read()
        
        # Find the start of the old analysis section
        analysis_start_marker = "### LLM Analysis:"
        if analysis_start_marker in original_md_content:
            new_md_content = original_md_content.split(analysis_start_marker, 1)[0] + f"{analysis_start_marker}\n{analysis_body}"
        else: # If marker not found or it's a new file, append
            new_md_content = original_md_content + f"\n\n---\n### LLM Analysis (Re-evaluation):\n{analysis_body}"

        with open(md_path, "w", encoding="utf-8") as f_md:
            f_md.write(new_md_content)

        return jsonify({
            "success": True, 
            "new_analysis_html": markdown.markdown(analysis_body, extensions=['fenced_code','tables', 'nl2br']),
            "new_tags": new_tags,
            "new_model": model_to_use
        })

    except Exception as e:
        log_dashboard_error(f"Re-eval: Failed to update files for {run_name}: {e}")
        return jsonify({"success": False, "error": f"Failed to save new analysis: {e}"}), 500

def main(argv=None, *, port=5000, host="127.0.0.1", token=None):
    ensure_resultat_dir()

    if argv:
        i = 0
        while i < len(argv):

            arg = argv[i]
            if arg == "-p" and i + 1 < len(argv):
                i += 1
                try: port = int(argv[i])
                except ValueError: print("Invalid port [%r]" % argv[i], file=sys.stderr)
            elif arg == "-h" and i + 1 < len(argv):
                i += 1
                host = argv[i]
            elif arg == "--token" and i + 1 < len(argv):
                i += 1
                token = argv[i]
            elif arg.startswith("--host="): host = arg.split("=")[1]
            elif arg.startswith("--port="): port = int(arg.split("=")[1])
            elif arg == "--help": print("Usage: dashboard.py [-p port] [-h host] [--token T]"); return 1
            i += 1

    if token:
        app.config["TOKEN_AUTH"] = token
        def missing_model_html(start_response):
            start_response("404 Not Found", [('Content-Type', 'text/html')])
            return [b"<h1>Model not found</h1>"]
        dispatch_app = DispatcherMiddleware(missing_model_html, {
            "/": app
        })
        print(f"WebDashboard (auth) → http://{host}:{port}", flush=True)
        try:
            run_simple(host, port, dispatch_app, use_reloader=False)
        except OSError as e: print(f"Flask start fail: {e}"); return 1
        return 0

    print(f"Flask dashboard starting. Results: {RESULTAT_DIR_DASHBOARD} — URL: http://{host}:{port}/", flush=True)
    try: app.run(host=host, port=port)
    except OSError as e: print(f"Flask start fail: {e}"); log_dashboard_error(f"Flask start fail: {e}"); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))