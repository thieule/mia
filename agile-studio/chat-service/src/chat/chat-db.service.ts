import { Injectable, Logger, OnModuleDestroy, OnModuleInit } from "@nestjs/common";
import { createPool, Pool } from "mysql2/promise";

@Injectable()
export class ChatDbService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(ChatDbService.name);
  private pool!: Pool;

  onModuleInit() {
    const host = (process.env.CHAT_MYSQL_HOST || "127.0.0.1").trim();
    const port = Number(process.env.CHAT_MYSQL_PORT || 3306);
    const user = (process.env.CHAT_MYSQL_USER || "app").trim();
    const password = (process.env.CHAT_MYSQL_PASSWORD || "app").trim();
    const database = (process.env.CHAT_MYSQL_DATABASE || "agile_studio").trim();
    this.pool = createPool({
      host,
      port,
      user,
      password,
      database,
      waitForConnections: true,
      connectionLimit: 10,
      enableKeepAlive: true,
    });
    this.logger.log(`MySQL pool: ${user}@${host}:${port}/${database}`);
  }

  getPool(): Pool {
    return this.pool;
  }

  async onModuleDestroy() {
    await this.pool?.end();
  }
}
