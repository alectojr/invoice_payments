from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import re
import qrcode
from io import BytesIO
import base64
import requests

app = Flask(__name__)
app.secret_key = "brilliant_driving_school_2026_secret_key"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///brilliant_payments.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ====================== MODELS ======================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    full_name = db.Column(db.String(150))
    phone = db.Column(db.String(20))

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_no = db.Column(db.String(50), unique=True, nullable=False)
    student_name = db.Column(db.String(150), nullable=False)
    course = db.Column(db.String(50), nullable=False)
    payment_type = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default="Paid")
    date = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Create tables
with app.app_context():
    db.create_all()

# ====================== SMS HELPERS ======================
def normalize_phone(phone):
    if not phone:
        return None
    phone = phone.strip()
    phone = re.sub(r'[^0-9+]', '', phone)
    if phone.startswith('00'):
        phone = '+' + phone[2:]
    if phone.startswith('0') and len(phone) >= 9:
        phone = '+255' + phone[1:]
    if phone.startswith('255') and not phone.startswith('+'):
        phone = '+' + phone
    if re.fullmatch(r'\+\d{10,15}', phone):
        return phone
    return None


def send_invoice_sms(course, student_name=None):
    username = os.getenv('AFRICASTALKING_USERNAME', 'sandbox')
    api_key = os.getenv('AFRICASTALKING_API_KEY', 'atsk_74d33ad403c6ae2694a8b52b77be08447e7693a51daf229e322c8bcd215c2564ab22bc06')
    is_sandbox = username == 'sandbox'
    base_url = 'https://api.sandbox.africastalking.com' if is_sandbox else 'https://api.africastalking.com'
    endpoint = base_url + '/version1/messaging'

    message = (
        f"Asante kwa kujisajili na Brilliant Driving School. "
        f"Malipo yako ya {course} yamepokelewa Ofisini kwetu. "
        "Kwa maswali zaidi Piga 0762003011"
    )

    invalid_numbers = []
    recipients = []
    if student_name:
        matched = User.query.filter(User.full_name == student_name, User.phone != None).all()
        for u in matched:
            normalized = normalize_phone(u.phone)
            if normalized:
                recipients.append(normalized)
            else:
                invalid_numbers.append(u.phone)

    if not recipients:
        for u in User.query.filter(User.phone != None).all():
            normalized = normalize_phone(u.phone)
            if normalized:
                recipients.append(normalized)
            else:
                invalid_numbers.append(u.phone)

    recipients = list(dict.fromkeys(recipients))
    if not recipients:
        return None, 'No valid recipient phone numbers are available.'

    try:
        response = requests.post(
            endpoint,
            headers={
                'Accept': 'application/json',
                'apiKey': api_key,
            },
            data={
                'username': username,
                'to': ','.join(recipients),
                'message': message,
                'bulkSMSMode': 1,
            },
            timeout=15,
            verify=not is_sandbox,
        )
        if response.status_code >= 200 and response.status_code < 300:
            return response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text, None
        return None, f'AfricasTalking SMS request failed ({response.status_code}): {response.text}'
    except requests.exceptions.SSLError as err:
        return None, 'SMS failed due to SSL/TLS issue. In sandbox mode, verify=False may be required. ' + str(err)
    except Exception as err:
        return None, str(err)


def generate_invoice_no():
    today = datetime.now().strftime('%Y%m%d')
    prefix = f"BDS-{today}-"
    latest = (
        Payment.query
        .filter(Payment.invoice_no.like(f"{prefix}%"))
        .order_by(Payment.invoice_no.desc())
        .first()
    )
    if latest:
        try:
            last_number = int(latest.invoice_no.rsplit('-', 1)[1])
        except ValueError:
            last_number = 0
        next_number = last_number + 1
    else:
        next_number = 1

    invoice_no = f"{prefix}{next_number:04d}"
    while Payment.query.filter_by(invoice_no=invoice_no).first():
        next_number += 1
        invoice_no = f"{prefix}{next_number:04d}"
    return invoice_no

# ====================== ROUTES ======================
@app.route('/')
def home():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('home.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            session['user'] = username
            session['user_type'] = 'normal'
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid username or password!', 'error')
    return render_template('login.html')

@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == "admin" and password == "admin123":
            session['user'] = username
            session['user_type'] = 'admin'
            flash('Admin login successful!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid admin credentials!', 'error')
    return render_template('admin_login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        full_name = request.form.get('full_name')
        phone = request.form.get('phone')

        if User.query.filter_by(username=username).first():
            flash('Username already exists!', 'error')
            return redirect(url_for('signup'))

        new_user = User(username=username, password=password, full_name=full_name, phone=phone)
        db.session.add(new_user)
        db.session.commit()

        flash('Account created successfully! Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('home'))
    
    search = request.args.get('search', '')
    user_type = session.get('user_type', 'normal')
    
    if user_type == 'admin':
        # Admins see all payments
        payments = Payment.query.order_by(Payment.created_at.desc()).all()
        payments = Payment.query.filter(Payment.student_name.contains(search)).order_by(Payment.created_at.desc()).all() if search else payments
        
        total_revenue = sum(p.amount for p in payments)
        total_paid = sum(p.amount for p in payments if p.status == "Paid")
    else:
        # Regular users only see their own payments
        username = session.get('user')
        payments = Payment.query.filter_by(student_name=username).order_by(Payment.created_at.desc()).all()
        payments = Payment.query.filter_by(student_name=username).filter(Payment.student_name.contains(search)).order_by(Payment.created_at.desc()).all() if search else payments
        
        # Regular users don't see total revenue
        total_revenue = None
        total_paid = None
    
    return render_template('dashboard.html', 
                         payments=payments, 
                         total_revenue=total_revenue,
                         total_paid=total_paid,
                         search=search,
                         user_type=user_type)

@app.route('/new_invoice', methods=['GET', 'POST'])
def new_invoice():
    if 'user' not in session:
        return redirect(url_for('home'))
    if session.get('user_type') != 'admin':
        flash('Access denied! Only admins can create invoices.', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        student_name = request.form.get('student_name')
        course = request.form.get('course')
        payment_type = request.form.get('payment_type')

        # Auto amount calculation
        amount = 0
        if payment_type == "Refresher 1 Week":
            amount = 100000
        elif payment_type == "Refresher 2 Weeks":
            amount = 150000
        elif payment_type == "Full Course":
            amount = 250000 if course != "HGV" else 350000

        invoice_no = generate_invoice_no()
        date_str = datetime.now().strftime("%d %B %Y")

        new_payment = Payment(
            invoice_no=invoice_no,
            student_name=student_name,
            course=course,
            payment_type=payment_type,
            amount=amount,
            status="Paid",
            date=date_str
        )
        db.session.add(new_payment)
        db.session.commit()

        response, error = send_invoice_sms(course, student_name)
        if error:
            flash(f'Invoice {invoice_no} created successfully! SMS was not sent: {error}', 'warning')
        else:
            flash(f'Invoice {invoice_no} created successfully! SMS sent to users.', 'success')

        return redirect(url_for('view_invoice', invoice_no=invoice_no))

    return render_template('new_invoice.html')

@app.route('/view_invoice/<invoice_no>')
def view_invoice(invoice_no):
    if 'user' not in session:
        return redirect(url_for('home'))
    
    payment = Payment.query.filter_by(invoice_no=invoice_no).first_or_404()
    
    # Generate QR code with payment details
    qr_text = f"""Brilliant Driving School
Invoice: {payment.invoice_no}
Date: {payment.date}
Student: {payment.student_name}
Course: {payment.course}
Payment: {payment.payment_type}
Amount: {payment.amount:,} TSh
Status: {payment.status}"""
    
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(qr_text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    qr_base64 = base64.b64encode(buffered.getvalue()).decode()
    
    return render_template('view_invoice.html', payment=payment, qr_code=qr_base64)

@app.route('/add_payment/<int:payment_id>', methods=['GET', 'POST'])
def add_payment(payment_id):
    if 'user' not in session:
        return redirect(url_for('home'))
    if session.get('user_type') != 'admin':
        flash('Access denied! Only admins can add payments.', 'error')
        return redirect(url_for('dashboard'))
    
    existing_payment = Payment.query.get_or_404(payment_id)
    
    if request.method == 'POST':
        payment_type = request.form.get('payment_type')
        
        # Auto amount calculation
        amount = 0
        if payment_type == "Refresher 1 Week":
            amount = 100000
        elif payment_type == "Refresher 2 Weeks":
            amount = 150000
        elif payment_type == "Full Course":
            amount = 250000 if existing_payment.course != "HGV" else 350000
        
        invoice_no = generate_invoice_no()
        date_str = datetime.now().strftime("%d %B %Y")
        
        new_payment = Payment(
            invoice_no=invoice_no,
            student_name=existing_payment.student_name,
            course=existing_payment.course,
            payment_type=payment_type,
            amount=amount,
            status="Paid",
            date=date_str
        )
        db.session.add(new_payment)
        db.session.commit()
        
        response, error = send_invoice_sms(payment_type, existing_payment.student_name)
        if error:
            flash(f'Additional payment {invoice_no} added successfully! SMS was not sent: {error}', 'warning')
        else:
            flash(f'Additional payment {invoice_no} added successfully! SMS sent to users.', 'success')
        
        return redirect(url_for('view_invoice', invoice_no=invoice_no))
    
    return render_template('add_payment.html', existing_payment=existing_payment)
@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_payment(id):
    if 'user' not in session:
        return redirect(url_for('home'))
    if session.get('user_type') != 'admin':
        flash('Access denied! Only admins can edit payments.', 'error')
        return redirect(url_for('dashboard'))
    
    payment = Payment.query.get_or_404(id)
    
    if request.method == 'POST':
        payment.student_name = request.form.get('student_name')
        payment.course = request.form.get('course')
        payment.payment_type = request.form.get('payment_type')
        payment.amount = int(request.form.get('amount'))
        db.session.commit()
        flash('Payment updated successfully!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('edit_payment.html', payment=payment)


@app.route('/delete/<int:id>', methods=['POST'])
def delete_payment(id):
    if 'user' not in session:
        return redirect(url_for('home'))
    if session.get('user_type') != 'admin':
        flash('Access denied! Only admins can delete payments.', 'error')
        return redirect(url_for('dashboard'))
    
    password = request.form.get('password')
    if password != "admin123":
        flash('Incorrect password! Delete failed.', 'error')
        return redirect(url_for('dashboard'))
    
    payment = Payment.query.get_or_404(id)
    db.session.delete(payment)
    db.session.commit()
    flash('Payment record deleted!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/manage_users')
def manage_users():
    if 'user' not in session:
        return redirect(url_for('home'))
    if session.get('user_type') != 'admin':
        flash('Access denied! Only admins can manage users.', 'error')
        return redirect(url_for('dashboard'))
    
    users = User.query.all()
    return render_template('manage_users.html', users=users)

@app.route('/edit_user/<int:id>', methods=['GET', 'POST'])
def edit_user(id):
    if 'user' not in session:
        return redirect(url_for('home'))
    if session.get('user_type') != 'admin':
        flash('Access denied! Only admins can edit users.', 'error')
        return redirect(url_for('manage_users'))
    
    user = User.query.get_or_404(id)
    
    if request.method == 'POST':
        user.username = request.form.get('username')
        user.password = request.form.get('password')
        user.full_name = request.form.get('full_name')
        user.phone = request.form.get('phone')
        db.session.commit()
        flash('User updated successfully!', 'success')
        return redirect(url_for('manage_users'))
    
    return render_template('edit_user.html', user=user)

@app.route('/delete_user/<int:id>', methods=['POST'])
def delete_user(id):
    if 'user' not in session:
        return redirect(url_for('home'))
    if session.get('user_type') != 'admin':
        flash('Access denied! Only admins can delete users.', 'error')
        return redirect(url_for('manage_users'))
    
    password = request.form.get('password')
    if password != "admin123":
        flash('Incorrect password! Delete failed.', 'error')
        return redirect(url_for('manage_users'))
    
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()
    flash('User deleted!', 'success')
    return redirect(url_for('manage_users'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)