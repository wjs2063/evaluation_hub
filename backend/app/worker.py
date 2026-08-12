import asyncio
import signal

from app.core.config import settings
from app.core.db import engine
from app.evaluation_jobs import worker_identity, worker_slot


async def run_worker() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, stop.set)
    process_id = worker_identity()
    slots = [
        asyncio.create_task(worker_slot(f"{process_id}:slot-{index}", stop))
        for index in range(settings.EVALUATION_WORKER_CONCURRENCY)
    ]
    try:
        await stop.wait()
    finally:
        await asyncio.gather(*slots)
        await engine.dispose()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
