from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
import qrcode
from io import BytesIO
import base64
import os

app = Flask(__name__)
app.secret_key = "brilliant_driving_school_2026"

# Simple admin (change password later)
USERS = {"admin": "admin123"}   # ← Change this!

payments = []

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
        flash('Invalid username or password!', 'error')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', payments=payments[-10:])  # Last 10 payments

@app.route('/new_invoice', methods=['GET', 'POST'])
def new_invoice():
    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        student_name = request.form.get('student_name')
        course = request.form.get('course')
        payment_type = request.form.get('payment_type')
        amount = int(request.form.get('amount'))

        invoice_no = f"BDS-{datetime.now().strftime('%Y%m%d')}-{len(payments)+1:04d}"
        date_str = datetime.now().strftime("%d %B %Y")

        payment = {
            'invoice_no': invoice_no,
            'date': date_str,
            'student_name': student_name,
            'course': course,
            'payment_type': payment_type,
            'amount': amount
        }
        payments.append(payment)

        # QR Code with full details
        qr_text = f"Brilliant Driving School\nInvoice: {invoice_no}\nStudent: {student_name}\nCourse: {course}\nAmount: {amount:,} TSh"
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        qr_base64 = base64.b64encode(buffered.getvalue()).decode()

        return render_template('invoice.html', payment=payment, qr_base64=qr_base64)

    return render_template('new_invoice.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)