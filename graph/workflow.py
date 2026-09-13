"""
graph/workflow.py
Pure-asyncio orchestrator — replaces LangGraph to avoid C-extension deps.
Runs the 4-agent pipeline with retry logic, state tracking, and error recovery.
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Optional
from loguru import logger

from agents.login_agent import run_login_agent
from agents.scraper_agent import run_scraper_agent
from agents.resume_agent import run_resume_agent
from agents.apply_agent import run_apply_agent
from tools.db import init_db, get_stats
from tools.browser import browser_manager


# ─── Shared Pipeline State ────────────────────────────────────────────────────

@dataclass
class PipelineState:
    """Mutable state passed through all pipeline stages."""
    page: object = None
    context: object = None
    scraped_jobs: List[dict] = field(default_factory=list)
    tailored_jobs: List[dict] = field(default_factory=list)
    apply_stats: dict = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    dry_run: bool = False
    start_time: float = field(default_factory=time.time)


# ─── Stage Runner with Retry ──────────────────────────────────────────────────

async def run_stage(
    name: str,
    coro,
    state: PipelineState,
    retries: int = 2,
    critical: bool = True,
) -> bool:
    """
    Run a pipeline stage coroutine with retry logic.

    Args:
        name: Display name for logging
        coro: Awaitable to run
        state: Shared pipeline state
        retries: Max retry attempts on failure
        critical: If True and all retries fail, halt the pipeline

    Returns:
        True if stage succeeded, False if it failed
    """
    banner = "=" * 55
    logger.info(f"\n{banner}\n  {name}\n{banner}")

    for attempt in range(1, retries + 2):
        try:
            result = await coro
            return result
        except Exception as e:
            if attempt <= retries:
                wait = 2 ** attempt  # Exponential backoff: 2s, 4s
                logger.warning(
                    f"⚠️  {name} failed (attempt {attempt}/{retries + 1}): {e}\n"
                    f"   Retrying in {wait}s..."
                )
                await asyncio.sleep(wait)
            else:
                msg = f"❌ {name} failed after {retries + 1} attempts: {e}"
                logger.error(msg)
                state.errors.append(msg)
                if critical:
                    raise RuntimeError(msg) from e
                return False
    return False


# ─── Individual Stage Coroutines ──────────────────────────────────────────────

async def _stage_init(state: PipelineState) -> bool:
    await init_db()
    logger.info("✅ Database initialized")
    return True


async def _stage_login(state: PipelineState) -> bool:
    page, context = await run_login_agent()
    state.page = page
    state.context = context
    return True


async def _stage_scrape(state: PipelineState) -> bool:
    jobs = await run_scraper_agent(state.page)
    state.scraped_jobs = jobs
    logger.info(f"📋 Scraped {len(jobs)} new jobs")
    return True


async def _stage_tailor(state: PipelineState) -> bool:
    jobs_input = state.scraped_jobs if state.scraped_jobs else None
    tailored = await run_resume_agent(jobs_input, concurrency=3)
    state.tailored_jobs = tailored
    logger.info(f"✍️  Tailored {len(tailored)} resumes")
    return True


async def _stage_apply(state: PipelineState) -> bool:
    stats = await run_apply_agent(state.page, state.tailored_jobs)
    state.apply_stats = stats
    return True


# ─── Summary Report ───────────────────────────────────────────────────────────

async def _print_report(state: PipelineState) -> None:
    elapsed = round(time.time() - state.start_time, 1)
    db_stats = await get_stats()
    mode = "DRY RUN" if state.dry_run else "LIVE"

    logger.info(f"""
╔══════════════════════════════════════════════╗
║        LINKEDIN JOB AGENT — SUMMARY          ║
╠══════════════════════════════════════════════╣
║  Mode        : {mode:<30} ║
║  Duration    : {elapsed}s{'':<27} ║
╠══════════════════════════════════════════════╣
║  This run:                                   ║
║    Jobs found  : {len(state.scraped_jobs):<28} ║
║    Resumes made: {len(state.tailored_jobs):<28} ║
║    Applied     : {state.apply_stats.get('applied', 0):<28} ║
║    Skipped     : {state.apply_stats.get('skipped', 0):<28} ║
║    Failed      : {state.apply_stats.get('failed', 0):<28} ║
╠══════════════════════════════════════════════╣
║  All-time DB totals:                         ║
║    Applied     : {db_stats.get('APPLIED', 0):<28} ║
║    Pending     : {db_stats.get('PENDING', 0):<28} ║
║    Failed      : {db_stats.get('FAILED', 0):<28} ║
╚══════════════════════════════════════════════╝
""")

    if state.errors:
        logger.warning("Errors encountered:")
        for e in state.errors:
            logger.warning(f"  • {e}")


# ─── Main Pipeline ────────────────────────────────────────────────────────────

async def run_workflow(dry_run: bool = False) -> PipelineState:
    """
    Execute the full 4-agent LinkedIn job application pipeline.

    Stages (in order):
        1. init    → DB setup
        2. login   → LinkedIn authentication
        3. scrape  → Job discovery + filtering
        4. tailor  → LLM resume customisation
        5. apply   → Form fill + submission

    Args:
        dry_run: Scrape + tailor but skip actual submission

    Returns:
        Final PipelineState with all results
    """
    state = PipelineState(dry_run=dry_run)

    # Override DRY_RUN in settings if passed from CLI
    if dry_run:
        import config.settings as cfg
        cfg.DRY_RUN = True

    stages = [
        ("🗄️  Stage 1/5 — Init DB",        _stage_init(state),   False),
        ("🔐 Stage 2/5 — Login",            _stage_login(state),  True),
        ("🔍 Stage 3/5 — Scrape Jobs",      _stage_scrape(state), True),
        ("✍️  Stage 4/5 — Tailor Resumes",  _stage_tailor(state), False),
        ("🚀 Stage 5/5 — Apply",            _stage_apply(state),  False),
    ]

    try:
        for name, coro, critical in stages:
            success = await run_stage(name, coro, state, retries=2, critical=critical)
            if not success and critical:
                logger.error(f"Critical stage failed: {name} — aborting pipeline")
                break
    finally:
        await _print_report(state)
        # Only close if browser was opened in this workflow run
        if state.page is not None:
            await browser_manager.close()

    return state
