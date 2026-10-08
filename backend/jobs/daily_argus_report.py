"""Render Cron entry point for Argus's previous-local-day report."""

import asyncio
import logging

import asyncpg

from backend.agents.argus.agent import summarize_daily_report
from backend.agents.argus.client import OpenRouterError
from backend.config import get_settings
from backend.services.argus_reporting import format_report_facts, summarize_previous_local_day
from backend.services.telegram import send_telegram_message

_logger = logging.getLogger("argus.daily_report")


async def run_daily_report() -> None:
    settings = get_settings()
    if not settings.argus_report_database_url:
        raise RuntimeError("Falta ARGUS_REPORT_DATABASE_URL de solo lectura")
    dsn = settings.argus_report_database_url.replace("postgres://", "postgresql://", 1)
    pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=1,
        max_size=2,
        command_timeout=15,
        server_settings={"default_transaction_read_only": "on"},
    )
    try:
        summary = await summarize_previous_local_day(pool=pool)
        facts = format_report_facts(summary)
        try:
            narrative = await summarize_daily_report(summary)
        except OpenRouterError as exc:
            _logger.warning("openrouter_daily_summary_unavailable reason=%s", str(exc))
            narrative = "Resumen narrativo no disponible; se envían las métricas calculadas por AEGIS."
        await send_telegram_message(f"{facts}\n\n{narrative}")
        _logger.info("argus_daily_report_sent report_date=%s", summary.get("report_date", "unknown"))
    finally:
        await pool.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run_daily_report())


if __name__ == "__main__":
    main()
