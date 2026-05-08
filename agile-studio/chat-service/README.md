# Agile Studio Chat Service (NestJS)

Service chat tách riêng dùng **NestJS + Socket.IO**.

## Run local

```bash
cd agile-studio/chat-service
npm install
npm run start:dev
```

Mặc định chạy ở `http://localhost:9130`.

## Channel ID convention

- Channel chung theo project: `projectId_channelName`
  - Ví dụ: `10_general`
- Channel private theo user trong project: `projectId_userId`
  - Ví dụ: `10_25`
- **Room ảo** (không có bản ghi `chat_channels`): comment story — `{projectId}_story_{storyId}`  
  - Web client `chat:join` / `chat:leave` giống channel thường.
  - Hub gọi nội bộ `POST /api/chat/internal/story-events/broadcast` để push `chat:event`.

## REST API

### Send message

`POST /api/chat/messages`

Body mẫu (project channel):

```json
{
  "projectId": 10,
  "targetKind": "project_channel",
  "channelName": "general",
  "senderUserId": 5,
  "senderName": "ThieuLe",
  "content": "hello channel"
}
```

Body mẫu (private user):

```json
{
  "projectId": 10,
  "targetKind": "private_user",
  "userId": 25,
  "senderUserId": 5,
  "senderName": "ThieuLe",
  "content": "hello private"
}
```

### List messages

`GET /api/chat/messages?projectId=10&targetKind=project_channel&channelName=general`

Hoặc:

`GET /api/chat/messages?projectId=10&targetKind=private_user&userId=25`

### Story activity broadcast (internal, Hub → chat-service)

`POST /api/chat/internal/story-events/broadcast`

```json
{
  "projectId": 1,
  "storyId": 2,
  "eventType": "story.comment.created",
  "payload": { "comment": { } }
}
```

`eventType`: `story.comment.created` | `story.comment.updated` | `story.comment.deleted`  
(`deleted` dùng `payload.comment_id`.)

### Wiki doc feedback broadcast (internal)

`POST /api/chat/internal/wiki-doc-events/broadcast`

```json
{
  "projectId": 1,
  "docId": "uuid-doc",
  "eventType": "wiki.comment.created",
  "payload": { "comment": {} }
}
```

`eventType`: `wiki.comment.created` | `wiki.comment.updated` | `wiki.comment.deleted` (`deleted`: `payload.comment_id`).

Client join room `{projectId}_wiki_doc_{docId}` (virtual, `chat:join`).

## WebSocket (Socket.IO)

Namespace: `/ws/chat`

Events:

- `chat:join` `{ "channelId": "10_general" }`
- `chat:leave` `{ "channelId": "10_general" }`
- `chat:send` (body như REST send message)
- server push:
  - `chat:message` (message payload)
  - `chat:event` — envelope realtime không lưu DB, luôn có `type: "event"`:
    - Story: `eventType` `story.comment.*`; `projectId`, `storyId`, `payload`
    - Wiki doc: `eventType` `wiki.comment.*`; `projectId`, `docId`, `payload`
  - `chat:joined`, `chat:left`, `chat:sent`, `chat:error`

Mỗi room tương ứng **1 channel** hoặc room ảo story như trên.
