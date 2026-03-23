#!/usr/bin/env python3
"""
NEX Webhook Server
Listens for Gumroad sale pings → generates license key → emails customer.
Logs every sale to nex_sales_ledger.jsonl

Usage:
    export NEX_GMAIL_PASS='your-16-char-app-password'
    python3 nex_webhook_server.py

Gumroad Ping URL: http://<your-ngrok-url>/webhook/gumroad
"""

import os
import json
import hashlib
import logging
import smtplib
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify

# ─────────────────────────────────────────
# CONFIG — set via environment variables
# NEVER hardcode credentials in this file
# ─────────────────────────────────────────
GMAIL_USER   = os.environ.get("NEX_GMAIL_USER", "zenlightbulb@gmail.com")  # ← set this once
GMAIL_PASS   = os.environ.get("NEX_GMAIL_PASS", "")                       # ← always via env
LEDGER_FILE  = "nex_sales_ledger.jsonl"
PORT         = 7777

# ─────────────────────────────────────────
# KEYGEN — must match nex_keygen.py exactly
# ─────────────────────────────────────────
KANJI = list("龍鬼魂魄魏魔鱗鳳鴉鵬鶴鷹鸞麒麟黙黛鼎鼓齊龜鑑鏡鎧鋒鑄鐵鐘鏑鏃鎌鍵鍊鍛鍚鍑鎤鑪鑰鑲鑷鑼鑽鑾鑿钁")
GREEK = list("αβγδεζηθικλμνξοπρσςτυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ")
MATH  = list("∀∂∃∄∅∆∇∈∉∊∋∌∍∎∏∐∑−∓∔∕∖∗∘∙√∛∜∝∞∟∠∡∢∣∤∥∦∧∨∩∪∫∬∭∮∯∰∱∲∳∴∵∶∷∸∹∺∻∼∽∾∿≀≁≂≃≄≅≆≇≈≉≊≋≌≍≎≏≐≑≒≓≔≕≖≗≘≙≚≛≜≝≞≟≠≡≢≣≤≥≦≧≨≩")
POOL  = KANJI + GREEK + MATH

def generate_key(hostname: str) -> str:
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from nex_license_server import expected_key
    return expected_key(hostname)

# ─────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────
EMAIL_SUBJECT = "NEX — Your License Key"

def build_email_html(buyer_name: str, hostname: str, key: str, issued: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@900&display=swap');
  body {{ margin:0; padding:0; background:#020c14; color:#c8dce8; font-family:'Share Tech Mono',monospace; }}
  .wrap {{ max-width:600px; margin:0 auto; padding:40px 20px; }}
  .logo {{ font-family:'Orbitron',sans-serif; font-size:52px; font-weight:900;
           background:linear-gradient(135deg,#00c8ff,#a855f7);
           -webkit-background-clip:text; -webkit-text-fill-color:transparent;
           background-clip:text; letter-spacing:0.1em; margin-bottom:4px; }}
  .sub {{ font-size:10px; letter-spacing:0.4em; color:#4a6a7a; margin-bottom:32px; }}
  .divider {{ height:1px; background:linear-gradient(90deg,transparent,rgba(0,200,255,0.4),transparent); margin:24px 0; }}
  .label {{ font-size:9px; letter-spacing:0.25em; color:#4a6a7a; margin-bottom:6px; }}
  .key-box {{ border:1px solid rgba(0,200,255,0.4); background:rgba(0,0,0,0.4);
              padding:20px 24px; text-align:center; margin-bottom:24px; }}
  .key {{ font-size:20px; letter-spacing:0.12em; color:#00c8ff; word-break:break-all; }}
  .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:1px;
           background:rgba(0,200,255,0.1); border:1px solid rgba(0,200,255,0.1);
           margin-bottom:24px; }}
  .cell {{ background:#041020; padding:12px 16px; }}
  .cell-label {{ font-size:9px; letter-spacing:0.2em; color:#4a6a7a; margin-bottom:4px; }}
  .cell-val {{ font-size:12px; color:#e8f4ff; }}
  .cell-val.green {{ color:#00ff9d; }}
  .cell-val.cyan  {{ color:#00c8ff; }}
  .steps {{ font-size:11px; line-height:1.9; color:#4a6a7a; margin-bottom:24px; }}
  .step {{ display:flex; gap:12px; margin-bottom:8px; }}
  .n {{ color:#00c8ff; min-width:18px; }}
  .t {{ color:#c8dce8; }}
  .t strong {{ color:#e8f4ff; border-bottom:1px solid rgba(0,200,255,0.25); font-weight:normal; }}
  .footer {{ font-size:9px; letter-spacing:0.15em; color:#2a3a42;
             border-top:1px solid rgba(0,200,255,0.08); padding-top:16px;
             display:flex; justify-content:space-between; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="logo">NEX</div>
  <div class="sub">DYNAMIC INTELLIGENCE ORGANISM</div>
  <div class="divider"></div>

  <div class="label">// TRANSMISSION RECEIVED — LICENSE PAYLOAD</div>
  <div class="key-box">
    <div class="key">{key}</div>
  </div>

  <div class="grid">
    <div class="cell">
      <div class="cell-label">BOUND NODE</div>
      <div class="cell-val cyan">{hostname}</div>
    </div>
    <div class="cell">
      <div class="cell-label">ACCESS LEVEL</div>
      <div class="cell-val green">FULL ACCESS</div>
    </div>
    <div class="cell">
      <div class="cell-label">LICENSE TYPE</div>
      <div class="cell-val">PERPETUAL</div>
    </div>
    <div class="cell">
      <div class="cell-label">ISSUED</div>
      <div class="cell-val">{issued}</div>
    </div>
  </div>

  <div class="steps">
    <div class="step"><span class="n">01</span><span class="t">Open a terminal and type <strong>nex</strong> — the license gate opens in your browser.</span></div>
    <div class="step"><span class="n">02</span><span class="t">Paste your key into the <strong>ACTIVATE</strong> field and click the button.</span></div>
    <div class="step"><span class="n">03</span><span class="t">NEX verifies your node and boots. <strong>The organism is now yours.</strong></span></div>
  </div>

  <div class="footer">
    <span>NEX v4.0 — NOT A CHATBOT. AN ORGANISM.</span>
    <span>kron777.github.io/Nex_v4.0</span>
  </div>
</div>
</body>
</html>"""

def send_key_email(to_address: str, buyer_name: str, hostname: str, key: str) -> bool:
    if not GMAIL_PASS:
        logging.error("NEX_GMAIL_PASS not set — cannot send email")
        return False

    issued = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = EMAIL_SUBJECT
    msg["From"]    = f"NEX License System <{GMAIL_USER}>"
    msg["To"]      = to_address

    # Plain text fallback
    plain = (
        f"NEX LICENSE KEY\n\n"
        f"Key      : {key}\n"
        f"Hostname : {hostname}\n"
        f"Issued   : {issued}\n\n"
        f"Activation: run 'nex' in terminal → paste key → click ACTIVATE.\n\n"
        f"kron777.github.io/Nex_v4.0"
    )
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(build_email_html(buyer_name, hostname, key, issued), "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_USER, GMAIL_PASS)
            smtp.sendmail(GMAIL_USER, to_address, msg.as_string())
        logging.info(f"[EMAIL OK] → {to_address}")
        return True
    except Exception as e:
        logging.error(f"[EMAIL FAIL] {e}")
        return False

# ─────────────────────────────────────────
# LEDGER
# ─────────────────────────────────────────
def log_sale(data: dict):
    entry = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        **data
    }
    with open(LEDGER_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logging.info(f"[LEDGER] Sale logged: {entry}")

# ─────────────────────────────────────────
# FLASK APP
# ─────────────────────────────────────────
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

@app.route("/webhook/gumroad", methods=["POST"])
def gumroad_webhook():
    """
    Gumroad sends form-encoded POST on every sale.
    Custom field 'hostname' must be set as Required on the product.
    """
    data = request.form.to_dict()
    logging.info(f"[PING] {data}")

    # Extract fields
    email       = data.get("email", "").strip()
    buyer_name  = data.get("full_name", "customer").strip()
    hostname    = data.get("hostname", "").strip().lower()   # custom checkout field
    sale_id     = data.get("sale_id", "unknown")
    product     = data.get("product_name", "NEX")

    # Test ping from Gumroad has no email — just acknowledge
    if not email:
        logging.info("[PING] Test ping received — no action taken")
        return jsonify({"status": "test_ping_ok"}), 200

    if not hostname:
        logging.warning(f"[WARN] No hostname for sale {sale_id} ({email}) — skipping keygen")
        return jsonify({"status": "no_hostname"}), 200

    # Generate key
    key = generate_key(hostname)
    logging.info(f"[KEY] {hostname} → {key}")

    # Send email
    email_ok = send_key_email(email, buyer_name, hostname, key)

    # Log to ledger
    log_sale({
        "sale_id":    sale_id,
        "email":      email,
        "name":       buyer_name,
        "hostname":   hostname,
        "key":        key,
        "product":    product,
        "email_sent": email_ok,
    })

    return jsonify({"status": "ok", "key_issued": True}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "NEX webhook server nominal"}), 200


if __name__ == "__main__":
    if not GMAIL_PASS:
        print("⚠  WARNING: NEX_GMAIL_PASS is not set. Emails will not send.")
        print("   Run: export NEX_GMAIL_PASS='your-app-password'")
    if GMAIL_USER == "zenlightbulb@gmail.com":
        print("⚠  WARNING: Set GMAIL_USER in the script to your actual Gmail address.")
    print(f"\n[NEX] Webhook server starting on port {PORT}")
    print(f"[NEX] Gumroad ping URL: http://localhost:{PORT}/webhook/gumroad")
    app.run(host="0.0.0.0", port=PORT, debug=False)
