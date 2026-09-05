# Build context is the repo root (the SPA imports ../*.md docs at build time).
FROM node:20-alpine AS build
WORKDIR /app
COPY frontend-react/package.json frontend-react/package-lock.json ./frontend/
RUN cd frontend && npm ci
COPY frontend-react/ ./frontend/
COPY README.md ARCHITECTURE.md TICKER_STATS.md API.md ./
COPY Model/README.md ./Model/README.md
RUN cd frontend && npm run build

FROM nginx:alpine
COPY frontend-react/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
