from __future__ import annotations

import argparse
import getpass
import logging
from pathlib import Path
from typing import Sequence

from rich.logging import RichHandler
from rich.traceback import install

from .client import PBaseClient
from .scraper import PBaseScraper


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download full-resolution images from PBase galleries.",
    )
    parser.add_argument(
        "--username",
        required=True,
        help="PBase username (account owner).",
    )
    parser.add_argument(
        "--password",
        help="PBase password. If omitted, the program prompts for it.",
    )
    parser.add_argument(
        "--output",
        default="downloads",
        help="Directory where images will be stored (default: downloads).",
    )
    parser.add_argument(
        "--start",
        action="append",
        help=(
            "Optional gallery paths or URLs to start from. "
            "Drag multiple --start flags if you want to limit scraping to specific galleries. "
            "Defaults to <username>/root."
        ),
    )
    parser.add_argument(
        "--base-url",
        default="https://pbase.com",
        help="Base URL for PBase. Override only for testing.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds to wait between HTTP requests (default: 0.5).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    return parser


def configure_logging(level: str) -> None:
    install(show_locals=False)
    log_level = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    handler = RichHandler(
        rich_tracebacks=True,
        markup=True,
        show_time=False,
        show_path=False,
    )
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        handlers=[handler],
    )
    logging.captureWarnings(True)


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(args.log_level)

    password = args.password or getpass.getpass("PBase password: ")
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    client = PBaseClient(
        username=args.username,
        password=password,
        base_url=args.base_url,
        request_delay=args.delay,
    )
    client.login()

    scraper = PBaseScraper(client, output_dir=output_dir)
    scraper.scrape(args.start)


if __name__ == "__main__":
    main()
