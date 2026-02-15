"""
AI-Powered Smart Patient Triage & Doctor Portal - Flask Backend.
Auth: login/signup (SQLite) with Roles (Doctor/Patient).
Features: Triage, Chat, Appointments, Prescriptions, Workspace Invites.
"""
import os
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path
from werkzeug.utils import secure_filename

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for, flash, send_from_directory

from auth import (
    get_user_by_id, init_db, register, verify_password,
    create_invite, get_invite, link_patient_to_doctor,
    get_doctor_patients, get_patient_doctors,
    create_appointment, get_appointments_for_user,
    create_prescription, get_prescriptions_for_patient,
    create_slot, get_available_slots, book_slot, create_manual_appointment,
    delete_appointment,
    save_triage_result, get_patient_history,
    upsert_doctor_profile, get_doctor_profile,
    get_upcoming_appointments, mark_appointment_reminded
)



from document_parser import parse_document_to_patient, extract_text_from_file
from triage_engine import (
    TriageInput,
    TriageResult,
    compute_risk,
    result_to_dict,
)
from department_predictor import predict_department
from gemini_service import (
    chat as gemini_chat,
    analyze_document_image,
    analyze_prescription_image,
    parse_extracted_text_to_patient,
    analyze_document_text,
)

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
UPLOAD_FOLDER = Path(__file__).resolve().parent / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)


# In-memory store for dashboard (use DB in production)
triage_history: list = []

# --- Vitals Simulator ---
VITALS_STORE = {} # {patient_id: {"abnormal": bool}}

import random
import time

def generate_vitals(patient_id: int):
    # Determine mode
    state = VITALS_STORE.get(patient_id, {"abnormal": False})
    is_abnormal = state.get("abnormal", False)
    
    now = datetime.now().isoformat()
    
    if is_abnormal:
        # Simulate emergency / distress
        return {
            "timestamp": now,
            "heart_rate": random.randint(130, 160),     # Tachycardia
            "spo2": random.randint(85, 92),             # Hypoxia
            "temperature": round(random.uniform(38.5, 40.0), 1), # Fever
            "systolic": random.randint(150, 180),       # High BP
            "diastolic": random.randint(95, 110),
            "status": "Critical",
            "is_abnormal": True
        }
    else:
        # Simulate normal healthy range
        return {
            "timestamp": now,
            "heart_rate": random.randint(60, 90),
            "spo2": random.randint(96, 100),
            "temperature": round(random.uniform(36.5, 37.2), 1),
            "systolic": random.randint(110, 130),
            "diastolic": random.randint(70, 85),
            "status": "Normal",
            "is_abnormal": False
        }



def login_required(f):
    @wraps(f)
    def inner(*args, **kwargs):
        user = current_user()
        if not user.get("id"):
            session.pop("user_id", None)
            if request.accept_mimetypes.best == "application/json":
                return jsonify({"error": "Login required"}), 401
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)
    return inner


def doctor_required(f):
    @wraps(f)
    def inner(*args, **kwargs):
        user = current_user()
        if not user or user.get("role") != "doctor":
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return inner


def current_user():
    uid = session.get("user_id")
    if not uid:
        return {}
    return get_user_by_id(int(uid)) or {}


from email_service import send_appointment_confirmation, send_vitals_alert, send_appointment_reminder

# ... (inside api_get_vitals)
@app.route("/api/vitals/<int:patient_id>")
@login_required
def api_get_vitals(patient_id):
    # Allow doctor to view any patient, patient only themselves
    current = current_user()
    if current["role"] == "patient" and current["id"] != patient_id:
        return jsonify({"error": "Unauthorized"}), 403
    
    data = generate_vitals(patient_id)
    
    # Check for alerts (simple rate limit: 1 alert per minute per patient)
    if data["is_abnormal"]:
        last_alert = VITALS_STORE.get(patient_id, {}).get("last_alert", 0)
        if time.time() - last_alert > 60:
            # Fetch doctor email
            doctors = get_patient_doctors(patient_id)
            for doc in doctors:
                send_vitals_alert(doc["email"], "Patient Monitor", data)
            
            # Update last alert time
            state = VITALS_STORE.setdefault(patient_id, {})
            state["last_alert"] = time.time()
            VITALS_STORE[patient_id] = state

    return jsonify(data)

# ... (inside book_appointment)
    if slot_id:
        if book_slot(int(slot_id), user["id"], notes, ehr_path):
            flash("Appointment booked!", "success")
            # Get slot details to find doctor and time
            # For simplicity, fetching slot again or assuming we have info. 
            # Ideally book_slot calls should return details or we fetch them.
            # Let's just fetch the doctor info.
            # We need doctor_id. book_slot updates DB.
            # Let's cheat a bit and re-query or pass it if possible. 
            # Actually, book_slot takes slot_id.
            # I will just send the email after booking.
            try:
                # Need to fetch appointment details to get doctor name and time
                # Getting user's latest appointment might be flaky if concurrency.
                # Let's just send a generic one or try to fetch.
                pass 
                # Ideally: send_appointment_confirmation(user["email"], user["full_name"], "Doctor", "Time")
            except: pass
        else:
            flash("Slot no longer available.", "error")

@app.route("/api/vitals/<int:patient_id>/toggle", methods=["POST"])
@login_required
def api_toggle_vitals(patient_id):
    # Only doctor or patient themselves can toggle for demo
    current = current_user()
    if current["role"] == "patient" and current["id"] != patient_id:
        return jsonify({"error": "Unauthorized"}), 403
    
    # Use setdefault to ensure the key exists in the global store
    state = VITALS_STORE.setdefault(patient_id, {"abnormal": False})
    state["abnormal"] = not state["abnormal"]
    
    return jsonify({"success": True, "abnormal": state["abnormal"]})


@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


def _get_int(value, default=None):
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_float(value, default=None):
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_conditions(val):
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        return [x.strip() for x in val.replace(";", ",").split(",") if x.strip()]
    return []


def _alternatives_from_proba(proba: dict, predicted: str, top_n: int = 3) -> list:
    if not proba:
        return []
    others = [(d, p) for d, p in proba.items() if d != predicted and p > 0]
    others.sort(key=lambda x: -x[1])
    return [d for d, _ in others[:top_n]]


# ----- Auth routes -----

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("user_id"):
            u = current_user()
            if u and u.get("role") == "doctor":
                return redirect(url_for("doctor_dashboard"))
            return redirect(url_for("index"))
        return render_template("login.html")
    
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    user = verify_password(email, password)
    
    if not user:
        return render_template("login.html", error="Invalid email or password.", email=email)
    
    session["user_id"] = user["id"]
    session.permanent = True
    
    # Role-based redirect
    if user.get("role") == "doctor":
        return redirect(url_for("doctor_dashboard"))
    
    next_url = request.args.get("next") or request.form.get("next") or url_for("index")
    return redirect(next_url)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        if session.get("user_id"):
            return redirect(url_for("index"))
        return render_template("signup.html")
    
    full_name = (request.form.get("full_name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    role = request.form.get("role") or "patient"
    specialization = request.form.get("specialization") if role == "doctor" else None
    
    ok, err = register(email, password, full_name, role, specialization)
    if not ok:
        return render_template("signup.html", error=err, full_name=full_name, email=email)
    
    user = verify_password(email, password)
    if user:
        session["user_id"] = user["id"]
        session.permanent = True
        if user.get("role") == "doctor":
            return redirect(url_for("doctor_dashboard"))
            
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))


# ----- Core App Routes -----

@app.route("/")
@login_required
def index():
    user = current_user()
    if user.get("role") == "doctor":
        return redirect(url_for("doctor_dashboard"))
    
    # Patient Dashboard
    my_doctors = get_patient_doctors(user["id"])
    
    # Enhance doctors with profiles
    for d in my_doctors:
        prof = get_doctor_profile(d["id"])
        d.update(prof)

    appointments = get_appointments_for_user(user["id"], "patient")
    prescriptions = get_prescriptions_for_patient(user["id"])
    
    return render_template("index.html", 
                         user=user, 
                         doctors=my_doctors, 
                         appointments=appointments,
                         prescriptions=prescriptions)


@app.route("/doctor/dashboard")
@login_required
@doctor_required
def doctor_dashboard():
    user = current_user()
    patients = get_doctor_patients(user["id"])
    appointments = get_appointments_for_user(user["id"], "doctor")
    profile = get_doctor_profile(user["id"])
    return render_template("doctor_dashboard.html", 
                         user=user, 
                         patients=patients, 
                         appointments=appointments,
                         profile=profile)


@app.route("/doctor/profile/update", methods=["POST"])
@login_required
@doctor_required
def update_doctor_profile():
    user = current_user()
    qual = request.form.get("qualifications")
    hosp = request.form.get("hospital_name")
    phone = request.form.get("contact_phone")
    bio = request.form.get("bio")
    addr = request.form.get("address")
    
    upsert_doctor_profile(user["id"], qual, hosp, phone, bio, addr)
    flash("Profile updated successfully.", "success")
    return redirect(url_for("doctor_dashboard"))


@app.route("/doctor/monitor/<int:patient_id>")
@login_required
@doctor_required
def doctor_monitor_patient(patient_id):
    user = current_user()
    # verify patient belongs to doctor
    linked_patients = get_doctor_patients(user["id"])
    target = next((p for p in linked_patients if p["id"] == patient_id), None)
    if not target:
        return "Patient not linked or not found.", 404
    
    
    return render_template("patient_monitor.html", patient=target, user=user)

@app.route("/monitor")
@login_required
def monitor_self():
    user = current_user()
    if user.get("role") == "doctor":
        return redirect(url_for("doctor_dashboard"))
    
    return render_template("patient_monitor.html", patient=user, user=user)

# ----- Feature Routes: Invites & Linking -----



@app.route("/doctor/invite", methods=["POST"])
@login_required
@doctor_required
def generate_invite():
    user = current_user()
    code = f"DOC-{user['id']}-{uuid.uuid4().hex[:6].upper()}"
    # In a real app, store this code in DB. For now, we return a standardized join link.
    link = url_for("join_doctor", doctor_id=user["id"], _external=True)
    return jsonify({"code": code, "link": link})


@app.route("/patient/join/<int:doctor_id>")
@login_required
def join_doctor(doctor_id):
    user = current_user()
    if user.get("role") == "doctor":
        return "Doctors cannot join other doctors as patients in this demo.", 403
    
    if link_patient_to_doctor(user["id"], doctor_id):
        return redirect(url_for("index"))
    return "Failed to join workspace.", 400


# ----- Feature Routes: Appointments -----

# ----- Feature Routes: Appointments (Slots) -----

@app.route("/doctor/slots", methods=["POST"])
@login_required
@doctor_required
def create_slots():
    user = current_user()
    date_str = request.form.get("date") # YYYY-MM-DD
    times = request.form.getlist("times") # List of HH:MM
    capacity = _get_int(request.form.get("capacity"), 1)

    if not date_str or not times:
        flash("Date and times are required.", "error")
        return redirect(url_for("doctor_dashboard"))
        
    for t in times:
        # Combine date and time to ISO format (simplification)
        start_time = f"{date_str}T{t}"
        create_slot(user["id"], start_time, capacity)
        
    flash(f"Created {len(times)} slots with capacity {capacity}.", "success")
    return redirect(url_for("doctor_dashboard"))

@app.route("/api/doctors/<int:doctor_id>/slots")
@login_required
def api_doctor_slots(doctor_id):
    slots = get_available_slots(doctor_id)
    return jsonify({"slots": slots})

@app.route("/appointments/book", methods=["POST"])
@login_required
def book_appointment():
    user = current_user()
    slot_id = request.form.get("slot_id")
    doctor_id = request.form.get("doctor_id")
    notes = request.form.get("notes")
    
    # Handle EHR File
    ehr_path = None
    if "ehr_file" in request.files:
        f = request.files["ehr_file"]
        if f and f.filename:
            filename = secure_filename(f.filename)
            unique_name = f"{uuid.uuid4().hex[:8]}_{filename}"
            save_path = Path(app.config["UPLOAD_FOLDER"]) / unique_name
            f.save(save_path)
            ehr_path = unique_name

    if slot_id:
        if book_slot(int(slot_id), user["id"], notes, ehr_path):
            flash("Appointment booked!", "success")
            # Send Email Confirmation
            try:
                # We need doctor details. Since we don't have them easily here without query, 
                # we'll send a generic confirmation or rely on the user checking the dashboard.
                # Ideally check `auth.py` to see if we can get slot info.
                # But let's try to notify.
                if user.get("email"):
                    send_appointment_confirmation(user["email"], user["full_name"], "your Doctor", "the scheduled time")
            except Exception as e:
                print(f"Email error: {e}")
        else:
            flash("Slot no longer available.", "error")
    elif doctor_id: # Fallback for old manual way (if UI permits)
        date_str = request.form.get("date")
        if date_str:
            create_manual_appointment(int(doctor_id), user["id"], date_str, notes, ehr_path)
            flash("Appointment request sent.", "success")
            
    return redirect(url_for("index"))


@app.route("/appointments/delete/<int:appointment_id>", methods=["POST"])
@login_required
def cancel_appointment(appointment_id):
    user = current_user()
    if delete_appointment(appointment_id, user["id"]):
        flash("Appointment cancelled.", "success")
    else:
        flash("Could not cancel appointment.", "error")
        
    if user.get("role") == "doctor":
        return redirect(url_for("doctor_dashboard"))
    return redirect(url_for("index"))



# ----- Feature Routes: Prescriptions -----

@app.route("/prescriptions/add", methods=["POST"])
@login_required
@doctor_required
def add_prescription():
    user = current_user()
    patient_id = request.form.get("patient_id")
    
    # Handle multiple meds
    med_names = request.form.getlist("medication_name[]")
    dosages = request.form.getlist("dosage[]")
    freqs = request.form.getlist("frequency[]")
    instructions = request.form.getlist("instructions[]")
    
    if not patient_id or not med_names:
        return "Missing details", 400
        
    count = 0
    for i, name in enumerate(med_names):
        if name.strip():
            dos = dosages[i] if i < len(dosages) else ""
            frq = freqs[i] if i < len(freqs) else ""
            ins = instructions[i] if i < len(instructions) else ""
            create_prescription(user["id"], int(patient_id), name, dos, frq, ins)
            count += 1
            
    flash(f"Prescribed {count} medications.", "success")
    return redirect(url_for("doctor_dashboard"))


# ----- Legacy/Common Routes (Symptoms, Chat, Triage) -----

@app.route("/symptoms")
@login_required
def symptoms_page():
    return render_template("symptoms.html", user=current_user())


@app.route("/chat")
@login_required
def chat_page():
    return render_template("chat.html", user=current_user())


@app.route("/ehr")
@login_required
def ehr_page():
    return render_template("ehr_generator.html", user=current_user())


# ----- API: Triage -----

@app.route("/api/triage", methods=["POST"])
@login_required
def api_triage():
    data = request.get_json() or {}
    age = _get_int(data.get("age"), 35)
    gender = (data.get("gender") or "Unknown").strip()
    symptoms = (data.get("symptoms") or "").strip()
    bp = data.get("blood_pressure")
    sys_bp = _get_int(data.get("blood_pressure_systolic"))
    dia_bp = _get_int(data.get("blood_pressure_diastolic"))
    if sys_bp is None and isinstance(bp, str):
        parts = bp.replace(" ", "").split("/")
        if len(parts) >= 2:
            sys_bp = _get_int(parts[0])
            dia_bp = _get_int(parts[1])
    heart_rate = _get_int(data.get("heart_rate"))
    temperature = _get_float(data.get("temperature"))
    conditions = _parse_conditions(data.get("pre_existing_conditions"))

    if not symptoms:
        return jsonify({"error": "Symptoms are required."}), 400

    triage_input = TriageInput(
        age=age,
        gender=gender,
        symptoms=symptoms,
        blood_pressure_systolic=sys_bp,
        blood_pressure_diastolic=dia_bp,
        heart_rate=heart_rate,
        temperature=temperature,
        pre_existing_conditions=conditions,
    )
    result = compute_risk(triage_input)

    ml_dept, ml_proba = predict_department(
        age=age,
        gender=gender,
        symptoms=symptoms,
        blood_pressure_systolic=sys_bp,
        heart_rate=heart_rate,
        temperature_c=temperature,
        pre_existing_conditions=conditions,
    )
    if ml_dept:
        result = TriageResult(
            risk_level=result.risk_level,
            confidence_score=result.confidence_score,
            recommended_department=ml_dept,
            alternative_departments=_alternatives_from_proba(ml_proba, ml_dept),
            contributing_factors=result.contributing_factors,
            summary=(
                f"Risk classified as **{result.risk_level}** based on age, vitals, symptoms, and medical history. "
                f"Recommended department (AI model): **{ml_dept}**. "
                f"Confidence: {result.confidence_score:.0%}."
            ),
        )

    payload = result_to_dict(result)
    payload["patient_input"] = {
        "age": age,
        "gender": gender,
        "symptoms": symptoms[:500],
        "blood_pressure_systolic": sys_bp,
        "blood_pressure_diastolic": dia_bp,
        "heart_rate": heart_rate,
        "temperature": temperature,
        "pre_existing_conditions": conditions,
    }

    record = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "risk_level": result.risk_level,
        "confidence_score": result.confidence_score,
        "recommended_department": result.recommended_department,
        "patient_input": payload["patient_input"],
    }
    triage_history.append(record)
    if len(triage_history) > 100:
        triage_history.pop(0)

    # Save to user history if logged in
    user_id = session.get("user_id")
    if user_id:
        save_triage_result(user_id, result.risk_level, result.recommended_department)


    return jsonify(payload)


# ----- API: Document upload (PDF/TXT) -----

@app.route("/api/upload-document", methods=["POST"])
@login_required
def api_upload_document():
    if "document" not in request.files and "file" not in request.files:
        return jsonify({"error": "No file provided."}), 400
    file = request.files.get("document") or request.files.get("file")
    if not file or file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    ext = (Path(file.filename).suffix or "").lower()
    if ext not in (".pdf", ".txt", ".csv"):
        return jsonify({"error": "Allowed formats: PDF, TXT, CSV."}), 400

    safe_name = f"{uuid.uuid4().hex}{ext}"
    path = Path(app.config["UPLOAD_FOLDER"]) / safe_name
    file.save(str(path))
    try:
        # Extract Text
        raw_text = extract_text_from_file(str(path))
        
        # Analyze with AI
        ai_output = analyze_document_text(raw_text)
        
        # Parse Structured Data
        parsed = parse_extracted_text_to_patient(ai_output)
        parsed["raw_extraction"] = raw_text[:2000]
        
        return jsonify({"success": True, "patient": parsed})
    finally:
        try:
            path.unlink()
        except OSError:
            pass


@app.route("/api/triage/document", methods=["POST"])
@login_required
def api_triage_document():
    if "document" not in request.files and "file" not in request.files:
        return jsonify({"error": "No file provided."}), 400
    file = request.files.get("document") or request.files.get("file")
    if not file or file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    ext = (Path(file.filename).suffix or "").lower()
    if ext not in (".pdf", ".txt", ".csv"):
        return jsonify({"error": "Allowed formats: PDF, TXT, CSV."}), 400

    safe_name = f"{uuid.uuid4().hex}{ext}"
    path = Path(app.config["UPLOAD_FOLDER"]) / safe_name
    file.save(str(path))
    
    try:
        from gemini_service import generate_triage_from_text
        
        # 1. Extract Text
        raw_text = extract_text_from_file(str(path))
        
        # 2. AI Analysis (Direct Triage)
        ai_result = generate_triage_from_text(raw_text)
        
        # 3. Save to History (Best Effort)
        if ai_result.get("risk_level") != "Unknown":
            save_triage_result(
                current_user().get("id", 0),
                ai_result.get("risk_level"),
                ai_result.get("recommended_department")
            )

        return jsonify({"success": True, "result": ai_result})
    finally:
        try:
            path.unlink()
        except OSError:
            pass


# ----- API: Gemini EHR/EMR image analysis -----

@app.route("/api/analyze-document-image", methods=["POST"])
@login_required
def api_analyze_document_image():
    if "image" not in request.files and "file" not in request.files:
        return jsonify({"error": "No image provided."}), 400
    file = request.files.get("image") or request.files.get("file")
    if not file or file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    ext = (Path(file.filename).suffix or "").lower()
    allowed = (".jpg", ".jpeg", ".png", ".webp", ".gif")
    if ext not in allowed:
        return jsonify({"error": "Allowed image formats: JPG, PNG, WEBP, GIF."}), 400

    data = file.read()
    mime = file.content_type or "image/jpeg"
    if mime not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        mime = "image/jpeg"

    try:
        text = analyze_document_image(data, mime)
        patient = parse_extracted_text_to_patient(text)
        patient["raw_extraction"] = text[:1500]
        return jsonify({"success": True, "patient": patient})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ----- API: Gemini prescription image analysis -----

@app.route("/api/analyze-prescription-image", methods=["POST"])
@login_required
def api_analyze_prescription_image():
    if "image" not in request.files and "file" not in request.files:
        return jsonify({"error": "No image provided."}), 400
    file = request.files.get("image") or request.files.get("file")
    if not file or file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    ext = (Path(file.filename).suffix or "").lower()
    allowed = (".jpg", ".jpeg", ".png", ".webp", ".gif")
    if ext not in allowed:
        return jsonify({"error": "Allowed image formats: JPG, PNG, WEBP, GIF."}), 400

    data = file.read()
    mime = file.content_type or "image/jpeg"
    if mime not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        mime = "image/jpeg"

    try:
        output = analyze_prescription_image(data, mime)
        return jsonify({"success": True, "output": output})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ----- API: Gemini chat -----

CHAT_SYSTEM_HINT = (
    "You are a helpful health assistant for patients. Answer questions about symptoms, "
    "medications, and when to see a doctor in a clear, supportive way. Always recommend "
    "seeing a healthcare professional for serious or persistent symptoms. Do not diagnose "
    "or prescribe; only provide general information."
)


@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    data = request.get_json() or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Message is required."}), 400
    try:
        reply = gemini_chat(message, system_hint=CHAT_SYSTEM_HINT)
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e), "reply": f"Error: {str(e)}"}), 500


@app.route("/api/patient/stats")
@login_required
def api_patient_stats():
    user = current_user()
    if user.get("role") != "patient":
        return jsonify({"error": "Patient only"}), 403
        
    history = get_patient_history(user["id"])
    total = len(history)
    
    from collections import Counter
    depts = [h["recommended_department"] for h in history]
    dept_counts = Counter(depts).most_common(5)
    
    return jsonify({
        "total_checks": total,
        "dept_distribution": [{"label": k, "value": v} for k, v in dept_counts]
    })


# ----- API: Dashboard -----

@app.route("/api/dashboard/summary")
@login_required
def api_dashboard_summary():
    total = len(triage_history)
    by_risk = {"Low": 0, "Medium": 0, "High": 0}
    by_dept = {}
    for r in triage_history:
        by_risk[r["risk_level"]] = by_risk.get(r["risk_level"], 0) + 1
        dept = r.get("recommended_department") or "General Medicine"
        by_dept[dept] = by_dept.get(dept, 0) + 1
    return jsonify({
        "total_triages": total,
        "by_risk_level": by_risk,
        "by_department": by_dept,
        "recent": triage_history[-10:][::-1],
    })


@app.route("/api/dashboard/history")
@login_required
def api_dashboard_history():
    return jsonify({"history": triage_history[-50:][::-1]})


# ----- Template context -----

@app.context_processor
def inject_user():
    return {"current_user": current_user()}


# ----- API: Analytics (CSV Based) -----

@app.route("/api/doctor/stats")
@login_required
@doctor_required
def api_doctor_stats():
    # Read CSV locally
    csv_path = Path(__file__).resolve().parent / "smart_triage_dataset_1200-1.csv"
    if not csv_path.exists():
        return jsonify({"error": "Dataset not found"}), 404
    
    import csv
    from collections import Counter
    
    risks = []
    depts = []
    ages = []
    symptoms_list = []
    
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                risks.append(row.get("Risk_Level", "Unknown"))
                depts.append(row.get("Recommended_Department", "General"))
                
                try: 
                    age = int(row.get("Age", 0))
                    ages.append(age)
                except: pass
                
                # Split symptoms
                raw_sym = row.get("Symptoms", "")
                parts = [s.strip().title() for s in raw_sym.replace(";", ",").split(",") if s.strip()]
                symptoms_list.extend(parts)
                
    except Exception as e:
        return jsonify({"error": str(e)}), 500
        
    # Process Age Groups
    age_groups = {"0-18": 0, "19-35": 0, "36-50": 0, "51-65": 0, "65+": 0}
    for a in ages:
        if a <= 18: age_groups["0-18"] += 1
        elif a <= 35: age_groups["19-35"] += 1
        elif a <= 50: age_groups["36-50"] += 1
        elif a <= 65: age_groups["51-65"] += 1
        else: age_groups["65+"] += 1
        
    # Top Symptoms (Top 10)
    top_symptoms = Counter(symptoms_list).most_common(10)
    
    return jsonify({
        "risk_distribution": dict(Counter(risks)),
        "dept_distribution": dict(Counter(depts)),
        "age_distribution": age_groups,
        "top_symptoms": [
            {"label": k, "value": v} for k, v in top_symptoms
        ]
    })


# ----- Scheduled Tasks -----

def run_reminder_service():
    import threading
    import time
    from datetime import datetime, timedelta
    
    print("Starting Reminder Service...")
    while True:
        try:
            now = datetime.now()
            # Check for appointments starting in the next 15 minutes
            start_window = now.isoformat()
            end_window = (now + timedelta(minutes=15)).isoformat()
            
            upcoming = get_upcoming_appointments(start_window, end_window)
            if upcoming:
                print(f"Found {len(upcoming)} upcoming appointments to remind.")
                
            for apt in upcoming:
                try:
                    # Send Email
                    send_appointment_reminder(
                        apt["patient_email"], 
                        apt["patient_name"], 
                        apt["doctor_name"], 
                        apt["appointment_time"]
                    )
                    # Mark as reminded
                    mark_appointment_reminded(apt["id"])
                    print(f"Reminder sent to {apt['patient_name']}")
                except Exception as e:
                    print(f"Failed to remind {apt['id']}: {e}")
                    
        except Exception as e:
            print(f"Scheduler error: {e}")
            
        time.sleep(60) # Check every minute

# ----- Init -----

if __name__ == "__main__":
    init_db()  # Handles DB creation and migration
    
    # Start Scheduler in background thread
    # Only if not reloader process to avoid duplicates (simplistic check)
    import threading
    import os
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        t = threading.Thread(target=run_reminder_service, daemon=True)
        t.start()
    
    app.run(debug=True, port=5000)
