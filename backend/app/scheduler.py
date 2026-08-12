import asyncio
import logging
import signal

from app.core.config import settings
from app.core.db import engine
from app.evaluation_jobs import enqueue_due_schedules

logger = logging.getLogger(__name__)


async def run_scheduler() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, stop.set)
    try:
        while not stop.is_set():
            try:
                await enqueue_due_schedules()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Evaluation scheduler could not enqueue due schedules")
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=settings.EVALUATION_SCHEDULER_POLL_SECONDS
                )
            except TimeoutError:
                pass
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(run_scheduler())


if __name__ == "__main__":
    main()
