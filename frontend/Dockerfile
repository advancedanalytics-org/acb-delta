FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# mock (default) or live; see .env.example.
ARG VITE_API_MODE=mock
ENV VITE_API_MODE=$VITE_API_MODE
RUN npm run build

FROM nginx:alpine
RUN apk add --no-cache openssl
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80 443 3000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD wget -qO- http://127.0.0.1:3000/ >/dev/null || wget -qO- http://127.0.0.1:80/ >/dev/null || exit 1
ENTRYPOINT ["/docker-entrypoint.sh"]
