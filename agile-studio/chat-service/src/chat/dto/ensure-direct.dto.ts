import { Type } from "class-transformer";
import { IsInt, Min } from "class-validator";

/** Nội bộ: đồng bộ kênh DM sau khi agile_hub thêm member vào project. */
export class EnsureDirectChannelsDto {
  @Type(() => Number)
  @IsInt()
  @Min(1)
  projectId!: number;

  @Type(() => Number)
  @IsInt()
  @Min(1)
  memberId!: number;
}

/** Nội bộ: đồng bộ kênh `general` ngay khi tạo project. */
export class EnsureProjectChannelsDto {
  @Type(() => Number)
  @IsInt()
  @Min(1)
  projectId!: number;
}
