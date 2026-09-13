from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
TAILORED_DIR = DATA_DIR / "tailored"
SESSION_PATH = DATA_DIR / "session.json"
DB_PATH = DATA_DIR / "jobs.db"
BASE_RESUME_PATH = Path(os.getenv("BASE_RESUME_PATH", str(DATA_DIR / "base_resume.pdf")))
if not BASE_RESUME_PATH.exists() and (DATA_DIR / "base_resume.pdf.pdf").exists():
    BASE_RESUME_PATH = DATA_DIR / "base_resume.pdf.pdf"

# Create dirs
DATA_DIR.mkdir(exist_ok=True)
TAILORED_DIR.mkdir(exist_ok=True)

# ─── LinkedIn Credentials ─────────────────────────────────────────────────────
LINKEDIN_EMAIL: str = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD: str = os.getenv("LINKEDIN_PASSWORD", "")

# ─── LLM ──────────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-3.6-flash")

# ─── Job Search ───────────────────────────────────────────────────────────────
JOB_KEYWORDS: str = os.getenv("JOB_KEYWORDS", "AI Automation")
JOB_LOCATION: str = os.getenv("JOB_LOCATION", "Remote")
MAX_JOBS_PER_RUN: int = int(os.getenv("MAX_JOBS_PER_RUN", "30"))
POSTED_WITHIN_HOURS: int = int(os.getenv("POSTED_WITHIN_HOURS", "24"))

# Keywords that increase priority
INCLUDE_KEYWORDS = [
    "AI", "Automation", "LLM", "Agentic", "Python", "n8n",
    "Make.com", "Zapier", "Machine Learning", "NLP", "GPT",
    "OpenAI", "LangChain", "Workflow", "RPA"
]

# Job titles that should be skipped
EXCLUDE_KEYWORDS = [
    "Senior Director", "VP of", "C-Level", "Manual QA only"
]

# ─── Browser Settings ─────────────────────────────────────────────────────────
HEADLESS: bool = os.getenv("HEADLESS", "false").lower() == "true"
SLOW_MO: int = int(os.getenv("SLOW_MO", "80"))  # ms between actions

# ─── Application Mode ─────────────────────────────────────────────────────────
HUMAN_IN_THE_LOOP: bool = os.getenv("HUMAN_IN_THE_LOOP", "true").lower() == "true"
DRY_RUN: bool = os.getenv("DRY_RUN", "false").lower() == "true"

# ─── Your Contact Info (for form fill) ───────────────────────────────────────
APPLICANT_NAME: str = os.getenv("APPLICANT_NAME", "Your Name")
APPLICANT_EMAIL: str = os.getenv("APPLICANT_EMAIL", LINKEDIN_EMAIL)
APPLICANT_PHONE: str = os.getenv("APPLICANT_PHONE", "+91-XXXXXXXXXX")
APPLICANT_LOCATION: str = os.getenv("APPLICANT_LOCATION", "India (Remote)")

# ─── LinkedIn Search URL Template ────────────────────────────────────────────
def build_search_url(keywords: str = JOB_KEYWORDS, hours: int = POSTED_WITHIN_HOURS) -> str:
    """Build LinkedIn job search URL with remote + time + Easy Apply filters."""
    from urllib.parse import quote
    keywords_encoded = quote(keywords)
    time_seconds = hours * 3600
    return (
        f"https://www.linkedin.com/jobs/search/"
        f"?keywords={keywords_encoded}"
        f"&f_WT=2"                # Remote only
        f"&f_AL=true"             # Easy Apply only!
        f"&f_TPR=r{time_seconds}" # Posted within N hours
        f"&sortBy=DD"             # Sort by date
    )

