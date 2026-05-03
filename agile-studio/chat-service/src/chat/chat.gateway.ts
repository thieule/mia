import {
  ConnectedSocket,
  MessageBody,
  OnGatewayConnection,
  OnGatewayDisconnect,
  SubscribeMessage,
  WebSocketGateway,
  WebSocketServer,
} from "@nestjs/websockets";
import { Server, Socket } from "socket.io";
import { SendMessageDto } from "./dto/send-message.dto";
import { ChatService } from "./chat.service";

@WebSocketGateway({
  namespace: "/ws/chat",
  cors: {
    origin: "*",
  },
})
export class ChatGateway implements OnGatewayConnection, OnGatewayDisconnect {
  @WebSocketServer()
  server!: Server;

  constructor(private readonly chatService: ChatService) {}

  handleConnection(client: Socket) {
    client.emit("chat:connected", { socketId: client.id });
  }

  handleDisconnect(_client: Socket) {}

  @SubscribeMessage("chat:join")
  handleJoin(
    @ConnectedSocket() client: Socket,
    @MessageBody() body: { channelId: string }
  ) {
    const channelId = (body?.channelId || "").trim();
    if (!channelId) {
      client.emit("chat:error", { message: "channelId is required" });
      return;
    }
    client.join(channelId);
    client.emit("chat:joined", { channelId });
  }

  @SubscribeMessage("chat:leave")
  handleLeave(
    @ConnectedSocket() client: Socket,
    @MessageBody() body: { channelId: string }
  ) {
    const channelId = (body?.channelId || "").trim();
    if (!channelId) {
      client.emit("chat:error", { message: "channelId is required" });
      return;
    }
    client.leave(channelId);
    client.emit("chat:left", { channelId });
  }

  @SubscribeMessage("chat:send")
  async handleSend(@ConnectedSocket() client: Socket, @MessageBody() body: SendMessageDto) {
    try {
      const msg = await this.chatService.sendMessage(body);
      this.broadcastToChannel(msg.channelId, msg);
      client.emit("chat:sent", { id: msg.id, channelId: msg.channelId });
    } catch (err) {
      const message = err instanceof Error ? err.message : "send failed";
      client.emit("chat:error", { message });
    }
  }

  @SubscribeMessage("chat:typing")
  handleTyping(
    @ConnectedSocket() client: Socket,
    @MessageBody() body: { channelId: string; senderUserId: number; senderName?: string; isTyping?: boolean }
  ) {
    const channelId = (body?.channelId || "").trim();
    const senderUserId = Number(body?.senderUserId || 0);
    if (!channelId || senderUserId <= 0) return;
    client.to(channelId).emit("chat:typing", {
      channelId,
      senderUserId,
      senderName: (body?.senderName || "").trim() || undefined,
      isTyping: body?.isTyping !== false,
    });
  }

  broadcastToChannel(channelId: string, payload: unknown) {
    this.server.to(channelId).emit("chat:message", payload);
  }

  /** Virtual room per story (not a chat channel row): `{projectId}_story_{storyId}` */
  static storyCommentsRoomId(projectId: number, storyId: number): string {
    return `${projectId}_story_${storyId}`;
  }

  /** Push structured activity (comments, …) — envelope uses `type: "event"` vs chat messages. */
  broadcastStoryEvent(projectId: number, storyId: number, envelope: Record<string, unknown>) {
    const room = ChatGateway.storyCommentsRoomId(projectId, storyId);
    this.server.to(room).emit("chat:event", envelope);
  }

  emitMessageDeleted(channelId: string, messageId: string) {
    this.server.to(channelId).emit("chat:messageDeleted", { channelId, id: messageId });
  }

  emitMessageReaction(channelId: string, messageId: string, reactions: unknown) {
    this.server.to(channelId).emit("chat:messageReaction", { channelId, id: messageId, reactions });
  }

  emitTyping(channelId: string, senderUserId: number, senderName?: string, isTyping: boolean = true) {
    this.server.to(channelId).emit("chat:typing", {
      channelId,
      senderUserId,
      senderName: (senderName || "").trim() || undefined,
      isTyping,
    });
  }
}
