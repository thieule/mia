import { Type } from "class-transformer";
import { IsIn, IsInt, IsObject, Min } from "class-validator";

export const STORY_CHAT_EVENT_TYPES = [
  "story.comment.created",
  "story.comment.updated",
  "story.comment.deleted",
] as const;

export type StoryChatEventType = (typeof STORY_CHAT_EVENT_TYPES)[number];

/** Hub → chat-service: broadcast realtime payload (no DB row). Socket emits `chat:event`. */
export class StoryEventBroadcastDto {
  @Type(() => Number)
  @IsInt()
  @Min(1)
  projectId!: number;

  @Type(() => Number)
  @IsInt()
  @Min(1)
  storyId!: number;

  @IsIn(STORY_CHAT_EVENT_TYPES)
  eventType!: StoryChatEventType;

  @IsObject()
  payload!: Record<string, unknown>;
}
