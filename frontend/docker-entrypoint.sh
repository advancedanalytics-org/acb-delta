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

# Optional basic auth for every page and /api, for deployments with no proxy in front
# (docker-compose.prod.yml requires it). Empty = no auth (local stack, or Caddy does it on the VM).
mkdir -p /etc/nginx/auth
if [ -n "$BASIC_AUTH_USER" ] && [ -n "$BASIC_AUTH_PASSWORD" ]; then
    case "$BASIC_AUTH_USER" in
        *:*) echo "[entrypoint] BASIC_AUTH_USER must not contain ':'" >&2; exit 1 ;;
    esac
    hash=$(printf '%s' "$BASIC_AUTH_PASSWORD" | openssl passwd -apr1 -stdin)
    printf '%s:%s\n' "$BASIC_AUTH_USER" "$hash" > /etc/nginx/auth/htpasswd
    chmod 640 /etc/nginx/auth/htpasswd
    chown root:nginx /etc/nginx/auth/htpasswd
    printf 'auth_basic "acb-delta";\nauth_basic_user_file /etc/nginx/auth/htpasswd;\n' \
        > /etc/nginx/auth/basic.conf
    echo "[entrypoint] Basic auth enabled for user $BASIC_AUTH_USER"
else
    : > /etc/nginx/auth/basic.conf
fi

exec nginx -g "daemon off;"
