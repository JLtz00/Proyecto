from __future__ import annotations

import argparse
import threading
import webbrowser

from waitress import serve

from . import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Inicia la Mesa local del asesor NBO.")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--jury", action="store_true",
        help="Inicia la demostracion aislada para jurados en una SQLite temporal.",
    )
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}{'/jury' if args.jury else ''}"
    if not args.no_browser:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()
    label = "Modo Jurado" if args.jury else "Mesa del asesor"
    print(f"{label} disponible en {url}")
    app = create_app({"JURY_MODE": True}) if args.jury else create_app()
    serve(app, host="127.0.0.1", port=args.port, threads=4)


if __name__ == "__main__":
    main()
