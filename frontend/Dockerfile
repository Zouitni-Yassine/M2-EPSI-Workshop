# Étape 1 : construire l'application. Les URL sont figées au build, parce que
# c'est le navigateur du visiteur qui les appelle, pas le conteneur.
FROM node:22-alpine AS build
WORKDIR /app

ARG VITE_API_URL=http://localhost:8000/api
ARG VITE_AUTH_URL=http://localhost:8300
ARG VITE_DETECTOR_URL=http://localhost:8100
ARG VITE_REMEDIATION_URL=http://localhost:8200
ARG VITE_STRIPE_PUBLISHABLE_KEY
ARG VITE_CARD_ENTRY=own
ARG VITE_PAYPAL_CLIENT_ID
ARG VITE_DATA_SOURCE=api

COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Étape 2 : servir les fichiers statiques.
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=5s --timeout=2s --retries=3 CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
