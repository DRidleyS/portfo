import os
import smtplib
import csv
import base64
import dotenv
from flask import Flask, request, redirect, render_template
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from dotenv import load_dotenv
from email_service import send_email_with_attachment
from flask_mail import Mail, Message
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.send']
load_dotenv()  # Load environment variables from .env file

app = Flask(__name__)

# Flask-Mail configuration
app.config['MAIL_SERVER'] = os.getenv('SMTP_SERVER')
app.config['MAIL_PORT'] = int(os.getenv('SMTP_PORT', 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('EMAIL_USER')
app.config['MAIL_PASSWORD'] = os.getenv('EMAIL_PASS')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('EMAIL_USER')

mail = Mail(app)

# CSV writer for logging messages sent through contact form
def write_to_csv(data):
    with open("database.csv", mode='a') as database:
        name = data["name"]
        email = data["email"]
        message = data["message"]
        csv_writer = csv.writer(database, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
        csv_writer.writerow([name, email, message])

# CSV reader for reading the messages sent through contact form
def read_csv_file():
    data = []
    with open('database.csv', 'r') as file:
        reader = csv.reader(file)
        for row in reader:
            data.append(row)
    return data

def create_message(sender, to, subject, message_text):
    message = MIMEText(message_text)
    message['to'] = to
    message['from'] = sender
    message['subject'] = subject
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {'raw': raw_message}

def send_message(service, user_id, message):
    try:
        message = service.users().messages().send(userId=user_id, body=message).execute()
        print('Message Id: %s' % message['id'])
        return message
    except Exception as e:
        print('An error occurred: %s' % e)
        return None

# Email sender for sending the messages sent through contact form
def send_email_with_csv_contents():
    csv_data = read_csv_file()
    email_body = "\n".join([",".join(row) for row in csv_data])

    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json')
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    service = build('gmail', 'v1', credentials=creds)
    sender = os.getenv('EMAIL_USER')
    to = os.getenv('EMAIL_USER')
    subject = 'CSV File Contents'
    message = create_message(sender, to, subject, email_body)
    send_message(service, 'me', message)

@app.route("/", methods=['POST', 'GET'])
def home():
    '''
    Home route with a conditional statement for cool people that send me a message
    '''
    if request.method == 'POST':
        data = request.form.to_dict()
        write_to_csv(data)
        send_email_with_csv_contents()
        return cargallery()
    return render_template("index.html")

@app.route("/cargallery")
def cargallery():
    return render_template("cargallery.html")

@app.route('/send-email', methods=['POST'])
def send_email():
    name = request.form['name']
    email = request.form['email']
    message = request.form['message']

    # Define your CSV file path
    csv_file_path = os.path.join(os.path.dirname(__file__), 'database.csv')

    # Email content
    subject = "CSV File from Contact Form"
    body = f"Name: {name}\nEmail: {email}\nMessage: {message}\n\nPlease find the attached CSV file."

    send_email_with_attachment('dorianridley@gmail.com', subject, body, csv_file_path)

    return redirect('/')

if __name__ == "__main__":
    app.run(debug=True)
