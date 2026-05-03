FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY tsconfig.json tsconfig.build.json nest-cli.json ./
COPY src ./src

RUN npm run build

ENV CHAT_SERVICE_PORT=9130
EXPOSE 9130

CMD ["npm", "run", "start:prod"]
