"""
Train a Random Forest classifier to predict Recommended_Department from the
smart triage dataset. Saves model, feature encoders, and metadata for use at inference.
"""
import json
import re
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report

# Paths
DATA_PATH = Path(__file__).resolve().parent / "smart_triage_dataset_1200-1.csv"
MODEL_DIR = Path(__file__).resolve().parent / "model_artifacts"
MODEL_DIR.mkdir(exist_ok=True)

# Known vocabularies (from dataset exploration)
SYMPTOMS_VOCAB = [
    "Abdominal Pain", "Back Pain", "Blurred Vision", "Chest Pain", "Cough",
    "Dizziness", "Fatigue", "Fever", "Headache", "Numbness",
    "Shortness of Breath", "Sore Throat", "Vomiting",
]
CONDITIONS_VOCAB = [
    "Anemia", "Asthma", "Diabetes", "Heart Disease", "Hypertension",
    "Kidney Disease", "Thyroid Disorder",
]
GENDERS = ["Female", "Male", "Other"]


def _parse_multi(s: str, vocab: list) -> list:
    """Parse comma-separated string and return list of tokens that appear in vocab."""
    if pd.isna(s) or not str(s).strip():
        return []
    tokens = [x.strip() for x in re.split(r",\s*", str(s)) if x.strip()]
    return [t for t in tokens if t in vocab]


def _symptoms_to_vec(s: str) -> np.ndarray:
    """Convert symptoms string to binary vector of shape (len(SYMPTOMS_VOCAB),)."""
    vec = np.zeros(len(SYMPTOMS_VOCAB), dtype=np.float32)
    for t in _parse_multi(s, SYMPTOMS_VOCAB):
        idx = SYMPTOMS_VOCAB.index(t)
        vec[idx] = 1.0
    return vec


def _conditions_to_vec(s: str) -> np.ndarray:
    """Convert pre-existing conditions string to binary vector."""
    vec = np.zeros(len(CONDITIONS_VOCAB), dtype=np.float32)
    if pd.isna(s) or str(s).strip().lower() in ("", "none"):
        return vec
    for t in _parse_multi(s, CONDITIONS_VOCAB):
        idx = CONDITIONS_VOCAB.index(t)
        vec[idx] = 1.0
    return vec


def _gender_to_idx(g: str) -> int:
    g = (g or "Other").strip()
    return GENDERS.index(g) if g in GENDERS else 0


def build_features(df: pd.DataFrame) -> np.ndarray:
    """Build feature matrix: [Age, Gender_idx, BP_sys, HR, Temp_F, symptom_bin..., condition_bin...]."""
    rows = []
    for _, r in df.iterrows():
        age = float(r["Age"]) if pd.notna(r["Age"]) else 40.0
        gender_idx = _gender_to_idx(r["Gender"])
        bp = float(r["Blood_Pressure_Systolic"]) if pd.notna(r["Blood_Pressure_Systolic"]) else 120.0
        hr = float(r["Heart_Rate"]) if pd.notna(r["Heart_Rate"]) else 75.0
        temp = float(r["Temperature_F"]) if pd.notna(r["Temperature_F"]) else 98.6
        sym_vec = _symptoms_to_vec(r["Symptoms"])
        cond_vec = _conditions_to_vec(r["Pre_Existing_Conditions"])
        row = [age, float(gender_idx), bp, hr, temp] + sym_vec.tolist() + cond_vec.tolist()
        rows.append(row)
    return np.array(rows, dtype=np.float32)


def main():
    print("Loading dataset...")
    df = pd.read_csv(DATA_PATH)
    df["Pre_Existing_Conditions"] = df["Pre_Existing_Conditions"].fillna("None")

    X = build_features(df)
    y = df["Recommended_Department"].values
    classes = sorted(df["Recommended_Department"].unique())

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    print("Training Random Forest...")
    clf = RandomForestClassifier(
        n_estimators=200,
        max_depth=12,
        min_samples_split=5,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=-1,
    )
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    print(f"Test accuracy: {acc:.4f}")
    print(classification_report(y_test, y_pred, zero_division=0))

    # Save model and metadata
    joblib.dump(clf, MODEL_DIR / "department_rf.joblib")
    metadata = {
        "symptoms_vocab": SYMPTOMS_VOCAB,
        "conditions_vocab": CONDITIONS_VOCAB,
        "genders": GENDERS,
        "classes": list(classes),
        "feature_order": [
            "age", "gender_idx", "blood_pressure_systolic", "heart_rate", "temperature_f"
        ] + [f"symptom_{s}" for s in SYMPTOMS_VOCAB] + [f"condition_{c}" for c in CONDITIONS_VOCAB],
    }
    with open(MODEL_DIR / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"Model and metadata saved to {MODEL_DIR}")


if __name__ == "__main__":
    main()
