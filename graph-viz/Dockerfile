FROM node:20-alpine AS builder
WORKDIR /app

# Dépendances Node
COPY graph-viz/package*.json ./
RUN npm ci

# Code source
COPY graph-viz/ .

# TTL dans /data/ (= ../data relatif à /app, comme en dev local)
COPY data/forest_kg.ttl /data/forest_kg.ttl

RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
