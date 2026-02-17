import os
import sqlite3
import threading
import requests
import imaplib
import email
import re
from flask import Flask, render_template, request, jsonify, session, redirect

app = Flask(__name__)
app.secret_key = "secretkey123"


# =========================
# Render-safe paths
# =========================

BASE_DIR = "/opt/render/project/src"
DB_FILE = os.path.join(BASE_DIR, "accounts.db")

LOCK = threading.Lock()

ADMIN_PASSWORD = "123456"

REDDIT_SENDER = "noreply@redditmail.com"


# =========================
# Database Initialization
# =========================

def init_db():

    os.makedirs(BASE_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT,
            password TEXT,
            refresh_token TEXT,
            client_id TEXT,
            status TEXT
        )
    """)

    conn.commit()
    conn.close()


init_db()


# =========================
# Get Stats for Admin
# =========================

def get_stats():

    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM accounts WHERE status='AVAILABLE'")
    available = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM accounts WHERE status='IN_USE'")
    in_use = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM accounts WHERE status='USED'")
    used = c.fetchone()[0]

    conn.close()

    return {
        "available": available,
        "in_use": in_use,
        "used": used
    }


# =========================
# Get next account
# =========================

def get_account():

    with LOCK:

        conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        c = conn.cursor()

        c.execute("""
            SELECT id,email,password,refresh_token,client_id
            FROM accounts
            WHERE status='AVAILABLE'
            LIMIT 1
        """)

        row = c.fetchone()

        if not row:
            conn.close()
            return None

        account_id = row[0]

        c.execute("""
            UPDATE accounts
            SET status='IN_USE'
            WHERE id=?
        """, (account_id,))

        conn.commit()
        conn.close()

        return {
            "id": row[0],
            "email": row[1],
            "password": row[2],
            "refresh_token": row[3],
            "client_id": row[4],
        }


# =========================
# Mark Used
# =========================

def mark_used(account_id):

    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()

    c.execute("""
        UPDATE accounts
        SET status='USED'
        WHERE id=?
    """, (account_id,))

    conn.commit()
    conn.close()


# =========================
# Mark Available Again
# =========================

def mark_available(account_id):

    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()

    c.execute("""
        UPDATE accounts
        SET status='AVAILABLE'
        WHERE id=?
    """, (account_id,))

    conn.commit()
    conn.close()


# =========================
# Add Accounts
# =========================

def add_accounts(text):

    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    c = conn.cursor()

    lines = text.strip().split("\n")

    added = 0

    for line in lines:

        parts = line.strip().split(":")

        if len(parts) < 4:
            continue

        c.execute("""
            INSERT INTO accounts
            (email,password,refresh_token,client_id,status)
            VALUES (?,?,?,?,?)
        """, (
            parts[0],
            parts[1],
            parts[2],
            parts[3],
            "AVAILABLE"
        ))

        added += 1

    conn.commit()
    conn.close()

    return added


# =========================
# Get Access Token
# =========================

def get_token(refresh_token, client_id):

    try:

        r = requests.post(
            "https://login.microsoftonline.com/common/oauth2/v2.0/token",
            data={
                "client_id": client_id,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
            },
            timeout=10
        )

        if r.status_code != 200:
            return None

        return r.json().get("access_token")

    except:
        return None


# =========================
# Get OTP
# =========================

def get_otp(email_addr, token):

    try:

        auth = f"user={email_addr}\1auth=Bearer {token}\1\1"

        imap = imaplib.IMAP4_SSL("outlook.office365.com")
        imap.authenticate("XOAUTH2", lambda x: auth)
        imap.select("INBOX")

        typ, data = imap.search(None, "ALL")

        ids = data[0].split()

        for num in reversed(ids):

            typ, msg_data = imap.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])

            sender = msg.get("From", "")

            if REDDIT_SENDER in sender.lower():

                subject = msg.get("Subject", "")

                match = re.search(r"\d{6}", subject)

                if match:

                    imap.logout()
                    return match.group()

        imap.logout()

    except:
        return None

    return None


# =========================
# Routes
# =========================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/get_account")
def route_get_account():

    acc = get_account()

    if not acc:
        return jsonify({"status": "empty"})

    return jsonify({"status": "ok", **acc})


@app.route("/check_otp", methods=["POST"])
def route_check_otp():

    data = request.json

    token = get_token(data["refresh_token"], data["client_id"])

    if not token:
        return jsonify({"otp": None})

    otp = get_otp(data["email"], token)

    if otp:
        mark_used(data["id"])

    return jsonify({"otp": otp})


@app.route("/skip", methods=["POST"])
def route_skip():

    data = request.json

    mark_available(data["id"])

    return jsonify({"ok": True})


# =========================
# Admin Login + Dashboard
# =========================

@app.route("/admin", methods=["GET", "POST"])
def admin():

    if request.method == "POST":

        if request.form.get("password") == ADMIN_PASSWORD:

            session["admin"] = True
            return redirect("/admin")

    if not session.get("admin"):
        return render_template("admin_login.html")

    stats = get_stats()

    return render_template(
        "admin.html",
        stats=stats
    )


@app.route("/add_accounts", methods=["POST"])
def route_add_accounts():

    if not session.get("admin"):
        return "Unauthorized"

    added = add_accounts(request.form.get("accounts", ""))

    stats = get_stats()

    return render_template(
        "admin.html",
        stats=stats,
        added=added
    )


# =========================
# Render Port Binding
# =========================

if __name__ == "__main__":
    app.run(debug=True)
