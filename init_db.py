#!/usr/bin/env python3
import os, csv

# 1) Where to put the CSV
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "database.csv")

# 2) Exact headers in the correct order
HEADERS = [
    "Timestamp",
    "name",
    "email",
    "car",
    "phone",
    "is_mobile",
    "contact_method",
    "calltime",
    "appointmenttime",
    "message",
    "Status"
]

def init_db():
    # Remove any existing file
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Removed old database: {DB_PATH}")

    # Create a brand-new CSV, writing only the header row
    with open(DB_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HEADERS)

    print(f"Initialized new database with headers at: {DB_PATH}")

if __name__ == "__main__":
    init_db()