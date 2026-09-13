"""
main.py
CLI entrypoint for the LinkedIn Job Application Agent.

Usage:
    python main.py               # Live run (human-in-the-loop before submit)
    python main.py --dry-run     # Scrape + tailor only, no submit
    python main.py --scrape-only # Only scrape and store jobs
    python main.py --stats       # Show database stats
    python main.py --schedule    # Run on cron schedule (daily 9am)
"""
import asyncio
import argparse
import sys
from pathlib import Path

# Fix Windows console UTF-8 encoding for emojis and box drawing characters
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from loguru import logger

# Configure logging
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="INFO",
    colorize=True,
)
logger.add(
    "data/agent.log",
    rotation="10 MB",
    retention="7 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
    level="DEBUG",
)


async def run_stats():
    """Print current database statistics."""
    from tools.db import init_db, get_stats
    await init_db()
    stats = await get_stats()

    print("\n" + "=" * 40)
    print("📊 LinkedIn Agent — Database Stats")
    print("=" * 40)
    total = sum(stats.values())
    for status, count in stats.items():
        bar = "█" * min(count, 30)
        print(f"  {status:<12} {count:>4}  {bar}")
    print("-" * 40)
    print(f"  {'TOTAL':<12} {total:>4}")
    print("=" * 40 + "\n")


async def run_scrape_only():
    """Scrape and store jobs without tailoring or applying."""
    from tools.db import init_db
    from agents.login_agent import run_login_agent
    from agents.scraper_agent import run_scraper_agent
    from tools.browser import browser_manager

    await init_db()
    try:
        page, _ = await run_login_agent()
        jobs = await run_scraper_agent(page)
        logger.success(f"✅ Stored {len(jobs)} new jobs to database")
    finally:
        await browser_manager.close()


async def run_signup_only():
    """Create a new LinkedIn account using signup flow."""
    from agents.login_agent import run_signup_agent
    from tools.browser import browser_manager

    try:
        page, _ = await run_signup_agent()
        logger.success("✅ LinkedIn signup completed successfully!")
        logger.info("📌 Browser remains open for verification if needed. Press Ctrl+C to close.")
    finally:
        await browser_manager.close()


def setup_schedule():
    """Set up APScheduler to run the agent daily at 9am."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from graph.workflow import run_workflow

    def _run():
        asyncio.run(run_workflow())

    scheduler = BlockingScheduler()
    scheduler.add_job(
        _run,
        trigger="cron",
        hour=9,
        minute=0,
        id="daily_linkedin_agent",
        name="Daily LinkedIn Job Application",
        replace_existing=True,
    )
    logger.info("⏰ Scheduler started — running daily at 9:00 AM")
    logger.info("   Press Ctrl+C to stop")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


def main():
    parser = argparse.ArgumentParser(
        description="LinkedIn AI Job Application Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                  Full run with human review before submit
  python main.py --dry-run        Scrape + tailor resumes, no submission
  python main.py --scrape-only    Only discover and store jobs
  python main.py --signup         Create a new LinkedIn account
  python main.py --stats          Show application statistics
  python main.py --schedule       Run on daily cron schedule (9 AM)
  python main.py --max-apply 5    Limit to 5 applications this run
        """,
    )
    parser.add_argument("--dry-run",     action="store_true", help="No actual submission")
    parser.add_argument("--scrape-only", action="store_true", help="Only scrape jobs")
    parser.add_argument("--signup",      action="store_true", help="Create a new LinkedIn account")
    parser.add_argument("--stats",       action="store_true", help="Show DB stats")
    parser.add_argument("--schedule",    action="store_true", help="Run on daily schedule")
    parser.add_argument("--max-apply",   type=int, default=None, help="Max applications per run")
    parser.add_argument("--headless",    action="store_true", help="Run browser in headless mode")
    args = parser.parse_args()

    # Override settings from CLI
    if args.max_apply:
        import config.settings as s
        s.MAX_JOBS_PER_RUN = args.max_apply

    if args.headless:
        import config.settings as s
        s.HEADLESS = True

    # ── Dispatch ──────────────────────────────────────────────────────────────
    if args.stats:
        asyncio.run(run_stats())

    elif args.signup:
        asyncio.run(run_signup_only())

    elif args.scrape_only:
        asyncio.run(run_scrape_only())

    elif args.schedule:
        setup_schedule()

    else:
        # Full pipeline run
        from graph.workflow import run_workflow
        from tools.browser import browser_manager

        async def run():
            try:
                await run_workflow(dry_run=args.dry_run)
            finally:
                await browser_manager.close()

        asyncio.run(run())


if __name__ == "__main__":
    main()
