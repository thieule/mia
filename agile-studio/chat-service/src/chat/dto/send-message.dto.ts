import { IsIn, IsInt, IsNotEmpty, IsOptional, IsString, MaxLength, Min } from "class-validator";
import { ChatTargetKind } from "../chat.types";
import { Type } from "class-transformer";

export class SendMessageDto {
  @Type(() => Number)
  @IsInt()
  @Min(1)
  projectId!: number;

  @IsIn(["project_channel", "private_user"])
  targetKind!: ChatTargetKind;

  @IsOptional()
  @IsString()
  @IsNotEmpty()
  @MaxLength(80)
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
  @MaxLength(120)
  senderName?: string;

  @IsString()
  @IsNotEmpty()
  @MaxLength(4000)
  content!: string;
}
