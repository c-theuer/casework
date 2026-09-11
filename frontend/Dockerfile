FROM node:22-slim AS build

WORKDIR /app

# Vite inlines VITE_* variables into the built JS at build time, not at
# container runtime -- so the deployed backend URL has to be supplied here,
# as a build arg, not as a Cloud Run env var on the running container.
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

# Cloud Run assigns $PORT at runtime; the base image's docker-entrypoint
# renders nginx.conf.template via envsubst before nginx starts, so this only
# needs to be a sane default for `docker run` outside Cloud Run.
ENV PORT=8080
EXPOSE 8080
