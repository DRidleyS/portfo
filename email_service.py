import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Validate required environment variables
required_vars = ['SMTP_SERVER', 'SMTP_PORT', 'EMAIL_PASS']
for var in required_vars:
    if not os.getenv(var):
        raise EnvironmentError(f"Missing required environment variable: {var}")

def send_email_with_attachment(subject, body, csv_file_path):
    try:
        smtp_server = os.getenv('SMTP_SERVER')
        smtp_port = int(os.getenv('SMTP_PORT'))
        sender_email = os.getenv('EMAIL_USER')
        receiver_email = os.getenv('EMAIL_USER')
        password = os.getenv('EMAIL_PASS')

        # Create the email
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = receiver_email
        msg['Subject'] = subject

        # Add body to email with UTF-8 encoding
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        # Open CSV file in binary mode
        with open(csv_file_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())

        # Encode file in ASCII characters to send by email
        encoders.encode_base64(part)

        # Add header as key/value pair to attachment part
        part.add_header(
            "Content-Disposition",
            f"attachment; filename= {os.path.basename(csv_file_path)}",
        )

        # Add attachment to message and convert message to string
        msg.attach(part)
        text = msg.as_string()

        # Send the email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()  # Secure the connection
            server.login(sender_email, password)
            server.sendmail(sender_email, receiver_email, text)
        print("Email sent successfully.")
    except Exception as e:
        print(f"Failed to send email: {e}")