"""
tools/pdf_builder.py
Builds a clean, professional PDF resume from structured JSON data.
"""
import re
from pathlib import Path
from datetime import datetime
from loguru import logger
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable, ListFlowable, ListItem
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER


# ─── Color palette ────────────────────────────────────────────────────────────
PRIMARY   = colors.HexColor("#1a1a2e")
ACCENT    = colors.HexColor("#0f3460")
LIGHT_GRAY = colors.HexColor("#f0f0f0")
MID_GRAY  = colors.HexColor("#666666")


def _clean(text: str) -> str:
    """Strip HTML/special chars for ReportLab."""
    return re.sub(r"<[^>]+>", "", str(text or "")).strip()


def build_resume_pdf(resume_data: dict, output_path: str | Path) -> Path:
    """
    Generate a polished PDF resume from structured JSON.

    Args:
        resume_data: Dict matching RESUME_TAILOR_SCHEMA from llm.py
        output_path: Destination PDF file path

    Returns:
        Path to the generated PDF
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    name_style = ParagraphStyle("Name", fontSize=22, textColor=PRIMARY,
                                 fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=2)
    contact_style = ParagraphStyle("Contact", fontSize=9, textColor=MID_GRAY,
                                    alignment=TA_CENTER, spaceAfter=8)
    section_style = ParagraphStyle("Section", fontSize=11, textColor=ACCENT,
                                    fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=3)
    body_style = ParagraphStyle("Body", fontSize=9.5, textColor=PRIMARY,
                                 leading=14, spaceAfter=2)
    bullet_style = ParagraphStyle("Bullet", fontSize=9, textColor=PRIMARY,
                                   leading=13, leftIndent=12)
    sub_style = ParagraphStyle("Sub", fontSize=9.5, textColor=MID_GRAY,
                                fontName="Helvetica-Oblique", spaceAfter=2)

    story = []

    def section_header(title: str):
        story.append(Spacer(1, 4))
        story.append(Paragraph(title.upper(), section_style))
        story.append(HRFlowable(width="100%", thickness=1, color=ACCENT, spaceAfter=4))

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(Paragraph(_clean(resume_data.get("full_name", "")), name_style))
    story.append(Paragraph(_clean(resume_data.get("contact", "")), contact_style))

    # ── Summary ───────────────────────────────────────────────────────────────
    summary = resume_data.get("summary", "")
    if summary:
        section_header("Professional Summary")
        story.append(Paragraph(_clean(summary), body_style))

    # ── Skills ────────────────────────────────────────────────────────────────
    skills = resume_data.get("skills", [])
    if skills:
        section_header("Skills")
        skills_text = " • ".join(_clean(s) for s in skills)
        story.append(Paragraph(skills_text, body_style))

    # ── Experience ────────────────────────────────────────────────────────────
    experience = resume_data.get("experience", [])
    if experience:
        section_header("Experience")
        for job in experience:
            title_line = f"<b>{_clean(job.get('title', ''))}</b> — {_clean(job.get('company', ''))}"
            story.append(Paragraph(title_line, body_style))
            story.append(Paragraph(_clean(job.get("dates", "")), sub_style))
            for bullet in job.get("bullets", []):
                story.append(Paragraph(f"• {_clean(bullet)}", bullet_style))
            story.append(Spacer(1, 5))

    # ── Projects ──────────────────────────────────────────────────────────────
    projects = resume_data.get("projects", [])
    if projects:
        section_header("Projects")
        for proj in projects:
            story.append(Paragraph(f"<b>{_clean(proj.get('name', ''))}</b>", body_style))
            story.append(Paragraph(_clean(proj.get("description", "")), bullet_style))
            tech = proj.get("tech_stack", "")
            if tech:
                story.append(Paragraph(f"<i>Tech: {_clean(tech)}</i>", sub_style))
            story.append(Spacer(1, 4))

    # ── Education ─────────────────────────────────────────────────────────────
    education = resume_data.get("education", [])
    if education:
        section_header("Education")
        for edu in education:
            story.append(Paragraph(
                f"<b>{_clean(edu.get('degree', ''))}</b> — {_clean(edu.get('institution', ''))}  <i>({_clean(edu.get('year', ''))})</i>",
                body_style,
            ))

    # ── Certifications ────────────────────────────────────────────────────────
    certs = resume_data.get("certifications", [])
    if certs:
        section_header("Certifications")
        for cert in certs:
            story.append(Paragraph(f"• {_clean(cert)}", bullet_style))

    doc.build(story)
    logger.success(f"📄 Resume PDF built: {output_path}")
    return output_path
