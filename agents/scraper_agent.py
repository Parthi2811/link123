"""
agents/scraper_agent.py
Searches LinkedIn for AI automation remote jobs, scrapes full job details,
filters them, and stores them to the SQLite database.
"""
import asyncio
import re
import random
from typing import List, Optional
from loguru import logger
from playwright.async_api import Page
from tools.browser import human_delay
from tools.db import insert_job, job_exists, update_job_status
from config import settings as cfg
from config.settings import (
    build_search_url,
    JOB_KEYWORDS,
    INCLUDE_KEYWORDS,
    EXCLUDE_KEYWORDS,
)



def _extract_job_id(url: str) -> Optional[str]:
    """Extract LinkedIn job ID from URL."""
    match = re.search(r"/jobs/view/(\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"currentJobId=(\d+)", url)
    return match.group(1) if match else None


def _score_job(title: str, description: str) -> int:
    """
    Score a job 0-100 based on keyword relevance.
    Higher score = more relevant.
    """
    text = (title + " " + description).lower()
    score = 0
    for kw in INCLUDE_KEYWORDS:
        if kw.lower() in text:
            score += 10
    for kw in EXCLUDE_KEYWORDS:
        if kw.lower() in text:
            score -= 30
    return max(0, min(100, score))


def _is_relevant(title: str, description: str) -> bool:
    """Return True if the job passes the relevance filter."""
    score = _score_job(title, description)
    return score >= 10  # At least one matching keyword


async def _expand_job_description(page: Page) -> str:
    """Click 'See more' to expand truncated job descriptions."""
    try:
        see_more = await page.query_selector(
            "button.jobs-description__footer-button, "
            "button[aria-label*='See more'], "
            ".jobs-description__content button, "
            "#job-details button, "
            "button:has-text('See more')"
        )
        if see_more:
            await see_more.click()
            await human_delay(400, 800)
    except Exception:
        pass

    # Extract full description text
    desc_el = await page.query_selector(
        ".jobs-description__content, "
        ".jobs-description-content__text, "
        "#job-details, "
        ".jobs-description, "
        ".jobs-box__html-content, "
        ".jobs-details__main-content"
    )
    if desc_el:
        return (await desc_el.inner_text()).strip()
    return ""


async def _scrape_job_card(page: Page, card_selector) -> Optional[dict]:
    """
    Click a job card and extract all job details.
    Returns structured job dict or None if failed.
    """
    try:
        # Scroll and click
        try:
            link = await card_selector.query_selector("a.job-card-list__title, a.job-card-container__link, a[href*='/jobs/view/'], a")
            if link:
                await link.scroll_into_view_if_needed()
                await link.click()
            else:
                await card_selector.scroll_into_view_if_needed()
                await card_selector.click()
        except Exception:
            await card_selector.click()

        await human_delay(1000, 2000)

        # Wait for detail panel to load (resilient selectors, short timeout)
        detail_selectors = (
            ".job-details-jobs-unified-top-card__container--two-pane, "
            ".job-details-jobs-unified-top-card, "
            ".jobs-details__main-content, "
            ".jobs-search__job-details, "
            ".jobs-unified-top-card, "
            ".jobs-details-top-card, "
            ".scaffold-layout__detail, "
            "[data-view-name='job-details'], "
            ".jobs-description, "
            "#job-details"
        )
        try:
            await page.wait_for_selector(detail_selectors, timeout=4000)
        except Exception:
            pass

        # Extract metadata with fallbacks
        title_el = await page.query_selector(
            "h1.job-details-jobs-unified-top-card__job-title, "
            ".job-details-jobs-unified-top-card__job-title, "
            "h2.job-details-jobs-unified-top-card__job-title, "
            ".jobs-unified-top-card__job-title, "
            "h1.jobs-unified-top-card__job-title, "
            ".jobs-details h1, "
            ".scaffold-layout__detail h1, "
            "h1"
        )
        card_title_el = await card_selector.query_selector(
            ".job-card-list__title, a.job-card-container__link, strong"
        )

        company_el = await page.query_selector(
            ".job-details-jobs-unified-top-card__company-name a, "
            ".job-details-jobs-unified-top-card__company-name, "
            ".jobs-unified-top-card__company-name a, "
            ".jobs-unified-top-card__company-name, "
            ".jobs-unified-top-card__subtitle-primary-grouping a, "
            ".job-details-jobs-unified-top-card__primary-description a"
        )
        card_company_el = await card_selector.query_selector(
            ".job-card-container__primary-description, .artdeco-entity-lockup__subtitle"
        )

        location_el = await page.query_selector(
            ".job-details-jobs-unified-top-card__primary-description-container, "
            ".job-details-jobs-unified-top-card__workplace-type, "
            ".jobs-unified-top-card__bullet, "
            ".jobs-unified-top-card__workplace-type, "
            ".job-details-jobs-unified-top-card__primary-description"
        )
        card_location_el = await card_selector.query_selector(
            ".job-card-container__metadata-item"
        )

        posted_el = await page.query_selector(
            ".jobs-unified-top-card__posted-date, "
            ".job-details-jobs-unified-top-card__primary-description span:has-text('ago'), "
            "span.tvm__text:has-text('ago')"
        )

        title = (await title_el.inner_text()).strip() if title_el else ""
        if not title and card_title_el:
            title = (await card_title_el.inner_text()).strip()
        title = title or "Unknown Title"

        company = (await company_el.inner_text()).strip() if company_el else ""
        if not company and card_company_el:
            company = (await card_company_el.inner_text()).strip()
        company = company or "Unknown Company"

        location = (await location_el.inner_text()).strip() if location_el else ""
        if not location and card_location_el:
            location = (await card_location_el.inner_text()).strip()
        location = location or "Remote"

        posted = (await posted_el.inner_text()).strip() if posted_el else ""

        # Extract job URL and ID
        job_url = page.url
        card_link = await card_selector.query_selector(
            "a[href*='/jobs/view/'], a.job-card-container__link, a.job-card-list__title"
        )
        if card_link:
            href = await card_link.get_attribute("href")
            if href and "/jobs/view/" in href:
                job_url = f"https://www.linkedin.com{href}" if href.startswith("/") else href

        job_id = _extract_job_id(job_url) or re.sub(r'\W+', '_', f"{title}_{company}")

        # Check Easy Apply button
        easy_apply_btn = await page.query_selector(
            "button.jobs-apply-button[aria-label*='Easy Apply'], "
            ".jobs-apply-button--top-card, "
            "button[aria-label*='Easy Apply'], "
            "button.jobs-apply-button:has-text('Easy Apply')"
        )
        card_easy_apply = await card_selector.query_selector(
            ".job-card-container__apply-method, :has-text('Easy Apply')"
        )
        easy_apply = (easy_apply_btn is not None) or (card_easy_apply is not None)

        # Expand and extract full JD
        description = await _expand_job_description(page)
        if not description:
            try:
                card_desc = await card_selector.inner_text()
                description = f"{title} at {company}. {card_desc}"
            except Exception:
                description = f"{title} at {company}"

        return {
            "job_id":      job_id,
            "title":       title,
            "company":     company,
            "location":    location,
            "posted_date": posted,
            "job_url":     job_url,
            "description": description,
            "easy_apply":  easy_apply,
        }

    except Exception as e:
        logger.warning(f"⚠️ Failed to scrape job card: {e}")
        return None



async def run_scraper_agent(page: Page) -> List[dict]:
    """
    Main scraper agent.
    Returns list of new jobs found and stored in DB.
    """
    logger.info(f"🔍 Searching for: '{JOB_KEYWORDS}' (Remote)")

    search_url = build_search_url()
    await page.goto(search_url, wait_until="domcontentloaded")
    await human_delay(2000, 3500)

    jobs_found = []
    jobs_processed = 0
    page_num = 0

    while jobs_processed < cfg.MAX_JOBS_PER_RUN:
        # Get all job cards on current page
        cards = await page.query_selector_all(
            ".jobs-search-results__list-item, "
            ".scaffold-layout__list-item"
        )

        if not cards:
            logger.info("No job cards found on this page")
            break

        logger.info(f"📋 Found {len(cards)} job cards on page {page_num + 1}")

        for card in cards:
            if jobs_processed >= cfg.MAX_JOBS_PER_RUN:
                break

            job_data = await _scrape_job_card(page, card)
            if not job_data:
                continue

            job_id = job_data["job_id"]

            # Skip if already in DB
            if await job_exists(job_id):
                logger.debug(f"⏭️  Already seen: {job_data['title']}")
                continue

            # Skip non-Easy-Apply jobs (optional: remove to include external apply)
            if not job_data["easy_apply"]:
                logger.debug(f"⏭️  No Easy Apply: {job_data['title']}")
                await update_job_status(job_id, "SKIPPED", notes="No Easy Apply")
                await insert_job({**job_data, "status": "SKIPPED"})
                continue

            # Relevance filter
            if not _is_relevant(job_data["title"], job_data["description"]):
                logger.debug(f"⏭️  Not relevant: {job_data['title']}")
                await insert_job(job_data)
                await update_job_status(job_id, "SKIPPED", notes="Low relevance score")
                continue

            # Store as PENDING
            await insert_job(job_data)
            jobs_found.append(job_data)
            jobs_processed += 1
            logger.info(f"✅ [{jobs_processed}/{cfg.MAX_JOBS_PER_RUN}] Queued: {job_data['title']} @ {job_data['company']}")

            # Human-like pause between cards
            await human_delay(800, 1800)

        # Try going to next page
        try:
            next_btn = await page.query_selector("button[aria-label='Page %d']" % (page_num + 2))
            if not next_btn:
                next_btn = await page.query_selector(".artdeco-pagination__button--next")
            if next_btn:
                await next_btn.click()
                await human_delay(2000, 4000)
                page_num += 1
            else:
                logger.info("📄 No more pages")
                break
        except Exception:
            break

    logger.success(f"🎯 Scraping complete: {len(jobs_found)} new jobs queued")
    return jobs_found
