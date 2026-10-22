FROM node:25-alpine AS build
WORKDIR /app
COPY apps/admin-web/package.json apps/admin-web/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci --include=dev --no-audit --no-fund; else npm install --include=dev --no-audit --no-fund; fi
COPY apps/admin-web/ ./
ARG VITE_GOOGLE_CLIENT_ID=
ENV VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID
RUN npm run build
FROM nginx:1.27-alpine
COPY apps/admin-web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
