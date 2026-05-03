import { Module } from "@nestjs/common";
import { ChatController } from "./chat.controller";
import { ChatDbService } from "./chat-db.service";
import { ChatGateway } from "./chat.gateway";
import { ChatService } from "./chat.service";

@Module({
  controllers: [ChatController],
  providers: [ChatDbService, ChatService, ChatGateway],
  exports: [ChatService, ChatGateway],
})
export class ChatModule {}
