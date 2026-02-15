"""
Department predictor: load trained Random Forest and predict Recommended_Department
from user input (age, gender, symptoms, vitals, conditions).
"""
import json
import re
from pathlib import Path
from typing import List, Optional, Tuple

import joblib
import numpy as np

MODEL_DIR = Path(__file__).resolve().parent / "model_artifacts"
_model = None
_metadata = None


def _load():
    global _model, _metadata
    if _model is None:
        _model = joblib.load(MODEL_DIR / "department_rf.joblib")
        with open(MODEL_DIR / "metadata.json") as f:
            _metadata = json.load(f)
    return _model, _metadata


def _parse_multi(s: str, vocab: list) -> list:
    if not s or not str(s).strip():
        return []
    # Normalize: allow comma or semicolon, strip, match case-insensitive to vocab
    s = str(s).strip()
    tokens = re.split(r"[,;]", s)
    out = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        for v in vocab:
            if v.lower() == t.lower():
                out.append(v)
                break
    return out


def _symptoms_to_vec(symptoms_str: str, vocab: list) -> np.ndarray:
    vec = np.zeros(len(vocab), dtype=np.float32)
    for t in _parse_multi(symptoms_str, vocab):
        if t in vocab:
            vec[vocab.index(t)] = 1.0
    return vec


def _conditions_to_vec(conditions: List[str], vocab: list) -> np.ndarray:
    vec = np.zeros(len(vocab), dtype=np.float32)
    for c in conditions or []:
        c = str(c).strip()
        if not c or c.lower() == "none":
            continue
        for v in vocab:
            if v.lower() == c.lower():
                vec[vocab.index(v)] = 1.0
                break
    return vec


def _gender_to_idx(gender: str, genders: list) -> int:
    g = (gender or "Other").strip()
    for i, x in enumerate(genders):
        if x.lower() == g.lower():
            return i
    return 0


def celsius_to_fahrenheit(c: float) -> float:
    if c is None:
        return 98.6
    return (c * 9 / 5) + 32


def predict_department(
    age: int,
    gender: str,
    symptoms: str,
    blood_pressure_systolic: Optional[int] = None,
    heart_rate: Optional[int] = None,
    temperature_c: Optional[float] = None,
    temperature_f: Optional[float] = None,
    pre_existing_conditions: Optional[List[str]] = None,
) -> Tuple[str, Optional[dict]]:
    """
    Predict recommended department from user input.
    Returns (department_name, proba_dict or None if model not loaded).
    temperature_c: temperature in Celsius (from form). If not provided, temperature_f used.
    """
    if not (MODEL_DIR / "department_rf.joblib").exists():
        return "General Medicine", None

    try:
        clf, meta = _load()
    except Exception:
        return "General Medicine", None

    symptoms_vocab = meta["symptoms_vocab"]
    conditions_vocab = meta["conditions_vocab"]
    genders = meta["genders"]

    age_f = float(age) if age is not None else 40.0
    gender_idx = _gender_to_idx(gender or "Other", genders)
    bp = float(blood_pressure_systolic) if blood_pressure_systolic is not None else 120.0
    hr = float(heart_rate) if heart_rate is not None else 75.0
    if temperature_f is not None:
        temp_f = float(temperature_f)
    elif temperature_c is not None:
        temp_f = celsius_to_fahrenheit(float(temperature_c))
    else:
        temp_f = 98.6

    sym_vec = _symptoms_to_vec(symptoms or "", symptoms_vocab)
    cond_vec = _conditions_to_vec(pre_existing_conditions or [], conditions_vocab)

    row = [age_f, float(gender_idx), bp, hr, temp_f] + sym_vec.tolist() + cond_vec.tolist()
    X = np.array([row], dtype=np.float32)

    pred = clf.predict(X)[0]
    proba = None
    if hasattr(clf, "predict_proba"):
        proba_arr = clf.predict_proba(X)[0]
        classes = clf.classes_
        proba = {str(c): float(p) for c, p in zip(classes, proba_arr)}

    return str(pred), proba
