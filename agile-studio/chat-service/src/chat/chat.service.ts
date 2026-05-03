import { BadRequestException, ForbiddenException, Injectable, NotFoundException } from "@nestjs/common";
import { RowDataPacket, ResultSetHeader } from "mysql2/promise";
import { ChatDbService } from "./chat-db.service";
import { ChannelQueryDto } from "./dto/channel-query.dto";
import { DeleteMessageQueryDto } from "./dto/delete-message-query.dto";
import { ReactMessageDto } from "./dto/react-message.dto";
import { SendMessageDto } from "./dto/send-message.dto";
import { ChatMessage, ChatReactionStat, ChatReactionType } from "./chat.types";

const MAX_MESSAGES_PER_FETCH = 200;
const REACTION_TYPES: ChatReactionType[] = ["seen", "like", "love", "doing", "wow", "angry", "happy"];

type ChannelKeyInput = {
  projectId: number;
  targetKind: "project_channel" | "private_user";
  channelName?: string;
  /** Peer member id for private_user (the other person in DM). */
  userId?: number;
  /** Current member id for private_user (list/delete). */
  viewerMemberId?: number;
  /** Sender = current member for private_user (send). */
  senderUserId?: number;
};

@Injectable()
export class ChatService {
  constructor(private readonly chatDb: ChatDbService) {}

  /**
   * Room id dùng cho socket/API: `{pid}_general` hoặc `{pid}_dm_{min}_{max}`.
   */
  resolveChannelKey(input: ChannelKeyInput): string {
    if (input.targetKind === "project_channel") {
      const channelName = (input.channelName || "").trim();
      if (!channelName) {
        throw new BadRequestException("channelName is required when targetKind=project_channel");
      }
      return `${input.projectId}_${channelName}`;
    }
    const peer = Number(input.userId);
    if (!peer || peer <= 0) {
      throw new BadRequestException("userId (peer) is required when targetKind=private_user");
    }
    const viewer = Number(input.viewerMemberId ?? input.senderUserId ?? 0);
    if (!viewer || viewer <= 0) {
      throw new BadRequestException("viewerMemberId (or senderUserId when sending) is required when targetKind=private_user");
    }
    const lo = Math.min(peer, viewer);
    const hi = Math.max(peer, viewer);
    return `${input.projectId}_dm_${lo}_${hi}`;
  }

  resolveChannelId(
    dto: Pick<SendMessageDto, "projectId" | "targetKind" | "channelName" | "userId" | "senderUserId">
  ): string {
    return this.resolveChannelKey({
      projectId: dto.projectId,
      targetKind: dto.targetKind,
      channelName: dto.channelName,
      userId: dto.userId,
      senderUserId: dto.senderUserId,
    });
  }

  resolveChannelIdFromQuery(dto: ChannelQueryDto | DeleteMessageQueryDto): string {
    const listDto = dto as ChannelQueryDto;
    const viewerFromDelete = "senderUserId" in dto ? (dto as DeleteMessageQueryDto).senderUserId : undefined;
    const viewer = listDto.viewerMemberId ?? viewerFromDelete;
    return this.resolveChannelKey({
      projectId: dto.projectId,
      targetKind: dto.targetKind,
      channelName: dto.channelName,
      userId: dto.userId,
      viewerMemberId: viewer,
    });
  }

  private async getChannelIdByKey(channelKey: string): Promise<number | null> {
    const pool = this.chatDb.getPool();
    const [rows] = await pool.execute<RowDataPacket[]>(
      "SELECT id FROM chat_channels WHERE channel_key = ? LIMIT 1",
      [channelKey]
    );
    const id = rows[0]?.id;
    return id != null ? Number(id) : null;
  }

  /**
   * Đảm bảo có dòng channel (khi thiếu trigger / dữ liệu cũ).
   */
  private async ensureChannelRow(channelKey: string, input: ChannelKeyInput): Promise<number> {
    const pool = this.chatDb.getPool();
    let id = await this.getChannelIdByKey(channelKey);
    if (id != null) return id;

    if (input.targetKind === "project_channel") {
      const name = (input.channelName || "").trim();
      await pool.execute(
        `INSERT IGNORE INTO chat_channels (project_id, kind, channel_name, member_low_id, member_high_id, channel_key)
         VALUES (?, 'project_channel', ?, NULL, NULL, ?)`,
        [input.projectId, name, channelKey]
      );
    } else {
      const peer = Number(input.userId);
      const viewer = Number(input.viewerMemberId ?? input.senderUserId ?? 0);
      const lo = Math.min(peer, viewer);
      const hi = Math.max(peer, viewer);
      await pool.execute(
        `INSERT IGNORE INTO chat_channels (project_id, kind, channel_name, member_low_id, member_high_id, channel_key)
         VALUES (?, 'direct', NULL, ?, ?, ?)`,
        [input.projectId, lo, hi, channelKey]
      );
    }
    id = await this.getChannelIdByKey(channelKey);
    if (id == null) {
      throw new BadRequestException("Could not resolve chat channel");
    }
    return id;
  }

  async listChannelsByProject(projectId: number): Promise<
    {
      id: number;
      kind: string;
      channelName: string | null;
      memberLowId: number | null;
      memberHighId: number | null;
      channelKey: string;
      createdAt: string;
    }[]
  > {
    const pool = this.chatDb.getPool();
    const [rows] = await pool.execute<RowDataPacket[]>(
      `SELECT id, kind, channel_name, member_low_id, member_high_id, channel_key, created_at
       FROM chat_channels
       WHERE project_id = ?
       ORDER BY kind ASC, channel_key ASC`,
      [projectId]
    );
    return rows.map((r) => ({
      id: Number(r.id),
      kind: String(r.kind),
      channelName: r.channel_name != null ? String(r.channel_name) : null,
      memberLowId: r.member_low_id != null ? Number(r.member_low_id) : null,
      memberHighId: r.member_high_id != null ? Number(r.member_high_id) : null,
      channelKey: String(r.channel_key),
      createdAt: r.created_at instanceof Date ? r.created_at.toISOString() : String(r.created_at),
    }));
  }

  private rowToMessage(
    row: RowDataPacket,
    channelKey: string,
    targetKind: "project_channel" | "private_user",
    projectId: number
  ): ChatMessage {
    return {
      id: String(row.id),
      projectId,
      channelId: channelKey,
      targetKind,
      senderUserId: Number(row.sender_member_id),
      senderName: row.sender_name ? String(row.sender_name) : undefined,
      content: String(row.content),
      createdAt: row.created_at instanceof Date ? row.created_at.toISOString() : String(row.created_at),
      reactions: [],
    };
  }

  private emptyReactionStats(): ChatReactionStat[] {
    return REACTION_TYPES.map((type) => ({ type, count: 0, mine: false }));
  }

  private async loadReactionStats(messageIds: number[], actorUserId?: number): Promise<Map<number, ChatReactionStat[]>> {
    const out = new Map<number, ChatReactionStat[]>();
    if (!messageIds.length) return out;
    const pool = this.chatDb.getPool();
    const actorId = Number(actorUserId || 0);
    const placeholders = messageIds.map(() => "?").join(",");
    const [rows] = await pool.execute<RowDataPacket[]>(
      `SELECT message_id, reaction_type, COUNT(*) AS total,
              SUM(CASE WHEN member_id = ? THEN 1 ELSE 0 END) AS mine_total
       FROM chat_message_reactions
       WHERE message_id IN (${placeholders})
       GROUP BY message_id, reaction_type`,
      [actorId > 0 ? actorId : -1, ...messageIds]
    );
    for (const id of messageIds) {
      out.set(id, this.emptyReactionStats());
    }
    for (const r of rows) {
      const mid = Number(r.message_id);
      const rt = String(r.reaction_type) as ChatReactionType;
      if (!REACTION_TYPES.includes(rt)) continue;
      const list = out.get(mid) || this.emptyReactionStats();
      const idx = list.findIndex((x) => x.type === rt);
      if (idx >= 0) {
        list[idx] = {
          type: rt,
          count: Number(r.total || 0),
          mine: Number(r.mine_total || 0) > 0,
        };
      }
      out.set(mid, list);
    }
    return out;
  }

  private async applySeenForViewer(messageIds: number[], viewerMemberId?: number): Promise<void> {
    const viewer = Number(viewerMemberId || 0);
    if (!messageIds.length || viewer <= 0) return;
    const pool = this.chatDb.getPool();
    await pool.query(
      `INSERT IGNORE INTO chat_message_reactions (message_id, member_id, reaction_type)
       VALUES ?`,
      [messageIds.map((id) => [id, viewer, "seen"])]
    );
  }

  async listMessages(query: ChannelQueryDto): Promise<ChatMessage[]> {
    const channelKey = this.resolveChannelIdFromQuery(query);
    const pool = this.chatDb.getPool();
    const channelId = await this.getChannelIdByKey(channelKey);
    if (channelId == null) return [];

    // Không bind LIMIT bằng ? — MySQL/mysqld_stmt_execute hay báo "Incorrect arguments"
    // khi placeholder ở LIMIT (MySQL 8 + mysql2/prepared statements).
    const [rows] = await pool.execute<RowDataPacket[]>(
      `SELECT id, sender_member_id, sender_name, content, created_at
       FROM chat_messages
       WHERE channel_id = ?
       ORDER BY id DESC
       LIMIT ${MAX_MESSAGES_PER_FETCH}`,
      [channelId]
    );
    const viewerId = Number(query.viewerMemberId || 0);
    const messageIds = rows.map((x) => Number(x.id)).filter((x) => Number.isFinite(x) && x > 0);
    const seenCandidateIds = rows
      .filter((x) => Number(x.sender_member_id) !== viewerId)
      .map((x) => Number(x.id))
      .filter((x) => Number.isFinite(x) && x > 0);
    // Auto-seen on fetch for viewers (excluding own messages).
    await this.applySeenForViewer(seenCandidateIds, query.viewerMemberId);
    const reactionMap = await this.loadReactionStats(messageIds, query.viewerMemberId);
    const asc = [...rows].reverse();
    return asc.map((r) => {
      const msg = this.rowToMessage(r, channelKey, query.targetKind, query.projectId);
      msg.reactions = reactionMap.get(Number(r.id)) || this.emptyReactionStats();
      return msg;
    });
  }

  async sendMessage(body: SendMessageDto): Promise<ChatMessage> {
    const channelKey = this.resolveChannelId(body);
    const input: ChannelKeyInput = {
      projectId: body.projectId,
      targetKind: body.targetKind,
      channelName: body.channelName,
      userId: body.userId,
      senderUserId: body.senderUserId,
    };
    const channelId = await this.ensureChannelRow(channelKey, input);
    const pool = this.chatDb.getPool();
    const senderName = (body.senderName || "").trim() || null;
    const [result] = await pool.execute<ResultSetHeader>(
      `INSERT INTO chat_messages (channel_id, sender_member_id, sender_name, content)
       VALUES (?, ?, ?, ?)`,
      [channelId, body.senderUserId, senderName, body.content.trim()]
    );
    const id = result.insertId;
    const [rows] = await pool.execute<RowDataPacket[]>(
      "SELECT id, sender_member_id, sender_name, content, created_at FROM chat_messages WHERE id = ? LIMIT 1",
      [id]
    );
    const row = rows[0];
    if (!row) {
      throw new BadRequestException("Message insert failed");
    }
    return this.rowToMessage(row, channelKey, body.targetKind, body.projectId);
  }

  async reactMessage(
    messageId: string,
    body: ReactMessageDto
  ): Promise<{ channelId: string; messageId: string; reactions: ChatReactionStat[] }> {
    const channelKey = this.resolveChannelKey({
      projectId: body.projectId,
      targetKind: body.targetKind,
      channelName: body.channelName,
      userId: body.userId,
      senderUserId: body.actorUserId,
    });
    const pool = this.chatDb.getPool();
    const channelId = await this.getChannelIdByKey(channelKey);
    if (channelId == null) throw new NotFoundException("Message not found");
    const mid = Number(messageId);
    if (!Number.isFinite(mid) || mid <= 0) throw new NotFoundException("Message not found");
    const [msgRows] = await pool.execute<RowDataPacket[]>(
      `SELECT id, sender_member_id FROM chat_messages WHERE id = ? AND channel_id = ? LIMIT 1`,
      [mid, channelId]
    );
    const msg = msgRows[0];
    if (!msg) throw new NotFoundException("Message not found");
    if (Number(msg.sender_member_id) === Number(body.actorUserId)) {
      throw new ForbiddenException("You cannot react to your own message");
    }
    const action = body.action || "toggle";
    if (action === "add") {
      await pool.execute(
        `INSERT IGNORE INTO chat_message_reactions (message_id, member_id, reaction_type) VALUES (?, ?, ?)`,
        [mid, body.actorUserId, body.reaction]
      );
    } else if (action === "remove") {
      await pool.execute(
        `DELETE FROM chat_message_reactions WHERE message_id = ? AND member_id = ? AND reaction_type = ?`,
        [mid, body.actorUserId, body.reaction]
      );
    } else {
      const [rows] = await pool.execute<RowDataPacket[]>(
        `SELECT 1 FROM chat_message_reactions WHERE message_id = ? AND member_id = ? AND reaction_type = ? LIMIT 1`,
        [mid, body.actorUserId, body.reaction]
      );
      if (rows[0]) {
        await pool.execute(
          `DELETE FROM chat_message_reactions WHERE message_id = ? AND member_id = ? AND reaction_type = ?`,
          [mid, body.actorUserId, body.reaction]
        );
      } else {
        await pool.execute(
          `INSERT IGNORE INTO chat_message_reactions (message_id, member_id, reaction_type) VALUES (?, ?, ?)`,
          [mid, body.actorUserId, body.reaction]
        );
      }
    }
    const stats = (await this.loadReactionStats([mid], body.actorUserId)).get(mid) || this.emptyReactionStats();
    return { channelId: channelKey, messageId: String(mid), reactions: stats };
  }

  async deleteMessage(messageId: string, query: DeleteMessageQueryDto): Promise<string> {
    const channelKey = this.resolveChannelIdFromQuery(query);
    const pool = this.chatDb.getPool();
    const channelId = await this.getChannelIdByKey(channelKey);
    if (channelId == null) {
      throw new NotFoundException("Message not found");
    }
    const mid = Number(messageId);
    if (!Number.isFinite(mid) || mid <= 0) {
      throw new NotFoundException("Message not found");
    }
    const [rows] = await pool.execute<RowDataPacket[]>(
      `SELECT id, sender_member_id FROM chat_messages WHERE id = ? AND channel_id = ? LIMIT 1`,
      [mid, channelId]
    );
    const row = rows[0];
    if (!row) {
      throw new NotFoundException("Message not found");
    }
    if (Number(row.sender_member_id) !== Number(query.senderUserId)) {
      throw new ForbiddenException("You can only delete your own messages");
    }
    await pool.execute("DELETE FROM chat_message_reactions WHERE message_id = ?", [mid]);
    await pool.execute("DELETE FROM chat_messages WHERE id = ? AND channel_id = ?", [mid, channelId]);
    return channelKey;
  }

  /**
   * Nội bộ: sau khi agile_hub thêm member — tạo kênh `general` (nếu thiếu) và mọi kênh DM với member khác.
   * Đọc `project_members` trên cùng DB; `INSERT IGNORE` idempotent với trigger MySQL.
   */
  async ensureChannelsAfterMemberAdded(projectId: number, memberId: number): Promise<{
    projectId: number;
    memberId: number;
    generalEnsured: boolean;
    directChannelsUpserted: number;
  }> {
    const pool = this.chatDb.getPool();
    const [g] = await pool.execute<ResultSetHeader>(
      `INSERT IGNORE INTO chat_channels (project_id, kind, channel_name, member_low_id, member_high_id, channel_key)
       VALUES (?, 'project_channel', 'general', NULL, NULL, ?)`,
      [projectId, `${projectId}_general`]
    );
    const generalEnsured = (g.affectedRows ?? 0) > 0;

    const [others] = await pool.execute<RowDataPacket[]>(
      `SELECT member_id FROM project_members WHERE project_id = ? AND member_id <> ?`,
      [projectId, memberId]
    );
    let directChannelsUpserted = 0;
    for (const row of others) {
      const oid = Number(row.member_id);
      if (!Number.isFinite(oid) || oid <= 0) continue;
      const lo = Math.min(memberId, oid);
      const hi = Math.max(memberId, oid);
      const channelKey = `${projectId}_dm_${lo}_${hi}`;
      const [r] = await pool.execute<ResultSetHeader>(
        `INSERT IGNORE INTO chat_channels (project_id, kind, channel_name, member_low_id, member_high_id, channel_key)
         VALUES (?, 'direct', NULL, ?, ?, ?)`,
        [projectId, lo, hi, channelKey]
      );
      directChannelsUpserted += r.affectedRows ?? 0;
    }
    return { projectId, memberId, generalEnsured, directChannelsUpserted };
  }

  /** Nội bộ: tạo channel `general` cho project (idempotent). */
  async ensureChannelsAfterProjectCreated(projectId: number): Promise<{
    projectId: number;
    generalEnsured: boolean;
  }> {
    const pool = this.chatDb.getPool();
    const [r] = await pool.execute<ResultSetHeader>(
      `INSERT IGNORE INTO chat_channels (project_id, kind, channel_name, member_low_id, member_high_id, channel_key)
       VALUES (?, 'project_channel', 'general', NULL, NULL, ?)`,
      [projectId, `${projectId}_general`]
    );
    return { projectId, generalEnsured: (r.affectedRows ?? 0) > 0 };
  }
}
