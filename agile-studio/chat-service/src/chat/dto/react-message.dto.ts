import { Type } from "class-transformer";
import { IsIn, IsInt, IsNotEmpty, IsOptional, IsString, Min } from "class-validator";
import { ChatReactionType, ChatTargetKind } from "../chat.types";

export class ReactMessageDto {
  @Type(() => Number)
  @IsInt()
  @Min(1)
  projectId!: number;

  @IsIn(["project_channel", "private_user"])
  targetKind!: ChatTargetKind;

  @IsOptional()
  @IsString()
  @IsNotEmpty()
  channelName?: string;

  @Type(() => Number)
  @IsOptional()
  @IsInt()
  @Min(1)
  userId?: number;

  @Type(() => Number)
  @IsInt()
  @Min(1)
  actorUserId!: number;

  @IsIn(["seen", "like", "love", "doing", "wow", "angry", "happy"])
  reaction!: ChatReactionType;

  @IsOptional()
  @IsIn(["toggle", "add", "remove"])
  action?: "toggle" | "add" | "remove";
}
