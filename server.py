import os
import csv
import base64
import uuid
import random
import smtplib
import requests
from flask import Flask, request, redirect, url_for, render_template, session, abort, flash, Response, g
from functools import wraps
from datetime import datetime, timedelta
from io import BytesIO
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from email.mime.text import MIMEText
from flask_mail import Mail, Message
from dotenv import load_dotenv
from decimal import Decimal, InvalidOperation


# Google API imports (commented out if not used; uncomment if needed)
# from google.oauth2.credentials import Credentials
# from google_auth_oauthlib.flow import InstalledAppFlow
# from google.auth.transport.requests import Request
# from googleapiclient.discovery import build

# Database
import pymysql
from pymysql.err import OperationalError, IntegrityError

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from email_service import send_email_with_attachment

SCOPES = ['https://www.googleapis.com/auth/gmail.send']  # If using Gmail API

app = Flask(__name__)

# Configuration
DATA_PATH = os.path.join(app.root_path, 'database.csv')
CSV_PATH = DATA_PATH
TESTIMONIALS_CSV = os.path.join(os.path.dirname(__file__), "testimonials.csv")
REVIEWS_CSV = "testimonials.csv"
DATA_CSV = os.path.join(os.path.dirname(__file__), "database.csv")

HEADERS = [
    "id",
    "Timestamp",
    "Name",
    "Email",
    "Car",
    "Phone",
    "Is Mobile",
    "Contact Method",
    "Best Time to Call",
    "Preferred Appointment Time",
    "Message",
    "Vehicle Type",
    "Services",
    "Total",
    "Status",
]

CSV_FIELDS = [
    'name',
    'car',
    'date',
    'testimonial',
    'before',
    'after',
    'service_type'
]

UPLOAD_FOLDER = os.path.join(app.root_path, 'static/uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 3 * 1024 * 1024  # 3 MB limit

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

# Load environment variables
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path)

app.secret_key = os.getenv('SECRET_KEY', 'your-default-key')

# Flask-Mail configuration (kept for auto-replies, etc.)
app.config.update(
    MAIL_SERVER=os.getenv('SMTP_SERVER', 'smtp.gmail.com'),
    MAIL_PORT=int(os.getenv('SMTP_PORT', 587)),
    MAIL_USE_TLS=True,
    MAIL_USERNAME=os.getenv('EMAIL_USER'),
    MAIL_PASSWORD=os.getenv('EMAIL_PASS'),
    MAIL_DEFAULT_SENDER=os.getenv('EMAIL_USER')
)

mail = Mail(app)

DEFAULT_SERVICES = [
    ("oil", 5000),
    ("coolant", 30000),
    ("brake_fluid", 20000),
    ("trans_fluid", 30000),
    ("diff_fluid", 30000),
    ("ceramic_coating", 365),
]

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("adminlogin"))
        return f(*args, **kwargs)
    return decorated

def get_db():
    if "db" not in g:
        g.db = pymysql.connect(
            host="dorianridleysmith.mysql.pythonanywhere-services.com",
            user="dorianridleysmit",
            password="dsautocaredb",
            database="dorianridleysmit$default",
            cursorclass=pymysql.cursors.DictCursor,
        )
    return g.db

@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()
'''
@app.before_request
def enforce_canonical_url():
    canonical_scheme = "https"
    canonical_host = "www.dsautocare.com"
    incoming_scheme = request.scheme
    incoming_host = request.host.split(":", 1)[0].lower()
    if incoming_scheme != canonical_scheme or incoming_host != canonical_host:
        new_url = request.url.replace(
            f"{incoming_scheme}://{incoming_host}",
            f"{canonical_scheme}://{canonical_host}",
            1,
        )
        return redirect(new_url, code=301)
'''
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def load_reviews():
    if not os.path.isfile(REVIEWS_CSV):
        return []
    reviews = []
    with open(REVIEWS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, fieldnames=CSV_FIELDS)
        for row in reader:
            if not row or not row.get('name', '').strip():
                continue
            reviews.append(row)
    return reviews

def load_testimonials():
    if not os.path.isfile(TESTIMONIALS_CSV):
        return []
    testimonials = []
    with open(TESTIMONIALS_CSV, newline="") as f:
        reader = csv.DictReader(f, fieldnames=CSV_FIELDS)
        for row in reader:
            if not row.get("name", "").strip():
                continue
            testimonials.append(row)
    return testimonials

def is_empty_submission(row):
    for field in ("Name", "Email", "Car", "Phone", "Message"):
        if row.get(field, "").strip():
            return False
    return row.get("Status", "").strip().lower() == "inbox"

def read_submissions():
    rows = []
    if os.path.isfile(CSV_PATH):
        with open(CSV_PATH, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    if rows and "Status" not in rows[0]:
        for row in rows:
            row["Status"] = "inbox"
        write_submissions(rows)
    # Ensure all rows have 'id'
    updated = False
    for row in rows:
        if 'id' not in row or not row['id'].strip():
            row['id'] = str(uuid.uuid4())
            updated = True
    if updated:
        write_submissions(rows)
    return rows

def write_submissions(rows):
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS, extrasaction="ignore")
        writer.writeheader()
        clean_rows = [{h: row.get(h, "") for h in HEADERS} for row in rows]
        writer.writerows(clean_rows)

def load_and_filter_submissions():
    rows = read_submissions()
    inbox, accepted, completed, trash = [], [], [], []
    for row in rows:
        if is_empty_submission(row):
            row["Status"] = "trash"
        state = row["Status"].strip().lower()
        bucket = {"inbox": inbox, "accepted": accepted, "completed": completed}.get(state, trash)
        bucket.append(row)
    write_submissions(rows)
    return inbox, accepted, completed, trash

def write_to_csv(data):
    id_val = str(uuid.uuid4())
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        is_new = not os.path.isfile(DATA_CSV)
        with open(DATA_CSV, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=HEADERS)
            if is_new:
                writer.writeheader()
            row = {
                'id': id_val,
                'Timestamp': timestamp,
                'Name': data.get("name", "").strip(),
                'Email': data.get("email", "").strip(),
                'Car': data.get("car", "").strip(),
                'Phone': data.get("phone", "").strip(),
                'Is Mobile': data.get("is_mobile", "no").strip(),
                'Contact Method': data.get("contact_method", "none").strip(),
                'Best Time to Call': data.get("calltime", "").strip(),
                'Preferred Appointment Time': data.get("appointmenttime", "").strip(),
                'Message': data.get("message", "").strip(),
                'Vehicle Type': data.get("vehicle_type", "").strip(),
                'Services': data.get("services", "").strip(),
                'Total': data.get("total", "").strip(),
                'Status': "inbox",
            }
            writer.writerow(row)

        print("✅ Wrote to CSV")
    except (OSError, csv.Error) as e:
        print("❌ CSV write failed:", e)

def update_submission_status(submission_id, new_status):
    rows = read_submissions()
    for row in rows:
        if row.get('id') == submission_id:
            row["Status"] = new_status
            write_submissions(rows)
            return
    abort(404, description="Submission not found")

def read_csv_file():
    try:
        with open(CSV_PATH, mode='r', newline='') as f:
            reader = csv.reader(f)
            headers = next(reader, [])
            rows = list(reader)
    except FileNotFoundError:
        return [], []
    if "Status" not in headers:
        headers.append("Status")
        rows = [row + ["inbox"] for row in rows]
        write_submissions(rows)
    return headers, rows

def send_reminder_email(to, subject, body):
    msg = Message(subject, recipients=[to])
    msg.body = body
    try:
        mail.send(msg)
        print(f"✅ Email sent to {to}")
    except Exception as e:
        print(f"❌ Failed to send email to {to}: {e}")

def initialize_services(vin, mileage):
    db = get_db()
    with db.cursor() as cursor:
        for service, interval in DEFAULT_SERVICES:
            cursor.execute(
                """
                INSERT INTO services (
                  vin,
                  service_type,
                  last_mileage,
                  recommended_interval,
                  last_service_date
                ) VALUES (%s, %s, %s, %s, CURDATE())
                """,
                (vin, service, mileage, interval),
            )
        db.commit()

def create_message(sender, to, subject, message_text):
    msg = MIMEText(message_text)
    msg['to'] = to
    msg['from'] = sender
    msg['subject'] = subject
    raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {'raw': raw_message}

def send_message(service, user_id, message):
    try:
        sent = service.users().messages().send(userId=user_id, body=message).execute()
        print(f"Message Id: {sent['id']}")
        return sent
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

def send_auto_reply(to_email, user_name, vehicle):
    subject = "We've received your service request"
    body = f"""Hi {user_name},

Thanks for reaching out to DS Auto Care! We’ve received your request and will review it shortly.
We're excited to work on your {vehicle} — it's in great hands.

If you enjoy your experience with us, please consider leaving a Google review to help others discover our service.

— Dorian @ DS Auto Care
"""
    msg = Message(subject, recipients=[to_email], body=body)
    try:
        mail.send(msg)
    except smtplib.SMTPDataError as e:
        print("SMTPDataError:", e)
    except Exception as e:
        print(f"Failed to send auto-reply: {e}")

@app.route("/", methods=["GET"])
def home():
    """
    Homepage: Only GET to load and display reviews/gallery.
    Contact form posts to /send-email separately.
    """
    all_reviews = load_reviews()
    review_count = len(all_reviews)  # Renamed for clarity; adjust template if needed
    # Random 3 reviews for gallery
    featured_reviews = random.sample(all_reviews, k=min(3, len(all_reviews))) if all_reviews else []
    return render_template(
        "index.html",
        featured_reviews=featured_reviews,
        submission_count=review_count  # Keep old name if template expects it
    )

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password_hash = generate_password_hash(password)
        db = get_db()
        with db.cursor() as cursor:
            try:
                cursor.execute(
                    "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)",
                    (name, email, password_hash),
                )
                db.commit()
            except IntegrityError:
                return "<h3>Email already registered. Try logging in.</h3>"
        return redirect(url_for("login"))
    return '''
    <h2>Register</h2>
    <form method="post">
      Name: <input type="text" name="name"><br><br>
      Email: <input type="email" name="email"><br><br>
      Password: <input type="password" name="password"><br><br>
      <input type="submit" value="Register">
    </form>
    '''



@app.route("/cargallery")
def cargallery():
    return render_template("cargallery.html")

@app.route("/testimonial_form")
def testimonial_form():
    return render_template("testimonial_form.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            return redirect(url_for("dashboard"))
        return "<h3>Login failed. Please check your credentials.</h3>"
    return '''
    <h2>Login</h2>
    <form method="post">
      Email: <input type="email" name="email"><br><br>
      Password: <input type="password" name="password"><br><br>
      <input type="submit" value="Login">
    </form>
    '''


@app.route("/send-email", methods=["POST"])
def send_email():
    # Honeypot: silently drop bots
    if request.form.get("website"):
        return redirect(url_for("cargallery"))

    # Required fields
    name = request.form.get("name", "").strip()
    email_addr = request.form.get("email", "").strip()
    if not (name and email_addr):
        return redirect(url_for("cargallery"))

    # reCAPTCHA (keep as-is)
    recaptcha_response = request.form.get("g-recaptcha-response", "")
    secret = os.getenv("RECAPTCHA_SECRET_KEY", "")
    try:
        resp = requests.post(
            "https://www.google.com/recaptcha/api/siteverify",
            data={"secret": secret, "response": recaptcha_response},
            timeout=5
        )
        if not resp.json().get("success"):
            return "Captcha verification failed. Please try again.", 400
    except requests.RequestException:
        return "Captcha verification unavailable. Please try again later.", 500

    # Extract fields safely (use Flask helpers)
    vehicle_type = request.form.get("vehicle_type", "").strip()
    services_list = request.form.getlist("services[]")
    services = ", ".join(s.strip() for s in services_list if s and s.strip())
    total_raw = request.form.get("total", "0")

    # Normalize total (handle list-like or scalar unexpectedly)
    if isinstance(total_raw, (list, tuple)):
        total_raw = total_raw[0] if total_raw else "0"
    total_raw = str(total_raw).strip() or "0"
    try:
        total_amount = Decimal(total_raw)
        # Keep the canonical string for CSV/email (no scientific notation)
        total = format(total_amount.normalize(), "f")
    except (InvalidOperation, ValueError):
        app.logger.warning("Invalid total received: %r; defaulting to 0", total_raw)
        total = "0"

    car = request.form.get("car", "").strip()
    phone = request.form.get("phone", "").strip()
    is_mobile = request.form.get("is_mobile", "no").strip()
    contact_method = request.form.get("contact_method", "none").strip()
    calltime = request.form.get("calltime", "").strip()
    appointmenttime = request.form.get("appointmenttime", "").strip()
    message = request.form.get("message", "").strip()

    # Prepare data dict for write_to_csv
    data = {
        "name": name,
        "email": email_addr,
        "car": car,
        "phone": phone,
        "is_mobile": is_mobile,
        "contact_method": contact_method,
        "calltime": calltime,
        "appointmenttime": appointmenttime,
        "message": message,
        "vehicle_type": vehicle_type,
        "services": services,
        "total": total
    }

    # Write to CSV safely
    try:
        write_to_csv(data)
        app.logger.info("Wrote quote to CSV for %s", email_addr)
    except (OSError, csv.Error) as e:
        app.logger.exception("CSV write failed")
        # continue; don't crash the route for CSV failures

    # Auto-reply to user
    subject = "Your Quote from DS Auto Care"
    body = (
        f"Hi {name},\n\n"
        f"Thanks for requesting your service! Here's a summary:\n"
        f"Vehicle Type: {vehicle_type}\n"
        f"Services: {services}\n"
        f"Total Estimate: ${total}\n\n"
        f"We're excited to work on your {car}, it's in great hands!\n\n"
        f"Keep your ringer on! Ill reach out to confirm your appointment as soon as I can!\n\n"

        f"— Dorian @ DS Auto Care\n"
    )
    try:
        msg = Message(subject, recipients=[email_addr], body=body)
        mail.send(msg)
    except Exception:
        app.logger.exception("Failed to send auto-reply")

    # Email staff (include quote details) and attach CSV
    staff_subject = "New Quote Request from DS Auto Care"
    staff_body = (
        f"Name: {name}\n"
        f"Email: {email_addr}\n"
        f"Vehicle Type: {vehicle_type}\n"
        f"Services: {services}\n"
        f"Total Estimate: ${total}\n"
        f"Car: {car}\n"
        f"Phone: {phone} ({'Mobile' if is_mobile == 'yes' else 'Not Mobile'})\n"
        f"Preferred Contact Method: {contact_method.capitalize()}\n"
        f"Best Time to Call: {calltime}\n"
        f"Requested Appointment: {appointmenttime}\n"
        f"Additional Notes:\n{message}\n"
    )
    try:
        csv_path = os.path.join(app.root_path, "database.csv")
        send_email_with_attachment(staff_subject, staff_body, csv_path)
    except Exception:
        app.logger.exception("Failed to send staff email")

    return redirect(url_for("cargallery"))


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))


@app.route("/adminlogin", methods=["GET", "POST"])
def adminlogin():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "").strip()
        env_user = os.getenv("ADMIN_USER", "").strip().lower()
        env_pass = os.getenv("ADMIN_PASS", "").strip()
        if username == env_user and password == env_pass:
            session["logged_in"] = True
            return redirect(url_for("submissions"))
        return "<h3>Login failed. Please try again.</h3>"
    return '''
    <form method="post">
      <label>Username:</label><br>
      <input type="text" name="username"><br>
      <label>Password:</label><br>
      <input type="password" name="password"><br>
      <input type="submit" value="Login">
    </form>
    '''

@app.route("/adminlogout")
def adminlogout():
    session.clear()
    return redirect(url_for("adminlogin"))

@app.route("/submit-testimonial", methods=["POST"])
def submit_testimonial():
    """
    Process testimonial submission (separate from contact form).
    """
    form = request.form
    name = form.get("name", "").strip()
    car = form.get("car", "").strip()
    service_type = form.get("service_type", "unspecified").strip()
    service_date = form.get("service_date", "").strip()
    testimonial = form.get("testimonial", "").strip()
    before_photo = request.files.get("before_photo")
    after_photo = request.files.get("after_photo")
    if not (before_photo and after_photo and allowed_file(before_photo.filename) and allowed_file(after_photo.filename)):
        return "<h3>Only JPG, JPEG, PNG, or GIF files are accepted.</h3>"
    before_filename = f"before_{uuid.uuid4().hex}_{secure_filename(before_photo.filename)}"
    after_filename = f"after_{uuid.uuid4().hex}_{secure_filename(after_photo.filename)}"
    before_photo.save(os.path.join(app.config["UPLOAD_FOLDER"], before_filename))
    after_photo.save(os.path.join(app.config["UPLOAD_FOLDER"], after_filename))
    with open(TESTIMONIALS_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([name, car, service_date, testimonial, before_filename, after_filename, service_type])
    return redirect("/reviews")

@app.route('/sitemap.xml', methods=['GET'])
def sitemap():
    pages = [
        {'loc': url_for('home', _external=True), 'changefreq':'daily', 'priority':'1.0'},
        {'loc': url_for('cargallery', _external=True), 'changefreq':'monthly', 'priority':'0.8'},
        {'loc': url_for('reviews', _external=True), 'changefreq':'weekly', 'priority':'0.7'},
        {'loc': url_for('submit_testimonial', _external=True), 'changefreq':'weekly', 'priority':'0.7'},
        {'loc': url_for('testimonial_form', _external=True), 'changefreq':'weekly', 'priority':'0.7'},
        {'loc': url_for('submissions', _external=True), 'changefreq':'weekly', 'priority':'0.7'},
    ]
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for p in pages:
        xml += ['  <url>', f'    <loc>{p["loc"]}</loc>', f'    <changefreq>{p["changefreq"]}</changefreq>', f'    <priority>{p["priority"]}</priority>', '  </url>']
    xml.append('</urlset>')
    return Response('\n'.join(xml), mimetype='application/xml')


import logging

logger = logging.getLogger(__name__)

@app.route("/submissions")
@login_required
def submissions():
    # Load all rows from your existing loader
    rows = read_submissions()  # expected: list of dicts
    # Prepare empty buckets
    buckets = {"inbox": [], "accepted": [], "completed": [], "trash": []}

    # Map rows into buckets based on Status field
    for row in rows:
        # Status can come from new form fields; normalize to a simple key
        raw_status = row.get("Status", row.get("status", "inbox"))
        if raw_status is None:
            raw_status = "inbox"
        st = str(raw_status).strip().lower()
        # Normalize obvious synonyms
        if st in ("inbox", "new", "pending", ""):
            key = "inbox"
        elif st in ("accepted", "accept"):
            key = "accepted"
        elif st in ("completed", "complete", "done"):
            key = "completed"
        elif st in ("trash", "deleted", "deleted-by-user"):
            key = "trash"
        else:
            # unknown status -> log and send to inbox (safe fallback)
            logger.warning("Unknown submission status %r for row id %s; routing to inbox", st, row.get('id'))
            key = "inbox"
        buckets[key].append(row)

    # Keep your previous filter logic for inbox to avoid empty junk rows
    def has_content(r):
        return any(r.get(f, "").strip() for f in ("Name", "Email", "Car", "Message"))

    filtered_inbox = [r for r in buckets["inbox"] if has_content(r)]

    # For now we keep HEADERS to avoid changing the template contract:
    return render_template(
        "submissions.html",
        headers=HEADERS,
        inbox=filtered_inbox,
        accepted=buckets["accepted"],
        completed=buckets["completed"],
        trash=buckets["trash"],
    )

@app.route("/accept/<string:id>", methods=["POST"])
@login_required
def accept_job(id):
    update_submission_status(id, "accepted")
    flash("Moved to Accepted", "success")
    return redirect(url_for("submissions"))

@app.route("/complete/<string:id>", methods=["POST"])
@login_required
def complete_job(id):
    update_submission_status(id, "completed")
    flash("Marked as Completed", "success")
    return redirect(url_for("submissions"))

@app.route("/delete/<string:id>", methods=["POST"])
@login_required
def delete_job(id):
    update_submission_status(id, "trash")
    flash("Moved to Trash", "warning")
    return redirect(url_for("submissions"))

@app.route('/clear_inbox', methods=['POST'])
@login_required
def clear_inbox():
    rows = read_submissions()
    moved = 0
    for row in rows:
        is_empty = (row['Status'] == 'inbox' and not any(row[field].strip() for field in ["Name", "Email", "Car", "Phone", "Message"]))
        if is_empty:
            row['Status'] = 'trash'
            moved += 1
    write_submissions(rows)
    flash(f"Moved {moved} empty submissions to Trash.", 'info')
    return redirect(url_for('submissions'))

@app.errorhandler(413)
def too_large(e):
    return "<h3>File too large. Please keep uploads under 3MB.</h3>", 413

@app.route("/reviews")
def reviews():
    reviews = load_reviews()
    return render_template("reviews.html", reviews=reviews)

if __name__ == "__main__":
    app.run(debug=True)