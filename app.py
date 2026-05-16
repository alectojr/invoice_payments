import random
import string
import time
import os
import re
import qrcode
import hashlib
import hmac
import secrets
from io import BytesIO
import base64
import requests
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "8b9456b816e37033f27ec4736b7b34f9051febe357b6d0c58659ffa0aac31dff"

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///brilliant_driving_school.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
ALLOWED_EXTENSIONS = {'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

db = SQLAlchemy(app)

# ====================== TRANSLATIONS ======================
# (Keep your existing TRANSLATIONS dict here - shortened for space)
TRANSLATIONS = {
    'en': {'dashboard': 'Dashboard', 'new_invoice': 'New Invoice', 'manage_users': 'Manage Users', 'students': 'Students'},
    'sw': {'dashboard': 'Dashibodi', 'new_invoice': 'Ankara Mpya', 'manage_users': 'Simamia Watumiaji', 'students': 'Wanafunzi'}
}

def get_language():
    return session.get('language', 'en')

def translate(key):
    lang = get_language()
    return TRANSLATIONS.get(lang, TRANSLATIONS['en']).get(key, key)

@app.context_processor
def inject_globals():
    return {'user_type': session.get('user_type', 'student'), 'translate': translate}

# ====================== MODELS ======================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(150))
    phone = db.Column(db.String(20))
    role = db.Column(db.String(20), default='student')
    temp_password = db.Column(db.String(256))
    reset_requested = db.Column(db.Boolean, default=False)

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    registration_number = db.Column(db.String(50), unique=True, nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    phone = db.Column(db.String(20), nullable=False)
    date_of_birth = db.Column(db.String(20))
    gender = db.Column(db.String(20))
    address = db.Column(db.Text)
    course = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='Pending')
    approved_by = db.Column(db.String(80))
    approved_at = db.Column(db.DateTime)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    def generate_reg_number(self):
        year = datetime.now().strftime('%Y')
        count = db.session.query(Student).count() + 1
        return f"BDS-{year}-{count:04d}"

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_no = db.Column(db.String(50), unique=True, nullable=False)
    student_name = db.Column(db.String(150), nullable=False)
    course = db.Column(db.String(50), nullable=False)
    payment_type = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='Paid')
    date = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    security_hash = db.Column(db.String(128))
    digital_signature = db.Column(db.String(128))
    verification_code = db.Column(db.String(16))
    security_pattern = db.Column(db.String(32))

class Receipt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'))
    uploaded_by = db.Column(db.String(80))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

# ====================== HELPER FUNCTIONS ======================
def generate_temp_password():
    fruits = ['apple', 'banana', 'orange', 'mango', 'pineapple', 'grape', 'strawberry']
    return random.choice(fruits) + str(random.randint(10, 99))

def generate_invoice_no():
    today = datetime.now().strftime('%Y%m%d')
    prefix = f"BDS-{today}-"
    latest = Payment.query.filter(Payment.invoice_no.like(f"{prefix}%")).order_by(Payment.invoice_no.desc()).first()
    next_number = int(latest.invoice_no.rsplit('-', 1)[1]) + 1 if latest else 1
    invoice_no = f"{prefix}{next_number:04d}"
    while Payment.query.filter_by(invoice_no=invoice_no).first():
        next_number += 1
        invoice_no = f"{prefix}{next_number:04d}"
    return invoice_no

def generate_security_hash(invoice_no, student_name, course, payment_type, amount, date):
    data = f"{invoice_no}|{student_name}|{course}|{payment_type}|{amount}|{date}|{app.secret_key}"
    return hashlib.sha256(data.encode()).hexdigest()

def generate_digital_signature(security_hash):
    return hmac.new(app.secret_key.encode(), security_hash.encode(), hashlib.sha256).hexdigest()

def generate_verification_code():
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))

def generate_security_pattern():
    return secrets.token_hex(16)

# ====================== DATABASE INIT ======================
with app.app_context():
    db.create_all()
    print("✅ Database ready with Student + Payment system")

# ====================== ROUTES ======================

@app.route('/')
def home():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('home.html')

@app.route('/register/student', methods=['GET', 'POST'])
def student_register():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        dob = request.form.get('date_of_birth')
        gender = request.form.get('gender')
        course = request.form.get('course')
        address = request.form.get('address')

        username = email or phone
        if User.query.filter_by(username=username).first():
            flash('Email or Phone already registered!', 'error')
            return redirect(url_for('student_register'))

        temp_pass = generate_temp_password()
        user = User(username=username, password=generate_password_hash(temp_pass),
                    full_name=full_name, phone=phone, role='student')
        db.session.add(user)
        db.session.commit()

        student = Student(full_name=full_name, email=email, phone=phone,
                         date_of_birth=dob, gender=gender, course=course,
                         address=address, user_id=user.id)
        db.session.add(student)
        db.session.commit()

        flash('Registration successful! Waiting for staff approval.', 'success')
        return redirect(url_for('login'))

    return render_template('student_register.html')

@app.route('/students')
def students_list():
    if session.get('user_type') not in ['admin', 'staff']:
        flash('Access denied!', 'error')
        return redirect(url_for('dashboard'))
    students = Student.query.order_by(Student.id.desc()).all()
    return render_template('students_list.html', students=students)

@app.route('/students/add', methods=['GET', 'POST'])
def add_student():
    if session.get('user_type') not in ['admin', 'staff']:
        flash('Access denied!', 'error')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        student = Student(
            full_name=request.form.get('full_name'),
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            date_of_birth=request.form.get('date_of_birth'),
            gender=request.form.get('gender'),
            course=request.form.get('course'),
            address=request.form.get('address'),
            status='Approved',
            approved_by=session.get('user'),
            approved_at=datetime.utcnow()
        )
        db.session.add(student)
        db.session.commit()
        flash('Student added successfully!', 'success')
        return redirect(url_for('students_list'))
    return render_template('add_student.html')

@app.route('/students/approve/<int:sid>')
def approve_student(sid):
    if session.get('user_type') not in ['admin', 'staff']:
        return redirect(url_for('dashboard'))
    student = Student.query.get_or_404(sid)
    student.status = 'Approved'
    student.approved_by = session.get('user')
    student.approved_at = datetime.utcnow()
    db.session.commit()
    flash('Student approved!', 'success')
    return redirect(url_for('students_list'))

@app.route('/students/reject/<int:sid>')
def reject_student(sid):
    if session.get('user_type') not in ['admin', 'staff']:
        return redirect(url_for('dashboard'))
    student = Student.query.get_or_404(sid)
    student.status = 'Rejected'
    db.session.commit()
    flash('Student rejected.', 'error')
    return redirect(url_for('students_list'))

# Keep your original login, dashboard, new_invoice, etc. routes here
# (You can add them back from your original file)

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('home'))
    return render_template('dashboard.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)