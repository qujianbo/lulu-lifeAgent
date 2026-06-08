import asyncio
import logging

from app.config import get_settings
from app.logging import configure_logging


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logging.getLogger(__name__).info("scheduler_started")

    while True:
        # M1 placeholder. M6 will scan scheduled_jobs and dispatch due tasks here.
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())

