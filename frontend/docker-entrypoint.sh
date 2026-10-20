#!/bin/sh
set -e

mkdir -p /etc/nginx/certs

# Generate fallback self-signed certificate if none exists, ensuring Nginx starts with SSL on port 443
if [ ! -f /etc/nginx/certs/fullchain.pem ] || [ ! -f /etc/nginx/certs/privkey.pem ]; then
    echo "[entrypoint] No TLS certificate found in /etc/nginx/certs/. Generating self-signed certificate fallback..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /etc/nginx/certs/privkey.pem \
        -out /etc/nginx/certs/fullchain.pem \
        -subj "/C=VN/O=ACB/CN=localhost" 2>/dev/null
fi

exec nginx -g "daemon off;"
