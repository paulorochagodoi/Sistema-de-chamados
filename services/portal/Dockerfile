# syntax=docker/dockerfile:1
FROM node:22-alpine AS build

WORKDIR /app

# dependências primeiro: mantém a camada em cache entre builds de código
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

# 127.0.0.1, e não localhost: o nginx faz `listen 80` (IPv4) e o wget do BusyBox
# tenta ::1 primeiro, o que daria "connection refused" e marcaria o container
# como unhealthy. O Traefik ignora container unhealthy — o roteador some e o
# painel responde 404 sem nenhum erro no log.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q --spider http://127.0.0.1/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
