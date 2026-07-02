from __future__ import annotations

import argparse
import json

from family_newsletter.app.config import get_settings
from family_newsletter.app.logging import configure_logging
from family_newsletter.app.newsletter.delivery import deliver_newsletter
from family_newsletter.app.scheduler import run_blocking


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m family_newsletter.app.run_daily",
        description=(
            "Regenerate the family newsletter fresh and send it by email, or run "
            "a scheduler that does so every morning at the configured local time."
        ),
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="Regenerate and send once immediately, then exit (no scheduler).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Regenerate and render but do NOT send. Safe before credentials exist.",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="Skip writing the HTML/text preview files to data/previews.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _build_parser().parse_args(argv)
    settings = get_settings()

    if args.now:
        result = deliver_newsletter(
            settings,
            dry_run=args.dry_run,
            write_preview=not args.no_preview,
        )
        print(json.dumps(result, indent=2, default=str))
        return 0

    run_blocking(settings, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
