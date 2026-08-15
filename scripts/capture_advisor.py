"""Genera capturas reales de la Mesa Flask mediante Chromium DevTools."""

from __future__ import annotations

import argparse
import base64
import gc
import json
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import yaml
from waitress import create_server
from websockets.sync.client import connect

from nbo.advisor_app import create_app
from nbo.advisor_local import LocalAdvisorApi
from nbo.config import load_config
from nbo.engine import NBOEngine


def _rpc(ws, request_id: int, method: str, params: dict | None = None) -> dict:
    ws.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
    while True:
        response = json.loads(ws.recv(timeout=30))
        if response.get("id") == request_id:
            if "error" in response:
                raise RuntimeError(response["error"])
            return response.get("result", {})


def _wait_file(path: Path, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(.15)
    raise TimeoutError(f"No se creó {path}")


def _browser_socket(profile: Path, base_url: str) -> str:
    marker = profile / "DevToolsActivePort"
    _wait_file(marker)
    port = int(marker.read_text(encoding="utf-8").splitlines()[0])
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as response:
            pages = [item for item in json.load(response) if item.get("type") == "page"]
        matches = [item for item in pages if item.get("url", "").startswith(base_url)]
        if matches:
            return matches[0]["webSocketDebuggerUrl"]
        time.sleep(.2)
    raise TimeoutError("Chromium no publicó la página esperada")


def _body(ws, request_id: int) -> tuple[int, str]:
    request_id += 1
    result = _rpc(ws, request_id, "Runtime.evaluate", {
        "expression": "document.body ? document.body.innerText : ''", "returnByValue": True,
    })
    return request_id, result.get("result", {}).get("value", "")


def _wait_text(ws, request_id: int, text: str, timeout: float = 45) -> int:
    deadline = time.monotonic() + timeout
    visible = ""
    while time.monotonic() < deadline:
        request_id, visible = _body(ws, request_id)
        if text in visible:
            return request_id
        time.sleep(.25)
    raise TimeoutError(f"No apareció {text!r}. Texto visible: {visible[-500:]}")


ACTIONS = {
    "none": None,
    "light": """
      if (document.documentElement.dataset.theme !== 'light') {
        document.querySelector('[data-theme-toggle]').click();
      }
    """,
    "reject": """
      document.querySelector('input[name="resultado_final"][value="rechazada"]').click();
      document.querySelector('select[name="motivo_rechazo"]').value = 'precio';
      document.querySelector('form[data-feedback-form]').requestSubmit();
    """,
    "accept": """
      document.querySelector('input[name="resultado_final"][value="aceptada"]').click();
      document.querySelector('form[data-feedback-form]').requestSubmit();
    """,
    "activate": """
      document.querySelector('input[name="evidence_reference"]').value = 'ORDER-CAPTURE-001';
      document.querySelector('input[name="evidence_reference"]').form.requestSubmit();
    """,
}


def capture(browser: Path, url: str, output: Path, expected: str, actions: list[tuple[str, str]]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nbo-browser-", ignore_cleanup_errors=True) as profile_name:
        profile = Path(profile_name)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen([
            str(browser), "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--disable-extensions", "--disable-background-networking", "--no-first-run",
            "--window-size=1440,1000", "--remote-debugging-port=0",
            f"--user-data-dir={profile}", url,
        ], creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            endpoint = _browser_socket(profile, url.split("?")[0])
            with connect(endpoint, open_timeout=10, max_size=20_000_000) as ws:
                request_id = 1
                _rpc(ws, request_id, "Page.enable")
                request_id = _wait_text(ws, request_id, expected)
                for action, action_expected in actions:
                    request_id += 1
                    _rpc(ws, request_id, "Runtime.evaluate", {"expression": ACTIONS[action]})
                    request_id = _wait_text(ws, request_id, action_expected)
                    time.sleep(.4)
                time.sleep(.8)
                request_id += 1
                result = _rpc(ws, request_id, "Page.captureScreenshot", {
                    "format": "png", "fromSurface": True, "captureBeyondViewport": False,
                })
                output.write_bytes(base64.b64decode(result["data"]))
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("assets/screenshots"))
    args = parser.parse_args()
    project_root = Path(__file__).parents[1]
    with tempfile.TemporaryDirectory(prefix="nbo-advisor-capture-", ignore_cleanup_errors=True) as temp_name:
        temp = Path(temp_name)
        config = load_config()
        config["project"]["data_dir"] = str(project_root / "dataset")
        config["project"]["artifact_dir"] = str(project_root / "artifacts")
        config["project"]["database_path"] = str(temp / "capture.sqlite3")
        config_path = temp / "config.yaml"
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        backend = LocalAdvisorApi(NBOEngine(str(config_path), persist=True))
        app = create_app({"SECRET_KEY": "capture-only"}, backend)
        port = _free_port()
        server = create_server(app, host="127.0.0.1", port=port, threads=2)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{port}"
        try:
            capture(args.browser, base, args.output_dir / "advisor-empty.png", "Listo para consultar", [])
            capture(args.browser, base + "/?cliente_id=CLI000013", args.output_dir / "advisor-found.png", "Resultado de la conversación", [("light", "Resultado de la conversación")])
            capture(args.browser, base + "/?cliente_id=CLI000013", args.output_dir / "advisor-rejection.png", "Resultado de la conversación", [("reject", "Resultado registrado")])
            capture(args.browser, base + "/?cliente_id=CLI000001", args.output_dir / "advisor-activation.png", "Resultado de la conversación", [("accept", "todavía no está activo"), ("activate", "Producto activado")])
        finally:
            server.close()
            server.task_dispatcher.shutdown()
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("El servidor temporal no se detuvo correctamente")
        del server, app, backend
        gc.collect()
        time.sleep(.5)


if __name__ == "__main__":
    main()
