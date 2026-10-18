"""Local stand-in for Microsoft Graph's memberOf endpoint, for parity. Both stacks are pointed here through
GRAPH_BASE_URL; the certificate is generated per run by scripts/parity.sh and trusted through SSL_CERT_FILE (FastAPI)
and GRAPH_CA_FILE (Rust). Usage: fake_graph.py PORT CERT KEY BASE_URL"""
import http.server
import json
import ssl
import sys
import urllib.parse

PORT, CERT, KEY, BASE = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]

# email -> the directory group ids it is in. Page one carries a nextLink; page two closes the walk.
MEMBERSHIPS = {
    "ana@example.test": ["GID-1", "gid-2", "Gid-3"],
}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        parts = url.path.split("/")
        query = urllib.parse.parse_qs(url.query)
        if not (len(parts) == 5 and parts[1] == "v1.0" and parts[2] == "users" and parts[4] == "memberOf"):
            return self.reply(404, {"error": {"code": "NotFound"}})
        email = urllib.parse.unquote(parts[3])
        ids = MEMBERSHIPS.get(email)
        if ids is None:
            return self.reply(404, {"error": {"code": "ResourceNotFound"}})
        if "page" in query:
            return self.reply(200, {"value": [{"id": i} for i in ids[2:]]})
        first = {"value": [{"id": i} for i in ids[:2]] + [{"id": ""}],
                 "@odata.nextLink": f"{BASE}/users/{urllib.parse.quote(email, safe='')}/memberOf?$select=id&page=2"}
        return self.reply(200, first)

    def reply(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(CERT, KEY)
server.socket = ctx.wrap_socket(server.socket, server_side=True)
server.serve_forever()
