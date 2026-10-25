# Build the SPA
FROM node:24-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# Vite inlines this at build time; an empty value disables frontend error reporting.
ARG VITE_SENTRY_DSN=""
ENV VITE_SENTRY_DSN=$VITE_SENTRY_DSN
# Public origin baked into canonical/OG at build time; override for production.
ARG VITE_SITE_ORIGIN="http://localhost:8080"
ENV VITE_SITE_ORIGIN=$VITE_SITE_ORIGIN
RUN npm run build

# Serve it and proxy the API
FROM nginx:1.29-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
