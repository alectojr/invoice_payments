from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import qrcode
import os
from io import BytesIO
import base64

app = Flask(__name__)
app.secret_key = "brilliant_driving_school_2026"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///brilliant_payments.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==================== DATABASE MODEL ====================
class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_no = db.Column(db.String(50), unique=True, nullable=False)
    student_name = db.Column(db.String(150), nullable=False)
    course = db.Column(db.String(50), nullable=False)
    payment_type = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    date = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Create database
with app.app_context():
    db.create_all()

# Simple Login
USERS = {"admin": "admin123"}   # Change password later

@app.route('/')
def home():
    if 'user' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username in USERS and USERS[username] == password:
            session['user'] = username
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid credentials!', 'error')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    payments = Payment.query.order_by(Payment.created_at.desc()).all()
    return render_template('dashboard.html', payments=payments)

@app.route('/new_invoice', methods=['GET', 'POST'])
def new_invoice():
    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        student_name = request.form.get('student_name')
        course = request.form.get('course')
        payment_type = request.form.get('payment_type')
        amount = int(request.form.get('amount'))

        invoice_no = f"BDS-{datetime.now().strftime('%Y%m%d')}-{len(Payment.query.all())+1:04d}"
        date_str = datetime.now().strftime("%d %B %Y")

        # Save to database
        new_payment = Payment(
            invoice_no=invoice_no,
            student_name=student_name,
            course=course,
            payment_type=payment_type,
            amount=amount,
            date=date_str
        )
        db.session.add(new_payment)
        db.session.commit()

        # Generate QR Code
        qr_text = f"Brilliant Driving School\nInvoice: {invoice_no}\nStudent: {student_name}\nAmount: {amount:,} TSh"
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        qr_base64 = base64.b64encode(buffered.getvalue()).decode()

        return render_template('invoice.html', payment=new_payment, qr_base64=qr_base64)

    return render_template('new_invoice.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)