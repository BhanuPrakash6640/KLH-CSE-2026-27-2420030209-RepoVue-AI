# ---- build ----
FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src

# Same-origin by default: nginx below proxies /api to the API service, so the
# browser never needs CORS and no API host is baked into the bundle.
ARG VITE_API_BASE=""
ARG VITE_API_KEY="dev-local-key"
ENV VITE_API_BASE=$VITE_API_BASE VITE_API_KEY=$VITE_API_KEY
RUN npm run build

# ---- serve ----
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD wget -qO- http://localhost/ >/dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
