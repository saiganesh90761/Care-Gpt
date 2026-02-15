"""
Parse uploaded health documents (EHR/EMR) - text extraction and field detection.
Supports .txt and .pdf; returns structured patient-like dict for triage input.
"""
import re
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None


def extract_text_from_pdf(file_path: str) -> str:
    if not PyPDF2:
        return ""
    text = []
    with open(file_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            text.append(page.extract_text() or "")
    return "\n".join(text)


def extract_text_from_file(file_path: str) -> str:
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(file_path)
    if suffix in (".txt", ".json", ".csv"):
        return path.read_text(encoding="utf-8", errors="ignore")
    return path.read_text(encoding="utf-8", errors="ignore")


# Common EHR/EMR field patterns (case-insensitive)
PATTERNS = {
    "age": re.compile(r"\b(?:age|DOB|date of birth|y\.?o\.?|years old)\s*[:\-=]?\s*(\d{1,3})\b", re.I),
    "gender": re.compile(r"\b(?:gender|sex)\s*[:\-=]?\s*(male|female|other|m|f)\b", re.I),
    "symptoms": re.compile(r"\b(?:symptoms?|complaint|chief complaint|presenting)\s*[:\-=]?\s*(.+?)(?=\n\n|\n\w+[\s]*[:\-=]|$)", re.I | re.S),
    "blood_pressure": re.compile(r"\b(?:BP|blood pressure|B\/P)\s*[:\-=]?\s*(\d{2,3})\s*\/\s*(\d{2,3})", re.I),
    "heart_rate": re.compile(r"\b(?:HR|heart rate|pulse|BPM)\s*[:\-=]?\s*(\d{2,3})\b", re.I),
    "temperature": re.compile(r"\b(?:temp|temperature|T)\s*[:\-=]?\s*(\d{2}\.?\d*)\s*°?[CF]?\b", re.I),
    "conditions": re.compile(r"\b(?:conditions?|diagnosis|history|pre-?existing|comorbidities?)\s*[:\-=]?\s*(.+?)(?=\n\n|\n\w+[\s]*[:\-=]|$)", re.I | re.S),
}


def parse_document_to_patient(file_path: str) -> Dict[str, Any]:
    raw = extract_text_from_file(file_path)
    out = {
        "age": None,
        "gender": "",
        "symptoms": "",
        "blood_pressure_systolic": None,
        "blood_pressure_diastolic": None,
        "heart_rate": None,
        "temperature": None,
        "pre_existing_conditions": [],
        "raw_snippet": raw[:1500] if raw else "",
    }

    m = PATTERNS["age"].search(raw)
    if m:
        val = int(m.group(1))
        out["age"] = min(120, max(1, val))

    m = PATTERNS["gender"].search(raw)
    if m:
        g = m.group(1).lower()
        out["gender"] = "Female" if g in ("f", "female") else "Male" if g in ("m", "male") else m.group(1)

    m = PATTERNS["symptoms"].search(raw)
    if m:
        out["symptoms"] = re.sub(r"\s+", " ", m.group(1).strip())[:2000]

    m = PATTERNS["blood_pressure"].search(raw)
    if m:
        out["blood_pressure_systolic"] = int(m.group(1))
        out["blood_pressure_diastolic"] = int(m.group(2))

    m = PATTERNS["heart_rate"].search(raw)
    if m:
        out["heart_rate"] = int(m.group(1))

    m = PATTERNS["temperature"].search(raw)
    if m:
        try:
            out["temperature"] = float(m.group(1).replace(",", "."))
        except ValueError:
            pass

    m = PATTERNS["conditions"].search(raw)
    if m:
        block = m.group(1)
        parts = re.split(r"[,;]|\n", block)
        out["pre_existing_conditions"] = [p.strip() for p in parts if p.strip()][:20]

    if not out["symptoms"] and out["raw_snippet"]:
        out["symptoms"] = "Symptoms not explicitly listed in document. Please review raw notes."
    return out
