import os
import threading
import requests
import imaplib
import email
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

ACCOUNTS_FILE = "accounts.txt"
LOCK = threading.Lock()

REDDIT_SENDER = "noreply@redditmail.com"


# -------------------------
# Get next available account
# -------------------------
def get_next_account():

    with LOCK:

        if not os.path.exists(ACCOUNTS_FILE):
            return None

        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for i, line in enumerate(lines):

            if line.startswith("AVAILABLE|"):

                account = line.strip().split("|", 1)[1]

                lines[i] = "ASSIGNED|" + account + "\n"

                with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                    f.writelines(lines)

                parts = account.split(":")

                return {
                    "email": parts[0],
                    "password": parts[1],
                    "refresh_token": parts[4],
                    "client_id": parts[5],
                }

        return None


# -------------------------
# Get access token
# -------------------------
def get_access_token(refresh_token, client_id):

    url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

    data = {
        "client_id": client_id,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
    }

    r = requests.post(url, data=data)

    if r.status_code != 200:
        return None

    return r.json().get("access_token")


# -------------------------
# Check reddit mail
# -------------------------
def check_reddit_mail(email_addr, access_token):

    try:

        auth_string = f"user={email_addr}\1auth=Bearer {access_token}\1\1"

        imap = imaplib.IMAP4_SSL("outlook.office365.com")
        imap.authenticate("XOAUTH2", lambda x: auth_string)
        imap.select("INBOX")

        typ, data = imap.search(None, "ALL")

        mail_ids = data[0].split()

        results = []

        for num in reversed(mail_ids):

            typ, msg_data = imap.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])

            sender = msg.get("From", "")

            if REDDIT_SENDER.lower() in sender.lower():

                results.append({
                    "from": sender,
                    "subject": msg.get("Subject")
                })

            if len(results) >= 3:
                break

        imap.logout()

        return results

    except Exception as e:

        print("IMAP error:", e)
        return []


# -------------------------
# Routes
# -------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/get_account")
def route_get_account():

    acc = get_next_account()

    if not acc:
        return jsonify({"status": "empty"})

    return jsonify({
        "status": "ok",
        "email": acc["email"],
        "password": acc["password"],
        "refresh_token": acc["refresh_token"],
        "client_id": acc["client_id"],
    })


@app.route("/check_mail", methods=["POST"])
def route_check_mail():

    data = request.json

    token = get_access_token(
        data["refresh_token"],
        data["client_id"]
    )

    if not token:
        return jsonify({"status": "error"})

    mails = check_reddit_mail(data["email"], token)

    return jsonify({
        "status": "ok",
        "mails": mails
    })


# Render requires this
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
