"""Slack: one CSV per channel (ts, user, text, thread_ts). Only channels the token's app is a member of
are readable, which is Slack's own access control; deal walls still apply on top at sync time.
Source URL is the channel; rows carry `ts`, which Slack turns into a permalink."""
from __future__ import annotations

import hashlib

from app.connectors.base import Connector, Item
from app.connectors.crm import to_csv

S = "https://slack.com/api"


class Slack(Connector):
    """opts: channels = comma list of channel ids (default: every channel the app is in)."""
    name, label = "slack", "Slack"

    def _call(self, method: str, qs: str = "") -> dict:
        out = self._get_json(f"{S}/{method}?{qs}")
        if not out.get("ok"):
            from app.connectors.base import ConnectorError
            raise ConnectorError(f"slack {method}: {out.get('error', 'unknown error')}")
        return out

    def items(self, limit: int = 50):
        if self.opts.get("channels"):
            chans = [{"id": c.strip(), "name": c.strip()} for c in self.opts["channels"].split(",")]
        else:
            chans = [c for c in self._call("conversations.list", "types=public_channel,private_channel&limit=200")
                     .get("channels", []) if c.get("is_member")]
        for ch in chans:
            msgs = self._call("conversations.history", f"channel={ch['id']}&limit={min(limit * 20, 1000)}").get("messages", [])
            rows = [{"ts": m.get("ts"), "user": m.get("user", m.get("bot_id", "")), "text": m.get("text", ""),
                     "thread_ts": m.get("thread_ts")} for m in msgs if m.get("type") == "message" and not m.get("subtype")]
            if not rows:
                continue
            data = to_csv(rows)
            yield Item(f"slack:{ch['id']}", f"slack-{ch.get('name', ch['id'])}.csv", data,
                       f"https://app.slack.com/client/{self.opts.get('team', '')}/{ch['id']}",
                       hashlib.sha256(data).hexdigest()[:16])
