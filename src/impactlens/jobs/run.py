"""Worker entrypoint: ``python -m impactlens.jobs.run [--once]``."""

from __future__ import annotations

import argparse
import json

from impactlens.app import create_container
from impactlens.jobs.workflow import Scheduler, run_cycle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ImpactLens scheduled news-to-impact worker")
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    args = parser.parse_args(argv)
    container = create_container()
    try:
        if args.once:
            print(json.dumps(run_cycle(container), indent=2, default=str))
            return 0
        scheduler = Scheduler(container, container.settings.news.poll_interval_seconds)
        scheduler.install_signal_handlers()
        scheduler.run()
        return 0
    finally:
        container.close()


if __name__ == "__main__":
    raise SystemExit(main())
