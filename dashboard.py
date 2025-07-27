#!/usr/bin/env python3
# Filename: dashboard.py
from flask import Flask, render_template, send_from_directory, abort, url_for, jsonify, request, Response
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

import ollama_client 

app = Flask(__name__)

OLLAMA_MODEL_DISPLAY_FALLBACK = "Unknown Model"
USER_STATUS_PENDING = "pending"
USER_STATUS_RESOLVED = "resolved"

DASHBOARD_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__)) 
CONFIG_FILE_PATH_DASHBOARD = os.path.join(DASHBOARD_PROJECT_ROOT, "config.json")
RESULTAT_DIR_DASHBOARD = os.path.join(os.getcwd(), "Resultat") 
DASHBOARD_LOG_FILE = os.path.join(os.getcwd(), "dashboard_log.txt")

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

def log_dashboard_error(message):
    print(f"DASHBOARD_ERR: [{datetime.now()}] {message}", file=sys.stderr, flush=True)
    try:
        with open(DASHBOARD_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
            exc_type, exc_value, exc_tb = sys.exc_info()
            if exc_type is not None: f.write(traceback.format_exc() + "\n")
    except Exception as e: print(f"CRIT_DASHBOARD_LOG_FAIL: {e}", file=sys.stderr, flush=True)

@app.route("/")
def index(): 
    ensure_resultat_dir(); runs_with_status = []
    try:
        # Sort directories by modification time, newest first
        dirs = [d for d in os.listdir(RESULTAT_DIR_DASHBOARD) if os.path.isdir(os.path.join(RESULTAT_DIR_DASHBOARD, d))]
        run_names = sorted(dirs, key=lambda d: os.path.getmtime(os.path.join(RESULTAT_DIR_DASHBOARD, d)), reverse=True)

        for run_name in run_names:
            status = USER_STATUS_PENDING; tags = []
            metadata_path = os.path.join(RESULTAT_DIR_DASHBOARD, run_name, "run_metadata.json")
            if os.path.isfile(metadata_path):
                try:
                    with open(metadata_path, "r", encoding="utf-8") as f_meta: metadata = json.load(f_meta)
                    status = metadata.get("user_status", USER_STATUS_PENDING)
                    tags = metadata.get("llm_generated_tags", [])
                except Exception: pass 
            runs_with_status.append({"name": run_name, "user_status": status, "tags": tags})
    except Exception as e: log_dashboard_error(f"Index: Error reading Resultat dir or metadata: {e}")
    return render_template("index.html", runs_with_status=runs_with_status)


@app.route("/api/runs") 
def get_runs_api():
    ensure_resultat_dir(); runs_with_status = []
    try:
        # Sort directories by modification time, newest first
        dirs = [d for d in os.listdir(RESULTAT_DIR_DASHBOARD) if os.path.isdir(os.path.join(RESULTAT_DIR_DASHBOARD, d))]
        run_names = sorted(dirs, key=lambda d: os.path.getmtime(os.path.join(RESULTAT_DIR_DASHBOARD, d)), reverse=True)

        for run_name in run_names:
            status = USER_STATUS_PENDING; tags = []
            metadata_path = os.path.join(RESULTAT_DIR_DASHBOARD, run_name, "run_metadata.json")
            if os.path.isfile(metadata_path):
                try:
                    with open(metadata_path, "r", encoding="utf-8") as f_meta: metadata = json.load(f_meta)
                    status = metadata.get("user_status", USER_STATUS_PENDING)
                    tags = metadata.get("llm_generated_tags", [])
                except Exception: pass
            runs_with_status.append({"name": run_name, "user_status": status, "tags": tags})
    except Exception as e: log_dashboard_error(f"API Err read Resultat: {e}"); return jsonify({"error": str(e)}), 500
    return jsonify(runs_with_status)

def _load_run_data_common(run_dir_path, run_name_for_log):
    data = { "name": run_name_for_log, "model_used": OLLAMA_MODEL_DISPLAY_FALLBACK, "timestamp": "N/A", 
        "hprof_source": "N/A", "mat_memory_setting": "N/A", "mat_report_type": "N/A", 
        "llm_analysis_html": "<p><em>Analysis N/A</em></p>", "metadata_error": None, "md_error": None, 
        "raw_md_snippet_on_load": "N/A", "md_filename_processed": None, "user_status": USER_STATUS_PENDING,
        "raw_llm_analysis_text": None, "raw_diagnostic_text": None,
        "llm_generated_tags": [], "llm_params_json": "{}"
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
            data["mat_memory_setting"] = metadata.get("mat_memory_mb_used", "N/A") 
            data["mat_report_type"] = metadata.get("mat_report_arg_used", "N/A")
            data["user_status"] = metadata.get("user_status", USER_STATUS_PENDING)
            data["llm_generated_tags"] = metadata.get("llm_generated_tags", [])
            data["llm_params_json"] = json.dumps(metadata.get("llm_parameters_used", {}), indent=4)
        except Exception as e: log_dashboard_error(f"Err parsing metadata.json for {run_name_for_log}: {e}"); data["metadata_error"] = f"Error parsing: {e}"
    else: data["metadata_error"] = "run_metadata.json not found"

    temp_md_fn = None
    try: 
        files_in_run_dir = os.listdir(run_dir_path)
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
            else: data["llm_analysis_html"] = "<p><em>MD file path invalid.</em></p>"
        else: data["llm_analysis_html"] = "<p><em>No analysis MD file found.</em></p>"
    except Exception as e: log_dashboard_error(f"Err processing MD for {run_name_for_log}: {e}"); data["md_error"] = f"Err MD: {e}"; data["llm_analysis_html"] = f"<p><em>Err loading MD: {e}</em></p>"
    
    # Fallback to find raw data if not in markdown
    if not data["raw_diagnostic_text"]:
        try:
            # Check for explicitly generated summary files
            trace_fn = next((f for f in os.listdir(run_dir_path) if f.lower().endswith(("_tshark_summary.txt", ".threads"))), None) \
                       or next((f for f in os.listdir(run_dir_path) if f.lower().endswith(".txt") and not f.lower().endswith("_tshark_summary.txt")), None)

            if trace_fn:
                with open(os.path.join(run_dir_path, trace_fn), "r", encoding="utf-8", errors="ignore") as f_trace:
                    data["raw_diagnostic_text"] = f_trace.read().strip()
        except Exception as e_trace:
            log_dashboard_error(f"Fallback: Error reading diagnostic file for {run_name_for_log}: {e_trace}")
    return data


@app.route("/run/<run>/")
def view_run(run):
    ensure_resultat_dir(); 
    if ".." in run or "/" in run or "\\" in run: log_dashboard_error(f"Path traversal: {run}"); abort(403)
    run_dir_path = os.path.join(RESULTAT_DIR_DASHBOARD, run)
    if not os.path.isdir(run_dir_path): log_dashboard_error(f"Run dir FNF: {run_dir_path}"); abort(404)
    run_info = _load_run_data_common(run_dir_path, run)
    
    mat_suspect_html, mat_pie_src = "<p><em>MAT report not available or not applicable.</em></p>", None
    mat_report_entry_file = None

    # Find MAT report entry point, searching subdirectories
    for root, _, files in os.walk(run_dir_path):
        if 'index.html' in files:
            mat_report_entry_file = os.path.relpath(os.path.join(root, 'index.html'), run_dir_path).replace('\\', '/')
            break

    mat_idx_link_txt = "MAT Report (Not Found)"
    mat_toc_link_txt = "MAT TOC (Not Found)"
    
    if mat_report_entry_file:
        mat_report_full_path = os.path.join(run_dir_path, mat_report_entry_file)
        mat_idx_link_txt = f"MAT Report ({os.path.basename(mat_report_entry_file)})"
        
        mat_toc_path = os.path.join(os.path.dirname(mat_report_full_path), "toc.html")
        if os.path.isfile(mat_toc_path):
            mat_toc_link_txt = "MAT Table of Contents"

        try:
            with open(mat_report_full_path, "r", encoding="utf-8", errors="ignore") as f_mat_idx:
                soup = BeautifulSoup(f_mat_idx.read(), "lxml")
            
            report_type = run_info.get("mat_report_type", "").lower()
            if "suspects" in report_type:
                h_suspect = soup.find(lambda t: t.name in ("h2", "h3") and "Problem Suspect 1" in t.get_text())
                if h_suspect:
                    detail_div = h_suspect.find_next_sibling("div", class_="details") or h_suspect.find_next_sibling()
                    if detail_div:
                        for tag in detail_div.find_all(("a", "img")):
                            attr = "href" if tag.name == "a" else "src"
                            if tag.has_attr(attr) and not tag[attr].startswith(("http", "//", "data:")):
                                # Construct relative path from the main run dir to the asset
                                asset_path_from_report = Path(os.path.dirname(mat_report_entry_file)) / tag[attr]
                                clean_fn = os.path.normpath(asset_path_from_report).replace("\\", "/")
                                tag[attr] = url_for("get_file_from_run", run=run, filename=clean_fn) if not clean_fn.startswith("../") else "#"
                        mat_suspect_html = detail_div.prettify()
                else:
                    mat_suspect_html = "<p><em>Leak Suspects report parsed, but 'Problem Suspect 1' section not found.</em></p>"
            else:
                 mat_suspect_html = f"<p><em>Displaying '{report_type}' MAT report. <a href='{url_for('get_file_from_run', run=run, filename=mat_report_entry_file)}' target='_blank'>Open full report.</a></em></p>"

            pie_img = soup.find("img", src=lambda s: s and "chart" in s.lower() and s.lower().endswith(".png"))
            if pie_img and pie_img.has_attr("src"):
                pie_path_from_report = Path(os.path.dirname(mat_report_entry_file)) / pie_img['src']
                pie_fn = os.path.normpath(pie_path_from_report).replace("\\", "/")
                if os.path.isfile(os.path.join(run_dir_path, pie_fn)):
                    mat_pie_src = url_for("get_file_from_run", run=run, filename=pie_fn)
        except Exception as e:
            log_dashboard_error(f"Err parsing MAT HTML for {run}: {e}"); mat_suspect_html = f"<p><em>Error parsing MAT HTML: {e}</em></p>"
            
    other_files = []
    try:
        all_files_in_dir = os.listdir(run_dir_path)
        md_name_only = os.path.basename(run_info["md_filename_processed"]) if run_info.get("md_filename_processed") else ""
        
        # General exclusion list
        excluded_files = {"run_metadata.json", md_name_only}
        if mat_report_entry_file:
            excluded_files.add(os.path.basename(mat_report_entry_file))
            # Also exclude the toc.html that belongs to the main report
            if os.path.isfile(os.path.join(os.path.dirname(os.path.join(run_dir_path, mat_report_entry_file)), "toc.html")):
                 excluded_files.add("toc.html")
        
        other_files = sorted(f for f in all_files_in_dir if f.lower().endswith((".zip",".log",".txt",".threads",".md", ".pcapng", ".html")) and f not in excluded_files)

    except Exception as e: log_dashboard_error(f"Err listing files for {run}: {e}"); traceback.print_exc(file=sys.stderr)

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
        thread_dump_details=run_info.get("raw_diagnostic_text", "N/A"),
        mat_problem_suspect_html=mat_suspect_html,
        mat_overview_pie_chart_url=mat_pie_src, 
        mat_report_index_link_text=mat_idx_link_txt,
        mat_report_toc_link_text=mat_toc_link_txt,
        mat_report_entry_file=mat_report_entry_file, 
        other_run_files=other_files,
        mat_report_type_used=run_info.get("mat_report_type"), 
        user_status=run_info.get("user_status"),
        llm_tags=run_info.get("llm_generated_tags", []),
        llm_params_json=run_info.get("llm_params_json", "{}"),
        initial_llm_analysis_text_for_chat=run_info.get("raw_llm_analysis_text", None),
        initial_diagnostic_text_for_chat=run_info.get("raw_diagnostic_text", None),
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
        thread_dump_details=run_info.get("raw_diagnostic_text", "N/A"),
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

def main(argv=None):
    ensure_resultat_dir(); port, host = 5000, "127.0.0.1"
    if argv: 
        i=0
        while i < len(argv):
            arg = argv[i]
            if arg == "--port" and i + 1 < len(argv): 
                try: port = int(argv[i+1]); i+=1
                except ValueError: print(f"WARN: Invalid port '{argv[i+1]}'", file=sys.stderr)
            elif arg.startswith("--port="): 
                try: port = int(arg.split("=",1)[1])
                except ValueError: print(f"WARN: Invalid port in '{arg}'", file=sys.stderr)
            elif arg == "--host" and i + 1 < len(argv): host = argv[i+1]; i+=1
            elif arg.startswith("--host="): host = arg.split("=",1)[1]
            elif arg == "--help": print("Usage: dashboard.py [--port P] [--host H]"); return 0
            i+=1
    print(f"Flask dashboard starting. Results: {RESULTAT_DIR_DASHBOARD}. URL: http://{host}:{port}/", flush=True)
    try: app.run(host=host, port=port, debug=False) # Debug=False for production/distribution
    except OSError as e: print(f"ERROR Flask: {e}", file=sys.stderr); log_dashboard_error(f"Flask start fail: {e}"); return 1
    return 0

if __name__ == "__main__": sys.exit(main(sys.argv[1:]))