/**
 * Chat flow: everything is written to the on-device database first, then the
 * server is called and the pending message is filled in. The UI just renders
 * the database (live queries), so it survives app restarts mid-request.
 */
import { ApiError, SessionExpiredError, currentSession } from "./auth";
import { chat, contextFrom, diagnose, type ChatTurn } from "./api";
import { getDb, newId, type Message } from "./db";
import { getLang, t, type StringKey } from "./i18n";
import { speak } from "./voice";

const MAX_HISTORY = 12;

export interface Outgoing {
  conversationId: string | null;
  text: string;
  photos: Blob[];
  viaVoice?: boolean;
}

/** Send a message (text and/or photos). Returns the conversation id (new chats get one). */
export async function sendMessage(out: Outgoing): Promise<string> {
  const db = getDb();
  const now = Date.now();
  const text = out.text.trim();

  let conversationId = out.conversationId;
  if (!conversationId) {
    conversationId = newId();
    await db.conversations.add({
      id: conversationId,
      title: text ? text.slice(0, 60) : t("photoCheck"),
      createdAt: now,
      updatedAt: now,
    });
  }

  const imageIds: string[] = [];
  for (const blob of out.photos) {
    const id = newId();
    await db.images.add({ id, blob, createdAt: now });
    imageIds.push(id);
  }

  const userMessage: Message = {
    id: newId(),
    conversationId,
    role: "user",
    createdAt: now,
    status: "done",
    ...(text ? { text } : {}),
    ...(imageIds.length ? { imageIds } : {}),
    ...(out.viaVoice ? { viaVoice: true } : {}),
  };
  await db.messages.add(userMessage);
  await db.conversations.update(conversationId, { updatedAt: now });

  // Photo checks first, so a question sent with the photo is answered with its result.
  for (const imageId of imageIds) {
    await runDiagnosis(await addPending(conversationId, userMessage.id, "diagnosis", imageId));
  }
  if (text) await runChat(await addPending(conversationId, userMessage.id, "chat"));
  return conversationId;
}

/** Retry a failed assistant message. */
export async function retry(message: Message): Promise<void> {
  await getDb().messages.update(message.id, { status: "pending", errorCode: undefined });
  const fresh = (await getDb().messages.get(message.id))!;
  if (fresh.kind === "diagnosis") await runDiagnosis(fresh);
  else await runChat(fresh);
}

async function addPending(
  conversationId: string, replyTo: string, kind: "chat" | "diagnosis", imageId?: string,
): Promise<Message> {
  const message: Message = {
    id: newId(),
    conversationId,
    role: "assistant",
    createdAt: Date.now(),
    status: "pending",
    kind,
    replyTo,
    ...(imageId ? { imageId } : {}),
  };
  await getDb().messages.add(message);
  return message;
}

async function fail(message: Message, err: unknown): Promise<void> {
  if (err instanceof SessionExpiredError) {
    // The login screen takes over; leave the message retryable.
    await getDb().messages.update(message.id, { status: "error", errorCode: "network" });
    return;
  }
  const code = err instanceof ApiError ? err.code : "generic";
  await getDb().messages.update(message.id, { status: "error", errorCode: code });
}

async function runDiagnosis(pending: Message): Promise<void> {
  const db = getDb();
  try {
    const image = await db.images.get(pending.imageId!);
    if (!image) throw new ApiError("generic", 0);
    if (!navigator.onLine) throw new ApiError("network", 0);
    const village = currentSession()?.user.village;
    const result = await diagnose(image.blob, getLang(), village);
    await db.messages.update(pending.id, { status: "done", diagnosis: result });
    await db.conversations.update(pending.conversationId, {
      diagnosisContext: contextFrom(result),
      updatedAt: Date.now(),
    });
  } catch (err) {
    await fail(pending, err);
  }
}

async function runChat(pending: Message): Promise<void> {
  const db = getDb();
  try {
    const question = await db.messages.get(pending.replyTo!);
    if (!question?.text) throw new ApiError("generic", 0);
    if (!navigator.onLine) throw new ApiError("network", 0);
    const conversation = await db.conversations.get(pending.conversationId);
    const history = await historyBefore(pending.conversationId, question.createdAt);
    const reply = await chat(question.text, getLang(), history, conversation?.diagnosisContext ?? null);
    await db.messages.update(pending.id, { status: "done", text: reply });
    await db.conversations.update(pending.conversationId, { updatedAt: Date.now() });
    if (question.viaVoice) speak(reply, getLang());
  } catch (err) {
    await fail(pending, err);
  }
}

/** Earlier completed turns, as the chat API expects them. Photo results become a short assistant line. */
async function historyBefore(conversationId: string, before: number): Promise<ChatTurn[]> {
  const messages = await getDb().messages
    .where("[conversationId+createdAt]")
    .between([conversationId, 0], [conversationId, before], true, false)
    .toArray();

  const turns: ChatTurn[] = [];
  for (const m of messages) {
    if (m.status !== "done") continue;
    if (m.role === "user" && m.text) turns.push({ role: "user", content: m.text });
    else if (m.role === "assistant" && m.text) turns.push({ role: "assistant", content: m.text });
    else if (m.role === "assistant" && m.diagnosis) {
      const d = m.diagnosis;
      turns.push({
        role: "assistant",
        content: `Photo check result: ${d.disease} (${d.confidence.toFixed(0)}% confidence${d.safe_to_act ? "" : ", not confirmed"}).`,
      });
    }
  }
  return turns.slice(-MAX_HISTORY);
}

/** User-facing text for an error code stored on a failed message. */
export function errorMessage(code: string | undefined): string {
  if (code === "network") return t("err_network");
  if (code === "not_authenticated" || code === "token_expired") return t("sessionExpired");
  if (code && code.length > 40) return code;   // the server already sent a translated sentence
  const key = `err_${code}` as StringKey;
  return t(key) !== key ? t(key) : t("chatUnavailable");
}

export async function deleteConversation(id: string): Promise<void> {
  const db = getDb();
  await db.transaction("rw", db.conversations, db.messages, db.images, async () => {
    const messages = await db.messages.where("conversationId").equals(id).toArray();
    const imageIds = messages.flatMap(m => m.imageIds ?? []);
    await db.images.bulkDelete(imageIds);
    await db.messages.bulkDelete(messages.map(m => m.id));
    await db.conversations.delete(id);
  });
}

export async function deleteAllConversations(): Promise<void> {
  const db = getDb();
  await db.transaction("rw", db.conversations, db.messages, db.images, async () => {
    await db.images.clear();
    await db.messages.clear();
    await db.conversations.clear();
  });
}

/** Messages left "pending" when the app was closed mid-request become retryable errors. */
export async function recoverInterrupted(): Promise<void> {
  const db = getDb();
  const stuck = await db.messages.filter(m => m.status === "pending").toArray();
  for (const m of stuck) await db.messages.update(m.id, { status: "error", errorCode: "network" });
}
