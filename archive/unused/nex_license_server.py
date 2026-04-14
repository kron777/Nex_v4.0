#!/usr/bin/env python3
"""
NEX LICENSE SERVER v2
=====================
Auto-kills any existing process on port 17749 before starting.
Browser gate POSTs key here — validates, stores, signals NEX to continue.
"""

import hmac, hashlib, socket, os, threading, unicodedata, json, urllib.parse, subprocess
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

NEX_SECRET = "∩船玉±θ手なΔΩ口5ΩΕら月6のρ学ら花≈Μ7てう≡森Ε*玉え"
ALPHABET   = "あλツΩミπさΦねΨカθユΣほΔきΞるζナβめΓをμ0123456789"[:32]
NEX_DIR    = Path.home() / ".nex"
KEY_FILE   = NEX_DIR / "license.key"
PORT       = 17749

_activated  = threading.Event()
_server_ref = None


def nfc(s): return unicodedata.normalize('NFC', s)

def encode_b32(data, length=16):
    bits = int.from_bytes(data, 'big'); total = len(data)*8; chars = []
    for i in range(length):
        s = total-(i+1)*5
        chars.append(ALPHABET[(bits<<abs(s))&0x1F if s<0 else (bits>>s)&0x1F])
    return ''.join(chars)

def expected_key(hostname):
    payload = nfc(hostname.strip().lower()).encode('utf-8')
    sig = hmac.new(NEX_SECRET.encode(), payload, hashlib.sha256).digest()
    raw = encode_b32(sig[:10], 16)
    return "NEX-" + '-'.join([raw[i:i+4] for i in range(0,16,4)])

def validate_key(key):
    # Import directly from validator to guarantee same secret
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from nex_license_validator import validate_key as _vk
        return _vk(key)
    except Exception:
        pass
    key = nfc(key.strip())
    hostname = socket.gethostname().strip().lower()
    for h in [hostname, "ANY"] + [f"ANY_{i}" for i in range(100)]:
        try:
            if hmac.compare_digest(key.encode('utf-8'), expected_key(h).encode('utf-8')):
                return True
        except Exception:
            pass
    return False

def store_key(key):
    NEX_DIR.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(nfc(key.strip()), encoding='utf-8')

def kill_port(port):
    """Kill any process using the port before binding."""
    try:
        subprocess.run(['fuser', '-k', f'{port}/tcp'], capture_output=True)
        import time; time.sleep(0.5)
    except Exception:
        pass

def _shutdown_soon():
    import time; time.sleep(1.5)
    if _server_ref: _server_ref.shutdown()


class LicenseHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        if self.path == '/status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self._cors(); self.end_headers()
            self.wfile.write(json.dumps({
                'status': 'waiting',
                'hostname': socket.gethostname(),
                'version': 'v4.0'
            }).encode())
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path == '/activate':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')
            try:
                key = json.loads(body).get('key', '').strip()
            except Exception:
                key = urllib.parse.parse_qs(body).get('key', [''])[0].strip()

            key = nfc(key)

            if validate_key(key):
                store_key(key)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self._cors(); self.end_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'message': 'License accepted. NEX is now active.'
                }).encode())
                _activated.set()
                threading.Thread(target=_shutdown_soon, daemon=True).start()
            else:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self._cors(); self.end_headers()
                self.wfile.write(json.dumps({
                    'success': False,
                    'message': 'Invalid key. Contact zenlightbulb@gmail.com'
                }).encode())
        else:
            self.send_response(404); self.end_headers()


def run_server(timeout=300):
    global _server_ref
    # Kill anything already on the port
    kill_port(PORT)
    server = HTTPServer(('127.0.0.1', PORT), LicenseHandler)
    _server_ref = server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    activated = _activated.wait(timeout=timeout)
    if not activated: server.shutdown()
    return activated


if __name__ == '__main__':
    print(f"[NEX] License server on http://127.0.0.1:{PORT}")
    print("[NEX] Activated ✅" if run_server() else "[NEX] Timed out ❌")
