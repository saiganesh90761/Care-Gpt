import smtplib
import os
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
from datetime import datetime

# Load env variables explicitly here to be safe
load_dotenv()
SMTP_EMAIL = os.environ.get("SMTP_EMAIL")
_pass = os.environ.get("SMTP_PASSWORD")
SMTP_PASSWORD = _pass.replace(" ", "") if _pass else None

def _send_async(to_email, subject, body):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print(f"SMTP error: Credentials missing. EMAIL set: {bool(SMTP_EMAIL)}, PASS set: {bool(SMTP_PASSWORD)}")
        return

    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_EMAIL
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"Email sent to {to_email}")
    except Exception as e:
        print(f"Failed to send email: {e}")

def send_email(to_email, subject, body):
    # Run in a separate thread to not block the request
    threading.Thread(target=_send_async, args=(to_email, subject, body)).start()

def send_appointment_confirmation(to_email, patient_name, doctor_name, time_str):
    subject = "Appointment Confirmation - HealthApp AI"
    dt = datetime.fromisoformat(time_str.replace("Z", ""))
    formatted_time = dt.strftime("%B %d, %Y at %I:%M %p")
    
    body = f"""
    <h2>Appointment Confirmed</h2>
    <p>Dear {patient_name},</p>
    <p>Your appointment with <b>{doctor_name}</b> has been confirmed.</p>
    <p><b>Time:</b> {formatted_time}</p>
    <p>Please arrive 10 minutes early.</p>
    <br>
    <p>Best regards,<br>HealthApp ChatBot Team</p>
    """
    send_email(to_email, subject, body)

def send_vitals_alert(doctor_email, patient_name, vitals):
    subject = f"URGENT: Abnormal Vitals Alert - {patient_name}"
    
    body = f"""
    <h2 style="color:red;">Critical Vitals Alert</h2>
    <p>Patient <b>{patient_name}</b> is showing abnormal vital signs.</p>
    <ul>
        <li><b>Heart Rate:</b> {vitals.get('heart_rate')} BPM</li>
        <li><b>SpO2:</b> {vitals.get('spo2')}%</li>
        <li><b>Blood Pressure:</b> {vitals.get('systolic')}/{vitals.get('diastolic')} mmHg</li>
        <li><b>Temperature:</b> {vitals.get('temperature')}°C</li>
    </ul>
    <p>Please review the patient's status immediately.</p>
    <br>
    <p>System Alert</p>
    """
    send_email(doctor_email, subject, body)

def send_appointment_reminder(to_email, patient_name, doctor_name, time_str):
    subject = "Reminder: Upcoming Appointment"
    dt = datetime.fromisoformat(time_str.replace("Z", ""))
    formatted_time = dt.strftime("%I:%M %p")
    
    body = f"""
    <h2>Appointment Reminder</h2>
    <p>Hello {patient_name},</p>
    <p>This is a reminder for your appointment with <b>{doctor_name}</b> today at <b>{formatted_time}</b>.</p>
    <br>
    <p>HealthApp AI</p>
    """
    send_email(to_email, subject, body)
