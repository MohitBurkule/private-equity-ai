"""Post the alert digest to Slack or Microsoft Teams through incoming webhooks. Webhook URLs come from the
environment (SLACK_WEBHOOK_URL, TEAMS_WEBHOOK_URL) and are checked against known hosts before any call, so a
misconfigured URL cannot send the digest to an arbitrary host. Each post is one plain-text message."""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from urllib.parse import urlparse

from app import outbound
from app.connectors.base import Http, default_http

ALLOWED = {"slack": ("hooks.slack.com",), "teams": ("outlook.office.com", "outlook.office365.com")}
Chat = Callable[[str], None]


class ChatNotConfigured(Exception):
    pass


def _check(kind: str, url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not any(host == h or host.endswith("." + h) for h in ALLOWED[kind]):
        raise ValueError(f"{kind} webhook must be an https URL on {', '.join(ALLOWED[kind])}")
    return url


def post_chat(text: str, *, slack_url: str | None = None, teams_url: str | None = None,
              http: Http = default_http) -> list[str]:
    """Send text to each configured webhook. Returns the kinds that were sent."""
    sent = []
    for kind, url in (("slack", slack_url), ("teams", teams_url)):
        if not url:
            continue
        body = json.dumps({"text": text})
        http(_check(kind, url), {"X-Post-Body": body, "Content-Type": "application/json"})
        sent.append(kind)
    return sent


def chat_poster(http: Http = default_http, pii: bool = False) -> Chat | None:
    """A poster for the workflow runner, or None when no webhook is configured. With `pii` on, identifiers are
    stripped from each message before it leaves."""
    slack, teams = os.environ.get("SLACK_WEBHOOK_URL"), os.environ.get("TEAMS_WEBHOOK_URL")
    if not (slack or teams):
        return None
    return lambda text: post_chat(outbound.text(pii, text), slack_url=slack, teams_url=teams, http=http)
