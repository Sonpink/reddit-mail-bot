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

ADMIN_PASSWORD = "123456"
DB_FILE = "accounts.db"

LOCK = threading.Lock()

REDDIT_SENDER = "noreply@redditmail.com"


# -------------------------
# Database setup
# -------------------------

def init_db():

    conn = sqlite3.connect(DB_FILE)
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


# -------------------------
# Get next account
# -------------------------

def get_account():

    with LOCK:

        conn = sqlite3.connect(DB_FILE)
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
            UPDATE accounts SET status='IN_USE'
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


# -------------------------
# Mark used
# -------------------------

def mark_used(account_id):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        UPDATE accounts SET status='USED'
        WHERE id=?
    """, (account_id,))

    conn.commit()
    conn.close()


# -------------------------
# Mark available again
# -------------------------

def mark_available(account_id):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        UPDATE accounts SET status='AVAILABLE'
        WHERE id=?
    """, (account_id,))

    conn.commit()
    conn.close()


# -------------------------
# Add accounts
# -------------------------

def add_accounts(text):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    lines = text.strip().split("\n")

    for line in lines:

        parts = line.strip().split(":")

        if len(parts) < 4:
            continue

        c.execute("""
            INSERT INTO accounts
            (email,password,refresh_token,client_id,status)
            VALUES (?,?,?,?,?)
        """, (parts[0], parts[1], parts[2], parts[3], "AVAILABLE"))

    conn.commit()
    conn.close()


# -------------------------
# Get access token
# -------------------------

def get_token(refresh, client):

    r = requests.post(
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        data={
            "client_id": client,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
            "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
        },
    )

    if r.status_code != 200:
        return None

    return r.json().get("access_token")


# -------------------------
# Get newest OTP
# -------------------------

def get_otp(email_addr, token):

    try:

        auth = f"user={email_addr}\1auth=Bearer {token}\1\1"

        imap = imaplib.IMAP4_SSL("outlook.office365.com")
        imap.authenticate("XOAUTH2", lambda x: auth)
        imap.select("INBOX")

        typ, data = imap.search(None, "ALL")

        for num in reversed(data[0].split()):

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
        pass

    return None


# -------------------------
# Routes
# -------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/get_account")
def route_get():

    acc = get_account()

    if not acc:
        return jsonify({"status": "empty"})

    return jsonify({"status": "ok", **acc})


@app.route("/check_otp", methods=["POST"])
def route_check():

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


# -------------------------
# Admin login
# -------------------------

@app.route("/admin", methods=["GET", "POST"])
def admin():

    if request.method == "POST":

        if request.form["password"] == ADMIN_PASSWORD:

            session["admin"] = True
            return redirect("/admin")

    if not session.get("admin"):
        return render_template("admin_login.html")

    return render_template("admin.html")


@app.route("/add_accounts", methods=["POST"])
def route_add():

    if not session.get("admin"):
        return "Unauthorized"

    add_accounts(request.form["accounts"])

    return "Accounts added successfully"


# -------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
