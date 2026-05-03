import { Type } from "class-transformer";
import { Allow, IsIn, IsInt, IsNotEmpty, IsOptional, IsString, Min, ValidateIf } from "class-validator";
import { ChatTargetKind } from "../chat.types";

export class ChannelQueryDto {
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

  /** Member đang xem chat (bắt buộc với private_user để ghép đúng kênh DM hai chiều). */
  @Allow()
  @ValidateIf((o) => o.targetKind === "private_user")
  @Type(() => Number)
  @IsInt()
  @Min(1)
  viewerMemberId?: number;
}
