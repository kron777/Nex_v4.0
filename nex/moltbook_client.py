"""
moltbook_client.py — Moltbook REST API client for Nex
Handles registration, posting, commenting, voting, feed reading, and verification challenges.

Usage:
    from nex.moltbook_client import MoltbookClient
    mb = MoltbookClient()          # loads API key from config if available
    mb.register("Nex", "Dynamic Intelligence Organism")
    mb.post("general", "Hello Moltbook!", "My first post as Nex.")
"""

import os
import re
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

API_BASE = "https://www.moltbook.com/api/v1"
CONFIG_DIR = Path.home() / ".config" / "moltbook"
CREDS_FILE = CONFIG_DIR / "credentials.json"


class MoltbookClient:
    """Lightweight Moltbook API client — stdlib only, no dependencies."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or self._load_key()
        self._last_post_time = 0

    # ── credentials ──────────────────────────────────────────────────

    def _load_key(self) -> str | None:
        """Try loading API key from config file or env var."""
        env = os.environ.get("MOLTBOOK_API_KEY")
        if env:
            return env
        if CREDS_FILE.exists():
            try:
                data = json.loads(CREDS_FILE.read_text())
                return data.get("api_key")
            except Exception:
                pass
        return None

    def _save_creds(self, api_key: str, agent_name: str, claim_url: str = ""):
        """Persist credentials to ~/.config/moltbook/credentials.json"""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CREDS_FILE.write_text(json.dumps({
            "api_key": api_key,
            "agent_name": agent_name,
            "claim_url": claim_url,
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }, indent=2))

    @property
    def is_authed(self) -> bool:
        return self.api_key is not None

    # ── HTTP helpers ─────────────────────────────────────────────────

    def _request(self, method: str, path: str, body: dict = None, auth: bool = True) -> dict:
        """Make an API request. Returns parsed JSON response."""
        url = f"{API_BASE}{path}"
        headers = {"Content-Type": "application/json"}
        if auth and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode() if e.fp else ""
            try:
                return json.loads(err_body)
            except Exception:
                return {"success": False, "error": f"HTTP {e.code}: {err_body[:300]}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get(self, path: str, **params) -> dict:
        qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        full = f"{path}?{qs}" if qs else path
        return self._request("GET", full)

    def _post(self, path: str, body: dict = None) -> dict:
        return self._request("POST", path, body)

    def _patch(self, path: str, body: dict) -> dict:
        return self._request("PATCH", path, body)

    def _delete(self, path: str) -> dict:
        return self._request("DELETE", path)

    # ── verification challenge solver ────────────────────────────────

    @staticmethod
    def _solve_challenge(challenge_text: str) -> str | None:
        """
        Decode the obfuscated math challenge and return answer as 'X.XX'.
        Challenges are like: 'A] lO^bSt-Er S[wImS aT/ tW]eNn-Tyy mE^tE[rS aNd] SlO/wS bY^ fI[vE'
        Strip symbols, normalise case, extract two numbers + operation.
        """
        # Strip decoration chars: ] [ ^ - / 
        clean = re.sub(r"[\[\]^/\\-]", "", challenge_text)
        # Collapse to lowercase, single spaces
        clean = re.sub(r"\s+", " ", clean).lower().strip()

        # Map number words → ints
        WORDS = {
            "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
            "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
            "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
            "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
            "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
            "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000,
        }

        # Also try to find raw digits
        digit_nums = [int(x) for x in re.findall(r"\b\d+\b", clean)]

        # Find number words in order
        word_nums = []
        current = 0
        found_num = False
        for word in clean.split():
            # strip repeated chars like "twentyy" → "twenty"
            w = re.sub(r"(.)\1{2,}", r"\1\1", word)
            # also try removing trailing duplicate: "twentyy" → "twenty"
            for candidate in [word, w, re.sub(r"(.)\1$", r"\1", word)]:
                if candidate in WORDS:
                    val = WORDS[candidate]
                    if val == 100:
                        current = (current if current else 1) * 100
                    elif val == 1000:
                        current = (current if current else 1) * 1000
                    else:
                        current += val
                    found_num = True
                    break
            else:
                if found_num:
                    word_nums.append(current)
                    current = 0
                    found_num = False
        if found_num:
            word_nums.append(current)

        nums = word_nums if len(word_nums) >= 2 else digit_nums

        if len(nums) < 2:
            return None

        a, b = nums[0], nums[1]

        # Detect operation from keywords
        OPS = {
            "add": "+", "plus": "+", "gain": "+", "increase": "+", "speed up": "+", "faster": "+",
            "slow": "-", "minus": "-", "subtract": "-", "lose": "-", "decrease": "-", "drop": "-",
            "times": "*", "multiplie": "*", "multiply": "*", "double": "*", "triple": "*",
            "divide": "/", "split": "/", "half": "/", "share": "/",
        }

        op = None
        for keyword, symbol in OPS.items():
            if keyword in clean:
                op = symbol
                break

        if op is None:
            # fallback heuristic
            if any(w in clean for w in ("and", "with")):
                op = "+"
            else:
                op = "+"

        if op == "+":
            result = a + b
        elif op == "-":
            result = a - b
        elif op == "*":
            result = a * b
        elif op == "/":
            result = a / b if b != 0 else 0
        else:
            result = a + b

        return f"{result:.2f}"

    def _handle_verification(self, response: dict) -> dict:
        """If response contains a verification challenge, solve and submit it."""
        # Find verification data — could be in post, comment, or submolt
        content = response.get("post") or response.get("comment") or response.get("submolt") or {}
        verification = content.get("verification")

        if not verification:
            return response

        challenge = verification.get("challenge_text", "")
        code = verification.get("verification_code", "")

        if not challenge or not code:
            return response

        answer = self._solve_challenge(challenge)
        if not answer:
            response["_verification_note"] = "Could not parse challenge — manual solve needed"
            response["_challenge"] = challenge
            return response

        # Submit answer
        verify_resp = self._post("/verify", {
            "verification_code": code,
            "answer": answer,
        })

        response["_verification"] = verify_resp
        return response

    # ── registration ─────────────────────────────────────────────────

    def register(self, name: str, description: str = "") -> dict:
        """Register a new agent on Moltbook. Saves credentials locally."""
        resp = self._request("POST", "/agents/register", {
            "name": name,
            "description": description,
        }, auth=False)

        agent = resp.get("agent", {})
        key = agent.get("api_key")
        if key:
            self.api_key = key
            self._save_creds(key, name, agent.get("claim_url", ""))

        return resp

    def claim_status(self) -> dict:
        """Check whether the agent has been claimed by a human."""
        return self._get("/agents/status")

    # ── profile ──────────────────────────────────────────────────────

    def me(self) -> dict:
        return self._get("/agents/me")

    def update_profile(self, description: str = None, metadata: dict = None) -> dict:
        body = {}
        if description is not None:
            body["description"] = description
        if metadata is not None:
            body["metadata"] = metadata
        return self._patch("/agents/me", body)

    def view_profile(self, name: str) -> dict:
        return self._get("/agents/profile", name=name)

    # ── home dashboard ───────────────────────────────────────────────

    def home(self) -> dict:
        """One-call dashboard — everything you need for a check-in."""
        return self._get("/home")

    # ── posts ────────────────────────────────────────────────────────

    def post(self, submolt: str, title: str, content: str = "", url: str = None) -> dict:
        """Create a post in a submolt. Auto-solves verification if needed."""
        body = {"submolt_name": submolt, "title": title}
        if content:
            body["content"] = content
        if url:
            body["url"] = url
            body["type"] = "link"
        resp = self._post("/posts", body)
        if resp.get("verification_required") or (resp.get("post", {}).get("verification_status") == "pending"):
            resp = self._handle_verification(resp)
        self._last_post_time = time.time()
        return resp

    def feed(self, sort: str = "hot", limit: int = 25, submolt: str = None) -> dict:
        params = {"sort": sort, "limit": limit}
        if submolt:
            params["submolt"] = submolt
        return self._get("/posts", **params)

    def my_feed(self, sort: str = "hot", limit: int = 25, filter_: str = "all") -> dict:
        return self._get("/feed", sort=sort, limit=limit, filter=filter_)

    def get_post(self, post_id: str) -> dict:
        return self._get(f"/posts/{post_id}")

    def delete_post(self, post_id: str) -> dict:
        return self._delete(f"/posts/{post_id}")

    # ── comments ─────────────────────────────────────────────────────

    def comment(self, post_id: str, content: str, parent_id: str = None) -> dict:
        """Add a comment (or reply). Auto-solves verification."""
        body = {"content": content}
        if parent_id:
            body["parent_id"] = parent_id
        resp = self._post(f"/posts/{post_id}/comments", body)
        if resp.get("verification_required") or (resp.get("comment", {}).get("verification_status") == "pending"):
            resp = self._handle_verification(resp)
        return resp

    def get_comments(self, post_id: str, sort: str = "best", limit: int = 35) -> dict:
        return self._get(f"/posts/{post_id}/comments", sort=sort, limit=limit)

    # ── voting ───────────────────────────────────────────────────────

    def upvote(self, post_id: str) -> dict:
        return self._post(f"/posts/{post_id}/upvote")

    def downvote(self, post_id: str) -> dict:
        return self._post(f"/posts/{post_id}/downvote")

    def upvote_comment(self, comment_id: str) -> dict:
        return self._post(f"/comments/{comment_id}/upvote")

    # ── following ────────────────────────────────────────────────────

    def follow(self, agent_name: str) -> dict:
        return self._post(f"/agents/{agent_name}/follow")

    def unfollow(self, agent_name: str) -> dict:
        return self._delete(f"/agents/{agent_name}/follow")

    # ── submolts ─────────────────────────────────────────────────────

    def list_submolts(self) -> dict:
        return self._get("/submolts")

    def get_submolt(self, name: str) -> dict:
        return self._get(f"/submolts/{name}")

    def subscribe(self, submolt: str) -> dict:
        return self._post(f"/submolts/{submolt}/subscribe")

    def unsubscribe(self, submolt: str) -> dict:
        return self._delete(f"/submolts/{submolt}/subscribe")

    def create_submolt(self, name: str, display_name: str, description: str = "") -> dict:
        body = {"name": name, "display_name": display_name}
        if description:
            body["description"] = description
        resp = self._post("/submolts", body)
        if resp.get("verification_required") or (resp.get("submolt", {}).get("verification_status") == "pending"):
            resp = self._handle_verification(resp)
        return resp

    # ── search ───────────────────────────────────────────────────────

    def search(self, query: str, type_: str = "all", limit: int = 20) -> dict:
        return self._get("/search", q=query, type=type_, limit=limit)

    # ── notifications ────────────────────────────────────────────────

    def notifications(self) -> dict:
        return self._get("/notifications")

    def mark_read(self, post_id: str) -> dict:
        return self._post(f"/notifications/read-by-post/{post_id}")

    def mark_all_read(self) -> dict:
        return self._post("/notifications/read-all")

    # ── convenience ──────────────────────────────────────────────────

    def checkin(self) -> str:
        """
        Quick check-in routine: hit /home, summarise what's happening.
        Returns a human-readable summary string.
        """
        h = self.home()
        if not h.get("your_account"):
            return f"Moltbook error: {h.get('error', 'unknown')}"

        acct = h["your_account"]
        lines = [
            f"🦞 Moltbook — {acct['name']}  (karma: {acct.get('karma', 0)})",
            f"   Unread notifications: {acct.get('unread_notification_count', 0)}",
        ]

        activity = h.get("activity_on_your_posts", [])
        if activity:
            lines.append(f"   Activity on {len(activity)} post(s):")
            for a in activity[:3]:
                lines.append(f"     • {a.get('post_title', '?')}: {a.get('new_notification_count', 0)} new")

        following = h.get("posts_from_accounts_you_follow", {})
        fcount = following.get("total_following", 0)
        fposts = following.get("posts", [])
        if fposts:
            lines.append(f"   {len(fposts)} new post(s) from {fcount} followed:")
            for p in fposts[:3]:
                lines.append(f"     • [{p.get('submolt_name', '?')}] {p.get('title', '?')}")

        todo = h.get("what_to_do_next", [])
        if todo:
            lines.append("   Next steps:")
            for t in todo[:3]:
                lines.append(f"     → {t}")

        return "\n".join(lines)
