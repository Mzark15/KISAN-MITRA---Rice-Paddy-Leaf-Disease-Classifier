import { useState } from "react";
import { ApiError, currentSession, deleteAccount, GUEST, logout, updateProfile } from "../lib/auth";
import { deleteAllConversations } from "../lib/chat";
import { APP_VERSION, PRIVACY_URL } from "../lib/config";
import { deleteUserDb } from "../lib/db";
import { errorText, LANGS, setLang, t, useLang, type Lang } from "../lib/i18n";
import { BackIcon } from "./icons";

export function SettingsScreen({ onBack }: { onBack: () => void }) {
  const lang = useLang();
  const user = currentSession()?.user;
  const [name, setName] = useState(user?.name ?? "");
  const [village, setVillage] = useState(user?.village ?? "");
  const [status, setStatus] = useState("");
  const [deleting, setDeleting] = useState(false);

  function chooseLanguage(code: Lang) {
    setLang(code);
    updateProfile({ language: code }).catch(() => {});   // best effort; works offline locally
  }

  async function saveProfile() {
    setStatus("");
    try {
      await updateProfile({ name: name.trim() || undefined, village: village.trim() || undefined });
      setStatus(t("saved"));
    } catch (err) {
      setStatus(errorText(err instanceof ApiError ? err.code : undefined));
    }
  }

  async function doLogout() {
    if (confirm(t("logoutConfirm"))) await logout();
  }

  async function clearHistory() {
    if (confirm(t("clearHistoryConfirm"))) await deleteAllConversations();
  }

  async function removeAccount() {
    if (!user || !confirm(t("deleteAccountConfirm"))) return;
    setDeleting(true);
    try {
      const userId = user.user_id;
      await deleteAccount();
      await deleteUserDb(userId);
    } catch (err) {
      setDeleting(false);
      setStatus(errorText(err instanceof ApiError ? err.code : undefined));
    }
  }

  return (
    <div className="screen settings">
      <header className="topbar">
        <button type="button" className="icon-btn" aria-label={t("back")} onClick={onBack}><BackIcon /></button>
        <h1 className="title">{t("settings")}</h1>
      </header>

      <div className="scroll">
        <section className="card">
          <h2>{t("language")}</h2>
          <div className="lang-pills left">
            {LANGS.map(l => (
              <button key={l.code} type="button" className={l.code === lang ? "pill active" : "pill"}
                onClick={() => chooseLanguage(l.code)}>{l.label}</button>
            ))}
          </div>
        </section>

        <section className="card">
          <h2>{t("profile")}</h2>
          <label className="field"><span>{t("phoneLabel")}</span><input value={user?.phone ?? ""} disabled /></label>
          <label className="field"><span>{t("name")}</span>
            <input value={name} maxLength={100} onChange={e => setName(e.target.value)} />
          </label>
          <label className="field"><span>{t("village")}</span>
            <input value={village} maxLength={100} onChange={e => setVillage(e.target.value)} />
          </label>
          <button type="button" className="primary" onClick={saveProfile}>{t("save")}</button>
          {status && <p className="small muted" role="status">{status}</p>}
        </section>

        <section className="card">
          <h2>{t("account")}</h2>
          {!GUEST && <button type="button" className="secondary wide" onClick={doLogout}>{t("logout")}</button>}
          <button type="button" className="secondary wide" onClick={clearHistory}>{t("clearHistory")}</button>
          {!GUEST && <>
            <p className="small muted">{t("deleteAccountInfo")}</p>
            <button type="button" className="danger wide" onClick={removeAccount} disabled={deleting}>
              {deleting ? t("deleting") : t("deleteAccount")}
            </button>
          </>}
        </section>

        <section className="card">
          <h2>{t("about")}</h2>
          <p className="small"><a href={PRIVACY_URL} target="_blank" rel="noreferrer">{t("privacyPolicy")}</a></p>
          <p className="small muted">{t("version")} {APP_VERSION}</p>
        </section>
      </div>
    </div>
  );
}
