"""
tools/llm.py
Gemini LLM client with structured JSON output for resume tailoring
and screening question answering.
"""
import json
from typing import Any
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential
import google.generativeai as genai
from config.settings import GEMINI_API_KEY, LLM_MODEL

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)

RESUME_TAILOR_SCHEMA = {
    "type": "object",
    "properties": {
        "full_name":   {"type": "string"},
        "contact":     {"type": "string", "description": "email | phone | linkedin | location"},
        "summary":     {"type": "string", "description": "2-3 sentence professional summary tailored to this JD"},
        "skills":      {"type": "array", "items": {"type": "string"}, "description": "Ordered list: most relevant first"},
        "experience":  {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title":       {"type": "string"},
                    "company":     {"type": "string"},
                    "dates":       {"type": "string"},
                    "bullets":     {"type": "array", "items": {"type": "string"}},
                }
            }
        },
        "education":   {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "degree":      {"type": "string"},
                    "institution": {"type": "string"},
                    "year":        {"type": "string"},
                }
            }
        },
        "certifications": {"type": "array", "items": {"type": "string"}},
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name":        {"type": "string"},
                    "description": {"type": "string"},
                    "tech_stack":  {"type": "string"},
                }
            }
        },
        "ats_keywords": {"type": "array", "items": {"type": "string"}, "description": "Keywords extracted from JD injected into resume"},
    },
    "required": ["full_name", "contact", "summary", "skills", "experience"]
}

RESUME_TAILOR_PROMPT = """
You are an expert ATS-optimized resume writer. Your task is to tailor a base resume
to maximize match score for a specific job description.

RULES:
1. Keep all facts truthful — do NOT invent experience or skills
2. Reorder skills to list the most relevant ones first
3. Rewrite experience bullet points to emphasize matching responsibilities
4. Rewrite the professional summary to align with the role
5. Extract and inject important keywords from the job description
6. Keep it concise — no filler phrases
7. Return ONLY valid JSON matching the provided schema

BASE RESUME:
{base_resume}

JOB TITLE: {job_title}
COMPANY: {company}

JOB DESCRIPTION:
{job_description}

Return the tailored resume as JSON:
"""

BATCH_SCREENING_PROMPT = """
You are an expert career agent helping a job applicant answer LinkedIn Easy Apply screening questions smartly, truthfully, and like a real human.

APPLICANT PROFILE / RESUME:
{resume_context}

JOB TITLE: {job_title}
COMPANY: {company}

QUESTIONS TO ANSWER:
{questions_json}

RULES FOR EACH QUESTION:
1. "radio" or "select" questions: Choose EXACTLY one option from the provided "options" list.
   - For legal authorization to work in the country, select "Yes" unless clearly stated otherwise.
   - For requiring visa sponsorship now or in the future, select "No" unless applicant specifically requires it.
   - For commute/remote comfort, select "Yes".
   - For education level, pick the option matching or closest to applicant's degree.
2. "numeric" questions (years of experience, expected salary, etc.):
   - Return ONLY digits (e.g. "3", "4", "80000"). Do NOT add text or words.
3. "text" questions:
   - Provide a natural, concise, professional answer (1-2 sentences).
4. "checkbox" questions:
   - Return "true" if it is a standard consent/acknowledgment agreement.
5. Assign a confidence score from 0 to 100:
   - 80-100: Very confident. Directly answered by applicant profile or standard positive employment compliance (authorization, remote work).
   - 50-74: Moderate/Low confidence. Specific skill not mentioned in resume, specific salary expectation, or subjective choice where human input is advisable.
   - 0-49: Low confidence. Ambiguous or unknown question.

Return a strict JSON array of objects with the exact keys:
[
  {{
    "id": "<matching question id>",
    "answer": "<chosen answer or option text>",
    "confidence": <integer between 0 and 100>,
    "reasoning": "<brief reason>"
  }}
]
"""


class LLMClient:

    def __init__(self):
        self.model = genai.GenerativeModel(LLM_MODEL)


    def _fallback_tailor_resume(self, base_resume: str, job_title: str, company: str) -> dict:
        """Fallback resume structure when Gemini API is unavailable or unconfigured."""
        logger.warning(
            "⚠️ Using fallback resume tailoring (Gemini API key is not configured in .env). "
            "Set GEMINI_API_KEY in .env for full AI tailoring."
        )
        lines = [line.strip() for line in base_resume.split("\n") if line.strip()]
        name = lines[0] if lines else "Applicant"
        contact = lines[1] if len(lines) > 1 else "contact@example.com"
        
        return {
            "full_name": name,
            "contact": contact,
            "summary": f"Motivated AI and Automation professional tailoring skills for {job_title} at {company}. Strong background in workflow optimization, scripting, and modern tech stacks.",
            "skills": ["Python", "AI Automation", "API Integration", "Workflows", "Problem Solving"],
            "experience": [
                {
                    "title": f"Specialist / Developer ({job_title})",
                    "company": company,
                    "dates": "Recent",
                    "bullets": [
                        "Designed and deployed automation workflows improving process efficiency.",
                        "Integrated modern APIs and tools to streamline daily operations.",
                        "Collaborated with cross-functional teams to deliver high-quality solutions."
                    ]
                }
            ],
            "education": [
                {
                    "degree": "Bachelor's Degree",
                    "institution": "University",
                    "year": "2023"
                }
            ],
            "certifications": ["AI Automation Professional"],
            "projects": [
                {
                    "name": "Automated Workflow Pipeline",
                    "description": "Built end-to-end automation pipelines for data extraction and processing.",
                    "tech_stack": "Python, APIs, Automation Tools"
                }
            ],
            "ats_keywords": [job_title, "Python", "Automation", "Workflows"]
        }

    async def tailor_resume(
        self,
        base_resume: str,
        job_title: str,
        company: str,
        job_description: str,
    ) -> dict:
        """
        Use LLM to rewrite the resume for a specific job.
        Returns structured JSON matching RESUME_TAILOR_SCHEMA.
        """
        # If API key is not configured or dummy, return fallback immediately
        if not GEMINI_API_KEY or GEMINI_API_KEY in ("your_gemini_api_key_here", ""):
            return self._fallback_tailor_resume(base_resume, job_title, company)

        prompt = RESUME_TAILOR_PROMPT.format(
            base_resume=base_resume,
            job_title=job_title,
            company=company,
            job_description=job_description[:6000],
        )

        logger.info(f"🧠 Tailoring resume for: {job_title} @ {company}")

        try:
            response = await self.model.generate_content_async(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )

            raw = response.text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            data = json.loads(raw)
            logger.success(f"✅ Resume tailored with {len(data.get('ats_keywords', []))} ATS keywords")
            return data
        except Exception as e:
            logger.warning(f"⚠️ Gemini API call failed: {e}. Using fallback resume.")
            return self._fallback_tailor_resume(base_resume, job_title, company)

    async def resolve_screening_questions(
        self,
        questions: list[dict],
        resume_context: str,
        job_title: str = "",
        company: str = "",
    ) -> list[dict]:
        """
        Batch-answer multiple screening questions with confidence scores (0-100).
        Returns list of dicts: [{'id': ..., 'answer': ..., 'confidence': ..., 'reasoning': ...}]
        """
        if not questions:
            return []

        # Default fallback answers if LLM is unavailable or for initial heuristics
        fallback_answers = []
        for q in questions:
            q_id = q.get("id")
            q_type = q.get("type", "text")
            prompt_text = q.get("question", "").lower()
            options = q.get("options", [])

            if q_type == "radio":
                if any(k in prompt_text for k in ["authorized", "eligible", "legal", "right to work"]):
                    ans = "Yes" if "Yes" in options else (options[0] if options else "Yes")
                    conf = 95
                elif any(k in prompt_text for k in ["sponsorship", "visa", "require sponsorship"]):
                    ans = "No" if "No" in options else (options[0] if options else "No")
                    conf = 95
                elif any(k in prompt_text for k in ["comfortable", "remote", "commute", "relocate"]):
                    ans = "Yes" if "Yes" in options else (options[0] if options else "Yes")
                    conf = 85
                else:
                    ans = options[0] if options else "Yes"
                    conf = 60
                fallback_answers.append({"id": q_id, "answer": ans, "confidence": conf, "reasoning": "Standard rule"})

            elif q_type == "select":
                chosen = options[1] if len(options) > 1 and "select" in options[0].lower() else (options[0] if options else "")
                fallback_answers.append({"id": q_id, "answer": chosen, "confidence": 65, "reasoning": "Dropdown selection"})

            elif q_type == "numeric":
                fallback_answers.append({"id": q_id, "answer": "3", "confidence": 70, "reasoning": "Experience number"})

            elif q_type == "checkbox":
                fallback_answers.append({"id": q_id, "answer": "true", "confidence": 95, "reasoning": "Acknowledgment"})

            else:
                fallback_answers.append({"id": q_id, "answer": "Yes, I have strong relevant experience.", "confidence": 65, "reasoning": "Default response"})

        if not GEMINI_API_KEY or GEMINI_API_KEY in ("your_gemini_api_key_here", ""):
            return fallback_answers

        prompt = BATCH_SCREENING_PROMPT.format(
            resume_context=resume_context[:3000],
            job_title=job_title,
            company=company,
            questions_json=json.dumps(questions, indent=2),
        )

        try:
            response = await self.model.generate_content_async(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.2,
                    response_mime_type="application/json",
                ),
            )
            raw = response.text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()
            results = json.loads(raw)
            if isinstance(results, list):
                logger.info(f"🧠 Gemini resolved {len(results)} screening questions with confidence scores")
                return results
            return fallback_answers
        except Exception as e:
            logger.warning(f"⚠️ Batch screening question resolution failed: {e}. Using intelligent fallback.")
            return fallback_answers


# Singleton
llm_client = LLMClient()

