import importlib.util
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "phi3:mini")
DEFAULT_GUARD_MODEL = os.getenv("PROMPT_GUARD_MODEL", "meta-llama/Llama-Prompt-Guard-2-86M")
LOCAL_GUARD_DIR = ROOT / "models" / "finetuned-prompt-guard"


def _ok(label: str, message: str) -> None:
    print(f"[OK]   {label}: {message}")


def _warn(label: str, message: str) -> None:
    print(f"[WARN] {label}: {message}")


def _fail(label: str, message: str) -> None:
    print(f"[FAIL] {label}: {message}")


def _find_ollama_bin() -> str | None:
    candidates = [
        "ollama",
        str(Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"),
        r"C:\Program Files\Ollama\ollama.exe",
    ]

    for candidate in candidates:
        try:
            result = subprocess.run(
                [candidate, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return candidate
        except Exception:
            continue
    return None


def _is_port_open(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        sock.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        sock.close()


def _get_ollama_models(base_url: str = "http://127.0.0.1:11434") -> list[str]:
    req = Request(url=f"{base_url}/api/tags", method="GET")
    with urlopen(req, timeout=5) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    models = payload.get("models", [])
    return [str(item.get("name", "")).strip() for item in models if item.get("name")]


def _check_transformers_guard_local() -> tuple[bool, str]:
    if importlib.util.find_spec("transformers") is None:
        return False, "transformers package is missing"

    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    candidates = []
    if LOCAL_GUARD_DIR.exists():
        candidates.append(str(LOCAL_GUARD_DIR))
    candidates.append(DEFAULT_GUARD_MODEL)

    errors: list[str] = []
    for candidate in candidates:
        try:
            local_only = not Path(candidate).exists()
            AutoTokenizer.from_pretrained(candidate, local_files_only=local_only)
            AutoModelForSequenceClassification.from_pretrained(candidate, local_files_only=local_only)
            return True, f"loadable source: {candidate}"
        except Exception as ex:
            errors.append(f"{candidate} -> {ex}")

    return False, " | ".join(errors[-2:])


def _check_python_import(path: str) -> tuple[bool, str]:
    try:
        __import__(path)
        return True, "import success"
    except Exception as ex:
        return False, str(ex)


def main() -> int:
    print("== Preflight Check ==")
    print(f"Project root: {ROOT}")
    print(f"Expected chat model: {DEFAULT_CHAT_MODEL}")
    print(f"Expected guard model: {DEFAULT_GUARD_MODEL}")
    print("")

    overall_ok = True

    ollama_bin = _find_ollama_bin()
    if ollama_bin:
        _ok("Ollama CLI", f"found at: {ollama_bin}")
    else:
        _fail("Ollama CLI", "not found. Install Ollama first.")
        overall_ok = False

    if _is_port_open("127.0.0.1", 11434):
        _ok("Ollama service", "port 11434 is listening")
    else:
        _fail("Ollama service", "not reachable at 127.0.0.1:11434")
        overall_ok = False

    if _is_port_open("127.0.0.1", 11434):
        try:
            models = _get_ollama_models()
            if DEFAULT_CHAT_MODEL in models:
                _ok("Chat model", f"{DEFAULT_CHAT_MODEL} is available locally")
            else:
                _fail("Chat model", f"{DEFAULT_CHAT_MODEL} not found in local Ollama store")
                if models:
                    _warn("Ollama models", ", ".join(models))
                overall_ok = False
        except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as ex:
            _fail("Ollama tags", f"cannot query model list: {ex}")
            overall_ok = False

    guard_ok, guard_msg = _check_transformers_guard_local()
    if guard_ok:
        _ok("Prompt Guard", guard_msg)
    else:
        _warn("Prompt Guard", guard_msg)

    vuln_ok, vuln_msg = _check_python_import("src.api.vulnerable_app")
    if vuln_ok:
        _ok("vulnerable_app import", vuln_msg)
    else:
        _fail("vulnerable_app import", vuln_msg)
        overall_ok = False

    sec_ok, sec_msg = _check_python_import("src.api.secure_app")
    if sec_ok:
        _ok("secure_app import", sec_msg)
    else:
        _warn("secure_app import", sec_msg)

    print("")
    if overall_ok:
        _ok("Result", "chatbot is ready to start with local phi3:mini")
        return 0

    _fail("Result", "startup requirements are not fully satisfied")
    return 1


if __name__ == "__main__":
    sys.exit(main())
