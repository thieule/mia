import { Type } from "class-transformer";
import { IsIn, IsInt, IsObject, IsString, Min, MinLength } from "class-validator";

export const WIKI_DOC_CHAT_EVENT_TYPES = [
  "wiki.comment.created",
  "wiki.comment.updated",
  "wiki.comment.deleted",
] as const;

export type WikiDocChatEventType = (typeof WIKI_DOC_CHAT_EVENT_TYPES)[number];

/** Hub → chat-service: realtime wiki feedback trong room `{projectId}_wiki_doc_{docId}`. */
export class WikiDocEventBroadcastDto {
  @Type(() => Number)
  @IsInt()
  @Min(1)
  projectId!: number;

  @IsString()
  @MinLength(1)
  docId!: string;

  @IsIn(WIKI_DOC_CHAT_EVENT_TYPES)
  eventType!: WikiDocChatEventType;

  @IsObject()
  payload!: Record<string, unknown>;
}
