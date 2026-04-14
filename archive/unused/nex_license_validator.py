#!/usr/bin/env python3
"""
NEX LICENSE VALIDATOR v2
=========================
Validates license on launch. If no key found:
- Spins up local license server on localhost:17749
- Opens the browser gate (which POSTs to the server)
- Waits for browser activation
- Continues booting once licensed
"""

import hmac
import hashlib
import os
import sys
import socket
import unicodedata
import webbrowser
import threading
from pathlib import Path

# ── SECRET — must match nex_keygen.py ────────────────────────────────────────
NEX_SECRET = "∩船玉±θ手なΔΩ口5ΩΕら月6のρ学ら花≈Μ7てう≡森Ε*玉え"

# ── CUSTOM ALPHABET ───────────────────────────────────────────────────────────
ALPHABET = "あλツΩミπさΦねΨカθユΣほΔきΞるζナβめΓをμ0123456789"
ALPHABET = ALPHABET[:32]

# ── PATHS ─────────────────────────────────────────────────────────────────────
NEX_DIR     = Path.home() / ".nex"
KEY_FILE    = NEX_DIR / "license.key"
GATE_HTML   = Path(__file__).parent / "nex_license_gate.html"
LICENSE_LOG = NEX_DIR / "license_audit.log"
PORT        = 17749


def nfc(s):
    return unicodedata.normalize('NFC', s)


def encode_b32_custom(data: bytes, length: int = 16) -> str:
    bits = int.from_bytes(data, 'big')
    total_bits = len(data) * 8
    chars = []
    for i in range(length):
        shift = total_bits - (i + 1) * 5
        idx = (bits << abs(shift)) & 0x1F if shift < 0 else (bits >> shift) & 0x1F
        chars.append(ALPHABET[idx])
    return ''.join(chars)


def expected_key(hostname: str) -> str:
    payload = nfc(hostname.strip().lower()).encode('utf-8')
    sig = hmac.new(NEX_SECRET.encode('utf-8'), payload, hashlib.sha256).digest()
    raw = encode_b32_custom(sig[:10], 16)
    return "NEX-" + '-'.join([raw[i:i+4] for i in range(0, 16, 4)])


def get_hostname() -> str:
    return socket.gethostname().strip().lower()


def validate_key(key: str) -> bool:
    key = nfc(key.strip())
    hostname = get_hostname()
    checks = [hostname, "ANY"] + [f"ANY_{i}" for i in range(100)]
    for h in checks:
        try:
            if hmac.compare_digest(key.encode('utf-8'), expected_key(h).encode('utf-8')):
                return True
        except Exception:
            pass
    return False


def read_stored_key():
    if KEY_FILE.exists():
        try:
            return KEY_FILE.read_text(encoding='utf-8').strip()
        except Exception:
            return None
    return None


def log_attempt(status, key=""):
    try:
        NEX_DIR.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        with open(LICENSE_LOG, 'a', encoding='utf-8') as f:
            f.write(f"[{ts}] host={get_hostname()} status={status} key={key[:12]}...\n")
    except Exception:
        pass


def open_gate():
    gate = GATE_HTML if GATE_HTML.exists() else Path(__file__).parent / "nex_license_gate.html"
    if gate.exists():
        url = f"file://{gate.resolve()}?port={PORT}&host={get_hostname()}"
        webbrowser.open(url)
    else:
        webbrowser.open(f"http://127.0.0.1:{PORT}/status")


def prompt_license():
    print()
    print("  ╔══════════════════════════════════════════════╗")
    print("  ║           NEX — LICENSE REQUIRED             ║")
    print("  ╠══════════════════════════════════════════════╣")
    print("  ║  No valid license key found on this system.  ║")
    print("  ║                                              ║")
    print("  ║  Email: zenlightbulb@gmail.com               ║")
    print(f"  ║  Host:  {get_hostname():<44}║")
    print("  ║                                              ║")
    print("  ║  Enter your key in the browser window...     ║")
    print("  ║  or Ctrl+C to exit.                          ║")
    print("  ╚══════════════════════════════════════════════╝")
    print()

    try:
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location(
            "nex_license_server",
            pathlib.Path(__file__).parent / "nex_license_server.py"
        )
        srv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(srv)
        srv.NEX_SECRET = NEX_SECRET
        srv.ALPHABET = ALPHABET

        print(f"  [NEX] License server ready on port {PORT}")
        threading.Thread(target=open_gate, daemon=True).start()
        print("  [NEX] Browser gate opening...")
        print("  [NEX] Waiting for activation...\n")

        try:
            result = srv.run_server(timeout=300)
        except KeyboardInterrupt:
            print("\n  [NEX] Exiting — no license provided.")
            return False

        if result:
            print("  [NEX] License accepted — booting NEX...")
            log_attempt("ACCEPTED_VIA_BROWSER")
            return True
        else:
            print("  [NEX] Timed out. Run 'nex' again to retry.")
            return False

    except Exception as e:
        print(f"  [NEX] License server error: {e}")
        return False


def check_license() -> bool:
    stored = read_stored_key()
    if stored and validate_key(stored):
        log_attempt("OK", stored)
        return True
    log_attempt("MISSING")
    result = prompt_license()
    if not result:
        sys.exit(1)
    return True


if __name__ == "__main__":
    check_license()
