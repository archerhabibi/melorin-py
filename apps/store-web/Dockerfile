FROM node:20-alpine AS build
WORKDIR /app
COPY apps/store-web/package.json apps/store-web/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci --include=dev --no-audit --no-fund; else npm install --include=dev --no-audit --no-fund; fi
COPY apps/store-web/ ./
RUN npm run build
FROM nginx:1.27-alpine
COPY apps/store-web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
