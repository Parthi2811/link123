# LinkedIn Job Application Agent

A fully autonomous agentic workflow that:
1. 🔐 Logs into LinkedIn (session-cached for speed)
2. 🔍 Searches for remote AI Automation jobs (last 24h)
3. ✍️ Tailors your resume per-job using Gemini LLM
4. 🚀 Applies via Easy Apply with your tailored resume

## Quick Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure credentials
```bash
copy .env.example .env
# Edit .env with your LinkedIn email, password, and Gemini API key
```

### 3. Add your base resume
```
data/base_resume.pdf   ← drop your PDF or DOCX here
```

### 4. Get Gemini API key (free)
→ https://aistudio.google.com/app/apikey

---

## Usage

```bash
# First run — dry run (no submission, just see what happens)
python main.py --dry-run

# Full run with human review before each submit (RECOMMENDED first time)
python main.py

# Auto-submit without review (after you're confident it works)
# Set HUMAN_IN_THE_LOOP=false in .env, then:
python main.py

# Only scrape jobs (no apply)
python main.py --scrape-only

# View application stats
python main.py --stats

# Run on daily schedule (9 AM every day)
python main.py --schedule
```

---

## File Structure

```
linkedin-job-agent/
├── agents/
│   ├── login_agent.py      # LinkedIn auth + session cache
│   ├── scraper_agent.py    # Job search + scrape + filter
│   ├── resume_agent.py     # LLM resume tailoring
│   └── apply_agent.py      # Easy Apply form automation
├── tools/
│   ├── browser.py          # Playwright factory + stealth
│   ├── llm.py              # Gemini LLM client
│   ├── resume_parser.py    # PDF/DOCX parser
│   ├── pdf_builder.py      # Tailored PDF generator
│   └── db.py               # SQLite job tracker
├── graph/
│   └── workflow.py         # LangGraph orchestration
├── config/
│   └── settings.py         # All configuration
├── data/
│   ├── base_resume.pdf     # YOUR resume goes here
│   ├── session.json        # Auto-saved browser session
│   ├── jobs.db             # SQLite job tracking DB
│   └── tailored/           # Generated PDFs per job
├── main.py                 # CLI entrypoint
└── .env                    # Your credentials (never commit!)
```

---

## How It Works

```
ORCHESTRATOR (LangGraph)
    │
    ├─ [1] Login Agent     → Restores session.json or logs in fresh
    ├─ [2] Scraper Agent   → Searches LinkedIn, filters Easy Apply + remote
    ├─ [3] Resume Agent    → Gemini Flash tailors resume for each job
    └─ [4] Apply Agent     → Fills form, uploads PDF, submits
```

## Anti-Detection

- Human-like delays (1-4s between actions)
- Persistent browser session (avoids repeated logins)
- Max 30 applications/day (safe volume)
- Stealth JS to hide `navigator.webdriver`

## ⚠️ Important

- This tool is for **personal use only**
- Automated scraping may violate LinkedIn's Terms of Service
- Use responsibly — recommended max: 20-30 applications/day
- Always review applications before submission (HUMAN_IN_THE_LOOP=true)
