import { useEffect, useRef, useState } from "react";
import { useLiveQuery } from "dexie-react-hooks";
import { deleteConversation, sendMessage } from "../lib/chat";
import { getDb } from "../lib/db";
import { t } from "../lib/i18n";
import { useOnline } from "../lib/native";
import { Composer } from "./Composer";
import { MessageView } from "./MessageView";
import { Logo, MenuIcon, NewChatIcon, OfflineIcon, TrashIcon } from "./icons";

interface Props {
  conversationId: string | null;
  onConversation: (id: string | null) => void;
  onMenu: () => void;
}

export function ChatScreen({ conversationId, onConversation, onMenu }: Props) {
  const online = useOnline();
  const [cameraRequest, setCameraRequest] = useState(0);
  const [toast, setToast] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  const conversation = useLiveQuery(
    () => (conversationId ? getDb().conversations.get(conversationId) : undefined),
    [conversationId],
  );
  const messages = useLiveQuery(
    () => (conversationId
      ? getDb().messages.where("[conversationId+createdAt]")
          .between([conversationId, 0], [conversationId, Infinity]).toArray()
      : []),
    [conversationId],
  ) ?? [];

  const busy = messages.some(m => m.status === "pending");
  const lastMessage = messages[messages.length - 1];
  const lastIsDiagnosis = lastMessage?.role === "assistant" && lastMessage.status === "done" && !!lastMessage.diagnosis;

  // Keep the newest message in view.
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, lastMessage?.status]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 4000);
    return () => clearTimeout(timer);
  }, [toast]);

  async function send(text: string, photos: Blob[], viaVoice?: boolean) {
    const id = await sendMessage({ conversationId, text, photos, viaVoice });
    if (id !== conversationId) onConversation(id);
  }

  async function remove() {
    if (!conversationId || !confirm(t("deleteChatConfirm"))) return;
    await deleteConversation(conversationId);
    onConversation(null);
  }

  return (
    <div className="screen chat">
      <header className="topbar">
        <button type="button" className="icon-btn" aria-label={t("menu")} onClick={onMenu}><MenuIcon /></button>
        <h1 className="title">{conversation?.title ?? t("appName")}</h1>
        {conversationId && (
          <button type="button" className="icon-btn" aria-label={t("deleteChat")} onClick={remove}><TrashIcon /></button>
        )}
        <button type="button" className="icon-btn" aria-label={t("newChat")} onClick={() => onConversation(null)}>
          <NewChatIcon />
        </button>
      </header>

      {!online && <div className="banner"><OfflineIcon /> {t("offline")}</div>}

      <div className="messages" ref={listRef}>
        {messages.length === 0 ? (
          <div className="empty">
            <Logo size={56} />
            <h2>{t("emptyTitle")}</h2>
            <p className="muted">{t("emptyHint")}</p>
            <div className="suggestions">
              <button type="button" className="suggestion" onClick={() => setCameraRequest(n => n + 1)}>📷 {t("suggest1")}</button>
              <button type="button" className="suggestion" onClick={() => send(t("suggest2"), [])}>{t("suggest2")}</button>
              <button type="button" className="suggestion" onClick={() => send(t("suggest3"), [])}>{t("suggest3")}</button>
            </div>
          </div>
        ) : (
          <>
            {messages.map(m => <MessageView key={m.id} m={m} />)}
            {lastIsDiagnosis && !busy && (
              <div className="suggestions inline">
                <button type="button" className="suggestion" onClick={() => send(t("followUp1"), [])}>{t("followUp1")}</button>
                <button type="button" className="suggestion" onClick={() => send(t("followUp2"), [])}>{t("followUp2")}</button>
              </div>
            )}
          </>
        )}
      </div>

      {toast && <div className="toast" role="status">{toast}</div>}

      <footer className="bottom">
        <Composer disabled={busy} onSend={send} cameraRequest={cameraRequest} onError={setToast} />
        <p className="disclaimer">{t("disclaimer")}</p>
      </footer>
    </div>
  );
}
