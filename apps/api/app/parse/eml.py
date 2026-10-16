"""EML parsing: headers + readable body as one page; attachments returned for separate ingest."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser

_TAG = re.compile(r"<(script|style).*?</\1>|<[^>]+>", re.IGNORECASE | re.DOTALL)


@dataclass
class ParsedEmail:
    text: str
    attachments: list[tuple[str, bytes]] = field(default_factory=list)


def parse_eml(data: bytes) -> ParsedEmail:
    msg = BytesParser(policy=policy.default).parsebytes(data)
    head = [f"{h}: {msg[h]}" for h in ("From", "To", "Cc", "Date", "Subject") if msg[h]]
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if body_part is not None:
        body = body_part.get_content()
        if body_part.get_content_type() == "text/html":
            body = re.sub(r"[ \t]+", " ", _TAG.sub(" ", body))
            body = re.sub(r"\n\s*\n+", "\n", body)
    atts = []
    for part in msg.iter_attachments():
        name = part.get_filename() or "attachment"
        payload = part.get_payload(decode=True)
        if payload:
            atts.append((name, payload))
    return ParsedEmail("\n".join(head) + "\n\n" + body.strip(), atts)
