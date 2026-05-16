import random
import os
from datetime import datetime
from io import BytesIO

from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# For PDF + QR Code
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import qrcode

app = Flask(__name__)
app.secret_key = "brilliant-driving-school-secret-2026"

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///brilliant_driving_school.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'

# Create upload folder
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

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
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20), nullable=False)
    course = db.Column(db.String(100))
    photo = db.Column(db.String(200))  # filename
    status = db.Column(db.String(20), default='Active')
    registration_date = db.Column(db.DateTime, default=datetime.utcnow)

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_no = db.Column(db.String(50), unique=True, nullable=False)
    student_name = db.Column(db.String(150), nullable=False)
    course = db.Column(db.String(100))
    payment_type = db.Column(db.String(100))
    amount = db.Column(db.Integer, nullable=False)
    date = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ====================== DATABASE INIT ======================
with app.app_context():
    db.create_all()

# ====================== PDF INVOICE WITH QR CODE ======================
def generate_pdf_invoice(payment):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    w, h = A4

    # Header
    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(w/2, h-80, "BRILLIANT DRIVING SCHOOL")
    c.setFont("Helvetica", 12)
    c.drawCentredString(w/2, h-100, "Professional Driving Training • Dar es Salaam")

    # Invoice Info
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, h-160, f"Invoice Number: {payment.invoice_no}")
    c.drawString(50, h-180, f"Date: {payment.date}")

    c.setFont("Helvetica", 12)
    c.drawString(50, h-210, f"Student Name: {payment.student_name}")
    c.drawString(50, h-230, f"Course: {payment.course}")
    c.drawString(50, h-250, f"Payment Type: {payment.payment_type}")

    # Amount
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, h-290, f"Total Amount: TSh {payment.amount:,}")

    # QR Code
    qr = qrcode.make(f"INVOICE:{payment.invoice_no}|STUDENT:{payment.student_name}|AMOUNT:{payment.amount}")
    qr.save("temp_qr.png")
    c.drawImage("temp_qr.png", w-200, h-420, 150, 150)

    # Approval Seal
    c.setFont("Helvetica-Bold", 16)
    c.setFillColorRGB(0, 0.7, 0)
    c.drawCentredString(w/2, h-480, "APPROVED FOR TEST")

    c.save()
    buffer.seek(0)
    return buffer

# ====================== ROUTES ======================
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    if session.get('user_type') == 'student':
        return redirect(url_for('student_dashboard'))
    
    # For admin/owner
    payments = Payment.query.order_by(Payment.created_at.desc()).all()
    return render_template('dashboard.html', payments=payments)

@app.route('/register', methods=['GET', 'POST'])
def student_register():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        course = request.form.get('course')

        username = email or phone
        if User.query.filter_by(username=username).first():
            flash('This email or phone is already registered!', 'error')
            return redirect(url_for('student_register'))

        # Handle photo upload
        photo_filename = None
        if 'photo' in request.files:
            file = request.files['photo']
            if file.filename:
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                photo_filename = filename

        user = User(
            username=username,
            password=generate_password_hash('123456'),
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
            photo=photo_filename
        )
        db.session.add(student)
        db.session.commit()

        flash('Registration Successful! Default password is 123456', 'success')
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
            session['full_name'] = user.full_name
            flash('Login Successful!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid username or password', 'error')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    payments = Payment.query.order_by(Payment.created_at.desc()).all()
    return render_template('dashboard.html', payments=payments)

@app.route('/new_payment', methods=['GET', 'POST'])
def new_payment():
    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        student_name = request.form.get('student_name')
        course = request.form.get('course')
        payment_type = request.form.get('payment_type')
        amount = int(request.form.get('amount', 0))

        invoice_no = f"INV-{datetime.now().strftime('%Y%m%d')}-{Payment.query.count()+1:04d}"

        payment = Payment(
            invoice_no=invoice_no,
            student_name=student_name,
            course=course,
            payment_type=payment_type,
            amount=amount,
            date=datetime.now().strftime('%d %B %Y')
        )
        db.session.add(payment)
        db.session.commit()

        flash('Invoice Created Successfully!', 'success')
        return redirect(url_for('view_invoice', invoice_no=invoice_no))

    return render_template('new_payment.html')

@app.route('/view_invoice/<invoice_no>')
def view_invoice(invoice_no):
    payment = Payment.query.filter_by(invoice_no=invoice_no).first_or_404()
    return render_template('view_invoice.html', payment=payment)

@app.route('/download_invoice/<invoice_no>')
def download_invoice(invoice_no):
    payment = Payment.query.filter_by(invoice_no=invoice_no).first_or_404()
    pdf_buffer = generate_pdf_invoice(payment)
    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f"{invoice_no}.pdf",
        mimetype='application/pdf'
    )

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)