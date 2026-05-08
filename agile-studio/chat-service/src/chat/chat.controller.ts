import { BadRequestException, Body, Controller, Delete, Get, Param, Post, Query } from "@nestjs/common";
import { ChatGateway } from "./chat.gateway";
import { ChannelQueryDto } from "./dto/channel-query.dto";
import { DeleteMessageQueryDto } from "./dto/delete-message-query.dto";
import { EnsureDirectChannelsDto, EnsureProjectChannelsDto } from "./dto/ensure-direct.dto";
import { ReactMessageDto } from "./dto/react-message.dto";
import { StoryEventBroadcastDto } from "./dto/story-event-broadcast.dto";
import { WikiDocEventBroadcastDto } from "./dto/wiki-doc-event-broadcast.dto";
import { SendMessageDto } from "./dto/send-message.dto";
import { TypingDto } from "./dto/typing.dto";
import { ChatService } from "./chat.service";

@Controller("chat")
export class ChatController {
  constructor(
    private readonly chatService: ChatService,
    private readonly chatGateway: ChatGateway
  ) {}

  @Post("messages")
  async sendMessage(@Body() body: SendMessageDto) {
    const msg = await this.chatService.sendMessage(body);
    this.chatGateway.broadcastToChannel(msg.channelId, msg);
    return msg;
  }

  @Post("typing")
  async typing(@Body() body: TypingDto) {
    const channelId = this.chatService.resolveChannelId(body);
    this.chatGateway.emitTyping(channelId, body.senderUserId, body.senderName, body.isTyping !== false);
    return { ok: true, channelId };
  }

  @Get("channels")
  async listChannels(@Query("projectId") projectIdRaw: string) {
    const projectId = Number(projectIdRaw);
    if (!Number.isFinite(projectId) || projectId < 1) {
      throw new BadRequestException("projectId is required and must be a positive integer");
    }
    return { projectId, channels: await this.chatService.listChannelsByProject(projectId) };
  }

  @Get("messages")
  async listMessages(@Query() query: ChannelQueryDto) {
    const channelId = this.chatService.resolveChannelIdFromQuery(query);
    const messages = await this.chatService.listMessages(query);
    return {
      channelId,
      messages,
    };
  }

  @Delete("messages/:messageId")
  async deleteMessage(@Param("messageId") messageId: string, @Query() query: DeleteMessageQueryDto) {
    const channelId = await this.chatService.deleteMessage(messageId, query);
    this.chatGateway.emitMessageDeleted(channelId, messageId);
    return { ok: true, channelId, id: messageId };
  }

  @Post("messages/:messageId/reactions")
  async reactMessage(@Param("messageId") messageId: string, @Body() body: ReactMessageDto) {
    const result = await this.chatService.reactMessage(messageId, body);
    this.chatGateway.emitMessageReaction(result.channelId, result.messageId, result.reactions);
    return { ok: true, ...result };
  }

  /** Nội bộ (agile_hub): đồng bộ kênh chat sau khi thêm member vào project. */
  @Post("internal/channels/ensure-after-member-added")
  async ensureAfterMemberAdded(@Body() body: EnsureDirectChannelsDto) {
    return this.chatService.ensureChannelsAfterMemberAdded(body.projectId, body.memberId);
  }

  /** Nội bộ (agile_hub/mcp): đồng bộ kênh general ngay khi tạo project. */
  @Post("internal/channels/ensure-after-project-created")
  async ensureAfterProjectCreated(@Body() body: EnsureProjectChannelsDto) {
    return this.chatService.ensureChannelsAfterProjectCreated(body.projectId);
  }

  /** Nội bộ (agile_hub): đồng bộ comment story realtime — không ghi `chat_messages`. */
  @Post("internal/story-events/broadcast")
  async broadcastStoryEvent(@Body() body: StoryEventBroadcastDto) {
    this.chatGateway.broadcastStoryEvent(body.projectId, body.storyId, {
      type: "event",
      eventType: body.eventType,
      projectId: body.projectId,
      storyId: body.storyId,
      payload: body.payload,
    });
    return { ok: true };
  }

  @Post("internal/wiki-doc-events/broadcast")
  async broadcastWikiDocEvent(@Body() body: WikiDocEventBroadcastDto) {
    const docId = (body.docId || "").trim();
    this.chatGateway.broadcastWikiDocEvent(body.projectId, docId, {
      type: "event",
      eventType: body.eventType,
      projectId: body.projectId,
      docId,
      payload: body.payload,
    });
    return { ok: true };
  }
}
