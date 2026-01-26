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

@app.route("/add-car", methods=["GET", "POST"])
def add_car():
    if "user_id" not in session:
        return redirect(url_for("login"))
    db = get_db()
    if request.method == "POST":
        vin = request.form.get("vin", "").strip().upper()
        make = request.form.get("make", "").strip()
        model = request.form.get("model", "").strip()
        year = request.form.get("year", "").strip()
        mileage = request.form.get("mileage", "").strip()
        with db.cursor() as cursor:
            try:
                cursor.execute(
                    "INSERT INTO cars (vin, make, model, year, mileage, owner_id) VALUES (%s, %s, %s, %s, %s, %s)",
                    (vin, make, model, year, mileage, session["user_id"]),
                )
                db.commit()
                initialize_services(vin, int(mileage))
            except IntegrityError:
                return "<h3>This VIN is already registered to another user.</h3>"
        return redirect(url_for("dashboard"))
    return '''
    <h2>Add a Car</h2>
    <form method="post">
      VIN: <input type="text" name="vin"><br><br>
      Make: <input type="text" name="make"><br><br>
      Model: <input type="text" name="model"><br><br>
      Year: <input type="text" name="year"><br><br>
      Mileage: <input type="number" name="mileage"><br><br>
      <input type="submit" value="Add Car">
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

@app.route("/add-mod", methods=["GET", "POST"])
def add_mod():
    if "user_id" not in session:
        return redirect(url_for("login"))
    vin = request.args.get("vin", "").strip().upper()
    db = get_db()
    if request.method == "POST":
        form = request.form
        vin = form.get("vin", "").strip().upper()
        mod_title = form.get("mod_title", "").strip()
        description = form.get("description", "").strip()
        mileage = form.get("mileage", "").strip()
        category = form.get("category", "").strip()
        installed_by = form.get("installed_by", "").strip()
        mod_image = request.files.get("mod_image")
        filename = None
        if mod_image and allowed_file(mod_image.filename):
            filename = f"mod_{uuid.uuid4().hex}_{secure_filename(mod_image.filename)}"
            mod_image.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO mod_logs (vin, user_id, mod_title, description, mileage, category, installed_by, image_filename) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (vin, session["user_id"], mod_title, description, mileage, category, installed_by, filename),
            )
            db.commit()
        return redirect(url_for("timeline", vin=vin))
    return f'''
    <h2>Add a Modification</h2>
    <form method="post" enctype="multipart/form-data">
      VIN: <input type="text" name="vin" value="{vin}"><br><br>
      Mod Title: <input type="text" name="mod_title"><br><br>
      Description:<br>
      <textarea name="description" rows="4" cols="40"></textarea><br><br>
      Mileage: <input type="number" name="mileage"><br><br>
      Category:
      <select name="category">
        <option value="Suspension">Suspension</option>
        <option value="Drivetrain">Drivetrain</option>
        <option value="Cosmetic">Cosmetic</option>
        <option value="Interior">Interior</option>
        <option value="Electronics">Electronics</option>
      </select><br><br>
      Installed By:
      <select name="installed_by">
        <option value="DIY">DIY</option>
        <option value="Professional">Professional</option>
      </select><br><br>
      Upload Image: <input type="file" name="mod_image"><br><br>
      <input type="submit" value="Add Mod">
    </form>
    '''

@app.route("/add-service", methods=["GET", "POST"])
def add_service():
    if "user_id" not in session:
        return redirect(url_for("login"))
    vin = request.args.get("vin", "").strip().upper()
    if not vin:
        return "<h3>No VIN specified.</h3>"
    db = get_db()
    if request.method == "POST":
        form = request.form
        svc_type = form.get("service_type", "").strip()
        try:
            last_mileage = int(form.get("last_mileage", "0"))
        except ValueError:
            last_mileage = 0
        try:
            interval = int(form.get("recommended_interval", "0"))
        except ValueError:
            interval = 0
        svc_date = form.get("last_service_date") or None
        with db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO services (vin, service_type, last_mileage, recommended_interval, last_service_date) VALUES (%s, %s, %s, %s, %s)",
                (vin, svc_type, last_mileage, interval, svc_date),
            )
            db.commit()
        return redirect(url_for("timeline", vin=vin))
    return f'''
    <h2>Add Past Service for {vin}</h2>
    <form method="post">
      <label>Service Type:</label>
      <input type="text" name="service_type" required placeholder="e.g. oil_change"><br><br>
      <label>Last Mileage:</label>
      <input type="number" name="last_mileage" required><br><br>
      <label>Interval (miles or days):</label>
      <input type="number" name="recommended_interval" required><br><br>
      <label>Last Service Date:</label>
      <input type="date" name="last_service_date" required><br><br>
      <input type="submit" value="Add Service">
    </form>
    <p><a href="{url_for('timeline', vin=vin)}">← Back to Timeline</a></p>
    '''

@app.route("/explore")
def explore():
    db = get_db()
    filters = ["c.is_public = 1"]
    args = []
    make = request.args.get("make", "").title().strip()
    model = request.args.get("model", "").title().strip()
    year = request.args.get("year", "").strip()
    zip_code = request.args.get("zip", "").strip()
    nickname = request.args.get("nickname", "").lower().strip()
    tier = request.args.get("tier", "").strip()
    min_sp = int(request.args.get("min_sp", "0"))
    sort = request.args.get("sort", "sp_desc")
    if make:
        filters.append("c.make = %s")
        args.append(make)
    if model:
        filters.append("c.model = %s")
        args.append(model)
    if year.isdigit():
        filters.append("c.year = %s")
        args.append(int(year))
    if zip_code:
        filters.append("c.zip_code = %s")
        args.append(zip_code)
    if nickname:
        filters.append("LOWER(c.nickname) LIKE %s")
        args.append(f"%{nickname}%")
    if tier:
        filters.append("c.horsepower IS NOT NULL AND c.torque IS NOT NULL AND c.weight IS NOT NULL")
    base_query = "SELECT c.*, u.owner_social FROM cars c JOIN users u ON c.owner_id = u.id WHERE " + " AND ".join(filters)
    if sort == "recent":
        base_query += " ORDER BY c.year DESC"
    else:
        base_query += " ORDER BY ((c.horsepower * 0.9) + (c.torque * 0.7)) * POW((3600.0 / c.weight), 1.5) DESC"
    with db.cursor() as cursor:
        cursor.execute(base_query, tuple(args))
        cars = cursor.fetchall()
    html = """
    <h2>Explore Public Builds</h2>
    <form method="get">
      <input name="make" placeholder="Make" value="{0}">
      <input name="model" placeholder="Model" value="{1}">
      <input name="year" placeholder="Year" value="{2}">
      <input name="zip" placeholder="Zip" value="{3}">
      <input name="nickname" placeholder="Nickname" value="{4}">
      <select name="tier">
        <option value="">Any Tier</option>
        <option value="Bronze">Bronze+</option>
        <option value="Silver">Silver+</option>
        <option value="Gold">Gold+</option>
        <option value="Platinum">Platinum+</option>
        <option value="Titanium">Titanium+</option>
        <option value="Mythic">Mythic</option>
      </select>
      <select name="sort">
        <option value="sp_desc">Sort by Street Power</option>
        <option value="recent">Sort by Year</option>
      </select>
      <input type="submit" value="Filter">
    </form><br>
    """.format(make, model, year, zip_code, nickname)
    for car in cars:
        hp = car.get("horsepower") or 0
        tq = car.get("torque") or 0
        weight = car.get("weight") or 1
        sp = int(((hp * 0.9) + (tq * 0.7)) * (3600.0 / weight) ** 1.5)
        if sp < min_sp:
            continue
        if sp >= 1000:
            badge, color = "🔥 Mythic", "#7e00ff"
        elif sp >= 800:
            badge, color = "🧬 Titanium", "#444"
        elif sp >= 600:
            badge, color = "💎 Platinum", "#b5b5b5"
        elif sp >= 400:
            badge, color = "🪙 Gold", "#e0b33a"
        elif sp >= 200:
            badge, color = "🪙 Silver", "#aaa"
        else:
            badge, color = "🪙 Bronze", "#8c6730"
        html += f"""
        <div style="border:1px solid {color}; padding:15px; margin-bottom:20px; background:#f8f8f8; border-radius:8px;">
          <h3>{car['nickname'] or f"{car['year']} {car['make']} {car['model']}" }</h3>
          <p>{car.get('build_bio') or 'No bio submitted.'}</p>
          <p><strong>SP:</strong> {sp} — <span style="color:{color}; font-weight:bold;">{badge}</span></p>
          <p><a href="{{ url_for('timeline', vin='{car['vin']}') }}">🔍 View Full Build</a></p>
        """
        if car.get("owner_social"):
            html += f"<p>Social: <a href='{car['owner_social']}' target='_blank'>{car['owner_social']}</a></p>"
        html += "</div>"
    return html

@app.route("/mods/<vin>")
def view_mods(vin):
    if "user_id" not in session:
        return redirect(url_for("login"))
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute("SELECT * FROM cars WHERE vin = %s", (vin,))
        car = cursor.fetchone()
        if not car or car["owner_id"] != session["user_id"]:
            return "<h3>You do not own this car.</h3>"
        category = request.args.get("category", "")
        cursor.execute(
            "SELECT * FROM mod_logs WHERE vin = %s AND (%s = '' OR category = %s) ORDER BY mod_date DESC",
            (vin, category, category),
        )
        mods = cursor.fetchall()
    html = f"<h2>Modifications for {car['year']} {car['make']} {car['model']}</h2><ul>"
    for mod in mods:
        html += f"<li><strong>{mod['mod_title']}</strong> @ {mod['mileage']} mi on {mod['mod_date']}<br>{mod['description']}<br>"
        if mod.get("installed_by"):
            html += f"<em>Installed By: {mod['installed_by']}</em><br>"
        if mod.get("image_filename"):
            html += f"<img src='/static/uploads/{mod['image_filename']}' width='300'><br>"
        html += "</li><br>"
    html += f"</ul><p><a href='{url_for('dashboard')}'>← Back to Dashboard</a></p>"
    return html

@app.route("/edit-car/<vin>", methods=["GET", "POST"])
def edit_car(vin):
    if "user_id" not in session:
        return redirect(url_for("login"))
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute("SELECT * FROM cars WHERE vin = %s AND owner_id = %s", (vin, session["user_id"]))
        car = cursor.fetchone()
    if not car:
        return "<h3>You can only edit your own car.</h3>"
    if request.method == "POST":
        form = request.form
        nickname = form.get("nickname", "").strip()
        build_bio = form.get("build_bio", "").strip()
        is_public = 1 if form.get("is_public") == "on" else 0
        owner_social = form.get("owner_social", "").strip()
        try:
            horsepower = int(form.get("horsepower", "0"))
        except ValueError:
            horsepower = None
        try:
            torque = int(form.get("torque", "0"))
        except ValueError:
            torque = None
        try:
            weight = int(form.get("weight", "0"))
        except ValueError:
            weight = None
        zip_code = form.get("zip_code", "").strip()
        with db.cursor() as cursor:
            cursor.execute(
                "UPDATE cars SET nickname = %s, build_bio = %s, is_public = %s, horsepower = %s, torque = %s, weight = %s, zip_code = %s WHERE vin = %s",
                (nickname, build_bio, is_public, horsepower, torque, weight, zip_code, vin)
            )
            cursor.execute("UPDATE users SET owner_social = %s WHERE id = %s", (owner_social, session["user_id"]))
            db.commit()
        return redirect(url_for("dashboard"))
    return f"""
    <h2>Edit Public Profile for {car['year']} {car['make']} {car['model']}</h2>
    <form method="post">
      Nickname: <input type="text" name="nickname" value="{car.get('nickname','')}"><br><br>
      Build Bio:<br>
      <textarea name="build_bio" rows="5" cols="40">{car.get('build_bio','')}</textarea><br><br>
      <label><input type="checkbox" name="is_public" {"checked" if car.get("is_public") else ""}> Make Public</label><br><br>
      Social Link: <input type="text" name="owner_social" value="{car.get('owner_social','')}"><br><br>
      <hr>
      <strong>Performance Stats</strong><br>
      Horsepower: <input type="number" name="horsepower" value="{car.get('horsepower') or ''}"><br>
      Torque (lb-ft): <input type="number" name="torque" value="{car.get('torque') or ''}"><br>
      Weight (lbs): <input type="number" name="weight" value="{car.get('weight') or ''}"><br><br>
      Zip Code: <input type="text" name="zip_code" value="{car.get('zip_code','')}"><br><br>
      <input type="submit" value="Save">
    </form>
    """

@app.route("/respond-transfer", methods=["POST"])
def respond_transfer():
    if "user_id" not in session:
        return redirect(url_for("login"))
    request_id = request.form.get("request_id", type=int)
    action = request.form.get("action", "")
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute("SELECT * FROM transfer_requests WHERE id = %s", (request_id,))
        req = cursor.fetchone()
    if not req or req["to_user_id"] != session["user_id"]:
        return "<h3>Invalid transfer request.</h3>"
    with db.cursor() as cursor:
        if action == "Accept":
            cursor.execute("UPDATE cars SET owner_id = %s WHERE vin = %s", (session["user_id"], req["vin"]))
            cursor.execute("INSERT INTO ownership_history (vin, from_user_id, to_user_id, transfer_date) VALUES (%s, %s, %s, CURDATE())", (req["vin"], req["from_user_id"], req["to_user_id"]))
            cursor.execute("UPDATE transfer_requests SET status = 'accepted' WHERE id = %s", (request_id,))
            db.commit()
            return "<h3>Ownership transfer accepted.</h3>"
        if action == "Decline":
            cursor.execute("UPDATE transfer_requests SET status = 'declined' WHERE id = %s", (request_id,))
            db.commit()
            return "<h3>Transfer request declined.</h3>"
    return "<h3>Unknown action.</h3>"

@app.route("/export/<vin>")
def export_pdf(vin):
    if "user_id" not in session:
        return redirect(url_for("login"))
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute("SELECT * FROM cars WHERE vin = %s", (vin,))
        car = cursor.fetchone()
    if not car or car["owner_id"] != session["user_id"]:
        return "<h3>You do not own this car.</h3>"
    with db.cursor() as cursor:
        cursor.execute("SELECT service_type, last_mileage, recommended_interval, last_service_date FROM services WHERE vin = %s", (vin,))
        services = cursor.fetchall()
        cursor.execute("SELECT mod_title, description, mileage, mod_date, installed_by FROM mod_logs WHERE vin = %s", (vin,))
        mods = cursor.fetchall()
        cursor.execute("SELECT u.name AS to_name, oh.transfer_date FROM ownership_history oh JOIN users u ON oh.to_user_id = u.id WHERE oh.vin = %s ORDER BY transfer_date", (vin,))
        ownership = cursor.fetchall()
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 50
    def write(text, size=12):
        nonlocal y
        pdf.setFont("Helvetica", size)
        pdf.drawString(50, y, text)
        y -= size + 4
    write("DS Auto Care Vehicle Report", 16)
    write(f"{car['year']} {car['make']} {car['model']} — VIN: {car['vin']}")
    write(f"Mileage: {car['mileage']} mi")
    write("")
    write("Ownership History:", 14)
    if ownership:
        for entry in ownership:
            write(f"{entry['transfer_date']}: transferred to {entry['to_name']}")
    else:
        write("No transfers recorded.")
    write("")
    write("Service Records:", 14)
    for s in services:
        next_due = s["last_mileage"] + s["recommended_interval"]
        write(f"{s['service_type'].replace('_', ' ').title()} @ {s['last_mileage']} mi on {s['last_service_date']} (Next due: {next_due} mi)")
    write("")
    write("Modifications:", 14)
    for m in mods:
        write(f"{m['mod_title']} @ {m['mileage']} mi on {m['mod_date']}")
        write(f"Installed By: {m['installed_by']}")
        write(f"Notes: {m['description']}")
        write("")
    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"{vin}_report.pdf", mimetype="application/pdf")

@app.route("/timeline/<vin>")
def timeline(vin):
    if "user_id" not in session:
        return redirect(url_for("login"))
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute("SELECT * FROM cars WHERE vin = %s", (vin,))
        car = cursor.fetchone()
    if not car or car["owner_id"] != session["user_id"]:
        return "<h3>You do not own this car.</h3>"
    with db.cursor() as cursor:
        cursor.execute("SELECT id, service_type, last_mileage, recommended_interval, last_service_date FROM services WHERE vin = %s ORDER BY last_service_date DESC, last_mileage DESC", (vin,))
        services = cursor.fetchall()
    today = datetime.today().date()
    lines = []
    lines.append(f"<h2>Service Timeline for {car['year']} {car['make']} {car['model']}</h2>")
    lines.append(f"<p>VIN: {car['vin']} | Current Mileage: {car['mileage']} mi</p>")
    lines.append(f"<p><a href='/add-service?vin={vin}'>➕ Add Past Service</a></p>")
    lines.append("<table border='1' cellpadding='5' cellspacing='0'><tr><th>Service</th><th>Last Mileage</th><th>Date</th><th>Next Due</th><th>Status</th><th>Actions</th></tr>")
    for s in services:
        if s["service_type"] == "ceramic_coating":
            applied = s["last_service_date"]
            expires = applied + timedelta(days=s["recommended_interval"])
            days_left = (expires - today).days
            next_due_display = expires.strftime("%b %d, %Y")
            if days_left <= 0:
                status = "🔴 Expired"
            elif days_left <= 30:
                status = "🟡 Expiring Soon"
            else:
                status = "✅ Good"
        else:
            due_mileage = s["last_mileage"] + s["recommended_interval"]
            miles_left = due_mileage - int(car['mileage'])
            next_due_display = f"{due_mileage} mi"
            if miles_left <= 0:
                status = "🔴 Due"
            elif miles_left <= 1000:
                status = "🟡 Due Soon"
            else:
                status = "✅ Good"
        lines.append(f"<tr><td>{s['service_type'].replace('_',' ').title()}</td><td>{s['last_mileage']}</td><td>{s['last_service_date']}</td><td>{next_due_display}</td><td>{status}</td><td><a href='/edit-service?service_id={s['id']}'>Edit</a> | <form method='post' action='/delete-service' style='display:inline;'><input type='hidden' name='service_id' value='{s['id']}'><input type='submit' value='Delete' onclick='return confirm(\"Delete?\")'></form></td></tr>")
    lines.append("</table>")
    lines.append(f"<p><a href='/dashboard'>← Back to Dashboard</a></p>")
    return "".join(lines)

@app.route("/edit-service")
def edit_service():
    if "user_id" not in session:
        return redirect(url_for("login"))
    service_id = request.args.get("service_id", type=int)
    if not service_id:
        return "<h3>Missing service ID.</h3>"
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT s.id, s.service_type, s.last_mileage, s.recommended_interval, s.last_service_date, c.owner_id, c.vin FROM services s JOIN cars c ON s.vin = c.vin WHERE s.id = %s",
            (service_id,)
        )
        row = cursor.fetchone()
    if not row or row["owner_id"] != session["user_id"]:
        return "<h3>Not authorized to edit this service.</h3>"
    vin = row["vin"]
    svc = row["service_type"].replace("_", " ").title()
    lm = row["last_mileage"]
    ri = row["recommended_interval"]
    ls = row["last_service_date"] or ""
    return f'''
    <h2>Edit Service: {svc}</h2>
    <form method="post" action="/update-service">
      <input type="hidden" name="service_id" value="{row['id']}">
      <input type="hidden" name="vin" value="{vin}">
      <label>Last Mileage:</label>
      <input type="number" name="last_mileage" value="{lm}" required><br><br>
      <label>Recommended Interval:</label>
      <input type="number" name="recommended_interval" value="{ri}" required><br><br>
      <label>Last Service Date:</label>
      <input type="date" name="last_service_date" value="{ls}"><br><br>
      <input type="submit" value="Save Changes">
    </form>
    <p><a href="/timeline/{vin}">← Back to Timeline</a></p>
    '''

@app.route("/update-service", methods=["POST"])
def update_service():
    if "user_id" not in session:
        return redirect(url_for("login"))
    service_id = request.form.get("service_id", type=int)
    vin = request.form.get("vin", "").upper().strip()
    last_mileage = request.form.get("last_mileage", type=int, default=0)
    recommended_interval = request.form.get("recommended_interval", type=int, default=0)
    last_service_date = request.form.get("last_service_date") or None
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute("SELECT c.owner_id FROM services s JOIN cars c ON s.vin = c.vin WHERE s.id = %s", (service_id,))
        owner = cursor.fetchone()
        if not owner or owner["owner_id"] != session["user_id"]:
            return "<h3>Not authorized to update this service.</h3>"
        cursor.execute(
            "UPDATE services SET last_mileage = %s, recommended_interval = %s, last_service_date = %s WHERE id = %s",
            (last_mileage, recommended_interval, last_service_date, service_id)
        )
        db.commit()
    return redirect(f"/timeline/{vin}")

@app.route("/delete-service", methods=["POST"])
def delete_service():
    if "user_id" not in session:
        return redirect(url_for("login"))
    service_id = request.form.get("service_id", type=int)
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute("SELECT s.vin, c.owner_id FROM services s JOIN cars c ON s.vin = c.vin WHERE s.id = %s", (service_id,))
        row = cursor.fetchone()
        if not row or row["owner_id"] != session["user_id"]:
            return "<h3>Not authorized to delete this service.</h3>"
        vin = row["vin"]
        cursor.execute("DELETE FROM services WHERE id = %s", (service_id,))
        db.commit()
    return redirect(f"/timeline/{vin}")

@app.route("/transfer-requests")
def transfer_requests():
    if "user_id" not in session:
        return redirect(url_for("login"))
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT tr.id, tr.vin, tr.requested_at, u.name AS from_name FROM transfer_requests tr JOIN users u ON tr.from_user_id = u.id WHERE tr.to_user_id = %s AND tr.status = 'pending'",
            (session["user_id"],)
        )
        requests_list = cursor.fetchall()
    html = "<h2>Pending Ownership Transfers</h2>"
    for req in requests_list:
        html += f'''
        <p><strong>{req["vin"]}</strong> from {req["from_name"]} | Requested on {req["requested_at"]}</p>
        <form method="post" action="/respond-transfer">
            <input type="hidden" name="request_id" value="{req["id"]}">
            <input type="submit" name="action" value="Accept">
            <input type="submit" name="action" value="Decline">
        </form>
        '''
    return html

@app.route("/transfer-car", methods=["GET", "POST"])
def transfer_car():
    if "user_id" not in session:
        return redirect(url_for("login"))
    db = get_db()
    vin_arg = request.args.get("vin", "").upper().strip()
    if request.method == "POST":
        form = request.form
        vin = form.get("vin", "").upper().strip()
        new_email = form.get("new_owner_email", "").lower().strip()
        with db.cursor() as cursor:
            cursor.execute("SELECT owner_id FROM cars WHERE vin = %s", (vin,))
            car = cursor.fetchone()
            if not car or car["owner_id"] != session["user_id"]:
                return "<h3>You can only transfer cars you own.</h3>"
            cursor.execute("SELECT id FROM users WHERE email = %s", (new_email,))
            new_owner = cursor.fetchone()
            if not new_owner:
                return "<h3>User not found. Make sure they’ve registered.</h3>"
            cursor.execute(
                "INSERT INTO transfer_requests (vin, from_user_id, to_user_id, requested_at) VALUES (%s, %s, %s, CURDATE())",
                (vin, session["user_id"], new_owner["id"])
            )
            db.commit()
        return "<h3>Transfer request sent. Awaiting approval.</h3>"
    return f'''
    <h2>Transfer a Car</h2>
    <form method="post">
      VIN: <input type="text" name="vin" value="{vin_arg}"><br><br>
      New Owner’s Email: <input type="email" name="new_owner_email"><br><br>
      <input type="submit" value="Initiate Transfer">
    </form>
    '''

@app.route("/complete-service", methods=["POST"])
def complete_service():
    if "user_id" not in session:
        return redirect(url_for("login"))
    vin = request.form.get("vin", "").strip().upper()
    service_type = request.form.get("service_type", "").strip().lower()
    current_mileage = request.form.get("current_mileage", type=int, default=0)
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE services SET last_mileage = %s, last_service_date = CURDATE() WHERE vin = %s AND service_type = %s",
            (current_mileage, vin, service_type),
        )
        db.commit()
    return redirect("/dashboard")


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

@app.route("/update-mileage", methods=["POST"])
def update_mileage():
    if "user_id" not in session:
        return redirect(url_for("login"))
    vin = request.form.get("vin", "").strip().upper()
    try:
        new_mileage = int(request.form.get("mileage", 0))
    except ValueError:
        return "<h3>Invalid mileage provided.</h3>"
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute("UPDATE cars SET mileage = %s WHERE vin = %s AND owner_id = %s", (new_mileage, vin, session["user_id"]))
        db.commit()
    return redirect("/dashboard")

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute("SELECT * FROM users WHERE id = %s", (session["user_id"],))
        user = cursor.fetchone()
        cursor.execute("SELECT * FROM cars WHERE owner_id = %s", (user["id"],))
        cars = cursor.fetchall()
    html = []
    html.append(f"<h2>Welcome, {user['name']}!</h2>")
    html.append("<h3>Your Garage:</h3>")
    for car in cars:
        html.append(f"<h4>{car['year']} {car['make']} {car['model']}</h4>")
        html.append(f"<p>VIN: {car['vin']} | Mileage: {car['mileage']} mi</p>")
        if car.get("is_public"):
            html.append("<p style='color:#28a745; font-weight:bold;'>🚀 Public Build Enabled</p><p><a href='/public/{car['vin']}'>🔗 View Public Card</a></p>")
        else:
            html.append("<p style='color:#888;'>Private Build — not listed in Explore</p>")
        html.append(f"<p><a href='/edit-car/{car['vin']}'>⚙️ Edit Public Settings</a></p>")
        html.append(f"<p><a href='/timeline/{car['vin']}'>View Service Timeline</a></p>")
        html.append(f"<p><a href='/export/{car['vin']}'>📄 Download PDF Report</a></p>")
        with db.cursor() as cursor:
            cursor.execute("SELECT * FROM services WHERE vin = %s", (car["vin"],))
            services = cursor.fetchall()
        html.append("<ul>")
        for s in services:
            due = s["last_mileage"] + s["recommended_interval"]
            if int(car["mileage"]) >= due:
                status = "🔴 Due"
            elif int(car["mileage"]) + 1000 >= due:
                status = "🟡 Due Soon"
            else:
                status = "✅ Good"
            html.append(f"<li>{s['service_type'].replace('_',' ').title()}: {status} (Due at {due} mi)<form method='post' action='/complete-service' style='display:inline; margin-left:1rem;'><input type='hidden' name='vin' value='{car['vin']}'><input type='hidden' name='service_type' value='{s['service_type']}'><input type='hidden' name='current_mileage' value='{car['mileage']}'><input type='submit' value='Mark Complete'></form></li>")
        html.append("</ul>")
        update_mileage_url = url_for("update_mileage")
        html.append(f'<form method="post" action="{update_mileage_url}"><input type="hidden" name="vin" value="{car["vin"]}"><label>Update Mileage:</label><input type="number" name="mileage" value="{car["mileage"]}"><input type="submit" value="Update"></form>')
        html.append(f'<p><a href="/transfer-car?vin={car["vin"]}">Transfer Ownership</a></p>')
    html.append(f'<p><a href="/add-car">+ Add Another Car</a></p>')
    html.append(f'<p><a href="/logout">Logout</a></p>')
    html.append('''<form method="post" action="/toggle-reminders"><label><input type="checkbox" name="email" checked> Email reminders</label><br><label><input type="checkbox" name="sms"> Text reminders</label><br><input type="submit" value="Update Preferences"></form>''')
    return "".join(html)

@app.route("/trigger-reminders")
def trigger_reminders():
    if "user_id" not in session:
        return redirect(url_for("login"))
    db = get_db()
    today = datetime.now().date()
    with db.cursor() as cursor:
        cursor.execute("SELECT id, name, email, wants_email_reminders, wants_text_reminders FROM users")
        users = cursor.fetchall()
    for user in users:
        if not (user.get("wants_email_reminders") or user.get("wants_text_reminders")):
            continue
        with db.cursor() as cursor:
            cursor.execute("SELECT * FROM cars WHERE owner_id = %s", (user["id"],))
            cars = cursor.fetchall()
        for car in cars:
            with db.cursor() as cursor:
                cursor.execute("SELECT service_type, last_mileage, recommended_interval, last_reminded_date FROM services WHERE vin = %s", (car["vin"],))
                services = cursor.fetchall()
            for service in services:
                due = service["last_mileage"] + service["recommended_interval"]
                if int(car["mileage"]) < due - 1000:
                    continue
                last_reminded = service.get("last_reminded_date")
                if last_reminded:
                    last_date = datetime.strptime(last_reminded, "%Y-%m-%d").date()
                    if (today - last_date).days < 30:
                        continue
                subject = f"Upcoming Service for {car['year']} {car['make']} {car['model']}"
                body = f"""Hi {user['name']},

Your {service['service_type'].replace('_', ' ').title()} service is due at {due} miles.
Current mileage: {car['mileage']}.

Stay mint — DS Auto Care
"""
                if user.get("wants_email_reminders"):
                    send_reminder_email(user["email"], subject, body)
                with db.cursor() as cursor:
                    cursor.execute("UPDATE services SET last_reminded_date = CURDATE() WHERE vin = %s AND service_type = %s", (car["vin"], service["service_type"]))
                    db.commit()
    return "<h3>Reminders processed.</h3>"

@app.route("/public/<vin>")
def public_build(vin):
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute("SELECT c.*, u.owner_social FROM cars c JOIN users u ON c.owner_id = u.id WHERE c.vin = %s AND c.is_public = 1", (vin,))
        car = cursor.fetchone()
    if not car:
        return "<h3>This build isn't public.</h3>"
    hp = car.get("horsepower", 0)
    tq = car.get("torque", 0)
    weight = car.get("weight", 1)
    sp_score = int(((hp * 0.9) + (tq * 0.7)) * (3600.0 / weight) ** 1.5)
    if sp_score >= 1000:
        tier, color = "🔥 Mythic", "#7e00ff"
    elif sp_score >= 800:
        tier, color = "🧬 Titanium", "#444"
    elif sp_score >= 600:
        tier, color = "💎 Platinum", "#b5b5b5"
    elif sp_score >= 400:
        tier, color = "🪙 Gold", "#e0b33a"
    elif sp_score >= 200:
        tier, color = "🪙 Silver", "#aaa"
    else:
        tier, color = "🪙 Bronze", "#8c6730"
    html = f"""
    <div style="border:2px solid {color}; padding:25px; border-radius:10px; max-width:800px; margin:auto; background:#fdfdfd; font-family:sans-serif;">
      <h2 style="color:{color}; font-size:2em;">{car['nickname'] or f"{car['year']} {car['make']} {car['model']}" }</h2>
      <p><strong>Build Bio:</strong> {car.get('build_bio','No bio yet.')}</p>
      <p><strong>Location:</strong> {car.get('zip_code','Not listed')}</p>
      <hr>
      <p><strong>Performance Stats:</strong><br>
         Horsepower: {hp} hp<br>
         Torque: {tq} lb-ft<br>
         Weight: {weight} lbs<br>
         <span style="font-size:1.3em; color:{color}; font-weight:bold;">Street Power: {sp_score} — {tier}</span>
      </p>
    """
    if car.get("owner_social"):
        html += f"<p><strong>Owner's Social:</strong> <a href='{car['owner_social']}' target='_blank'>{car['owner_social']}</a></p>"
    with db.cursor() as cursor:
        cursor.execute("SELECT * FROM mod_logs WHERE vin = %s", (vin,))
        mods = cursor.fetchall()
    html += "<hr><h3>Modifications</h3><ul>"
    for mod in mods:
        img_tag = ""
        if mod.get("image_filename"):
            img_url = f"/static/uploads/{mod['image_filename']}"
            img_tag = f"<br><img src='{img_url}' width='300'><br>"
        html += f"<li><strong>{mod['mod_title']}</strong> — {mod['mod_date']} @ {mod['mileage']} mi<br>{mod['description']}{img_tag}</li><br>"
    html += "</ul></div>"
    return html

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