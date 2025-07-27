# Filename: ollama_client.py
import os
import sys
import json
import requests 
import traceback
from datetime import datetime 

LOG_FILE_OLLAMA_CLIENT = os.path.join(os.getcwd(), "ollama_client_log.txt") 

def _log_error(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_msg = f"[{timestamp}] [OLLAMA_CLIENT_ERROR] {msg}\n"
    print(full_msg, file=sys.stderr, flush=True)
    try:
        if os.path.exists(LOG_FILE_OLLAMA_CLIENT) and os.path.getsize(LOG_FILE_OLLAMA_CLIENT) > 5 * 1024 * 1024:
            with open(LOG_FILE_OLLAMA_CLIENT, "w", encoding="utf-8") as f: f.write(f"[{timestamp}] Log truncated.\n")
    except OSError: pass
    try:
        with open(LOG_FILE_OLLAMA_CLIENT, "a", encoding="utf-8") as f: f.write(full_msg)
    except Exception as log_e: print(f"CRIT_LOGGING_FAILURE_IN_OLLAMA_CLIENT: {log_e}", file=sys.stderr, flush=True)

def get_ollama_api_base_url():
    return os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip('/')

def ollama_api_generate(model_tag, prompt_text, llm_parameters, timeout=300):
    ollama_api_url = f"{get_ollama_api_base_url()}/api/generate"
    headers = {"Content-Type": "application/json"}
    payload = { "model": model_tag, "prompt": prompt_text, "stream": False, "options": llm_parameters or {} }
    console_encoding = sys.stdout.encoding if sys.stdout else 'utf-8'
    response_obj = None
    try:
        response_obj = requests.post(ollama_api_url, headers=headers, json=payload, timeout=timeout)
        response_obj.raise_for_status()
        response_data = response_obj.json()
        if "response" in response_data: return response_data["response"].strip(), response_data
        else: _log_error(f"/api/generate Error: 'response' key missing. Full: {response_data}"); return None, response_data
    except requests.exceptions.Timeout:
        msg = f"/api/generate timeout ({timeout}s) for {model_tag}"; _log_error(msg); return None, {"error": "timeout", "message": msg}
    except requests.exceptions.HTTPError as http_err:
        err_content = response_obj.text if response_obj else "N/A"; status = response_obj.status_code if response_obj else None
        msg = f"/api/generate HTTP error: {http_err} - Status: {status} - Resp: {err_content.encode(console_encoding, errors='replace').decode(console_encoding)}"
        _log_error(msg); return None, {"error": "http_error", "message": msg, "status_code": status, "content": err_content}
    except requests.exceptions.RequestException as req_err:
        msg = f"/api/generate Request error: {req_err} for {model_tag}"; _log_error(msg); return None, {"error": "request_exception", "message": msg}
    except json.JSONDecodeError as json_err:
        resp_text = response_obj.text if response_obj else "N/A"
        msg = f"/api/generate JSON decode error: {json_err}. Response: {resp_text}"; _log_error(msg); return None, {"error": "json_decode_error", "message": msg, "raw_response": resp_text}
    except Exception as e:
        msg = f"Unexpected error /api/generate model {model_tag}: {e}\n{traceback.format_exc()}"; _log_error(msg); return None, {"error": "unexpected_exception", "message": str(e)}

def ollama_api_chat(model_tag, messages_history, llm_parameters, timeout=300):
    ollama_api_url = f"{get_ollama_api_base_url()}/api/chat"
    headers = {"Content-Type": "application/json"}
    payload = { "model": model_tag, "messages": messages_history, "stream": False, "options": llm_parameters or {} }
    console_encoding = sys.stdout.encoding if sys.stdout else 'utf-8'
    response_obj = None
    try:
        response_obj = requests.post(ollama_api_url, headers=headers, json=payload, timeout=timeout)
        response_obj.raise_for_status()
        response_data = response_obj.json()
        if "message" in response_data and "content" in response_data["message"]: return response_data["message"]["content"].strip(), response_data
        else: _log_error(f"/api/chat Error: 'message' or 'content' key missing. Full: {response_data}"); return None, response_data
    except requests.exceptions.Timeout:
        msg = f"/api/chat timeout ({timeout}s) for {model_tag}"; _log_error(msg); return None, {"error": "timeout", "message": msg}
    except requests.exceptions.HTTPError as http_err:
        err_content = response_obj.text if response_obj else "N/A"; status = response_obj.status_code if response_obj else None
        msg = f"/api/chat HTTP error: {http_err} - Status: {status} - Resp: {err_content.encode(console_encoding, errors='replace').decode(console_encoding)}"
        _log_error(msg); return None, {"error": "http_error", "message": msg, "status_code": status, "content": err_content}
    except requests.exceptions.RequestException as req_err:
        msg = f"/api/chat Request error: {req_err} for {model_tag}"; _log_error(msg); return None, {"error": "request_exception", "message": msg}
    except json.JSONDecodeError as json_err:
        resp_text = response_obj.text if response_obj else "N/A"
        msg = f"/api/chat JSON decode error: {json_err}. Response: {resp_text}"; _log_error(msg); return None, {"error": "json_decode_error", "message": msg, "raw_response": resp_text}
    except Exception as e:
        msg = f"Unexpected error /api/chat model {model_tag}: {e}\n{traceback.format_exc()}"; _log_error(msg); return None, {"error": "unexpected_exception", "message": str(e)}