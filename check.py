import requests
import imaplib
import email
import time
import sys

FILE = "outlook_mails.txt"

REDDIT_SENDER = "noreply@redditmail.com"


# -----------------------------
# Load account details
# -----------------------------
def get_account(email_input):

    try:
        with open(FILE, "r", encoding="utf-8") as f:

            for line in f:

                parts = line.strip().split(":")

                if len(parts) < 6:
                    continue

                email_addr = parts[0]
                refresh_token = parts[4]
                client_id = parts[5]

                if email_addr.lower() == email_input.lower():

                    return email_addr, refresh_token, client_id

    except FileNotFoundError:
        print("File outlook_mails.txt not found")
        return None, None, None

    return None, None, None


# -----------------------------
# Get access token
# -----------------------------
def get_access_token(refresh_token, client_id):

    url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

    data = {
        "client_id": client_id,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
    }

    try:
        r = requests.post(url, data=data)

        if r.status_code != 200:
            return None

        return r.json().get("access_token")

    except Exception:
        return None


# -----------------------------
# Fetch last 3 Reddit emails
# -----------------------------
def fetch_reddit_mails(email_addr, access_token):

    auth_string = f"user={email_addr}\1auth=Bearer {access_token}\1\1"

    try:
        imap = imaplib.IMAP4_SSL("outlook.office365.com")
        imap.authenticate("XOAUTH2", lambda x: auth_string)

        imap.select("INBOX")

        typ, data = imap.search(None, "ALL")

        mail_ids = data[0].split()

        reddit_mails = []

        # Check newest first
        for num in reversed(mail_ids):

            typ, msg_data = imap.fetch(num, "(RFC822)")

            msg = email.message_from_bytes(msg_data[0][1])

            sender = msg.get("From", "")

            if REDDIT_SENDER.lower() in sender.lower():

                reddit_mails.append(msg)

            if len(reddit_mails) == 3:
                break

        imap.logout()

        return reddit_mails

    except Exception as e:

        print("IMAP error:", str(e))
        return None


# -----------------------------
# Display Reddit emails
# -----------------------------
def display_mails(mails):

    if not mails:
        print("\nNo Reddit emails found.\n")
        return False

    print("\nLast Reddit Emails:\n")

    for msg in mails:

        print("From:", msg.get("From"))
        print("Subject:", msg.get("Subject"))
        print("-" * 40)

    return True


# -----------------------------
# Process single email account
# -----------------------------
def process_email():

    email_input = input("\nEnter Outlook email (or 'exit'): ").strip()

    if email_input.lower() == "exit":
        sys.exit()

    email_addr, refresh_token, client_id = get_account(email_input)

    if not email_addr:
        print("Email not found.")
        return

    access_token = get_access_token(refresh_token, client_id)

    if not access_token:
        print("Could not get access token.")
        return

    while True:

        mails = fetch_reddit_mails(email_addr, access_token)

        if mails is None:
            print("Error checking mails.")
            return

        found = display_mails(mails)

        if found:
            return

        choice = input("No Reddit mail. Recheck? (y/n): ").strip().lower()

        if choice != "y":
            return

        print("Rechecking...\n")
        time.sleep(2)


# -----------------------------
# Continuous bot loop
# -----------------------------
def main():

    print("Reddit Mail Checker Bot Started")
    print("Type 'exit' anytime to quit")

    while True:

        process_email()


# -----------------------------
# Run
# -----------------------------
if __name__ == "__main__":
    main()
