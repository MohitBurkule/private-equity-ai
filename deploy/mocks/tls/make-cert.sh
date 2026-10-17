#!/bin/sh
# SYNTHETIC, dev-only TLS for the WireMock market-data feed. Self-signed, 30 days, for localhost and the mock host
# name. Output goes to deploy/mocks/tls/out, which is git-ignored. Never used outside the mock stack.
set -eu
OUT="$(dirname "$0")/out"
mkdir -p "$OUT"
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$OUT/key.pem" -out "$OUT/cert.pem" -days 30 -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,DNS:capiq.synthetic.test,IP:127.0.0.1" -addext "basicConstraints=critical,CA:TRUE"
openssl pkcs12 -export -inkey "$OUT/key.pem" -in "$OUT/cert.pem" -out "$OUT/keystore.p12" -passout pass:synthetic
echo "wrote $OUT/cert.pem and $OUT/keystore.p12"
