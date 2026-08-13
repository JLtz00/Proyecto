from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import NBOEngine
from .schemas import DemoJourneyRequest
from .simulation import demo_journey


def main() -> None:
    parser = argparse.ArgumentParser(description="Recorrido aislado de rechazo y recuperación NBO")
    parser.add_argument("--cliente-id", default="CLI000001")
    parser.add_argument("--motivo", default="precio", choices=[
        "precio", "no_necesita", "ya_tiene_similar", "mal_momento", "no_confia", "otro",
    ])
    parser.add_argument("--json-output")
    parser.add_argument("--markdown-output")
    args = parser.parse_args()
    result = demo_journey(
        NBOEngine(persist=False),
        DemoJourneyRequest(cliente_id=args.cliente_id, motivo_rechazo=args.motivo),
    )
    if args.json_output:
        Path(args.json_output).write_text(
            json.dumps(result.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8",
        )
    if args.markdown_output:
        Path(args.markdown_output).write_text(result.markdown, encoding="utf-8")
    print(result.markdown)


if __name__ == "__main__":
    main()
