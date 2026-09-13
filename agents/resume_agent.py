"""
agents/resume_agent.py
LLM-powered resume tailoring agent.
For each pending job, generates a tailored PDF resume.
"""
import asyncio
from pathlib import Path
from datetime import datetime
from loguru import logger
from tools.llm import llm_client
from tools.pdf_builder import build_resume_pdf
from tools.resume_parser import parse_resume
from tools.db import get_pending_jobs, update_job_status
from config.settings import BASE_RESUME_PATH, TAILORED_DIR


# Cache base resume text (parse once, reuse)
_BASE_RESUME_TEXT: str | None = None


def get_base_resume_text() -> str:
    global _BASE_RESUME_TEXT
    if _BASE_RESUME_TEXT is None:
        if not Path(BASE_RESUME_PATH).exists():
            raise FileNotFoundError(
                f"Base resume not found at: {BASE_RESUME_PATH}\n"
                "Place your resume at: data/base_resume.pdf (or .docx)"
            )
        _BASE_RESUME_TEXT = parse_resume(BASE_RESUME_PATH)
    return _BASE_RESUME_TEXT


async def tailor_single_job(job: dict) -> dict | None:
    """
    Tailor resume for one job and save to PDF.
    Returns job dict with 'resume_path' added, or None on failure.
    """
    job_id    = job["job_id"]
    title     = job["title"]
    company   = job["company"]
    desc      = job["description"]

    await update_job_status(job_id, "TAILORING")

    try:
        base_resume = get_base_resume_text()

        # Call LLM to tailor
        tailored_data = await llm_client.tailor_resume(
            base_resume=base_resume,
            job_title=title,
            company=company,
            job_description=desc,
        )

        # Build PDF
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in f"{company}_{title}")[:60]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_path  = Path(TAILORED_DIR) / f"{safe_name}_{timestamp}.pdf"

        build_resume_pdf(tailored_data, pdf_path)

        # Update DB
        await update_job_status(job_id, "PENDING", resume_path=str(pdf_path))
        logger.success(f"📄 Tailored resume ready: {pdf_path.name}")

        return {**job, "resume_path": str(pdf_path), "tailored_data": tailored_data}

    except Exception as e:
        logger.error(f"❌ Resume tailoring failed for {title} @ {company}: {e}")
        await update_job_status(job_id, "FAILED", notes=str(e))
        return None


async def run_resume_agent(jobs: list[dict] | None = None, concurrency: int = 3) -> list[dict]:
    """
    Main resume agent — tailors resumes for all pending jobs.

    Args:
        jobs: List of job dicts (optional, fetches from DB if None)
        concurrency: Max parallel LLM calls

    Returns:
        List of jobs with tailored resume paths attached
    """
    if jobs is None:
        jobs = await get_pending_jobs(limit=50)

    if not jobs:
        logger.info("No pending jobs to tailor")
        return []

    logger.info(f"✍️  Tailoring resumes for {len(jobs)} jobs (concurrency={concurrency})")

    # Process in batches to respect API rate limits
    results = []
    semaphore = asyncio.Semaphore(concurrency)

    async def process_with_sem(job: dict):
        async with semaphore:
            return await tailor_single_job(job)

    tasks = [process_with_sem(job) for job in jobs]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in raw_results:
        if isinstance(r, dict):
            results.append(r)
        elif isinstance(r, Exception):
            logger.error(f"Tailoring task exception: {r}")

    logger.success(f"✅ Resume tailoring complete: {len(results)}/{len(jobs)} succeeded")
    return results
