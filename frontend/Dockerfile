# Étape 1 : construire l'application. Les URL sont relatives : le navigateur appelle la même
# origine que la page, et ce conteneur (nginx) relaie vers les services. L'application marche
# donc depuis n'importe quelle machine du réseau, pas seulement depuis l'hôte.
FROM node:22-alpine AS build
WORKDIR /app

ARG VITE_API_URL=/api
ARG VITE_AUTH_URL=
ARG VITE_DETECTOR_URL=/detector
ARG VITE_REMEDIATION_URL=/remediation
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
