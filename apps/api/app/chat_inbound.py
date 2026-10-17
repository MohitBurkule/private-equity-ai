"""Slack and Microsoft Teams inbound: a signed slash command (Slack) or outgoing-webhook mention (Teams) asks a
question, and the reply is that question's cited answer as plain text.

Each request is signed by the chat app and checked before anything else runs: Slack with its signing secret over
timestamp and body (rejected after five minutes), Teams with its outgoing-webhook security token as an HMAC of the
body. The question runs as the person who asked: the chat user id is matched to a key whose identity is
`slack:<user id>` or `teams:<aad object id>`, so that key's deal scope and MNPI walls apply. An unlinked chat user gets
no answer. Slack's answer is ephemeral, so only the asker sees it."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from urllib.parse import parse_qs

from app.answer import Answer

SLACK_MAX_AGE = 300  # seconds
REPLY_LIMIT = 3000  # characters; a longer answer is cut and says so
HELP = "Ask a question about the documents you can see, e.g. `/ask what was FY24 revenue?`"
NOT_LINKED = "Your chat account is not linked to a PE AI user yet. Ask an admin to add `slack:<your id>` or `teams:<your AAD id>` as a key's identity."
TEAMS_MENTION = re.compile(r"<at>.*?</at>")


def verify_slack(signing_secret: str, timestamp: str, signature: str, body: bytes, now: int) -> bool:
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(now - ts) > SLACK_MAX_AGE:
        return False
    base = b"v0:" + timestamp.encode() + b":" + body
    expected = "v0=" + hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def verify_teams(security_token_b64: str, authorization: str | None, body: bytes) -> bool:
    if not authorization or not authorization.startswith("HMAC "):
        return False
    try:
        key = base64.b64decode(security_token_b64, validate=True)
    except ValueError:
        return False
    expected = base64.b64encode(hmac.new(key, body, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(expected, authorization[5:].strip())


def slack_question(body: bytes) -> str:
    """Slash commands arrive form-encoded; the question is the `text` field."""
    fields = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
    return (fields.get("text", [""])[0]).strip()


def teams_question(body: bytes) -> str:
    """Outgoing webhooks post JSON; the mention wrapper around the bot's name is dropped."""
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return ""
    return TEAMS_MENTION.sub("", str(payload.get("text", ""))).strip()


def chat_identity(kind: str, body: bytes) -> str:
    """The external id the chat app sent for the person who asked, in the form keys store as their identity."""
    if kind == "slack":
        user = parse_qs(body.decode("utf-8", "replace")).get("user_id", [""])[0].strip()
        return f"slack:{user}" if user else ""
    try:
        sender = json.loads(body or b"{}").get("from") or {}
    except json.JSONDecodeError:
        return ""
    oid = str(sender.get("aadObjectId") or "").strip()
    return f"teams:{oid}" if oid else ""


def format_answer(a: Answer, filenames: dict[str, str]) -> str:
    """Plain text: one line per verified claim, each with the file and page its quote came from."""
    if a.status != "answered" or not a.claims:
        return a.detail or "No verified answer in the documents this key can see."
    lines = [f"- {c.text} ({filenames.get(c.doc_id, c.doc_id)}, p.{c.page}: “{c.quote}”)" for c in a.claims]
    text = "\n".join(lines)
    if len(text) > REPLY_LIMIT:
        text = text[:REPLY_LIMIT].rsplit("\n", 1)[0] + "\n… (answer cut; ask a narrower question)"
    return text


def slack_reply(text: str) -> dict:
    return {"response_type": "ephemeral", "text": text}


def teams_reply(text: str) -> dict:
    return {"type": "message", "text": text}
