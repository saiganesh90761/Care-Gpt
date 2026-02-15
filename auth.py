"""
Simple auth & data layer: SQLite store. Handles Users (Doctor/Patient), Appointments, Prescriptions, Slots.
"""
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = Path(__file__).resolve().parent / "patients.db"


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _get_conn()
    # Users table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT DEFAULT 'patient', -- 'doctor' or 'patient'
            specialization TEXT,         -- Only for doctors
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Migration for older DBs
    try:
        conn.execute("SELECT role FROM users LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'patient'")
        conn.execute("ALTER TABLE users ADD COLUMN specialization TEXT")



    # Migration for appointments table (add slot_id)
    try:
        conn.execute("SELECT slot_id FROM appointments LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE appointments ADD COLUMN slot_id INTEGER DEFAULT NULL")

    # Migration for appointments table (add ehr_file)
    try:
        conn.execute("SELECT ehr_file FROM appointments LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE appointments ADD COLUMN ehr_file TEXT DEFAULT NULL")

    # Links
    conn.execute("""
        CREATE TABLE IF NOT EXISTS doctor_patient_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(doctor_id) REFERENCES users(id),
            FOREIGN KEY(patient_id) REFERENCES users(id),
            UNIQUE(doctor_id, patient_id)
        )
    """)

    # Appointment Slots (New)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS appointment_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            start_time TEXT NOT NULL, -- ISO8601
            end_time TEXT,            -- ISO8601 (Optional, currently just assume 30m)
            is_booked BOOLEAN DEFAULT 0,
            capacity INTEGER DEFAULT 1,
            current_bookings INTEGER DEFAULT 0,
            FOREIGN KEY(doctor_id) REFERENCES users(id)
        )
    """)
    
    # Migration for appointment_slots table (add capacity, current_bookings)
    try:
        conn.execute("SELECT capacity FROM appointment_slots LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE appointment_slots ADD COLUMN capacity INTEGER DEFAULT 1")
        conn.execute("ALTER TABLE appointment_slots ADD COLUMN current_bookings INTEGER DEFAULT 0")
        # Initialize current_bookings based on is_booked for existing slots
        conn.execute("UPDATE appointment_slots SET current_bookings = 1 WHERE is_booked = 1")
    
    # Migration for appointments table (add is_reminded)
    try:
        conn.execute("SELECT is_reminded FROM appointments LIMIT 1")
    except sqlite3.OperationalError:
        try:
            conn.execute("ALTER TABLE appointments ADD COLUMN is_reminded BOOLEAN DEFAULT 0")
        except: pass

    # Appointments (Modified to link to slot potentially, but keeping simple)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            slot_id INTEGER, -- Optional link to slot
            ehr_file TEXT,   -- Optional EHR file path
            appointment_time TEXT NOT NULL, 
            status TEXT DEFAULT 'scheduled',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(doctor_id) REFERENCES users(id),
            FOREIGN KEY(patient_id) REFERENCES users(id)
        )
    """)


    # Prescriptions
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prescriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            medication_name TEXT NOT NULL,
            dosage TEXT NOT NULL,
            frequency TEXT NOT NULL,
            instructions TEXT,
            date_prescribed TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(doctor_id) REFERENCES users(id),
            FOREIGN KEY(patient_id) REFERENCES users(id)
        )
    """)

    # Invites
    conn.execute("""
        CREATE TABLE IF NOT EXISTS invites (
            code TEXT PRIMARY KEY,
            doctor_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            is_used BOOLEAN DEFAULT 0,
            FOREIGN KEY(doctor_id) REFERENCES users(id)
        )
    """)

    # Triage History
    conn.execute("""
        CREATE TABLE IF NOT EXISTS triage_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            risk_level TEXT NOT NULL,
            recommended_department TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES users(id)
        )
    """)

    # Doctor Profiles
    conn.execute("""
        CREATE TABLE IF NOT EXISTS doctor_profiles (
            user_id INTEGER PRIMARY KEY,
            qualifications TEXT,
            hospital_name TEXT,
            contact_phone TEXT,
            bio TEXT,
            address TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    # Migration for appointments table (add is_reminded)
    try:
        conn.execute("SELECT is_reminded FROM appointments LIMIT 1")
    except sqlite3.OperationalError:
        try:
            conn.execute("ALTER TABLE appointments ADD COLUMN is_reminded BOOLEAN DEFAULT 0")
        except: pass

    conn.commit()
    conn.close()

# --- Profiles ---

def upsert_doctor_profile(user_id: int, qual: str, hosp: str, phone: str, bio: str, addr: str):
    conn = _get_conn()
    conn.execute("""
        INSERT INTO doctor_profiles (user_id, qualifications, hospital_name, contact_phone, bio, address)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            qualifications=excluded.qualifications,
            hospital_name=excluded.hospital_name,
            contact_phone=excluded.contact_phone,
            bio=excluded.bio,
            address=excluded.address
    """, (user_id, qual, hosp, phone, bio, addr))
    conn.commit()
    conn.close()

def get_doctor_profile(user_id: int):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM doctor_profiles WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def register(email: str, password: str, full_name: str, role: str = 'patient', specialization: str = None) -> tuple[bool, str]:
    if not email or not email.strip():
        return False, "Email is required."
    if not password or len(password) < 6:
        return False, "Password must be at least 6 characters."
    if not full_name or not full_name.strip():
        return False, "Full name is required."
    
    email = email.strip().lower()
    full_name = full_name.strip()
    password_hash = generate_password_hash(password, method="scrypt")
    
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO users (email, password_hash, full_name, role, specialization) VALUES (?, ?, ?, ?, ?)",
            (email, password_hash, full_name, role, specialization),
        )
        conn.commit()
        return True, ""
    except sqlite3.IntegrityError:
        return False, "An account with this email already exists."
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_email(email: str) -> dict | None:
    if not email: return None
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def verify_password(email: str, password: str) -> dict | None:
    user = get_user_by_email(email)
    if not user or not check_password_hash(user["password_hash"], password):
        return None
    return user


# --- Helpers ---

def create_invite(doctor_id: int) -> str:
    code = uuid.uuid4().hex[:8].upper()
    conn = _get_conn()
    conn.execute("INSERT INTO invites (code, doctor_id) VALUES (?, ?)", (code, doctor_id))
    conn.commit()
    conn.close()
    return code

def get_invite(code: str):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM invites WHERE code = ? AND is_used = 0", (code,)).fetchone()
    conn.close()
    return dict(row) if row else None

def link_patient_to_doctor(patient_id: int, doctor_id: int):
    conn = _get_conn()
    try:
        conn.execute("INSERT OR IGNORE INTO doctor_patient_links (doctor_id, patient_id) VALUES (?, ?)", (doctor_id, patient_id))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def get_doctor_patients(doctor_id: int):
    conn = _get_conn()
    rows = conn.execute("""
        SELECT u.id, u.full_name, u.email, l.status 
        FROM doctor_patient_links l
        JOIN users u ON l.patient_id = u.id
        WHERE l.doctor_id = ?
    """, (doctor_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_patient_doctors(patient_id: int):
    conn = _get_conn()
    rows = conn.execute("""
        SELECT u.id, u.full_name, u.email, u.specialization
        FROM doctor_patient_links l
        JOIN users u ON l.doctor_id = u.id
        WHERE l.patient_id = ?
    """, (patient_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# --- Slots & Appointments ---

# --- Slots & Appointments ---

def create_slot(doctor_id: int, time_str: str, capacity: int = 1):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO appointment_slots (doctor_id, start_time, capacity, current_bookings) VALUES (?, ?, ?, 0)", 
        (doctor_id, time_str, capacity)
    )
    conn.commit()
    conn.close()

def get_available_slots(doctor_id: int):
    conn = _get_conn()
    # Return slots where booked < capacity
    rows = conn.execute("""
        SELECT * FROM appointment_slots 
        WHERE doctor_id = ? AND current_bookings < capacity
        ORDER BY start_time ASC
    """, (doctor_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def book_slot(slot_id: int, patient_id: int, note: str = "", ehr_path: str = None):
    conn = _get_conn()
    
    # Check availability with capacity
    slot = conn.execute(
        "SELECT * FROM appointment_slots WHERE id = ? AND current_bookings < capacity", 
        (slot_id,)
    ).fetchone()
    
    if not slot:
        conn.close()
        return False
    
    # Increment bookings
    new_bookings = slot["current_bookings"] + 1
    is_fully_booked = 1 if new_bookings >= slot["capacity"] else 0
    
    conn.execute(
        "UPDATE appointment_slots SET current_bookings = ?, is_booked = ? WHERE id = ?", 
        (new_bookings, is_fully_booked, slot_id)
    )
    
    # Create appointment record
    conn.execute(
        "INSERT INTO appointments (doctor_id, patient_id, slot_id, appointment_time, notes, ehr_file) VALUES (?, ?, ?, ?, ?, ?)",
        (slot["doctor_id"], patient_id, slot_id, slot["start_time"], note, ehr_path)
    )
    conn.commit()
    conn.close()
    return True

# Fallback for manual booking without slots
def create_manual_appointment(doctor_id: int, patient_id: int, time_str: str, notes: str = "", ehr_path: str = None):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO appointments (doctor_id, patient_id, appointment_time, notes, ehr_file) VALUES (?, ?, ?, ?, ?)",
        (doctor_id, patient_id, time_str, notes, ehr_path)
    )
    conn.commit()
    conn.close()

create_appointment = create_manual_appointment

def delete_appointment(appointment_id: int, user_id: int):
    conn = _get_conn()
    # Check ownership
    apt = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
    if not apt:
        conn.close()
        return False
    
    # Allow deletion if the user is either the patient or the doctor
    if apt["patient_id"] != user_id and apt["doctor_id"] != user_id:
        conn.close()
        return False
    
    # If linked to a slot, decrement booking count
    if apt["slot_id"]:
        conn.execute("""
            UPDATE appointment_slots 
            SET current_bookings = MAX(0, current_bookings - 1), is_booked = 0 
            WHERE id = ?
        """, (apt["slot_id"],))
        
    # Delete the appointment
    conn.execute("DELETE FROM appointments WHERE id = ?", (appointment_id,))
    conn.commit()
    conn.close()
    return True


def get_appointments_for_user(user_id: int, role: str):
    conn = _get_conn()
    query = f"""
        SELECT a.*, u.full_name as other_name, u.email as other_email
        FROM appointments a
        JOIN users u ON a.{'doctor_id' if role == 'patient' else 'patient_id'} = u.id
        WHERE a.{'patient_id' if role == 'patient' else 'doctor_id'} = ?
        ORDER BY a.appointment_time DESC
    """
    rows = conn.execute(query, (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# --- Prescriptions ---

def create_prescription(doctor_id: int, patient_id: int, name: str, dosage: str, freq: str, instructions: str):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO prescriptions (doctor_id, patient_id, medication_name, dosage, frequency, instructions) VALUES (?, ?, ?, ?, ?, ?)",
        (doctor_id, patient_id, name, dosage, freq, instructions)
    )
    conn.commit()
    conn.close()

def get_prescriptions_for_patient(patient_id: int):
    conn = _get_conn()
    rows = conn.execute("""
        SELECT p.*, d.full_name as doctor_name 
        FROM prescriptions p
        JOIN users d ON p.doctor_id = d.id
        WHERE p.patient_id = ?
        ORDER BY p.date_prescribed DESC
    """, (patient_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# --- Triage Stats ---

def save_triage_result(patient_id: int, risk: str, dept: str):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO triage_history (patient_id, risk_level, recommended_department) VALUES (?, ?, ?)",
        (patient_id, risk, dept)
    )
    conn.commit()
    conn.close()

def get_patient_history(patient_id: int):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT risk_level, recommended_department, created_at FROM triage_history WHERE patient_id = ? ORDER BY created_at DESC",
        (patient_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_upcoming_appointments(start_iso: str, end_iso: str):
    conn = _get_conn()
    try:
        # Join with users to get emails and names
        query = """
            SELECT a.id, a.appointment_time, 
                   p.full_name as patient_name, p.email as patient_email,
                   d.full_name as doctor_name
            FROM appointments a
            JOIN users p ON a.patient_id = p.id
            JOIN users d ON a.doctor_id = d.id
            WHERE a.appointment_time >= ? AND a.appointment_time <= ?
              AND (a.is_reminded IS NULL OR a.is_reminded = 0)
        """
        rows = conn.execute(query, (start_iso, end_iso)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"Error fetching upcoming appointments: {e}")
        return []
    finally:
        conn.close()

def mark_appointment_reminded(appointment_id: int):
    conn = _get_conn()
    try:
        conn.execute("UPDATE appointments SET is_reminded = 1 WHERE id = ?", (appointment_id,))
        conn.commit()
    except: pass
    finally:
        conn.close()

