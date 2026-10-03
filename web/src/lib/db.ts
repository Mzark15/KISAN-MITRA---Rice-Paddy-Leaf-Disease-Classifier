/**
 * On-device storage for chats and photos (IndexedDB via Dexie).
 *
 * One database per logged-in farmer, so two people sharing a phone never see
 * each other's chats. Everything here works offline; syncing to AWS can be
 * added later on top of the same tables.
 */
import Dexie, { type Table } from "dexie";
import type { Diagnosis, DiagnosisContext } from "./api";

export interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  /** Latest photo result in this chat; sent with every question so advice stays specific. */
  diagnosisContext?: DiagnosisContext | null;
}

export type MessageStatus = "done" | "pending" | "error";

export interface Message {
  id: string;
  conversationId: string;
  role: "user" | "assistant";
  createdAt: number;
  status: MessageStatus;
  text?: string;
  imageIds?: string[];
  diagnosis?: Diagnosis;
  /** What the pending/error assistant message is for: a photo check or a chat reply. */
  kind?: "chat" | "diagnosis";
  /** Assistant messages: the user message they answer (used to retry). */
  replyTo?: string;
  /** Photo-check messages: which photo was checked. */
  imageId?: string;
  errorCode?: string;
  feedback?: boolean;
  viaVoice?: boolean;
}

export interface StoredImage {
  id: string;
  blob: Blob;
  createdAt: number;
}

export class KisanDB extends Dexie {
  conversations!: Table<Conversation, string>;
  messages!: Table<Message, string>;
  images!: Table<StoredImage, string>;

  constructor(name: string) {
    super(name);
    this.version(1).stores({
      conversations: "id, updatedAt",
      messages: "id, conversationId, [conversationId+createdAt]",
      images: "id",
    });
  }
}

let db: KisanDB | null = null;

export function dbName(userId: string): string {
  return `kisan-mitra-${userId}`;
}

export function openDb(userId: string): KisanDB {
  if (db?.name !== dbName(userId)) {
    db?.close();
    db = new KisanDB(dbName(userId));
  }
  return db;
}

export function getDb(): KisanDB {
  if (!db) throw new Error("Database not open");
  return db;
}

export async function deleteUserDb(userId: string): Promise<void> {
  if (db?.name === dbName(userId)) {
    db.close();
    db = null;
  }
  await Dexie.delete(dbName(userId));
}

export function newId(): string {
  // randomUUID needs a secure context; plain-http LAN testing in a browser isn't one.
  if (crypto.randomUUID) return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, "0")).join("");
}

/** Ask the browser not to evict our data under storage pressure (web only; the app's storage is private). */
export function requestPersistentStorage(): void {
  navigator.storage?.persist?.().catch(() => {});
}
