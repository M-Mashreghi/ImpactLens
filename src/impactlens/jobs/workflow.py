"""One workflow cycle and a lightweight interval scheduler with graceful shutdown."""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable

from impactlens.logging_setup import get_logger, log_context, log_event
from impactlens.storage.repositories import NotFoundError

logger = get_logger("jobs")
JOB_NAME = "news_to_impact"


def run_cycle(container) -> dict:
    """Poll → analyze new unique items → score active snapshots → alerts. Failures are isolated."""
    run_id = container.job_runs.start(JOB_NAME)
    summary: dict = {"sources": [], "analyses": {}, "impacts": 0, "alerts": {}, "errors": []}
    with log_context(stage="workflow", job_run_id=run_id):
        try:
            for poll in container.ingestion.poll_all(container.registry):
                summary["sources"].append(
                    poll.model_dump(include={"source_key", "new", "duplicates", "item_errors", "failed"})
                )
            outcomes = container.analysis_service.analyze_pending()
            for outcome in outcomes:
                summary["analyses"][outcome.status] = summary["analyses"].get(outcome.status, 0) + 1
            snapshots = container.portfolios.active_snapshots()
            version = container.impact_service.config.version
            for analysis in container.analyses.list(status="Valid", limit=1000):
                for snapshot in snapshots:
                    if container.impacts.find(analysis["analysis_id"], snapshot.snapshot_id, version):
                        continue  # already scored for this snapshot/version: no repeated work or alerts
                    try:
                        result = container.impact_service.score(analysis["analysis_id"], snapshot)
                        summary["impacts"] += 1
                        impact = container.impacts.get(result.impact_id)
                        decision = container.alert_service.evaluate(impact, snapshot.portfolio_id)
                        summary["alerts"][decision.status] = summary["alerts"].get(decision.status, 0) + 1
                    except (ValueError, NotFoundError) as exc:
                        summary["errors"].append(
                            {"analysis_id": analysis["analysis_id"], "error": str(exc)[:200]}
                        )
                    except Exception as exc:  # one item never stops the cycle
                        summary["errors"].append(
                            {
                                "analysis_id": analysis["analysis_id"],
                                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                            }
                        )
                        log_event(
                            logger,
                            logging.ERROR,
                            "impact step failed",
                            analysis_id=analysis["analysis_id"],
                            error_type=type(exc).__name__,
                        )
            status = "completed_with_errors" if summary["errors"] else "completed"
            container.job_runs.finish(run_id, status, summary)
        except Exception as exc:
            container.job_runs.finish(
                run_id, "failed", summary, error=f"{type(exc).__name__}: {str(exc)[:500]}"
            )
            log_event(logger, logging.ERROR, "workflow cycle failed", error_type=type(exc).__name__)
            summary["errors"].append({"cycle": f"{type(exc).__name__}: {exc}"})
            status = "failed"
        log_event(logger, logging.INFO, "workflow cycle finished", status=status, impacts=summary["impacts"])
    summary["status"] = status
    summary["run_id"] = run_id
    return summary


class Scheduler:
    """Runs ``run_cycle`` every ``interval_seconds`` until stopped; a failed cycle never stops it."""

    def __init__(
        self, container, interval_seconds: float, *, cycle: Callable[[object], dict] = run_cycle
    ) -> None:
        self.container = container
        self.interval = interval_seconds
        self.cycle = cycle
        self.stop_event = threading.Event()
        self.results: list[dict] = []

    def install_signal_handlers(self) -> None:
        def _stop(signum, _frame):  # noqa: ANN001
            log_event(logger, logging.INFO, "shutdown requested", signal=signum)
            self.stop_event.set()

        signal.signal(signal.SIGINT, _stop)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _stop)

    def run(self, max_cycles: int | None = None) -> list[dict]:
        cycles = 0
        while not self.stop_event.is_set():
            try:
                self.results.append(self.cycle(self.container))
            except Exception as exc:  # defensive: cycle itself should never raise
                log_event(logger, logging.ERROR, "cycle crashed", error_type=type(exc).__name__)
                self.results.append({"status": "crashed", "error": str(exc)[:200]})
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            self.stop_event.wait(self.interval)
        return self.results

    def stop(self) -> None:
        self.stop_event.set()
