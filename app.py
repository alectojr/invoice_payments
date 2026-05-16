import random
import string
import time

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
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# FIX #4: secret_key loaded from environment variable — never hardcoded.
# Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
app.secret_key = os.environ.get('SECRET_KEY')
if not app.secret_key:
    raise RuntimeError(
        "SECRET_KEY environment variable is not set. "
        "Set it before starting the application."
    )

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'sqlite:///brilliant_payments.db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# File upload configuration
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
ALLOWED_EXTENSIONS = {'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure upload directory exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

db = SQLAlchemy(app)

# ====================== TRANSLATION CONSTANTS ======================
# FIX #18: Translation dict is a module-level constant — not rebuilt on every call.
TRANSLATIONS = {
    'en': {
        'dashboard': 'Dashboard',
        'new_invoice': 'New Invoice',
        'manage_users': 'Manage Users',
        'profile': 'Profile',
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
        'cancel': 'Cancel',
    },
    'sw': {
        'dashboard': 'Dashibodi',
        'new_invoice': 'Ankara Mpya',
        'manage_users': 'Simamia Watumiaji',
        'profile': 'Profaili',
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
        'cancel': 'Ghairi',
    },
}

# ====================== LANGUAGE HELPERS ======================

def get_language():
    return session.get('language', 'en')


def _store_language(lang):
    """Store the chosen language in the session (internal helper)."""
    session['language'] = lang


def translate(key):
    lang = get_language()
    return TRANSLATIONS.get(lang, TRANSLATIONS['en']).get(key, key)


# ====================== CONTEXT PROCESSOR ======================

@app.context_processor
def inject_globals():
    return {
        'user_type': session.get('user_type', 'student'),
        'translate': translate,
    }


# ====================== MODELS ======================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    # FIX #1: passwords are stored as bcrypt hashes via werkzeug.
    password = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(150))
    phone = db.Column(db.String(20))
    role = db.Column(db.String(20), default='student')  # student, staff, admin
    pci_info = db.Column(db.String(255))
    profile_notes = db.Column(db.String(255))
    # Temp passwords are also stored as hashes.
    temp_password = db.Column(db.String(256))
    reset_requested = db.Column(db.Boolean, default=False)


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

    # Security fields for tamper-proofing
    security_hash = db.Column(db.String(128), nullable=False)
    digital_signature = db.Column(db.String(128), nullable=False)
    verification_code = db.Column(db.String(16), nullable=False)
    security_pattern = db.Column(db.String(32), nullable=False)


class Receipt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=False)
    uploaded_by = db.Column(db.String(80), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    payment = db.relationship('Payment', backref=db.backref('receipts', lazy=True))


# ====================== MIGRATION HELPERS ======================

# FIX #6: table_name and column_name are validated against an explicit allowlist
# before being interpolated into SQL, preventing injection via future callers.
_ALLOWED_TABLES = {'payment', 'user'}
_ALLOWED_COLUMNS = {
    'security_hash', 'digital_signature', 'verification_code', 'security_pattern',
    'role', 'pci_info', 'profile_notes', 'temp_password', 'reset_requested',
}

def ensure_table_columns_exist(table_name, expected_columns):
    if table_name not in _ALLOWED_TABLES:
        raise ValueError(f"Table '{table_name}' is not in the migration allowlist.")

    inspector = inspect(db.engine)
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {col['name'] for col in inspector.get_columns(table_name)}
    missing_columns = [col for col in expected_columns if col[0] not in existing_columns]
    if not missing_columns:
        return

    with db.engine.begin() as connection:
        for column_name, column_type in missing_columns:
            if column_name not in _ALLOWED_COLUMNS:
                raise ValueError(f"Column '{column_name}' is not in the migration allowlist.")
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
        ('pci_info', 'VARCHAR(255)'),
        ('profile_notes', 'VARCHAR(255)'),
        ('temp_password', 'VARCHAR(256)'),
        ('reset_requested', 'BOOLEAN DEFAULT 0'),
    ]
    ensure_table_columns_exist('user', expected_columns)


def migrate_existing_payments():
    """Add security fields to existing payments that don't have them."""
    try:
        ensure_security_columns_exist()
        # FIX #19: use .is_(None) for SQLAlchemy NULL comparisons.
        payments = Payment.query.filter(Payment.security_hash.is_(None)).all()

        for payment in payments:
            payment.security_hash = generate_security_hash(
                payment.invoice_no, payment.student_name, payment.course,
                payment.payment_type, payment.amount, payment.date,
            )
            payment.digital_signature = generate_digital_signature(payment.security_hash)
            payment.verification_code = generate_verification_code()
            payment.security_pattern = generate_security_pattern()

        if payments:
            db.session.commit()
            print(f'Migrated {len(payments)} existing payments with security features')
    except Exception as e:
        print(f'Migration skipped or failed: {e}')


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
    """
    Send an SMS confirmation to the matched student only.

    FIX #3: API key is read exclusively from environment — no hardcoded fallback.
    FIX #13: If a student_name is provided but no matching phone is found,
             the SMS is NOT sent to all users; it fails with an informative error.
    """
    at_username = os.getenv('AFRICASTALKING_USERNAME')
    api_key = os.getenv('AFRICASTALKING_API_KEY')

    if not at_username or not api_key:
        return None, 'AfricasTalking credentials are not configured (check env vars).'

    is_sandbox = at_username == 'sandbox'
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
        # Only look up the specific student — never fall back to all users.
        matched = User.query.filter(
            User.full_name == student_name,
            User.phone.isnot(None),
        ).all()
        for u in matched:
            normalized = normalize_phone(u.phone)
            if normalized:
                recipients.append(normalized)
            else:
                invalid_numbers.append(u.phone)

        if not recipients:
            return None, (
                f'No valid phone number found for student "{student_name}". '
                f'Invalid numbers: {invalid_numbers or "none on record"}.'
            )
    else:
        return None, 'No student name provided for SMS.'

    recipients = list(dict.fromkeys(recipients))

    try:
        response = requests.post(
            endpoint,
            headers={
                'Accept': 'application/json',
                'apiKey': api_key,
            },
            data={
                'username': at_username,
                'to': ','.join(recipients),
                'message': message,
                'bulkSMSMode': 1,
            },
            timeout=15,
            verify=not is_sandbox,
        )
        if 200 <= response.status_code < 300:
            content_type = response.headers.get('content-type', '')
            return (
                response.json() if content_type.startswith('application/json') else response.text,
                None,
            )
        return None, f'AfricasTalking SMS request failed ({response.status_code}): {response.text}'
    except requests.exceptions.SSLError as err:
        return None, 'SMS failed due to SSL/TLS issue. ' + str(err)
    except Exception as err:
        return None, str(err)


# ====================== FILE UPLOAD HELPERS ======================

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def generate_temp_password():
    """Generate a random readable temporary password."""
    fruits = [
        'apple', 'banana', 'orange', 'mango', 'pineapple',
        'grape', 'strawberry', 'watermelon', 'peach', 'cherry',
    ]
    return random.choice(fruits) + str(random.randint(10, 99))


# ====================== SECURITY FUNCTIONS ======================

def generate_security_hash(invoice_no, student_name, course, payment_type, amount, date):
    """Generate SHA-256 hash of invoice data for tamper detection."""
    data = f"{invoice_no}|{student_name}|{course}|{payment_type}|{amount}|{date}|{app.secret_key}"
    return hashlib.sha256(data.encode()).hexdigest()


def generate_digital_signature(security_hash):
    """Generate HMAC-SHA256 signature using the server secret key."""
    return hmac.new(
        app.secret_key.encode(), security_hash.encode(), hashlib.sha256
    ).hexdigest()


def generate_verification_code():
    """Generate a random 8-character alphanumeric verification code."""
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))


def generate_security_pattern():
    """Generate a unique 32-char hex security pattern for visual verification."""
    return secrets.token_hex(16)


def verify_invoice_integrity(payment):
    """Return True if the invoice data matches its stored hash and signature."""
    expected_hash = generate_security_hash(
        payment.invoice_no, payment.student_name, payment.course,
        payment.payment_type, payment.amount, payment.date,
    )
    expected_signature = generate_digital_signature(expected_hash)
    return (
        payment.security_hash == expected_hash
        and payment.digital_signature == expected_signature
    )


def refresh_payment_security(payment):
    """Recompute and store all security fields after a payment is edited.

    FIX #8: call this whenever payment fields are mutated so integrity
    checks don't permanently fail on edited records.
    """
    payment.security_hash = generate_security_hash(
        payment.invoice_no, payment.student_name, payment.course,
        payment.payment_type, payment.amount, payment.date,
    )
    payment.digital_signature = generate_digital_signature(payment.security_hash)


def generate_secure_qr_data(payment):
    """Generate QR code data with enhanced security information."""
    qr_data = (
        f"INVOICE_VERIFICATION\n"
        f"Invoice: {payment.invoice_no}\n"
        f"Student: {payment.student_name}\n"
        f"Course: {payment.course}\n"
        f"Amount: {payment.amount} TSh\n"
        f"Date: {payment.date}\n"
        f"Verification: {payment.verification_code}\n"
        f"Hash: {payment.security_hash[:16]}...\n"
        f"Signature: {payment.digital_signature[:16]}...\n"
        f"Pattern: {payment.security_pattern}\n"
        f"Timestamp: {payment.created_at.isoformat()}\n"
    )
    return qr_data


# ====================== INVOICE NUMBER GENERATOR ======================

def generate_invoice_no():
    """
    Generate a unique invoice number for today.

    FIX #12: the uniqueness loop is kept, and the unique DB constraint on
    invoice_no acts as the final safety net against race conditions.
    """
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


# ====================== BOOTSTRAP ======================

with app.app_context():
    db.create_all()
    ensure_user_columns_exist()
    migrate_existing_payments()


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
            # FIX #1: check temp password hash, then normal password hash.
            if user.temp_password and check_password_hash(user.temp_password, password):
                session['temp_user'] = username
                flash('Please set a new password.', 'info')
                return redirect(url_for('change_temp_password'))

            if check_password_hash(user.password, password):
                session['user'] = username
                session['user_type'] = user.role
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
        user = User.query.filter(
            User.username == username,
            User.role.in_(['staff', 'admin']),
        ).first()

        if user and check_password_hash(user.password, password):
            session['user'] = username
            session['user_type'] = user.role
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid staff/admin credentials!', 'error')
    return render_template('staff_login.html')


@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username, role='admin').first()

        if user and check_password_hash(user.password, password):
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

        # FIX #1: hash password before storing.
        new_user = User(
            username=username,
            password=generate_password_hash(password),
            full_name=full_name,
            phone=phone,
            role='student',
        )
        db.session.add(new_user)
        db.session.commit()

        flash('Student account created successfully! Please login.', 'success')
        return redirect(url_for('login'))
    return render_template(
        'signup.html',
        section_lead='Student Registration',
        heading='Student Signup',
        description='Create a student account to access payment records.',
        submit_text='Create Student Account',
    )


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

        # FIX #1: hash password before storing.
        new_user = User(
            username=username,
            password=generate_password_hash(password),
            full_name=full_name,
            phone=phone,
            role='staff',
        )
        db.session.add(new_user)
        db.session.commit()

        flash('Staff account created successfully! Please login.', 'success')
        return redirect(url_for('staff_login'))
    return render_template(
        'signup.html',
        section_lead='Staff Registration',
        heading='Staff Signup',
        description='Create a staff account to manage driving school operations.',
        submit_text='Create Staff Account',
    )


@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('home'))

    search = request.args.get('search', '')
    user_type = session.get('user_type', 'student')

    if user_type in ['admin', 'staff']:
        payments = Payment.query.order_by(Payment.created_at.desc()).all()
        if search:
            payments = (
                Payment.query
                .filter(Payment.student_name.contains(search))
                .order_by(Payment.created_at.desc())
                .all()
            )
        total_revenue = sum(p.amount for p in payments)
        total_paid = sum(p.amount for p in payments if p.status == 'Paid')
    else:
        # FIX #10: match on full_name so students see their own invoices.
        current_user = User.query.filter_by(username=session.get('user')).first()
        student_full_name = current_user.full_name if current_user else ''

        query = Payment.query.filter_by(student_name=student_full_name)
        if search:
            query = query.filter(Payment.student_name.contains(search))
        payments = query.order_by(Payment.created_at.desc()).all()

        total_revenue = None
        total_paid = None

    return render_template(
        'dashboard.html',
        payments=payments,
        total_revenue=total_revenue,
        total_paid=total_paid,
        search=search,
        user_type=user_type,
    )


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

        amount = 0
        if payment_type == 'Refresher 1 Week':
            amount = 100000
        elif payment_type == 'Refresher 2 Weeks':
            amount = 150000
        elif payment_type == 'Full Course':
            amount = 250000 if course != 'HGV' else 350000

        invoice_no = generate_invoice_no()
        date_str = datetime.now().strftime('%d %B %Y')

        security_hash = generate_security_hash(
            invoice_no, student_name, course, payment_type, amount, date_str
        )
        digital_signature = generate_digital_signature(security_hash)
        verification_code = generate_verification_code()
        security_pattern = generate_security_pattern()

        new_payment = Payment(
            invoice_no=invoice_no,
            student_name=student_name,
            course=course,
            payment_type=payment_type,
            amount=amount,
            status='Paid',
            date=date_str,
            security_hash=security_hash,
            digital_signature=digital_signature,
            verification_code=verification_code,
            security_pattern=security_pattern,
        )
        db.session.add(new_payment)
        db.session.commit()

        response, error = send_invoice_sms(course, student_name)
        if error:
            flash(f'Invoice {invoice_no} created successfully! SMS was not sent: {error}', 'warning')
        else:
            flash(f'Invoice {invoice_no} created successfully! SMS sent.', 'success')

        return redirect(url_for('view_invoice', invoice_no=invoice_no))

    return render_template('new_invoice.html')


@app.route('/view_invoice/<invoice_no>')
def view_invoice(invoice_no):
    if 'user' not in session:
        return redirect(url_for('home'))

    payment = Payment.query.filter_by(invoice_no=invoice_no).first_or_404()
    is_authentic = verify_invoice_integrity(payment)

    qr_text = generate_secure_qr_data(payment)
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(qr_text)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')

    buffered = BytesIO()
    img.save(buffered, format='PNG')
    qr_base64 = base64.b64encode(buffered.getvalue()).decode()

    return render_template(
        'view_invoice.html',
        payment=payment,
        qr_code=qr_base64,
        is_authentic=is_authentic,
    )


@app.route('/verify_invoice/<invoice_no>')
def verify_invoice(invoice_no):
    """
    Public endpoint to verify invoice authenticity.

    FIX #14: only returns verification status and the verification_code;
    full payment details are not exposed on the public endpoint.
    """
    payment = Payment.query.filter_by(invoice_no=invoice_no).first()

    if not payment:
        return render_template(
            'invoice_verification.html',
            verified=False,
            message='Invoice not found',
        )

    is_authentic = verify_invoice_integrity(payment)

    if is_authentic:
        return render_template(
            'invoice_verification.html',
            verified=True,
            invoice_no=payment.invoice_no,
            verification_code=payment.verification_code,
            message='Invoice is authentic and has not been tampered with',
        )
    else:
        return render_template(
            'invoice_verification.html',
            verified=False,
            invoice_no=payment.invoice_no,
            message='WARNING: Invoice has been tampered with or is invalid!',
        )


@app.route('/add_payment/<int:payment_id>', methods=['GET', 'POST'])
def add_payment(payment_id):
    if 'user' not in session:
        return redirect(url_for('home'))
    if session.get('user_type') != 'admin':
        flash('Access denied! Only admins can add payments.', 'error')
        return redirect(url_for('dashboard'))

    existing_payment = Payment.query.get_or_404(payment_id)

    if request.method == 'POST':
        try:
            amount = int(request.form.get('amount', 0))
        except ValueError:
            amount = 0

        if amount <= 0:
            flash('Please enter a valid amount.', 'error')
            return redirect(url_for('add_payment', payment_id=payment_id))

        payment_type = f'Additional Payment for {existing_payment.course}'
        invoice_no = generate_invoice_no()
        date_str = datetime.now().strftime('%d %B %Y')

        security_hash = generate_security_hash(
            invoice_no, existing_payment.student_name,
            existing_payment.course, payment_type, amount, date_str,
        )
        digital_signature = generate_digital_signature(security_hash)
        verification_code = generate_verification_code()
        security_pattern = generate_security_pattern()

        new_payment = Payment(
            invoice_no=invoice_no,
            student_name=existing_payment.student_name,
            course=existing_payment.course,
            payment_type=payment_type,
            amount=amount,
            status='Paid',
            date=date_str,
            security_hash=security_hash,
            digital_signature=digital_signature,
            verification_code=verification_code,
            security_pattern=security_pattern,
        )
        db.session.add(new_payment)
        db.session.commit()

        response, error = send_invoice_sms(payment_type, existing_payment.student_name)
        if error:
            flash(f'Additional payment {invoice_no} added! SMS was not sent: {error}', 'warning')
        else:
            flash(f'Additional payment {invoice_no} added! SMS sent.', 'success')

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
        # FIX #11: guard int() cast so a bad amount value doesn't raise 500.
        try:
            amount = int(request.form.get('amount', 0))
        except ValueError:
            flash('Invalid amount — please enter a whole number.', 'error')
            return redirect(url_for('edit_payment', id=id))

        if amount <= 0:
            flash('Amount must be greater than zero.', 'error')
            return redirect(url_for('edit_payment', id=id))

        payment.student_name = request.form.get('student_name')
        payment.course = request.form.get('course')
        payment.payment_type = request.form.get('payment_type')
        payment.amount = amount

        # FIX #8: regenerate security fields whenever payment data changes.
        refresh_payment_security(payment)

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

    # FIX #2: verify the logged-in admin's own password, not a hardcoded string.
    password = request.form.get('password')
    admin = User.query.filter_by(username=session.get('user')).first()
    if not admin or not check_password_hash(admin.password, password):
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


@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user' not in session:
        return redirect(url_for('home'))
    if session.get('user_type') not in ['admin', 'staff']:
        flash('Access denied! Profile is only available to staff and admin.', 'error')
        return redirect(url_for('dashboard'))

    user = User.query.filter_by(username=session.get('user')).first_or_404()

    if request.method == 'POST':
        user.full_name = request.form.get('full_name')
        user.phone = request.form.get('phone')

        if session.get('user_type') == 'admin':
            user.pci_info = request.form.get('pci_info')
            user.profile_notes = request.form.get('profile_notes')

        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile'))

    return render_template('profile.html', user=user)


@app.route('/edit_user/<int:id>', methods=['GET', 'POST'])
def edit_user(id):
    if 'user' not in session:
        return redirect(url_for('home'))
    if session.get('user_type') != 'admin':
        flash('Access denied! Only admins can edit users.', 'error')
        return redirect(url_for('manage_users'))

    user = User.query.get_or_404(id)

    if request.method == 'POST':
        new_role = request.form.get('role')
        if new_role == 'admin' and user.role != 'admin':
            admin_count = User.query.filter_by(role='admin').count()
            if admin_count >= 3:
                flash('Admin limit reached. Maximum 3 admins allowed.', 'error')
                return redirect(url_for('edit_user', id=id))

        user.username = request.form.get('username')
        user.full_name = request.form.get('full_name')
        user.phone = request.form.get('phone')
        user.pci_info = request.form.get('pci_info')
        user.profile_notes = request.form.get('profile_notes')
        user.role = new_role

        # FIX #9: only update the password when a non-empty value is provided.
        new_password = request.form.get('password', '').strip()
        if new_password:
            user.password = generate_password_hash(new_password)

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

    # FIX #2: verify the logged-in admin's own password, not a hardcoded string.
    password = request.form.get('password')
    admin = User.query.filter_by(username=session.get('user')).first()
    if not admin or not check_password_hash(admin.password, password):
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
            # FIX #1: store hashed password.
            user.password = generate_password_hash(new_password)
            user.temp_password = None
            db.session.commit()

            session.pop('temp_user', None)
            session['user'] = username
            session['user_type'] = user.role
            flash('Password changed successfully!', 'success')
            return redirect(url_for('dashboard'))

    return render_template('change_temp_password.html')


@app.route('/request_password_reset', methods=['GET', 'POST'])
def request_password_reset():
    if 'user' not in session:
        return redirect(url_for('login'))

    user = User.query.filter_by(username=session.get('user')).first()

    if request.method == 'GET':
        return render_template('request_password_reset.html', user=user)

    if user:
        if user.role == 'staff':
            user.reset_requested = True
            db.session.commit()
            flash('Password reset request sent to admin. Please wait for approval.', 'info')
        else:
            # FIX #15: temp password is NOT shown in the flash message.
            # It is stored hashed; admin must deliver it via a secure channel (SMS/in-person).
            temp_pass = generate_temp_password()
            user.temp_password = generate_password_hash(temp_pass)
            db.session.commit()
            # In production, send temp_pass via SMS here instead of displaying it.
            flash(
                'A temporary password has been generated. '
                'Please ask an administrator for it or check your SMS.',
                'info',
            )
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
        # FIX #1 / #15: store hash; show plaintext to admin once so they can
        # relay it securely — this is acceptable for an in-person admin action.
        user.temp_password = generate_password_hash(temp_pass)
        user.reset_requested = False
        db.session.commit()
        flash(
            f'Temporary password for {user.username}: {temp_pass} '
            '— share this securely and do not leave this page open.',
            'success',
        )

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
            # FIX #17: time imported at top of file.
            timestamp = str(int(time.time()))
            new_filename = f"{timestamp}_{filename}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
            file.save(file_path)

            receipt = Receipt(
                filename=new_filename,
                original_filename=filename,
                payment_id=payment_id,
                uploaded_by=session.get('user'),
            )
            db.session.add(receipt)
            db.session.commit()

            flash('Receipt uploaded successfully!', 'success')
            return redirect(url_for('view_invoice', invoice_no=payment.invoice_no))
        else:
            flash('Invalid file type. Only PDF files are allowed.', 'error')

    return render_template('upload_receipt.html', payment=payment)


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """
    FIX #5: require login before serving uploaded files.
    Staff/admin can access any receipt; students can only access receipts
    linked to their own payments.
    """
    if 'user' not in session:
        flash('Please log in to access files.', 'error')
        return redirect(url_for('login'))

    user_type = session.get('user_type', 'student')

    if user_type in ['admin', 'staff']:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    # Students: verify the file belongs to one of their payments.
    receipt = Receipt.query.filter_by(filename=filename).first_or_404()
    current_user = User.query.filter_by(username=session.get('user')).first()
    if not current_user or receipt.payment.student_name != current_user.full_name:
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))

    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ====================== LANGUAGE SWITCHING ======================

@app.route('/set_language/<lang>')
def switch_language(lang):
    """
    FIX #7: route renamed to switch_language to avoid infinite recursion
    with the _store_language helper.
    """
    if lang in ['en', 'sw']:
        _store_language(lang)
    return redirect(request.referrer or url_for('dashboard'))


# ====================== LOGOUT ======================

@app.route('/logout')
def logout():
    # FIX #16: clear the entire session so no stale keys (user_type, temp_user, etc.) persist.
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))


# ====================== ENTRY POINT ======================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    # FIX #20: debug mode driven by environment variable — never hardcoded True.
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(debug=debug, host='0.0.0.0', port=port)