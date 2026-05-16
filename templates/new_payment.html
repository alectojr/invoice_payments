import random
import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import qrcode
from io import BytesIO

app = Flask(__name__)
app.secret_key = "brilliant-driving-school-2026"

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///brilliant_school.db'
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
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20), nullable=False)
    course = db.Column(db.String(100))
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

# ====================== INIT ======================
with app.app_context():
    db.create_all()

# ====================== PDF INVOICE GENERATOR ======================
def generate_pdf_invoice(payment):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Header
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(width/2, height-80, "BRILLIANT DRIVING SCHOOL")
    c.setFont("Helvetica", 12)
    c.drawCentredString(width/2, height-100, "Professional Driving Training | Dar es Salaam")

    # Invoice Details
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, height-150, f"Invoice #: {payment.invoice_no}")
    c.drawString(50, height-170, f"Date: {payment.date}")

    c.setFont("Helvetica", 12)
    c.drawString(50, height-200, f"Student: {payment.student_name}")
    c.drawString(50, height-220, f"Course: {payment.course}")
    c.drawString(50, height-240, f"Payment Type: {payment.payment_type}")

    # Amount
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height-280, f"Amount Paid: TSh {payment.amount:,}")

    # QR Code
    qr = qrcode.QRCode(version=1, box_size=4)
    qr.add_data(f"INVOICE:{payment.invoice_no}\nSTUDENT:{payment.student_name}\nAMOUNT:{payment.amount}")
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save("temp_qr.png")

    c.drawImage("temp_qr.png", width-180, height-380, 150, 150)

    # Approval Text
    c.setFont("Helvetica-Bold", 14)
    c.setFillColorRGB(0, 0.6, 0)
    c.drawCentredString(width/2, height-450, "APPROVED FOR TEST")

    c.setFont("Helvetica", 10)
    c.drawCentredString(width/2, height-470, "Scan QR Code to Verify • Brilliant Driving School")

    c.save()
    buffer.seek(0)
    return buffer

# ====================== ROUTES ======================
@app.route('/')
def home():
    return redirect(url_for('student_register'))

@app.route('/register', methods=['GET', 'POST'])
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

        user = User(username=username, password=generate_password_hash('123456'),
                    full_name=full_name, phone=phone, role='student')
        db.session.add(user)
        db.session.commit()

        student = Student(registration_number=f"BDS-{datetime.now().year}-{db.session.query(Student).count()+1:04d}",
                         full_name=full_name, email=email, phone=phone, course=course)
        db.session.add(student)
        db.session.commit()

        flash('Registration Successful!', 'success')
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
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid credentials', 'error')
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

        flash('Invoice Created!', 'success')
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
        download_name=f"Invoice_{invoice_no}.pdf",
        mimetype='application/pdf'
    )

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)