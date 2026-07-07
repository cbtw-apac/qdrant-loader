from __future__ import annotations

import argparse
import json

from harborrag_app.api.dependencies import get_app_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harbor")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--json", action="store_true", dest="as_json")
    sample = sub.add_parser("sample-ingest")
    sample.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = get_app_service()
    response = service.health() if args.command == "doctor" else service.ingest_once()
    payload = {"ok": response.ok, **response.data}
    print(json.dumps(payload, sort_keys=True) if args.as_json else payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
