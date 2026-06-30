# Multi-stage: build the Vite bundle, then serve it with nginx (+ /api proxy, SPA fallback).
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
# --legacy-peer-deps: a few unused Figma-default deps (react-popper, react-slick, …) still
# declare a React 18 peer; we run React 19, so skip strict peer resolution for them.
RUN npm install --no-audit --no-fund --legacy-peer-deps
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
