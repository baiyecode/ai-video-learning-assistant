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
# Display price and free Analysis Quota, mirrored from the SAME compose APP_ env vars
# the backend enforces, so repricing/re-quota is one edit and the static marketing,
# sitemap and llms.txt move together instead of silently lying.
ARG VITE_ANALYSIS_DAILY_QUOTA="3"
ENV VITE_ANALYSIS_DAILY_QUOTA=$VITE_ANALYSIS_DAILY_QUOTA
ARG VITE_SUBSCRIPTION_MONTHLY_USD="4.99"
ENV VITE_SUBSCRIPTION_MONTHLY_USD=$VITE_SUBSCRIPTION_MONTHLY_USD
RUN npm run build

# Serve it and proxy the API
FROM nginx:1.29-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
