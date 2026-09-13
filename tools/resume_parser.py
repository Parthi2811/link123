"""
tools/resume_parser.py
Parse base resume from PDF or DOCX into plain text.
Uses pdfplumber (pure Python, no compiler needed) for PDF parsing.
"""
from pathlib import Path
from loguru import logger


def parse_resume(path: str | Path) -> str:
    """
    Extract plain text from a resume PDF or DOCX.
    Returns the full resume text as a string.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Resume not found at: {path}")

    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _parse_pdf(path)
    elif suffix in (".docx", ".doc"):
        return _parse_docx(path)
    else:
        raise ValueError(f"Unsupported resume format: {suffix}. Use PDF or DOCX.")


def _parse_pdf(path: Path) -> str:
    """Extract text from PDF using pdfplumber (primary) with pypdf fallback."""
    # Primary: pdfplumber — best layout/table preservation
    try:
        import pdfplumber
        text_pages = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(x_tolerance=2, y_tolerance=2)
                if page_text:
                    text_pages.append(page_text)
        text = "\n".join(text_pages)
        if text.strip():
            logger.info(f"📄 Parsed PDF (pdfplumber): {len(text)} chars from {path.name}")
            return text
    except ImportError:
        logger.warning("pdfplumber not found, trying pypdf fallback")
    except Exception as e:
        logger.warning(f"pdfplumber failed ({e}), trying pypdf fallback")

    # Fallback: pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        text = "\n".join(
            page.extract_text() or "" for page in reader.pages
        )
        logger.info(f"📄 Parsed PDF (pypdf): {len(text)} chars from {path.name}")
        return text
    except ImportError:
        raise ImportError(
            "No PDF parser available. Install with: pip install pdfplumber pypdf"
        )


def _parse_docx(path: Path) -> str:
    """Extract text from DOCX using python-docx."""
    try:
        from docx import Document
        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n".join(paragraphs)
        logger.info(f"📄 Parsed DOCX: {len(text)} chars from {path.name}")
        return text
    except ImportError:
        raise ImportError("python-docx not installed. Run: pip install python-docx")
