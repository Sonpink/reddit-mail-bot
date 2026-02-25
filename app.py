import sqlite3
import threading
import requests
import imaplib
import email
import re
import time
from flask import Flask, render_template, request, jsonify, session, redirect, Response

app = Flask(__name__)
app.secret_key = "secretkey123"

# =====================================================
# DATABASE CONFIG (Persistent Disk)
# =====================================================

DB_FILE = "/var/data/accounts.db"

LOCK = threading.Lock()

ADMIN_PASSWORD = "123456"
REDDIT_SENDER = "noreply@redditmail.com"
LEASE_TIMEOUT = 300


# =====================================================
# DATABASE INIT
# =====================================================

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            password TEXT,
            refresh_token TEXT,
            client_id TEXT,
            status TEXT,
            assigned_at INTEGER
        )
    """)

    conn.commit()
    conn.close()


# Initialize DB at startup
init_db()


# =====================================================
# RESET EXPIRED
# =====================================================

def reset_expired_accounts():
    now = int(time.time())

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        UPDATE accounts
        SET status='AVAILABLE',
            assigned_at=NULL
        WHERE status='IN_USE'
        AND assigned_at IS NOT NULL
        AND (? - assigned_at) > ?
    """, (now, LEASE_TIMEOUT))

    conn.commit()
    conn.close()


# =====================================================
# ACCOUNT ASSIGNMENT
# =====================================================

def get_account():
    with LOCK:

        reset_expired_accounts()

        now = int(time.time())

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
            UPDATE accounts
            SET status='IN_USE',
                assigned_at=?
            WHERE id=?
        """, (now, account_id))

        conn.commit()
        conn.close()

        return {
            "id": row[0],
            "email": row[1],
            "password": row[2],
            "refresh_token": row[3],
            "client_id": row[4],
        }


def mark_used(account_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        UPDATE accounts
        SET status='USED',
            assigned_at=NULL
        WHERE id=?
    """, (account_id,))

    conn.commit()
    conn.close()


def mark_available(account_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        UPDATE accounts
        SET status='AVAILABLE',
            assigned_at=NULL
        WHERE id=?
    """, (account_id,))

    conn.commit()
    conn.close()


# =====================================================
# ROUTES
# =====================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/get_account")
def route_get_account():
    acc = get_account()
    if not acc:
        return jsonify({"status": "empty"})
    return jsonify({"status": "ok", **acc})


@app.route("/skip", methods=["POST"])
def route_skip():
    data = request.json
    mark_available(data["id"])
    return jsonify({"ok": True})


# =====================================================
# ADMIN
# =====================================================

def get_stats():

    conn = sqlite3.connect(DB_FILE)
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


@app.route("/admin", methods=["GET", "POST"])
def admin():

    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect("/admin")

    if not session.get("admin"):
        return render_template("admin_login.html")

    stats = get_stats()
    return render_template("admin.html", stats=stats)


@app.route("/add_accounts", methods=["POST"])
def route_add_accounts():

    if not session.get("admin"):
        return "Unauthorized"

    text = request.form.get("accounts", "")

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    lines = text.strip().split("\n")

    for line in lines:

        line = line.strip()
        if not line:
            continue

        parts = line.split(":")
        if len(parts) < 4:
            continue

        email = parts[0]
        password = parts[1]
        refresh_token = parts[-2]
        client_id = parts[-1]

        c.execute("""
            INSERT OR IGNORE INTO accounts
            (email,password,refresh_token,client_id,status,assigned_at)
            VALUES (?,?,?,?,?,NULL)
        """, (
            email,
            password,
            refresh_token,
            client_id,
            "AVAILABLE"
        ))

    conn.commit()
    conn.close()

    return redirect("/admin")


@app.route("/export_available")
def export_available():

    if not session.get("admin"):
        return "Unauthorized"

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        SELECT email,password,refresh_token,client_id
        FROM accounts
        WHERE status='AVAILABLE'
    """)

    rows = c.fetchall()
    conn.close()

    content = "\n".join(
        f"{r[0]}:{r[1]}:{r[2]}:{r[3]}" for r in rows
    )

    return Response(
        content,
        mimetype="text/plain",
        headers={
            "Content-Disposition": "attachment;filename=available_accounts_backup.txt"
        }
    )