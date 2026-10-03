import { useEffect, useState } from "react";
import { useLiveQuery } from "dexie-react-hooks";
import { errorMessage, retry } from "../lib/chat";
import { getDb, type Message } from "../lib/db";
import { getLang, t } from "../lib/i18n";
import { copyText, shareText } from "../lib/native";
import { speak, stopSpeaking } from "../lib/voice";
import { DiagnosisCard } from "./DiagnosisCard";
import { CopyIcon, RetryIcon, ShareIcon, SpeakerIcon, StopIcon } from "./icons";

function useImageUrl(id: string): string | null {
  const image = useLiveQuery(() => getDb().images.get(id), [id]);
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!image) return;
    const u = URL.createObjectURL(image.blob);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [image]);
  return url;
}

function Photo({ id }: { id: string }) {
  const url = useImageUrl(id);
  return url ? <img className="photo" src={url} alt="" /> : <div className="photo placeholder" />;
}

function AssistantActions({ text }: { text: string }) {
  const [speaking, setSpeaking] = useState(false);
  const [copied, setCopied] = useState(false);

  async function toggleSpeak() {
    if (speaking) { stopSpeaking(); setSpeaking(false); return; }
    setSpeaking(true);
    await speak(text, getLang());
    setSpeaking(false);
  }

  return (
    <div className="actions">
      <button type="button" className="icon-btn small" aria-label={speaking ? t("stopSpeaking") : t("speak")} onClick={toggleSpeak}>
        {speaking ? <StopIcon /> : <SpeakerIcon />}
      </button>
      <button type="button" className="icon-btn small" aria-label={t("copy")}
        onClick={async () => { await copyText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
        <CopyIcon />
      </button>
      <button type="button" className="icon-btn small" aria-label={t("share")} onClick={() => shareText(text, t("appName"))}>
        <ShareIcon />
      </button>
      {copied && <span className="small muted">{t("copied")}</span>}
    </div>
  );
}

export function MessageView({ m }: { m: Message }) {
  if (m.role === "user") {
    return (
      <div className="msg user">
        {m.imageIds?.map(id => <Photo key={id} id={id} />)}
        {m.text && <div className="bubble">{m.text}</div>}
      </div>
    );
  }

  if (m.status === "pending") {
    return (
      <div className="msg assistant">
        <div className="typing" aria-live="polite">
          <span className="dots"><i /><i /><i /></span>
          {m.kind === "diagnosis" ? t("checkingPhoto") : t("thinking")}
        </div>
      </div>
    );
  }

  if (m.status === "error") {
    return (
      <div className="msg assistant">
        <div className="error-box">
          <span>{errorMessage(m.errorCode)}</span>
          <button type="button" className="chip" onClick={() => retry(m)}><RetryIcon /> {t("retry")}</button>
        </div>
      </div>
    );
  }

  return (
    <div className="msg assistant">
      {m.diagnosis && <DiagnosisCard messageId={m.id} d={m.diagnosis} feedback={m.feedback} />}
      {m.text && (
        <>
          <div className="answer">{m.text}</div>
          <AssistantActions text={m.text} />
        </>
      )}
    </div>
  );
}
