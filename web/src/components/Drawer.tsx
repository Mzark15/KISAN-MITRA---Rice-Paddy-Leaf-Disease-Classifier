import { useLiveQuery } from "dexie-react-hooks";
import { currentSession } from "../lib/auth";
import { getDb, type Conversation } from "../lib/db";
import { t } from "../lib/i18n";
import { useBackHandler } from "../lib/native";
import { BookIcon, Logo, NewChatIcon, SettingsIcon } from "./icons";

interface Props {
  open: boolean;
  activeId: string | null;
  onClose: () => void;
  onSelect: (id: string | null) => void;
  onLibrary: () => void;
  onSettings: () => void;
}

function group(conversations: Conversation[]) {
  const startOfToday = new Date().setHours(0, 0, 0, 0);
  const startOfYesterday = startOfToday - 86_400_000;
  const groups: { label: string; items: Conversation[] }[] = [
    { label: t("today"), items: [] },
    { label: t("yesterday"), items: [] },
    { label: t("earlier"), items: [] },
  ];
  for (const c of conversations) {
    const i = c.updatedAt >= startOfToday ? 0 : c.updatedAt >= startOfYesterday ? 1 : 2;
    groups[i].items.push(c);
  }
  return groups.filter(g => g.items.length);
}

/** Side menu like ChatGPT: new chat, past chats (newest first), disease library, settings. */
export function Drawer({ open, activeId, onClose, onSelect, onLibrary, onSettings }: Props) {
  const conversations = useLiveQuery(() => getDb().conversations.orderBy("updatedAt").reverse().toArray(), []) ?? [];
  useBackHandler(open, onClose);
  const phone = currentSession()?.user.phone;

  return (
    <>
      <div className={`drawer-backdrop ${open ? "open" : ""}`} onClick={onClose} />
      <nav className={`drawer ${open ? "open" : ""}`} aria-label={t("chats")} aria-hidden={!open}>
        <div className="drawer-head">
          <Logo size={34} />
          <strong>{t("appName")}</strong>
        </div>
        <button type="button" className="drawer-item primary-item" onClick={() => onSelect(null)}>
          <NewChatIcon /> {t("newChat")}
        </button>
        <button type="button" className="drawer-item" onClick={onLibrary}><BookIcon /> {t("library")}</button>

        <div className="drawer-list">
          {conversations.length === 0 && <p className="muted small pad">{t("noChats")}</p>}
          {group(conversations).map(g => (
            <section key={g.label}>
              <h4>{g.label}</h4>
              {g.items.map(c => (
                <button key={c.id} type="button" className={`drawer-chat ${c.id === activeId ? "active" : ""}`}
                  onClick={() => onSelect(c.id)}>
                  {c.title}
                </button>
              ))}
            </section>
          ))}
        </div>

        <button type="button" className="drawer-item" onClick={onSettings}>
          <SettingsIcon /> {t("settings")}
          {phone && <span className="muted small push">{phone}</span>}
        </button>
      </nav>
    </>
  );
}
