#!/bin/bash
SSL_DIR="/etc/nginx/ssl"
CERT_FILE="$SSL_DIR/cert.pem"
KEY_FILE="$SSL_DIR/key.pem"

if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
  echo "🔐 Generating self-signed SSL certificate for development..."
  mkdir -p "$SSL_DIR"
  openssl req -x509 -nodes -days 365 \
    -newkey rsa:2048 \
    -keyout "$KEY_FILE" \
    -out "$CERT_FILE" \
    -subj "/C=US/ST=Dev/L=Dev/O=AI Freelance Automation/CN=localhost"
  chmod 600 "$KEY_FILE"
  chmod 644 "$CERT_FILE"
  echo "✅ SSL certificate generated."
else
  echo "✅ SSL certificate already exists."
fi