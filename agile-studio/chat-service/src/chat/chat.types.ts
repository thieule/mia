export type ChatTargetKind = "project_channel" | "private_user";
export type ChatReactionType = "seen" | "like" | "love" | "doing" | "wow" | "angry" | "happy";

export interface ChatReactionStat {
  type: ChatReactionType;
  count: number;
  mine: boolean;
}

export interface ChatMessage {
  id: string;
  projectId: number;
  channelId: string;
  targetKind: ChatTargetKind;
  senderUserId: number;
  senderName?: string;
  content: string;
  createdAt: string;
  reactions: ChatReactionStat[];
}
