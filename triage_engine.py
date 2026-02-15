"""
AI-Powered Triage Engine: Risk classification, department recommendation, explainability.
Uses rule-based + weighted scoring; can be replaced/extended with ML model.
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional

# --- Risk thresholds (configurable) ---
RISK_LOW = "Low"
RISK_MEDIUM = "Medium"
RISK_HIGH = "High"

DEPARTMENTS = [
    "General Medicine",
    "Cardiology",
    "Emergency",
    "Neurology",
    "Pulmonology",
    "Gastroenterology",
    "Dermatology",
    "Orthopedics",
]

# Symptom -> department hints (simplified mapping)
SYMPTOM_DEPARTMENT_MAP = {
    "chest pain": "Cardiology",
    "palpitation": "Cardiology",
    "heart": "Cardiology",
    "shortness of breath": "Pulmonology",
    "cough": "Pulmonology",
    "asthma": "Pulmonology",
    "headache": "Neurology",
    "dizziness": "Neurology",
    "seizure": "Neurology",
    "stroke": "Neurology",
    "numbness": "Neurology",
    "fever": "General Medicine",
    "vomiting": "Gastroenterology",
    "abdominal": "Gastroenterology",
    "diarrhea": "Gastroenterology",
    "rash": "Dermatology",
    "skin": "Dermatology",
    "joint pain": "Orthopedics",
    "fracture": "Orthopedics",
    "bleeding": "Emergency",
    "unconscious": "Emergency",
    "severe pain": "Emergency",
    "trauma": "Emergency",
}


@dataclass
class TriageInput:
    age: int
    gender: str
    symptoms: str
    blood_pressure_systolic: Optional[int] = None
    blood_pressure_diastolic: Optional[int] = None
    heart_rate: Optional[int] = None
    temperature: Optional[float] = None
    pre_existing_conditions: List[str] = field(default_factory=list)


@dataclass
class ContributingFactor:
    factor: str
    impact: str  # "high" | "medium" | "low"
    description: str


@dataclass
class TriageResult:
    risk_level: str
    confidence_score: float
    recommended_department: str
    alternative_departments: List[str]
    contributing_factors: List[ContributingFactor]
    summary: str


def _parse_bp(bp_str: str) -> tuple[Optional[int], Optional[int]]:
    """Parse '120/80' or '120' style BP."""
    if not bp_str or not str(bp_str).strip():
        return None, None
    s = re.sub(r"\s+", "", str(bp_str))
    parts = re.split(r"[/\-]", s)
    if len(parts) >= 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            pass
    try:
        return int(parts[0]), None
    except (ValueError, IndexError):
        return None, None


def _normalize_symptoms(s: str) -> str:
    return (s or "").lower().strip()


def compute_risk(input_data: TriageInput) -> TriageResult:
    factors: List[ContributingFactor] = []
    risk_score = 0.0
    max_score = 0.0

    symptoms_lower = _normalize_symptoms(input_data.symptoms)
    symptoms_list = [x.strip() for x in re.split(r"[,;]", symptoms_lower) if x.strip()]

    # --- Age ---
    max_score += 20
    if input_data.age >= 65:
        risk_score += 18
        factors.append(
            ContributingFactor("Age 65+", "high", "Older age increases risk and requires closer assessment.")
        )
    elif input_data.age >= 50:
        risk_score += 10
        factors.append(
            ContributingFactor("Age 50-64", "medium", "Middle age may warrant additional monitoring.")
        )
    else:
        risk_score += 2
        factors.append(ContributingFactor("Age", "low", "Age within lower-risk range."))

    # --- Vitals ---
    sys_bp = input_data.blood_pressure_systolic
    dia_bp = input_data.blood_pressure_diastolic
    if sys_bp is None and input_data.blood_pressure_systolic is None and isinstance(
        getattr(input_data, "blood_pressure", None), str
    ):
        sys_bp, dia_bp = _parse_bp(getattr(input_data, "blood_pressure", "") or "")

    if sys_bp is not None:
        max_score += 15
        if sys_bp >= 180 or (dia_bp is not None and dia_bp >= 120):
            risk_score += 15
            factors.append(
                ContributingFactor("Severe hypertension", "high", "Blood pressure in hypertensive crisis range.")
            )
        elif sys_bp >= 140 or (dia_bp is not None and dia_bp >= 90):
            risk_score += 10
            factors.append(
                ContributingFactor("Elevated blood pressure", "medium", "Blood pressure above normal range.")
            )
        else:
            risk_score += 2
            factors.append(ContributingFactor("Blood pressure", "low", "Blood pressure within acceptable range."))

    if input_data.heart_rate is not None:
        max_score += 15
        hr = input_data.heart_rate
        if hr >= 120 or hr < 50:
            risk_score += 14
            factors.append(
                ContributingFactor("Abnormal heart rate", "high", "Heart rate outside safe range.")
            )
        elif hr >= 100 or hr < 60:
            risk_score += 8
            factors.append(
                ContributingFactor("Elevated or low heart rate", "medium", "Heart rate may need monitoring.")
            )
        else:
            risk_score += 2
            factors.append(ContributingFactor("Heart rate", "low", "Heart rate within normal range."))

    if input_data.temperature is not None:
        max_score += 10
        temp = input_data.temperature
        if temp >= 39.0 or temp < 35.0:
            risk_score += 10
            factors.append(
                ContributingFactor("Abnormal temperature", "high", "Fever or hypothermia detected.")
            )
        elif temp >= 37.5 or temp < 36.0:
            risk_score += 5
            factors.append(
                ContributingFactor("Mild fever or low temp", "medium", "Temperature slightly outside normal.")
            )
        else:
            risk_score += 1
            factors.append(ContributingFactor("Temperature", "low", "Temperature within normal range."))

    # --- High-risk keywords in symptoms ---
    max_score += 25
    emergency_keywords = [
        "chest pain", "shortness of breath", "stroke", "seizure", "unconscious",
        "severe bleeding", "severe pain", "cannot breathe", "collapse", "fainting"
    ]
    medium_keywords = [
        "dizziness", "headache", "vomiting", "fever", "palpitation", "numbness",
        "confusion", "weakness", "abdominal pain", "cough", "rash"
    ]
    symptom_risk = 0
    for kw in emergency_keywords:
        if kw in symptoms_lower:
            symptom_risk = max(symptom_risk, 25)
            factors.append(
                ContributingFactor(f"Symptom: {kw}", "high", "Emergency-level symptom reported.")
            )
            break
    if symptom_risk < 25:
        for kw in medium_keywords:
            if kw in symptoms_lower:
                symptom_risk = max(symptom_risk, 12)
                factors.append(
                    ContributingFactor(f"Symptom: {kw}", "medium", "Symptom may require clinical evaluation.")
                )
                break
    if symptom_risk == 0 and symptoms_list:
        symptom_risk = 5
        factors.append(
            ContributingFactor("Reported symptoms", "low", "Symptoms documented for clinician review.")
        )
    risk_score += symptom_risk

    # --- Pre-existing conditions ---
    max_score += 15
    conditions = input_data.pre_existing_conditions or []
    if isinstance(conditions, str):
        conditions = [c.strip() for c in re.split(r"[,;]", (conditions or "")) if c.strip()]
    high_risk_conditions = ["heart disease", "diabetes", "copd", "asthma", "hypertension", "kidney disease"]
    cond_count = sum(1 for c in conditions for h in high_risk_conditions if h in (c or "").lower())
    if cond_count >= 2:
        risk_score += 15
        factors.append(
            ContributingFactor("Multiple high-risk conditions", "high", "Pre-existing conditions increase complexity.")
        )
    elif cond_count == 1:
        risk_score += 8
        factors.append(
            ContributingFactor("Pre-existing condition", "medium", "One chronic condition noted.")
        )
    else:
        risk_score += 2
        factors.append(ContributingFactor("Medical history", "low", "No high-risk conditions identified."))

    # Normalize score to 0-1 and map to risk level
    if max_score <= 0:
        max_score = 1
    normalized = risk_score / max_score

    if normalized >= 0.6:
        risk_level = RISK_HIGH
        confidence = min(0.98, 0.75 + normalized * 0.2)
    elif normalized >= 0.35:
        risk_level = RISK_MEDIUM
        confidence = min(0.92, 0.65 + normalized * 0.25)
    else:
        risk_level = RISK_LOW
        confidence = min(0.90, 0.70 + (1 - normalized) * 0.2)

    # Department recommendation
    recommended = "General Medicine"
    for phrase, dept in SYMPTOM_DEPARTMENT_MAP.items():
        if phrase in symptoms_lower:
            recommended = dept
            break

    alternatives = [d for d in DEPARTMENTS if d != recommended][:3]

    summary = (
        f"Risk classified as **{risk_level}** based on age, vitals, symptoms, and medical history. "
        f"Recommended department: **{recommended}**. "
        f"Confidence: {confidence:.0%}."
    )

    return TriageResult(
        risk_level=risk_level,
        confidence_score=round(confidence, 2),
        recommended_department=recommended,
        alternative_departments=alternatives,
        contributing_factors=factors,
        summary=summary,
    )


def result_to_dict(r: TriageResult) -> dict:
    return {
        "risk_level": r.risk_level,
        "confidence_score": r.confidence_score,
        "recommended_department": r.recommended_department,
        "alternative_departments": r.alternative_departments,
        "contributing_factors": [
            {"factor": f.factor, "impact": f.impact, "description": f.description}
            for f in r.contributing_factors
        ],
        "summary": r.summary,
    }
