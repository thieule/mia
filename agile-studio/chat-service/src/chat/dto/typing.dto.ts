import { Type } from "class-transformer";
import { IsIn, IsInt, IsNotEmpty, IsOptional, IsString, Min } from "class-validator";
import { ChatTargetKind } from "../chat.types";

export class TypingDto {
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
  senderUserId!: number;

  @IsOptional()
  @IsString()
  senderName?: string;

  @IsOptional()
  isTyping?: boolean;
}
