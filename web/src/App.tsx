import { useCallback, useEffect, useMemo, useState } from "react";
import { restoreSession, useAuth, type Session } from "./lib/auth";
import { recoverInterrupted } from "./lib/chat";
import { openDb, requestPersistentStorage } from "./lib/db";
import { getLang, setLang, useLang } from "./lib/i18n";
import { hideSplash, setBarIcons, useBackHandler } from "./lib/native";
import { ChatScreen } from "./components/ChatScreen";
import { Drawer } from "./components/Drawer";
import { LibraryScreen } from "./components/LibraryScreen";
import { LoginScreen } from "./components/LoginScreen";
import { SettingsScreen } from "./components/SettingsScreen";

type View = "chat" | "library" | "settings";

function MainApp({ session }: { session: Session }) {
  useMemo(() => openDb(session.user.user_id), [session.user.user_id]);
  const [view, setView] = useState<View>("chat");
  const [drawer, setDrawer] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);

  useEffect(() => {
    recoverInterrupted().catch(() => {});
    requestPersistentStorage();
    // Use the language saved in the farmer's profile (e.g. on a new phone).
    const saved = session.user.language;
    if (saved && saved !== getLang()) setLang(saved);
  }, [session.user.user_id]);

  const backToChat = useCallback(() => setView("chat"), []);
  useBackHandler(view !== "chat", backToChat);

  const select = (id: string | null) => {
    setConversationId(id);
    setView("chat");
    setDrawer(false);
  };

  return (
    <div className="app">
      {view === "chat" && (
        <ChatScreen conversationId={conversationId} onConversation={setConversationId} onMenu={() => setDrawer(true)} />
      )}
      {view === "library" && <LibraryScreen onBack={backToChat} />}
      {view === "settings" && <SettingsScreen onBack={backToChat} />}
      <Drawer
        open={drawer}
        activeId={conversationId}
        onClose={() => setDrawer(false)}
        onSelect={select}
        onLibrary={() => { setView("library"); setDrawer(false); }}
        onSettings={() => { setView("settings"); setDrawer(false); }}
      />
    </div>
  );
}

export function App() {
  const auth = useAuth();
  useLang();   // re-render everything when the language changes

  useEffect(() => {
    restoreSession().finally(hideSplash);
  }, []);

  // Green header in the app, light background on the login screen.
  useEffect(() => { setBarIcons(auth.status === "logged_in"); }, [auth.status]);

  if (auth.status === "loading") return null;   // the native splash screen is still showing
  if (auth.status === "logged_out" || !auth.session) return <LoginScreen message={auth.message} />;
  return <MainApp key={auth.session.user.user_id} session={auth.session} />;
}
