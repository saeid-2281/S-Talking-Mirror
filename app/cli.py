from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from loguru import logger

from app import __version__
from app.config import load_settings
from app.csv_loader import load_jobs
from app.database import initialize_default_database
from app.engine import BatchEngine
from app.logging_setup import configure_logging
from app.providers.elevenlabs import ElevenLabsProvider
from app.config.runtime import RuntimeConfig
from app.services.report_service import ReportService
from app.state import JobStateStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stalking",
        description="S Talking — Professional AI Audio Studio",
    )
    parser.add_argument("--version", action="version", version=f"S Talking {__version__}")
    parser.add_argument(
        "--settings",
        type=Path,
        default=Path("settings.json"),
        help="Path to settings JSON",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate a CSV without API calls")
    validate.add_argument("csv", type=Path)

    generate = subparsers.add_parser("generate", help="Generate audio from a CSV")
    generate.add_argument("csv", type=Path)
    generate.add_argument("--output", type=Path, default=Path("output"))
    generate.add_argument("--state", type=Path, default=Path("state/job-state.json"))

    subparsers.add_parser("voices", help="List ElevenLabs voices")
    subparsers.add_parser("models", help="List ElevenLabs TTS models")
    subparsers.add_parser("export-diagnostics", help="Export sanitized diagnostics ZIP")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    configure_logging(Path("logs"))
    initialize_default_database()

    try:
        if args.command == "validate":
            jobs = load_jobs(args.csv)
            characters = sum(len(job.text) for job in jobs)
            print(f"Valid CSV: {len(jobs)} rows, {characters:,} characters")
            return

        if args.command == "export-diagnostics":
            runtime = RuntimeConfig.from_root(Path.cwd())
            runtime.ensure_directories()
            bundle = ReportService(runtime).export_diagnostics_bundle()
            print(bundle)
            return

        settings = load_settings(args.settings)

        with ElevenLabsProvider(settings) as provider:
            if args.command == "voices":
                print(json.dumps(provider.list_voices(), indent=2, ensure_ascii=False))
                return

            if args.command == "models":
                print(json.dumps(provider.list_models(), indent=2, ensure_ascii=False))
                return

            jobs = load_jobs(args.csv)
            engine = BatchEngine(
                provider=provider,
                settings=settings,
                output_dir=args.output,
                state_store=JobStateStore(args.state),
            )
            summary = engine.run(jobs)
            print(
                f"Finished — total: {summary.total}, completed: {summary.completed}, "
                f"skipped: {summary.skipped}, failed: {summary.failed}"
            )
            if summary.failed:
                sys.exit(2)

    except Exception as exc:
        logger.error("{}", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
