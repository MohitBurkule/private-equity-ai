"""OAuth2 authorization-code flow for connectors, configured per connector from the environment:
OAUTH_<NAME>_CLIENT_ID, OAUTH_<NAME>_CLIENT_SECRET, OAUTH_<NAME>_AUTH_URL, OAUTH_<NAME>_TOKEN_URL,
OAUTH_<NAME>_SCOPES (optional). OAUTH_REDIRECT_BASE is the public https base for callbacks.

State is HMAC-signed with OAUTH_STATE_SECRET and expires after STATE_TTL seconds, so a callback cannot be
forged, replayed later, or pointed at another connector. Only the refresh token is stored (sealed by the
vault); access tokens are minted per sync and never persisted."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
from dataclasses import dataclass

from app.connectors.base import ConnectorError, Http

STATE_TTL = 600


class OAuthError(ConnectorError):
    pass


@dataclass(frozen=True)
class OAuthConfig:
    name: str
    client_id: str
    client_secret: str
    auth_url: str
    token_url: str
    scopes: str = ""


def config_for(name: str) -> OAuthConfig:
    p = f"OAUTH_{name.upper().replace('-', '_')}_"
    vals = {k: os.environ.get(p + k, "") for k in ("CLIENT_ID", "CLIENT_SECRET", "AUTH_URL", "TOKEN_URL")}
    if not all(vals.values()):
        raise OAuthError(f"OAuth for {name} is not configured")
    for url in (vals["AUTH_URL"], vals["TOKEN_URL"]):
        if not url.startswith("https://"):
            raise OAuthError("OAuth endpoints must be https")
    return OAuthConfig(name, vals["CLIENT_ID"], vals["CLIENT_SECRET"], vals["AUTH_URL"], vals["TOKEN_URL"],
                       os.environ.get(p + "SCOPES", ""))


def redirect_uri(name: str) -> str:
    base = os.environ.get("OAUTH_REDIRECT_BASE", "").rstrip("/")
    if not base.startswith("https://"):
        raise OAuthError("OAUTH_REDIRECT_BASE must be an https URL")
    return f"{base}/oauth/{name}/callback"


def _secret() -> bytes:
    s = os.environ.get("OAUTH_STATE_SECRET", "")
    if len(s) < 32:
        raise OAuthError("OAUTH_STATE_SECRET (32+ characters) is required")
    return s.encode()


def sign_state(payload: dict, now: float | None = None) -> str:
    body = dict(payload, exp=int((now or time.time()) + STATE_TTL))
    raw = base64.urlsafe_b64encode(json.dumps(body, sort_keys=True).encode()).decode()
    return f"{raw}.{hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()}"


def verify_state(state: str, now: float | None = None) -> dict:
    raw, _, sig = state.rpartition(".")
    if not raw or not hmac.compare_digest(sig, hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()):
        raise OAuthError("state signature invalid")
    try:
        body = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except ValueError as e:
        raise OAuthError("state unreadable") from e
    if body.get("exp", 0) < (now or time.time()):
        raise OAuthError("state expired; start the connection again")
    return body


def authorize_url(cfg: OAuthConfig, redirect: str, state: str) -> str:
    q = {"client_id": cfg.client_id, "redirect_uri": redirect, "response_type": "code", "state": state,
         "access_type": "offline", "prompt": "consent"}  # offline/consent: Google-style, ignored by most others
    if cfg.scopes:
        q["scope"] = cfg.scopes
    return f"{cfg.auth_url}?{urllib.parse.urlencode(q)}"


def _post_form(url: str, form: dict[str, str], http: Http) -> dict:
    # Http is GET-shaped; default_http sends X-Post-Body as the form body of a POST (see connectors/base.py).
    raw = http(url, {"X-Post-Body": urllib.parse.urlencode(form),
                     "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    try:
        doc = json.loads(raw)
    except ValueError as e:
        raise OAuthError("token endpoint returned non-JSON") from e
    if not isinstance(doc, dict) or "access_token" not in doc:
        raise OAuthError(f"token endpoint refused: {doc.get('error', 'no access token') if isinstance(doc, dict) else 'bad response'}")
    return doc


def exchange_code(cfg: OAuthConfig, code: str, redirect: str, http: Http) -> dict:
    return _post_form(cfg.token_url, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
                                      "client_id": cfg.client_id, "client_secret": cfg.client_secret}, http)


def refresh(cfg: OAuthConfig, refresh_token: str, http: Http) -> dict:
    return _post_form(cfg.token_url, {"grant_type": "refresh_token", "refresh_token": refresh_token,
                                      "client_id": cfg.client_id, "client_secret": cfg.client_secret}, http)
