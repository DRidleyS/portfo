CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cars (
    vin TEXT PRIMARY KEY,
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    year INTEGER NOT NULL,
    mileage INTEGER,
    owner_id INTEGER NOT NULL,
    is_transferable BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vin TEXT NOT NULL,
    service_type TEXT NOT NULL,
    last_mileage INTEGER,
    recommended_interval INTEGER,
    last_service_date TEXT,
    FOREIGN KEY (vin) REFERENCES cars(vin)
);

CREATE TABLE IF NOT EXISTS ownership_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vin TEXT NOT NULL,
    from_user_id INTEGER NOT NULL,
    to_user_id INTEGER NOT NULL,
    transfer_date TEXT,
    FOREIGN KEY (vin) REFERENCES cars(vin),
    FOREIGN KEY (from_user_id) REFERENCES users(id),
    FOREIGN KEY (to_user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS transfer_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vin TEXT NOT NULL,
    from_user_id INTEGER NOT NULL,
    to_user_id INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',
    requested_at TEXT,
    FOREIGN KEY (vin) REFERENCES cars(vin),
    FOREIGN KEY (from_user_id) REFERENCES users(id),
    FOREIGN KEY (to_user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS mod_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vin TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    mod_title TEXT NOT NULL,
    description TEXT,
    mileage INTEGER,
    mod_date TEXT DEFAULT CURRENT_DATE,
    FOREIGN KEY (vin) REFERENCES cars(vin),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

ALTER TABLE mod_logs ADD COLUMN image_filename TEXT;

ALTER TABLE mod_logs ADD COLUMN category TEXT DEFAULT 'unspecified';

CREATE TABLE IF NOT EXISTS mod_service_links (
    mod_id INTEGER,
    service_id INTEGER,
    FOREIGN KEY (mod_id) REFERENCES mod_logs(id),
    FOREIGN KEY (service_id) REFERENCES services(id)
);

ALTER TABLE mod_logs ADD COLUMN installed_by TEXT DEFAULT 'unspecified';

ALTER TABLE users
ADD COLUMN wants_email_reminders INTEGER DEFAULT 0;

ALTER TABLE users
ADD COLUMN wants_text_reminders INTEGER DEFAULT 0;

ALTER TABLE users
ADD COLUMN phone_number TEXT;

ALTER TABLE services
ADD COLUMN last_reminded_date TEXT;

CREATE TABLE IF NOT EXISTS user_reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    reminder_type TEXT NOT NULL,
    last_triggered TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

ALTER TABLE users
ADD COLUMN wants_email_reminders INTEGER DEFAULT 0;

ALTER TABLE users
ADD COLUMN wants_text_reminders INTEGER DEFAULT 0;

ALTER TABLE users
ADD COLUMN phone_number TEXT;

ALTER TABLE cars ADD COLUMN is_public INTEGER DEFAULT 0;
ALTER TABLE cars ADD COLUMN build_bio TEXT;
ALTER TABLE cars ADD COLUMN nickname TEXT;

ALTER TABLE users ADD COLUMN owner_social TEXT;

ALTER TABLE cars ADD COLUMN horsepower INTEGER;
ALTER TABLE cars ADD COLUMN torque INTEGER;
ALTER TABLE cars ADD COLUMN weight INTEGER;
ALTER TABLE cars ADD COLUMN zip_code TEXT;