from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .api.app import EngineApp
from .common.brand import PRODUCT_NAME


async def _stdio() -> int:
    app = EngineApp()
    return await app.run_stdio()


async def _run_job(job_type: str, params: dict, data_dir: str | None) -> int:
    app = EngineApp(Path(data_dir) if data_dir else None)
    result = await app.run_cli(job_type, params)
    print(json.dumps(result, indent=2, default=str))
    job = result.get("job") or {}
    return 0 if job.get("state") == "succeeded" else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="shorts-engine", description=f"{PRODUCT_NAME} media engine")
    parser.add_argument("--stdio", action="store_true", help="speak the NDJSON stdio protocol")
    parser.add_argument("--data-dir", default=None, help="override the data directory")
    parser.add_argument("--version", action="store_true")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run-job", help="run one job inline (testing)")
    run.add_argument("type")
    run.add_argument("--params", required=True, help="JSON object of job parameters")
    args = parser.parse_args()
    if args.version:
        from .common.brand import ENGINE_VERSION

        print(ENGINE_VERSION)
        return 0
    if args.command == "run-job":
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as exc:
            print(f"Invalid --params JSON: {exc}", file=sys.stderr)
            return 2
        return asyncio.run(_run_job(args.type, params, args.data_dir))
    if args.stdio or not sys.stdin.isatty():
        return asyncio.run(_stdio())
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
