FROM node:24.21.0-bookworm AS base
FROM base AS build

WORKDIR /app
COPY package*.json ./
RUN npm ci

# copy node_modules from the build image
FROM base

WORKDIR /app
RUN chown node:node /app
COPY --from=build --chown=node:node /app/node_modules node_modules
COPY --chown=node:node . /app
USER node

CMD ["npm", "run", "dev"]
