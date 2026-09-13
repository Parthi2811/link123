"""
agents/apply_agent.py
LinkedIn Easy Apply automation agent.
Fills multi-step application forms and uploads tailored resumes.
"""
import asyncio
import random
from pathlib import Path
from loguru import logger
from playwright.async_api import Page
from tools.browser import human_delay, human_type
from tools.llm import llm_client
from tools.db import update_job_status
from config import settings as cfg
from config.settings import (
    APPLICANT_NAME,
    APPLICANT_EMAIL,
    APPLICANT_PHONE,
    APPLICANT_LOCATION,
    HUMAN_IN_THE_LOOP,
)



async def _close_open_modal(page: Page) -> None:
    """Close any open Easy Apply dialog and confirm discard."""
    try:
        close = await page.query_selector(
            "button[aria-label='Dismiss'], button[data-test-modal-close-btn], .artdeco-modal__dismiss"
        )
        if close:
            await close.click()
            await human_delay(500, 1000)
            # Confirm discard if prompted
            discard = await page.query_selector(
                "button[data-control-name='discard_application_confirm_btn'], "
                "button[data-test-dialog-primary-btn], "
                "button:has-text('Discard')"
            )
            if discard:
                await discard.click()
                await human_delay(500, 1000)
    except Exception:
        pass


async def _fill_text_field(page: Page, field, value: str) -> None:
    """Clear and fill a text input field."""
    try:
        await field.click()
        await human_delay(200, 500)
        # Clear existing value
        await field.triple_click()
        await human_delay(100, 200)
        await field.type(value, delay=60 + random.randint(-20, 40))
    except Exception as e:
        logger.debug(f"Field fill error: {e}")


async def _handle_screening_questions(
    page: Page,
    resume_summary: str,
    job_title: str = "",
    company: str = "",
) -> None:
    """
    Intelligently detect, answer, and review LinkedIn screening questions.
    Uses LLM for answering with confidence scoring.
    Triggers interactive human review if any question's confidence < 75.
    """
    try:
        questions_to_solve = []
        element_refs = {}

        # ── 1. Text & Numeric Inputs ───────────────────────────────────────────
        text_inputs = await page.query_selector_all(
            ".jobs-easy-apply-form-section__grouping input[type='text'], "
            ".jobs-easy-apply-form-section__grouping input[type='number'], "
            ".jobs-easy-apply-form-section__grouping input[type='tel'], "
            ".jobs-easy-apply-form-section__grouping textarea"
        )
        for idx, input_el in enumerate(text_inputs):
            input_id = await input_el.get_attribute("id") or f"text_{idx}"
            label_el = await page.query_selector(f"label[for='{input_id}']")
            if not label_el:
                parent = await input_el.evaluate_handle("el => el.closest('.jobs-easy-apply-form-section__grouping')")
                label_el = await parent.query_selector("label") if parent else None

            label_text = (await label_el.inner_text()).strip() if label_el else ""
            current_val = (await input_el.input_value()).strip()
            if current_val:
                continue

            # Standard direct fields
            lower = label_text.lower()
            if any(kw in lower for kw in ["first name", "given name"]):
                await _fill_text_field(page, input_el, APPLICANT_NAME.split()[0])
            elif any(kw in lower for kw in ["last name", "surname", "family name"]):
                parts = APPLICANT_NAME.split()
                await _fill_text_field(page, input_el, parts[-1] if len(parts) > 1 else "")
            elif "email" in lower:
                await _fill_text_field(page, input_el, APPLICANT_EMAIL)
            elif any(kw in lower for kw in ["phone", "mobile", "contact number"]):
                await _fill_text_field(page, input_el, APPLICANT_PHONE)
            elif any(kw in lower for kw in ["city", "current location"]):
                await _fill_text_field(page, input_el, APPLICANT_LOCATION)
            else:
                is_numeric = any(kw in lower for kw in ["year", "experience", "salary", "rate", "how many"]) or \
                             (await input_el.get_attribute("inputmode")) == "numeric"
                q_obj = {
                    "id": input_id,
                    "type": "numeric" if is_numeric else "text",
                    "question": label_text,
                    "options": [],
                }
                questions_to_solve.append(q_obj)
                element_refs[input_id] = ("input", input_el)

        # ── 2. Radio Button Groups ─────────────────────────────────────────────
        radio_groups = await page.query_selector_all(
            "fieldset[data-test-form-builder-radio-button-form-component='true'], "
            ".jobs-easy-apply-form-section__grouping:has(input[type='radio']), "
            "fieldset:has(input[type='radio'])"
        )
        for g_idx, group in enumerate(radio_groups):
            legend_el = await group.query_selector("legend, .fb-form-element-label, span.t-14")
            group_question = (await legend_el.inner_text()).strip() if legend_el else f"Question {g_idx + 1}"

            # Check if an option is already selected in this group
            checked = await group.query_selector("input[type='radio']:checked")
            if checked:
                continue

            radios = await group.query_selector_all("input[type='radio']")
            radio_data = []
            for r in radios:
                r_id = await r.get_attribute("id")
                r_label = await page.query_selector(f"label[for='{r_id}']")
                label_txt = (await r_label.inner_text()).strip() if r_label else (await r.get_attribute("value") or "")
                radio_data.append((label_txt, r))

            if radio_data:
                g_id = f"radio_group_{g_idx}"
                options = [txt for txt, _ in radio_data if txt]
                questions_to_solve.append({
                    "id": g_id,
                    "type": "radio",
                    "question": group_question,
                    "options": options,
                })
                element_refs[g_id] = ("radio", radio_data)

        # ── 3. Select Dropdowns ────────────────────────────────────────────────
        dropdowns = await page.query_selector_all(
            ".jobs-easy-apply-form-section__grouping select"
        )
        for d_idx, select_el in enumerate(dropdowns):
            s_id = await select_el.get_attribute("id") or f"select_{d_idx}"
            label_el = await page.query_selector(f"label[for='{s_id}']")
            label_text = (await label_el.inner_text()).strip() if label_el else f"Selection {d_idx + 1}"

            # Check if already selected
            curr_val = await select_el.input_value()
            if curr_val and curr_val != "Select an option":
                continue

            opt_els = await select_el.query_selector_all("option")
            options = [(await opt.inner_text()).strip() for opt in opt_els]
            options = [o for o in options if o and "select" not in o.lower()]

            if options:
                questions_to_solve.append({
                    "id": s_id,
                    "type": "select",
                    "question": label_text,
                    "options": options,
                })
                element_refs[s_id] = ("select", select_el)

        # ── 4. Checkboxes ──────────────────────────────────────────────────────
        checkboxes = await page.query_selector_all(
            ".jobs-easy-apply-form-section__grouping input[type='checkbox']"
        )
        for c_idx, chk in enumerate(checkboxes):
            if await chk.is_checked():
                continue
            c_id = await chk.get_attribute("id") or f"chk_{c_idx}"
            label_el = await page.query_selector(f"label[for='{c_id}']")
            label_text = (await label_el.inner_text()).strip() if label_el else f"Agreement {c_idx + 1}"
            questions_to_solve.append({
                "id": c_id,
                "type": "checkbox",
                "question": label_text,
                "options": ["true", "false"],
            })
            element_refs[c_id] = ("checkbox", chk)

        if not questions_to_solve:
            return

        logger.info(f"🔎 Detected {len(questions_to_solve)} screening questions on this step. Resolving with AI...")

        # ── 5. AI Resolution with Confidence Scoring ───────────────────────────
        resolved_answers = await llm_client.resolve_screening_questions(
            questions=questions_to_solve,
            resume_context=resume_summary,
            job_title=job_title,
            company=company,
        )
        ans_map = {item.get("id"): item for item in resolved_answers if item.get("id")}

        # ── 6. Human In The Loop for Low-Confidence (< 75%) ────────────────────
        low_confidence_items = []
        for q in questions_to_solve:
            item = ans_map.get(q["id"], {})
            conf = item.get("confidence", 60)
            if conf < 75:
                low_confidence_items.append((q, item))

        if low_confidence_items:
            logger.warning(
                f"\n{'=' * 65}\n"
                f"🤔 HUMAN IN THE LOOP — {len(low_confidence_items)} Question(s) With Confidence < 75%\n"
                f"Job: {job_title} @ {company}\n"
                f"{'=' * 65}"
            )
            for idx, (q, item) in enumerate(low_confidence_items, 1):
                q_text = q["question"]
                q_opts = f" (Options: {', '.join(q['options'])})" if q.get("options") else ""
                sug_ans = item.get("answer", "")
                conf = item.get("confidence", 60)
                reason = item.get("reasoning", "")

                print(f"\n[{idx}/{len(low_confidence_items)}] Question: {q_text}{q_opts}")
                print(f"      🤖 AI Suggestion: \"{sug_ans}\"  [Confidence: {conf}% | {reason}]")
                try:
                    user_resp = input(f"      👉 Press ENTER to accept \"{sug_ans}\", or type custom answer: ").strip()
                    if user_resp:
                        item["answer"] = user_resp
                        item["confidence"] = 100
                        logger.info(f"      ✓ User provided: \"{user_resp}\"")
                    else:
                        logger.info(f"      ✓ Accepted AI suggestion: \"{sug_ans}\"")
                except EOFError:
                    pass

            print(f"{'=' * 65}\n")

        # ── 7. Fill Form Elements on Page ──────────────────────────────────────
        for q in questions_to_solve:
            q_id = q["id"]
            final_item = ans_map.get(q_id, {})
            ans_val = str(final_item.get("answer", "")).strip()
            if not ans_val or q_id not in element_refs:
                continue

            elem_type, elem_ref = element_refs[q_id]

            if elem_type == "input":
                if q.get("type") == "numeric":
                    digits = re.sub(r"[^\d]", "", ans_val)
                    ans_val = digits if digits else "3"
                await _fill_text_field(page, elem_ref, ans_val)

            elif elem_type == "radio":
                clicked = False
                for opt_txt, r_el in elem_ref:
                    if ans_val.lower() in opt_txt.lower() or opt_txt.lower() in ans_val.lower():
                        await r_el.click()
                        clicked = True
                        break
                if not clicked and elem_ref:
                    await elem_ref[0][1].click()

            elif elem_type == "select":
                try:
                    await elem_ref.select_option(label=ans_val)
                except Exception:
                    try:
                        options = await elem_ref.query_selector_all("option")
                        for idx, opt in enumerate(options):
                            if ans_val.lower() in (await opt.inner_text()).lower():
                                await elem_ref.select_option(index=idx)
                                break
                    except Exception:
                        pass

            elif elem_type == "checkbox":
                if ans_val.lower() in ("true", "yes", "1"):
                    if not await elem_ref.is_checked():
                        await elem_ref.click()

            await human_delay(200, 400)

        # ── 8. Check for Inline Errors & Log Warnings ──────────────────────────
        errors = await page.query_selector_all(".artdeco-inline-feedback--error")
        for err in errors:
            err_text = (await err.inner_text()).strip()
            if err_text:
                logger.warning(f"⚠️ LinkedIn form validation warning: {err_text}")

    except Exception as e:
        logger.warning(f"⚠️ Screening question handler error: {e}")



async def apply_to_job(page: Page, job: dict) -> bool:
    """
    Apply to a single LinkedIn job via Easy Apply.

    Args:
        page: Active Playwright page
        job: Job dict with 'job_url', 'title', 'company', 'resume_path'

    Returns:
        True if application submitted successfully
    """
    job_id      = job["job_id"]
    title       = job["title"]
    company     = job["company"]
    resume_path = job.get("resume_path", "")
    tailored_data = job.get("tailored_data", {})
    resume_summary = tailored_data.get("summary", "") if tailored_data else ""

    if cfg.DRY_RUN:
        logger.info(f"🌵 DRY RUN — Would apply to: {title} @ {company}")
        await update_job_status(job_id, "APPLIED", resume_path=resume_path, notes="DRY_RUN")
        return True

    logger.info(f"🚀 Applying to: {title} @ {company}")

    try:
        # Navigate to job (already open from scraper, but verify)
        if job.get("job_url") and page.url != job["job_url"]:
            await page.goto(job["job_url"], wait_until="domcontentloaded")
            await human_delay(1500, 2500)

        # Click Easy Apply button (supports both <button> and <a> tags)
        easy_apply_btn = await page.wait_for_selector(
            "button[aria-label*='Easy Apply'], "
            "a[aria-label*='Easy Apply'], "
            "button:has-text('Easy Apply'), "
            "a:has-text('Easy Apply'), "
            ".jobs-apply-button, "
            "a[href*='/apply/']",
            timeout=8000
        )
        await human_delay(500, 1000)
        await easy_apply_btn.click()
        await human_delay(1500, 2500)

        # Multi-step form loop
        step = 0
        max_steps = 10

        while step < max_steps:
            step += 1
            logger.debug(f"  → Form step {step}")
            await human_delay(800, 1500)

            # Upload resume if file upload is present
            if resume_path and Path(resume_path).exists():
                file_input = await page.query_selector("input[type='file']")
                if file_input:
                    await file_input.set_input_files(resume_path)
                    await human_delay(1000, 2000)
                    logger.info(f"📎 Uploaded resume: {Path(resume_path).name}")

            # Handle screening questions with AI + Human-in-the-loop (<75% confidence)
            await _handle_screening_questions(page, resume_summary, job_title=title, company=company)


            # Check for "Next" or "Review" or "Submit" button
            next_btn = await page.query_selector(
                "button[aria-label='Continue to next step'], "
                "button[aria-label='Review your application'], "
                "button.artdeco-button--primary:has-text('Next'), "
                "button:has-text('Next'), "
                "button:has-text('Continue')"
            )
            submit_btn = await page.query_selector(
                "button[aria-label='Submit application'], "
                "button.artdeco-button--primary:has-text('Submit application'), "
                "button:has-text('Submit application'), "
                "button:has-text('Submit')"
            )
            review_btn = await page.query_selector(
                "button[aria-label='Review'], "
                "button.artdeco-button--primary:has-text('Review'), "
                "button:has-text('Review')"
            )

            if submit_btn:
                # Final submit step
                if HUMAN_IN_THE_LOOP:
                    logger.warning(
                        f"\n{'='*60}\n"
                        f"⏸️  HUMAN REVIEW REQUIRED\n"
                        f"Job: {title} @ {company}\n"
                        f"Resume: {resume_path}\n"
                        f"Press ENTER in the terminal to submit, or type 'skip' to skip:\n"
                        f"{'='*60}"
                    )
                    try:
                        user_input = input("→ ").strip().lower()
                        if user_input == "skip":
                            await update_job_status(job_id, "SKIPPED", notes="Skipped by user")
                            # Close dialog
                            close_btn = await page.query_selector("button[aria-label='Dismiss']")
                            if close_btn:
                                await close_btn.click()
                            return False
                    except EOFError:
                        pass  # Non-interactive mode, proceed

                await submit_btn.click()
                await human_delay(2000, 3000)
                logger.success(f"🎉 Application SUBMITTED: {title} @ {company}")
                await update_job_status(job_id, "APPLIED", resume_path=resume_path)
                return True

            elif review_btn:
                await review_btn.click()

            elif next_btn:
                await next_btn.click()

            else:
                logger.warning(f"⚠️ No navigation button found at step {step}")
                break

        logger.warning(f"⚠️ Max steps reached without submission for: {title}")
        await _close_open_modal(page)
        return False

    except Exception as e:
        logger.error(f"❌ Apply failed for {title} @ {company}: {e}")
        await update_job_status(job_id, "FAILED", notes=str(e))
        await _close_open_modal(page)
        return False



async def run_apply_agent(page: Page, jobs: list[dict]) -> dict:
    """
    Main apply agent — submits applications for all tailored jobs.

    Args:
        page: Authenticated Playwright page
        jobs: List of job dicts with resume_path attached

    Returns:
        Summary dict {applied, skipped, failed}
    """
    stats = {"applied": 0, "skipped": 0, "failed": 0}

    for job in jobs:
        if not job.get("resume_path"):
            logger.warning(f"⏭️  No resume path for {job['title']}, skipping")
            stats["skipped"] += 1
            continue

        success = await apply_to_job(page, job)

        if success:
            stats["applied"] += 1
        else:
            if job.get("status") == "SKIPPED":
                stats["skipped"] += 1
            else:
                stats["failed"] += 1

        # Respectful delay between applications (anti-bot)
        await human_delay(3000, 7000)

    logger.success(
        f"📊 Apply agent done — "
        f"Applied: {stats['applied']} | "
        f"Skipped: {stats['skipped']} | "
        f"Failed: {stats['failed']}"
    )
    return stats
