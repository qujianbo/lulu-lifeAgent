import asyncio
import logging

from app.config import get_settings
from app.database import create_engine, create_session_factory
from app.logging import configure_logging
from app.services.scheduler import SchedulerService

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("scheduler_started")
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    while True:
        try:
            async with session_factory() as session:
                async with session.begin():
                    result = await SchedulerService(session).run_once()
                    if result.scanned:
                        logger.info("scheduler_tick_processed", extra=result.__dict__)
        except Exception:
            # Keep the worker alive; transient dependency errors retry on the next tick.
            logger.exception("scheduler_tick_failed")
        await asyncio.sleep(settings.scheduler_poll_seconds)


if __name__ == "__main__":
    asyncio.run(main())
