import random
import string
import secrets
import hashlib
import hmac
import os
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "super-secret-key-change-in-production"

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///brilliant_driving_school.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ====================== MODELS ======================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(150))
    phone = db.Column(db.String(20))
    role = db.Column(db.String(20), default='student')

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    registration_number = db.Column(db.String(50), unique=True, nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    phone = db.Column(db.String(20), nullable=False)
    course = db.Column(db.String(100))
    status = db.Column(db.String(20), default='Pending')
    approved_by = db.Column(db.String(80))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

# ====================== HELPERS ======================
def generate_temp_password():
    fruits = ['apple', 'banana', 'orange', 'mango']
    return random.choice(fruits) + str(random.randint(10, 99))

# ====================== INIT ======================
with app.app_context():
    db.create_all()

# ====================== ROUTES ======================

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/register/student', methods=['GET', 'POST'])
def student_register():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        course = request.form.get('course')

        username = email or phone
        if User.query.filter_by(username=username).first():
            flash('Already registered!', 'error')
            return redirect(url_for('student_register'))

        user = User(
            username=username,
            password=generate_password_hash(generate_temp_password()),
            full_name=full_name,
            phone=phone,
            role='student'
        )
        db.session.add(user)
        db.session.commit()

        student = Student(
            registration_number=f"BDS-{datetime.now().year}-{Student.query.count()+1:04d}",
            full_name=full_name,
            email=email,
            phone=phone,
            course=course,
            user_id=user.id
        )
        db.session.add(student)
        db.session.commit()

        flash('Registration successful! Awaiting approval.', 'success')
        return redirect(url_for('login'))

    return render_template('student_register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user'] = username
            session['user_type'] = user.role
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid credentials', 'error')
    return render_template('login.html')

@app.route('/staff_login', methods=['GET', 'POST'])
def staff_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.role in ['staff', 'admin']:
            session['user'] = username
            session['user_type'] = user.role
            flash('Staff login successful!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid staff credentials', 'error')
    return render_template('staff_login.html')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('home'))
    return render_template('dashboard.html')

@app.route('/students')
def students_list():
    if session.get('user_type') not in ['admin', 'staff']:
        flash('Access denied!', 'error')
        return redirect(url_for('dashboard'))
    students = Student.query.all()
    return render_template('students_list.html', students=students)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)