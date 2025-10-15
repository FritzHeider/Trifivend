# ui/Dockerfile
# Multi-stage Node image for Next.js 15
FROM node:22-alpine AS deps
WORKDIR /app
# If you use pnpm or yarn, swap accordingly
COPY ui/package.json ui/package-lock.json* ./ 
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY ui/ ./
# For Next.js telemetry off in CI
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOST=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/node_modules ./node_modules

EXPOSE 3000
CMD ["npm", "start"]
