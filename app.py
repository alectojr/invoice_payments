import random
import string

from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from datetime import datetime
import os
import re
import qrcode
from io import BytesIO
import base64
import requests
import hashlib
import hmac
import secrets
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "brilliant_driving_school_2026_secret_key"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///brilliant_payments.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# File upload configuration
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
ALLOWED_EXTENSIONS = {'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure upload directory exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

db = SQLAlchemy(app)

# Context processor to make user_type and translate function available in all templates
@app.context_processor
def inject_globals():
    return {
        'user_type': session.get('user_type', 'student'),
        'translate': translate
    }

# ====================== MODELS ======================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    full_name = db.Column(db.String(150))
    phone = db.Column(db.String(20))
    role = db.Column(db.String(20), default="student")  # student, staff, admin
    temp_password = db.Column(db.String(120))  # For password reset
    reset_requested = db.Column(db.Boolean, default=False)

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
    
    # Security fields for tamper-proofing
    security_hash = db.Column(db.String(128), nullable=False)  # SHA-256 hash
    digital_signature = db.Column(db.String(128), nullable=False)  # HMAC signature
    verification_code = db.Column(db.String(16), nullable=False)  # Random verification code
    security_pattern = db.Column(db.String(32), nullable=False)  # Unique pattern

class Receipt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=False)
    uploaded_by = db.Column(db.String(80), nullable=False)  # username of uploader
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    payment = db.relationship('Payment', backref=db.backref('receipts', lazy=True))

# Migration helper for existing tables
def ensure_table_columns_exist(table_name, expected_columns):
    inspector = inspect(db.engine)
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {col['name'] for col in inspector.get_columns(table_name)}
    missing_columns = [col for col in expected_columns if col[0] not in existing_columns]
    if not missing_columns:
        return

    with db.engine.begin() as connection:
        for column_name, column_type in missing_columns:
            connection.execute(text(
                f'ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}'
            ))
            print(f'Added missing column to {table_name}: {column_name}')


def ensure_security_columns_exist():
    expected_columns = [
        ('security_hash', 'VARCHAR(128)'),
        ('digital_signature', 'VARCHAR(128)'),
        ('verification_code', 'VARCHAR(16)'),
        ('security_pattern', 'VARCHAR(32)'),
    ]
    ensure_table_columns_exist('payment', expected_columns)


def ensure_user_columns_exist():
    expected_columns = [
        ('role', 'VARCHAR(20) DEFAULT "student"'),
        ('temp_password', 'VARCHAR(120)'),
        ('reset_requested', 'BOOLEAN DEFAULT 0'),
    ]
    ensure_table_columns_exist('user', expected_columns)


def migrate_existing_payments():
    """Add security fields to existing payments that don't have them"""
    try:
        ensure_security_columns_exist()
        payments = Payment.query.filter(Payment.security_hash == None).all()

        for payment in payments:
            payment.security_hash = generate_security_hash(
                payment.invoice_no, payment.student_name, payment.course,
                payment.payment_type, payment.amount, payment.date
            )
            payment.digital_signature = generate_digital_signature(payment.security_hash)
            payment.verification_code = generate_verification_code()
            payment.security_pattern = generate_security_pattern()

        if payments:
            db.session.commit()
            print(f"Migrated {len(payments)} existing payments with security features")
    except Exception as e:
        print(f"Migration skipped or failed: {e}")
        # If columns don't exist yet, they'll be created with new payments

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

# ====================== FILE UPLOAD HELPERS ======================
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_temp_password():
    fruits = ['apple', 'banana', 'orange', 'mango', 'pineapple', 'grape', 'strawberry', 'watermelon', 'peach', 'cherry']
    return random.choice(fruits) + str(random.randint(10, 99))

# ====================== LANGUAGE HELPERS ======================
def get_language():
    return session.get('language', 'en')

def set_language(lang):
    session['language'] = lang

def translate(key):
    translations = {
        'en': {
            'dashboard': 'Dashboard',
            'new_invoice': 'New Invoice',
            'manage_users': 'Manage Users',
            'logout': 'Logout',
            'login': 'Login',
            'signup': 'Sign Up',
            'admin_login': 'Admin Login',
            'staff_login': 'Staff Login',
            'total_revenue': 'Total Revenue',
            'total_paid': 'Total Paid',
            'search_students': 'Search by student name...',
            'search': 'Search',
            'invoice_no': 'Invoice No',
            'student_name': 'Student Name',
            'course': 'Course',
            'payment_type': 'Payment Type',
            'amount': 'Amount',
            'status': 'Status',
            'date': 'Date',
            'actions': 'Actions',
            'view_only': 'View Only',
            'add_payment': 'Add Payment',
            'edit': 'Edit',
            'delete': 'Delete',
            'print_invoice': 'Print Invoice',
            'back_dashboard': 'Back to Dashboard',
            'upload_receipt': 'Upload Receipt',
            'request_password': 'Request Password Reset',
            'change_password': 'Change Password',
            'current_password': 'Current Password',
            'new_password': 'New Password',
            'confirm_password': 'Confirm Password',
            'submit': 'Submit',
            'cancel': 'Cancel'
        },
        'sw': {
            'dashboard': 'Dashibodi',
            'new_invoice': 'Ankara Mpya',
            'manage_users': 'Simamia Watumiaji',
            'logout': 'Ondoka',
            'login': 'Ingia',
            'signup': 'Jisajili',
            'admin_login': 'Ingia Msimamizi',
            'staff_login': 'Ingia Mfanyakazi',
            'total_revenue': 'Jumla ya Mapato',
            'total_paid': 'Jumla ya Malipo',
            'search_students': 'Tafuta kwa jina la mwanafunzi...',
            'search': 'Tafuta',
            'invoice_no': 'Nambari ya Ankara',
            'student_name': 'Jina la Mwanafunzi',
            'course': 'Kozi',
            'payment_type': 'Aina ya Malipo',
            'amount': 'Kiasi',
            'status': 'Hali',
            'date': 'Tarehe',
            'actions': 'Vitendo',
            'view_only': 'Tazama Tu',
            'add_payment': 'Ongeza Malipo',
            'edit': 'Hariri',
            'delete': 'Futa',
            'print_invoice': 'Chapisha Ankara',
            'back_dashboard': 'Rudi Dashibodi',
            'upload_receipt': 'Pakia Risiti',
            'request_password': 'Omba Upya Nenosiri',
            'change_password': 'Badilisha Nenosiri',
            'current_password': 'Nenosiri la Sasa',
            'new_password': 'Nenosiri Mpya',
            'confirm_password': 'Thibitisha Nenosiri',
            'submit': 'Wasilisha',
            'cancel': 'Ghairi'
        }
    }
    lang = get_language()
    return translations.get(lang, translations['en']).get(key, key)

# ====================== SECURITY FUNCTIONS ======================
def generate_security_hash(invoice_no, student_name, course, payment_type, amount, date):
    """Generate SHA-256 hash of invoice data for tamper detection"""
    data = f"{invoice_no}|{student_name}|{course}|{payment_type}|{amount}|{date}|{app.secret_key}"
    return hashlib.sha256(data.encode()).hexdigest()

def generate_digital_signature(security_hash):
    """Generate HMAC signature using server secret key"""
    return hmac.new(app.secret_key.encode(), security_hash.encode(), hashlib.sha256).hexdigest()

def generate_verification_code():
    """Generate a random 8-character verification code"""
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))

def generate_security_pattern():
    """Generate a unique security pattern for visual verification"""
    return secrets.token_hex(16)

def verify_invoice_integrity(payment):
    """Verify that invoice hasn't been tampered with"""
    expected_hash = generate_security_hash(
        payment.invoice_no, payment.student_name, payment.course,
        payment.payment_type, payment.amount, payment.date
    )
    expected_signature = generate_digital_signature(expected_hash)
    
    return (payment.security_hash == expected_hash and 
            payment.digital_signature == expected_signature)

def generate_secure_qr_data(payment):
    """Generate QR code data with enhanced security information"""
    qr_data = f"""INVOICE_VERIFICATION
Invoice: {payment.invoice_no}
Student: {payment.student_name}
Course: {payment.course}
Amount: {payment.amount} TSh
Date: {payment.date}
Verification: {payment.verification_code}
Hash: {payment.security_hash[:16]}...
Signature: {payment.digital_signature[:16]}...
Pattern: {payment.security_pattern}
Timestamp: {payment.created_at.isoformat()}
"""
    return qr_data

# Run migration on app start
with app.app_context():
    db.create_all()
    ensure_user_columns_exist()
    migrate_existing_payments()


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
        user = User.query.filter_by(username=username).first()
        
        if user:
            # Check if user has temporary password that needs to be changed
            if user.temp_password and user.temp_password == password:
                session['temp_user'] = username
                flash('Please set a new password.', 'info')
                return redirect(url_for('change_temp_password'))
            
            # Normal login
            if user.password == password:
                session['user'] = username
                session['user_type'] = user.role  # student, staff, or admin
                flash('Login successful!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid password!', 'error')
        else:
            flash('User not found!', 'error')
    return render_template('login.html')

@app.route('/staff_login', methods=['GET', 'POST'])
def staff_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username, role='staff').first()
        
        if user and user.password == password:
            session['user'] = username
            session['user_type'] = 'staff'
            flash('Staff login successful!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid staff credentials!', 'error')
    return render_template('staff_login.html')

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

@app.route('/signup')
def signup():
    return render_template('signup_choice.html')

@app.route('/signup/student', methods=['GET', 'POST'])
def student_signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        full_name = request.form.get('full_name')
        phone = request.form.get('phone')

        if User.query.filter_by(username=username).first():
            flash('Username already exists!', 'error')
            return redirect(url_for('student_signup'))

        new_user = User(username=username, password=password, full_name=full_name, phone=phone, role='student')
        db.session.add(new_user)
        db.session.commit()

        flash('Student account created successfully! Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('signup.html', section_lead='Student Registration', heading='Student Signup', description='Create a student account to access payment records.', submit_text='Create Student Account')

@app.route('/signup/staff', methods=['GET', 'POST'])
def staff_signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        full_name = request.form.get('full_name')
        phone = request.form.get('phone')

        if User.query.filter_by(username=username).first():
            flash('Username already exists!', 'error')
            return redirect(url_for('staff_signup'))

        new_user = User(username=username, password=password, full_name=full_name, phone=phone, role='staff')
        db.session.add(new_user)
        db.session.commit()

        flash('Staff account created successfully! Please login.', 'success')
        return redirect(url_for('staff_login'))
    return render_template('signup.html', section_lead='Staff Registration', heading='Staff Signup', description='Create a staff account to manage driving school operations.', submit_text='Create Staff Account')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('home'))
    
    search = request.args.get('search', '')
    user_type = session.get('user_type', 'student')
    
    if user_type in ['admin', 'staff']:
        # Admins and staff see all payments
        payments = Payment.query.order_by(Payment.created_at.desc()).all()
        payments = Payment.query.filter(Payment.student_name.contains(search)).order_by(Payment.created_at.desc()).all() if search else payments
        
        total_revenue = sum(p.amount for p in payments)
        total_paid = sum(p.amount for p in payments if p.status == "Paid")
    else:
        # Students only see their own payments
        username = session.get('user')
        payments = Payment.query.filter_by(student_name=username).order_by(Payment.created_at.desc()).all()
        payments = Payment.query.filter_by(student_name=username).filter(Payment.student_name.contains(search)).order_by(Payment.created_at.desc()).all() if search else payments
        
        # Students don't see total revenue
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

        # Generate security data
        security_hash = generate_security_hash(invoice_no, student_name, course, payment_type, amount, date_str)
        digital_signature = generate_digital_signature(security_hash)
        verification_code = generate_verification_code()
        security_pattern = generate_security_pattern()

        new_payment = Payment(
            invoice_no=invoice_no,
            student_name=student_name,
            course=course,
            payment_type=payment_type,
            amount=amount,
            status="Paid",
            date=date_str,
            security_hash=security_hash,
            digital_signature=digital_signature,
            verification_code=verification_code,
            security_pattern=security_pattern
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
    
    # Verify invoice integrity
    is_authentic = verify_invoice_integrity(payment)
    
    # Generate secure QR code with enhanced verification data
    qr_text = generate_secure_qr_data(payment)
    
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(qr_text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    qr_base64 = base64.b64encode(buffered.getvalue()).decode()
    
    return render_template('view_invoice.html', 
                         payment=payment, 
                         qr_code=qr_base64, 
                         is_authentic=is_authentic)

@app.route('/verify_invoice/<invoice_no>')
def verify_invoice(invoice_no):
    """Public endpoint to verify invoice authenticity"""
    payment = Payment.query.filter_by(invoice_no=invoice_no).first()
    
    if not payment:
        return render_template('invoice_verification.html', 
                             verified=False, 
                             message="Invoice not found")
    
    is_authentic = verify_invoice_integrity(payment)
    
    if is_authentic:
        return render_template('invoice_verification.html', 
                             verified=True, 
                             payment=payment,
                             message="Invoice is authentic and has not been tampered with")
    else:
        return render_template('invoice_verification.html', 
                             verified=False, 
                             payment=payment,
                             message="WARNING: Invoice has been tampered with or is invalid!")

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
        
        # Generate security data
        security_hash = generate_security_hash(invoice_no, existing_payment.student_name, existing_payment.course, payment_type, amount, date_str)
        digital_signature = generate_digital_signature(security_hash)
        verification_code = generate_verification_code()
        security_pattern = generate_security_pattern()
        
        new_payment = Payment(
            invoice_no=invoice_no,
            student_name=existing_payment.student_name,
            course=existing_payment.course,
            payment_type=payment_type,
            amount=amount,
            status="Paid",
            date=date_str,
            security_hash=security_hash,
            digital_signature=digital_signature,
            verification_code=verification_code,
            security_pattern=security_pattern
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
        user.role = request.form.get('role')
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

# ====================== PASSWORD MANAGEMENT ======================
@app.route('/change_temp_password', methods=['GET', 'POST'])
def change_temp_password():
    if 'temp_user' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if new_password != confirm_password:
            flash('Passwords do not match!', 'error')
            return redirect(url_for('change_temp_password'))
        
        username = session.get('temp_user')
        user = User.query.filter_by(username=username).first()
        if user:
            user.password = new_password
            user.temp_password = None
            db.session.commit()
            
            session.pop('temp_user', None)
            session['user'] = username
            session['user_type'] = user.role
            flash('Password changed successfully!', 'success')
            return redirect(url_for('dashboard'))
    
    return render_template('change_temp_password.html')

@app.route('/request_password_reset', methods=['POST'])
def request_password_reset():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    username = session.get('user')
    user = User.query.filter_by(username=username).first()
    
    if user:
        if user.role == 'staff':
            # Staff request password reset from admin
            user.reset_requested = True
            db.session.commit()
            flash('Password reset request sent to admin. Please wait for approval.', 'info')
        else:
            # Students get temporary password
            temp_pass = generate_temp_password()
            user.temp_password = temp_pass
            db.session.commit()
            flash(f'Temporary password generated: {temp_pass}. Please login with this password.', 'info')
            session.pop('user', None)
            return redirect(url_for('login'))
    
    return redirect(url_for('dashboard'))

@app.route('/reset_staff_password/<int:user_id>', methods=['POST'])
def reset_staff_password(user_id):
    if 'user' not in session or session.get('user_type') != 'admin':
        flash('Access denied!', 'error')
        return redirect(url_for('manage_users'))
    
    user = User.query.get_or_404(user_id)
    if user.role == 'staff':
        temp_pass = generate_temp_password()
        user.temp_password = temp_pass
        user.reset_requested = False
        db.session.commit()
        flash(f'Temporary password for {user.username}: {temp_pass}', 'success')
    
    return redirect(url_for('manage_users'))

# ====================== FILE UPLOAD ======================
@app.route('/upload_receipt/<int:payment_id>', methods=['GET', 'POST'])
def upload_receipt(payment_id):
    if 'user' not in session:
        return redirect(url_for('login'))
    
    user_type = session.get('user_type')
    if user_type not in ['admin', 'staff']:
        flash('Access denied! Only staff and admins can upload receipts.', 'error')
        return redirect(url_for('dashboard'))
    
    payment = Payment.query.get_or_404(payment_id)
    
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            # Add timestamp to avoid conflicts
            import time
            timestamp = str(int(time.time()))
            new_filename = f"{timestamp}_{filename}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
            file.save(file_path)
            
            # Save to database
            receipt = Receipt(
                filename=new_filename,
                original_filename=filename,
                payment_id=payment_id,
                uploaded_by=session.get('user')
            )
            db.session.add(receipt)
            db.session.commit()
            
            flash('Receipt uploaded successfully!', 'success')
            return redirect(url_for('view_invoice', id=payment_id))
        else:
            flash('Invalid file type. Only PDF files are allowed.', 'error')
    
    return render_template('upload_receipt.html', payment=payment)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ====================== LANGUAGE SWITCHING ======================
@app.route('/set_language/<lang>')
def set_language(lang):
    if lang in ['en', 'sw']:
        set_language(lang)
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)