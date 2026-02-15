"""
Gemini API: chat, EHR/EMR image analysis, prescription image analysis.
Uses Gemini 2.5 Flash. GEMINI_API_KEY from env.
"""
import base64
import os
from typing import Optional

# Model ID for Gemini 2.5 Flash
MODEL_ID = "gemini-2.5-flash"

# Lazy init
_genai = None
_chat_model = None
_vision_model = None


def _configure():
    global _genai, _chat_model, _vision_model
    if _genai is not None:
        return
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")
    try:
        import google.generativeai as genai
        _genai = genai
        genai.configure(api_key=api_key)
        _chat_model = genai.GenerativeModel(MODEL_ID)
        _vision_model = genai.GenerativeModel(MODEL_ID)
    except Exception as e:
        raise RuntimeError(f"Gemini init failed: {e}") from e


def chat(user_message: str, system_hint: Optional[str] = None) -> str:
    """Send a message to Gemini 2.5 Flash and return the model's text reply."""
    _configure()
    prompt = user_message.strip()
    if not prompt:
        return "Please enter a message."
    if system_hint:
        prompt = f"{system_hint}\n\nUser: {prompt}"
    try:
        response = _chat_model.generate_content(prompt)
        if response.text:
            return response.text.strip()
        return "I couldn't generate a response. Please try again."
    except Exception as e:
        return f"Error: {str(e)}"


def analyze_document_text(text: str) -> str:
    """
    Use Gemini 2.5 Flash (Text) to extract structured patient info from raw text (PDF/TXT).
    Returns a single text block with age, gender, symptoms, vitals, conditions.
    """
    _configure()
    prompt = f"""Analyze this medical text (extracted from EHR/EMR). Extract and list:
- Age (number)
- Gender (Male/Female/Other)
- Symptoms (comma-separated)
- Blood pressure (systolic/diastolic if present e.g. 120/80)
- Heart rate (BPM if present)
- Temperature (with unit: F or C)
- Pre-existing conditions (comma-separated)

If a field is not found, write "Not specified". Use this exact format:
Age: ...
Gender: ...
Symptoms: ...
Blood pressure: ...
Heart rate: ...
Temperature: ...
Pre-existing conditions: ...

Text to analyze:
{text[:30000]}
"""
    try:
        response = _chat_model.generate_content(prompt)
        if response.text:
            return response.text.strip()
        return "Could not extract information."
    except Exception as e:
        return f"Error analyzing text: {str(e)}"


def analyze_document_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """
    Use Gemini 2.5 Flash vision to extract structured patient info from an EHR/EMR document image.
    Returns a single text block with age, gender, symptoms, vitals, conditions.
    """
    _configure()
    prompt = """Analyze this medical document (EHR/EMR or health record image). Extract and list:
- Age (number)
- Gender (Male/Female/Other)
- Symptoms (comma-separated)
- Blood pressure (systolic/diastolic if present, e.g. 120/80)
- Heart rate (BPM if present)
- Temperature (with unit: F or C)
- Pre-existing conditions (comma-separated)

If a field is not visible, write "Not specified". Be concise. Use this exact format so it can be parsed:
Age: ...
Gender: ...
Symptoms: ...
Blood pressure: ...
Heart rate: ...
Temperature: ...
Pre-existing conditions: ...
"""
    try:
        image_part = {
            "inline_data": {
                "mime_type": mime_type,
                "data": base64.b64encode(image_bytes).decode("utf-8"),
            }
        }
        response = _vision_model.generate_content([image_part, prompt])
        if response.text:
            return response.text.strip()
        return "Could not extract text from the image. Please ensure the image is clear and contains readable medical information."
    except Exception as e:
        return f"Error analyzing image: {str(e)}"


def analyze_prescription_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """
    Use Gemini 2.5 Flash vision to analyze a prescription image and generate a clear output.
    Returns structured text: medication(s), dosage, frequency, instructions, prescriber, etc.
    """
    _configure()
    prompt = """Analyze this prescription or medication document image. Generate a clear, readable output that includes:

1. **Medication(s)** – Name(s) of the drug(s) prescribed
2. **Dosage** – Amount per dose (e.g. 10mg, 500mg)
3. **Frequency** – How often to take (e.g. twice daily, every 8 hours)
4. **Instructions** – Special instructions (e.g. take with food, before bed)
5. **Duration** – Length of treatment if mentioned (e.g. 7 days, 30 days)
6. **Prescriber** – Doctor or prescriber name if visible
7. **Date** – Prescription date if visible
8. **Notes** – Any warnings, refills, or other relevant information

If something is not visible or unclear, say "Not specified". Format the output in clear sections with the headings above. Be concise but complete."""
    try:
        image_part = {
            "inline_data": {
                "mime_type": mime_type,
                "data": base64.b64encode(image_bytes).decode("utf-8"),
            }
        }
        response = _vision_model.generate_content([image_part, prompt])
        if response.text:
            return response.text.strip()
        return "Could not analyze the prescription image. Please ensure the image is clear and readable."
    except Exception as e:
        return f"Error analyzing prescription: {str(e)}"


def parse_extracted_text_to_patient(text: str) -> dict:
    """
    Parse the Gemini vision output into a patient dict for form pre-fill.
    """
    import re
    out = {
        "age": None,
        "gender": "",
        "symptoms": "",
        "blood_pressure_systolic": None,
        "blood_pressure_diastolic": None,
        "heart_rate": None,
        "temperature": None,
        "pre_existing_conditions": [],
        "raw": text[:2000],
    }
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if re.match(r"age\s*:", line, re.I):
            m = re.search(r"(\d{1,3})", line)
            if m:
                out["age"] = min(120, max(1, int(m.group(1))))
        elif re.match(r"gender\s*:", line, re.I):
            rest = re.sub(r"^gender\s*:\s*", "", line, flags=re.I).strip()
            if rest and "not specified" not in rest.lower():
                out["gender"] = rest.split(",")[0].strip()
        elif re.match(r"symptoms\s*:", line, re.I):
            rest = re.sub(r"^symptoms\s*:\s*", "", line, flags=re.I).strip()
            if rest and "not specified" not in rest.lower():
                out["symptoms"] = rest[:2000]
        elif re.match(r"blood\s*pressure\s*:", line, re.I):
            m = re.search(r"(\d{2,3})\s*/\s*(\d{2,3})", line)
            if m:
                out["blood_pressure_systolic"] = int(m.group(1))
                out["blood_pressure_diastolic"] = int(m.group(2))
        elif re.match(r"heart\s*rate\s*:", line, re.I):
            m = re.search(r"(\d{2,3})", line)
            if m:
                out["heart_rate"] = int(m.group(1))
        elif re.match(r"temperature\s*:", line, re.I):
            m = re.search(r"([\d.]+)\s*°?\s*[CF]?", line, re.I)
            if m:
                try:
                    val = float(m.group(1))
                    if " F" in line.upper() or "°F" in line or (val > 50 and val < 120):
                        out["temperature"] = round((val - 32) * 5 / 9, 1)  # F to C
                    else:
                        out["temperature"] = val
                except ValueError:
                    pass
                except Exception:
                    pass
        elif re.match(r"pre-existing\s*conditions\s*:", line, re.I) or re.match(r"pre\s*existing\s*conditions\s*:", line, re.I):
            rest = re.sub(r"^pre-?existing\s*conditions\s*:\s*", "", line, flags=re.I).strip()
            if rest and "not specified" not in rest.lower():
                out["pre_existing_conditions"] = [x.strip() for x in re.split(r"[,;]", rest) if x.strip()][:20]
    return out


def generate_triage_from_text(text: str) -> dict:
    """
    Directly analyze medical text and produce a triage result using Gemini.
    Returns a dict compatible with TriageResult structure.
    """
    _configure()
    prompt = f"""You are an advanced medical triage AI. Analyze the following medical report or text and produce a triage assessment.
    
Text to analyze:
{text[:30000]}

Provide the output in valid JSON format with the following keys:
- risk_level: "High", "Medium", or "Low"
- recommended_department: The most appropriate medical department (e.g. Cardiology, Neurology, General Medicine)
- summary: A brief explanation of the assessment (max 2 sentences)
- confidence_score: A number between 0.0 and 1.0 representing confidence
- contributing_factors: A list of objects, each with "factor", "impact" ("high"/"medium"/"low"), and "description"
- patient_vitals: Object with inferred age, gender, symptoms list

Do not include markdown formatting (like ```json), just the raw JSON string.
"""
    try:
        response = _chat_model.generate_content(prompt)
        raw = response.text.replace("```json", "").replace("```", "").strip()
        import json
        return json.loads(raw)
    except Exception as e:
        return {
            "risk_level": "Unknown",
            "recommended_department": "General Medicine",
            "summary": f"AI analysis failed: {str(e)}",
            "confidence_score": 0.0,
            "contributing_factors": []
        }
