"""Capture a fully rendered Streamlit page through the Chromium DevTools protocol."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect


def _rpc(socket, request_id: int, method: str, params: dict | None = None) -> dict:
    socket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
    while True:
        response = json.loads(socket.recv(timeout=30))
        if response.get("id") == request_id:
            if "error" in response:
                raise RuntimeError(response["error"])
            return response.get("result", {})


def _debug_port(profile: Path, timeout: float = 15) -> int:
    marker = profile / "DevToolsActivePort"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if marker.exists():
            return int(marker.read_text(encoding="utf-8").splitlines()[0])
        time.sleep(.2)
    raise TimeoutError("Chromium did not publish its DevTools port")


def _page_socket(port: int, url: str, timeout: float = 15) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as response:
            targets = json.load(response)
        pages = [target for target in targets if target.get("type") == "page"]
        matching = [target for target in pages if target.get("url", "").startswith(url.split("?")[0])]
        if matching:
            return matching[0]["webSocketDebuggerUrl"]
        time.sleep(.2)
    raise TimeoutError("The requested browser page was not created")


def capture(browser: Path, url: str, output: Path, expected_text: str, settle_seconds: float) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nbo-capture-") as profile_name:
        profile = Path(profile_name)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            [
                str(browser), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                "--disable-background-timer-throttling", "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding", "--run-all-compositor-stages-before-draw",
                "--window-size=1440,1000", "--remote-debugging-port=0",
                f"--user-data-dir={profile}", url,
            ],
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            port = _debug_port(profile)
            endpoint = _page_socket(port, url)
            with connect(endpoint, open_timeout=10, max_size=20_000_000) as socket:
                request_id = 1
                _rpc(socket, request_id, "Page.enable")
                request_id += 1
                _rpc(socket, request_id, "Page.bringToFront")
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    request_id += 1
                    state = _rpc(
                        socket,
                        request_id,
                        "Runtime.evaluate",
                        {"expression": "document.body ? document.body.innerText : ''", "returnByValue": True},
                    )
                    body = state.get("result", {}).get("value", "")
                    if expected_text in body and len(body) > 300:
                        break
                    time.sleep(.4)
                else:
                    raise TimeoutError(
                        f"Streamlit did not render expected text: {expected_text}. "
                        f"Visible text was: {body[-800:]}"
                    )
                time.sleep(settle_seconds)
                request_id += 1
                _rpc(
                    socket,
                    request_id,
                    "Runtime.evaluate",
                    {"expression": "window.scrollTo(0, 1); document.body.offsetHeight", "returnByValue": True},
                )
                time.sleep(.5)
                request_id += 1
                result = _rpc(
                    socket,
                    request_id,
                    "Page.captureScreenshot",
                    {"format": "png", "fromSurface": True, "captureBeyondViewport": False},
                )
                output.write_bytes(base64.b64decode(result["data"]))
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-text", required=True)
    parser.add_argument("--settle-seconds", type=float, default=3)
    args = parser.parse_args()
    capture(args.browser, args.url, args.output, args.expected_text, args.settle_seconds)


if __name__ == "__main__":
    main()
