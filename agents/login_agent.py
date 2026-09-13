"""
agents/login_agent.py
Handles LinkedIn authentication with session persistence.
Skips login if a valid session already exists.
Supports both login and signup flows.
"""
import asyncio
from loguru import logger
from playwright.async_api import Page, BrowserContext
from tools.browser import browser_manager, human_delay, human_type
from config.settings import LINKEDIN_EMAIL, LINKEDIN_PASSWORD, SESSION_PATH


LINKEDIN_HOME = "https://www.linkedin.com"
LINKEDIN_FEED = "https://www.linkedin.com/feed"
LINKEDIN_LOGIN = "https://www.linkedin.com/login/"
LINKEDIN_SIGNUP = "https://www.linkedin.com/login/"


async def is_logged_in(page: Page) -> bool:
    """Check if we're already authenticated by navigating to feed."""
    try:
        await page.goto(LINKEDIN_FEED, timeout=15000, wait_until="domcontentloaded")
        await human_delay(1000, 2000)
        # If we land on feed, we're logged in
        if "feed" in page.url:
            return True
        # If redirected to login page, we're not logged in
        if "login" in page.url or "authwall" in page.url:
            return False
        return False
    except Exception:
        return False


async def signup(page: Page) -> bool:
    """
    LinkedIn login/signup flow.
    First checks if already logged in.
    If not logged in, uses flexible selectors to fill email and password fields.
    Returns True if login was successful.
    """
    logger.info("📝 Checking LinkedIn authentication status...")

    # First, try to navigate to feed to check if already logged in
    try:
        await page.goto(LINKEDIN_FEED, timeout=10000, wait_until="domcontentloaded")
        await human_delay(1000, 2000)
        
        if "feed" in page.url:
            logger.success("✅ Already signed in - session is valid!")
            logger.info(f"   Current page: {page.url}")
            return True
    except Exception as e:
        logger.debug(f"Feed check failed: {e}")
    
    # Not logged in, proceed with login
    logger.info("🔑 Session expired or not authenticated - proceeding with login...")
    await page.goto(LINKEDIN_LOGIN, wait_until="domcontentloaded")
    await human_delay(2000, 3000)

    try:
        # Log page state for debugging
        logger.debug(f"Current URL: {page.url}")
        
        # Try multiple selector strategies for email/username field
        email_selector = None
        email_selectors = [
            '#username',  # Standard LinkedIn login page
            'input[name="email"]',
            'input[name="username"]',
            'input#email-or-phone',
            'input[id*="email"]',
            'input[placeholder*="Email"]',
            'input[placeholder*="email"]',
            'input[placeholder*="username"]',
        ]
        
        for selector in email_selectors:
            try:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    email_selector = selector
                    logger.info(f"✓ Found email field with selector: {selector}")
                    break
            except Exception as e:
                logger.debug(f"Selector {selector} failed: {e}")
                continue
        
        if not email_selector:
            logger.error("❌ Could not find email field. Available inputs:")
            inputs = await page.query_selector_all('input')
            for i, inp in enumerate(inputs):
                inp_id = await inp.get_attribute('id')
                inp_name = await inp.get_attribute('name')
                inp_type = await inp.get_attribute('type')
                inp_placeholder = await inp.get_attribute('placeholder')
                is_visible = await inp.is_visible()
                logger.info(f"   Input {i}: id={inp_id}, name={inp_name}, type={inp_type}, placeholder={inp_placeholder}, visible={is_visible}")
            return False
        
        # Fill email
        try:
            await page.fill(email_selector, LINKEDIN_EMAIL)
            await human_delay(400, 800)
            logger.info(f"✓ Email filled: {LINKEDIN_EMAIL}")
        except Exception as e:
            logger.error(f"❌ Failed to fill email: {e}")
            return False

        # Try multiple selector strategies for password field
        password_selector = None
        password_selectors = [
            '#password',  # Standard LinkedIn login page
            'input[name="password"]',
            'input[type="password"]',
            'input[id*="password"]',
            'input[placeholder*="Password"]',
            'input[placeholder*="password"]',
        ]
        
        for selector in password_selectors:
            try:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    password_selector = selector
                    logger.info(f"✓ Found password field with selector: {selector}")
                    break
            except Exception as e:
                logger.debug(f"Selector {selector} failed: {e}")
                continue
        
        if not password_selector:
            logger.error("❌ Could not find password field")
            return False
        
        # Fill password
        try:
            await page.fill(password_selector, LINKEDIN_PASSWORD)
            await human_delay(600, 1200)
            logger.info("✓ Password filled")
        except Exception as e:
            logger.error(f"❌ Failed to fill password: {e}")
            return False

        # Look for and click the login button
        submit_button = None
        button_selectors = [
            'button[type="submit"]',
            'button:has-text("Sign in")',
            'button:has-text("Log in")',
            'button[aria-label*="Sign in"]',
        ]
        
        for selector in button_selectors:
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible():
                    submit_button = btn
                    logger.info(f"✓ Found submit button with selector: {selector}")
                    break
            except:
                continue
        
        if submit_button:
            await submit_button.click()
            logger.info("✓ Sign-in button clicked")
            await human_delay(2000, 4000)
        else:
            logger.warning("⚠ Submit button not found, trying keyboard enter")
            await page.press(password_selector, "Enter")
            await human_delay(2000, 4000)

        # Wait for navigation and check URL
        try:
            await page.wait_for_url("**/feed/**", timeout=10000)
            logger.success(f"✅ Logged in successfully as {LINKEDIN_EMAIL}")
            return True
        except:
            logger.debug(f"Feed page not detected. Current URL: {page.url}")
        
        # Check for 2FA after login
        await handle_2fa(page)

        # Final verification
        await human_delay(1000, 2000)
        final_url = page.url
        logger.debug(f"Final URL: {final_url}")
        
        if "feed" in final_url or "checkpoint" not in final_url:
            logger.success(f"✅ Login completed as {LINKEDIN_EMAIL}")
            return True
        else:
            logger.warning(f"⚠ Login may require additional verification. Current URL: {final_url}")
            return False

    except Exception as e:
        logger.error(f"❌ Login error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False



async def handle_2fa(page: Page) -> bool:
    """
    Handle two-factor authentication.
    If 2FA is triggered, send a desktop notification and wait for manual input.
    """
    try:
        # Detect 2FA page (LinkedIn shows a PIN/OTP input)
        pin_input = await page.query_selector("input#input__email_verification_pin")
        if not pin_input:
            pin_input = await page.query_selector("input[name='pin']")

        if pin_input:
            logger.warning("🔐 2FA detected! Check your email/authenticator app.")

            # Desktop notification
            try:
                from plyer import notification
                notification.notify(
                    title="LinkedIn Job Agent — 2FA Required",
                    message="Open the browser and enter your 2FA code to continue.",
                    timeout=30,
                )
            except Exception:
                pass

            # Wait up to 2 minutes for user to fill in OTP
            logger.info("⏳ Waiting up to 120s for 2FA completion...")
            for _ in range(24):  # 24 x 5s = 120s
                await asyncio.sleep(5)
                if "feed" in page.url:
                    logger.success("✅ 2FA completed by user")
                    return True
                if await page.query_selector("input#input__email_verification_pin") is None:
                    break

        return True
    except Exception as e:
        logger.error(f"2FA handler error: {e}")
        return False


async def login(page: Page) -> bool:
    """
    Full LinkedIn login flow.
    Returns True if login was successful.
    """
    logger.info("🔑 Starting LinkedIn login...")

    await page.goto(LINKEDIN_LOGIN, wait_until="domcontentloaded")
    await human_delay(1500, 2500)

    # Fill email
    email_input = await page.wait_for_selector("#username", timeout=10000)
    await human_type(page, "#username", LINKEDIN_EMAIL)
    await human_delay(400, 800)

    # Fill password
    await human_type(page, "#password", LINKEDIN_PASSWORD)
    await human_delay(600, 1200)

    # Click sign in
    await page.click('button[type="submit"]')
    await human_delay(2000, 4000)

    # Check for 2FA
    await handle_2fa(page)

    # Verify login success
    if "feed" in page.url or "checkpoint" not in page.url:
        logger.success(f"✅ Logged in as {LINKEDIN_EMAIL}")
        return True
    else:
        logger.error(f"❌ Login failed. Current URL: {page.url}")
        return False


async def search_jobs(page: Page, job_query: str = "AI automation jobs") -> bool:
    """
    Search for jobs on LinkedIn.
    Returns True if search was successful.
    """
    logger.info(f"🔍 Searching for: {job_query}")
    
    try:
        # Navigate to jobs page with search query
        search_url = f'https://www.linkedin.com/jobs/search/?keywords={job_query.replace(" ", "%20")}'
        logger.info(f"   Navigating to: {search_url}")
        
        await page.goto(search_url, wait_until="domcontentloaded")
        await human_delay(3000, 4000)
        
        logger.success(f"✅ Job search completed for: {job_query}")
        logger.info(f"   Results page: {page.url}")
        logger.info(f"   You can now browse and apply for jobs on this page.")
        return True
        
    except Exception as e:
        logger.error(f"❌ Job search error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


async def run_login_agent() -> tuple[Page, BrowserContext]:
    """
    Main login agent entry point.
    Returns (page, context) ready for further navigation.
    """
    if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
        raise ValueError(
            "LinkedIn credentials missing! "
            "Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env file"
        )

    context = await browser_manager.start()
    page = await browser_manager.new_page()

    # Try restoring existing session first
    if await is_logged_in(page):
        logger.success("🔓 Session still valid — skipping login")
        await browser_manager.save_session()
        return page, context

    # Session expired, do full login
    success = await login(page)
    if not success:
        raise RuntimeError("LinkedIn login failed. Check credentials in .env")

    # Save session for next run
    await browser_manager.save_session()
    return page, context


async def run_signup_agent() -> tuple[Page, BrowserContext]:
    """
    Main signup agent entry point.
    Opens LinkedIn login page and authenticates with credentials.
    Returns (page, context) ready for further navigation.
    """
    if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
        raise ValueError(
            "LinkedIn credentials missing! "
            "Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env file"
        )

    context = await browser_manager.start()
    page = await browser_manager.new_page()

    # Perform login/signup
    success = await signup(page)
    if not success:
        raise RuntimeError("LinkedIn login failed. Check your credentials (.env file) and verify the login page structure.")

    # Save session for next run
    await browser_manager.save_session()
    logger.success("✅ Authentication agent completed successfully")
    
    # Search for AI automation jobs
    logger.info("\n🚀 Proceeding to job search...")
    await human_delay(1000, 2000)
    await search_jobs(page, "AI automation jobs")
    
    return page, context
