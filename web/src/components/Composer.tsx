import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { t, useLang } from "../lib/i18n";
import { chooseFile, chooseFromGallery, takePhoto } from "../lib/media";
import { tap, useBackHandler } from "../lib/native";
import { listen, stopListening, VoiceError } from "../lib/voice";
import { CameraIcon, CloseIcon, FileIcon, ImageIcon, MicIcon, PlusIcon, SendIcon, StopIcon } from "./icons";

const MAX_PHOTOS = 3;

interface Props {
  disabled: boolean;
  onSend: (text: string, photos: Blob[], viaVoice?: boolean) => void;
  /** Lets the empty-state "Take a photo" suggestion open the camera. */
  cameraRequest: number;
  onError: (message: string) => void;
}

function PhotoChip({ blob, onRemove }: { blob: Blob; onRemove: () => void }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    const u = URL.createObjectURL(blob);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [blob]);
  return (
    <div className="photo-chip">
      {url && <img src={url} alt="" />}
      <button type="button" aria-label={t("removePhoto")} onClick={onRemove}><CloseIcon /></button>
    </div>
  );
}

export function Composer({ disabled, onSend, cameraRequest, onError }: Props) {
  const lang = useLang();
  const [text, setText] = useState("");
  const [photos, setPhotos] = useState<Blob[]>([]);
  const [sheet, setSheet] = useState(false);
  const [listening, setListening] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);

  useBackHandler(sheet, () => setSheet(false));

  // Grow the text box with its content (up to a limit set in CSS).
  useLayoutEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [text]);

  async function addPhoto(source: () => Promise<Blob | null>) {
    setSheet(false);
    try {
      const blob = await source();
      if (blob) setPhotos(p => [...p, blob].slice(0, MAX_PHOTOS));
    } catch {
      onError(t("err_generic"));
    }
  }

  useEffect(() => {
    if (cameraRequest > 0) addPhoto(takePhoto);
  }, [cameraRequest]);

  function submit(viaVoice = false, overrideText?: string) {
    const value = (overrideText ?? text).trim();
    if (disabled || (!value && photos.length === 0)) return;
    tap();
    onSend(value, photos, viaVoice);
    setText("");
    setPhotos([]);
  }

  async function toggleMic() {
    if (listening) { stopListening(); return; }
    tap();
    setListening(true);
    try {
      const heard = await listen(lang, partial => setText(partial));
      // Spoken questions are sent straight away and the answer is read aloud.
      if (heard) submit(true, heard);
    } catch (err) {
      onError(err instanceof VoiceError && err.code === "denied" ? t("micDenied") : t("voiceUnavailable"));
    } finally {
      setListening(false);
    }
  }

  const canSend = !disabled && (text.trim().length > 0 || photos.length > 0);

  return (
    <div className="composer-wrap">
      {photos.length > 0 && (
        <div className="photo-chips">
          {photos.map((p, i) => <PhotoChip key={i} blob={p} onRemove={() => setPhotos(ps => ps.filter((_, j) => j !== i))} />)}
        </div>
      )}
      <div className={`composer ${listening ? "listening" : ""}`}>
        <button type="button" className="icon-btn" aria-label={t("attach")} onClick={() => setSheet(true)}
          disabled={photos.length >= MAX_PHOTOS || listening}>
          <PlusIcon />
        </button>
        <textarea
          ref={area}
          rows={1}
          value={text}
          placeholder={listening ? t("listening") : t("composerPlaceholder")}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => {
            // Enter sends on a keyboard; on phones Enter adds a new line (send with the button).
            if (e.key === "Enter" && !e.shiftKey && window.matchMedia("(pointer: fine)").matches) {
              e.preventDefault();
              submit();
            }
          }}
          readOnly={listening}
        />
        {canSend ? (
          <button type="button" className="icon-btn send" aria-label={t("send")} onClick={() => submit()}>
            <SendIcon />
          </button>
        ) : (
          <button type="button" className={`icon-btn mic ${listening ? "on" : ""}`}
            aria-label={listening ? t("stopSpeaking") : t("mic")} onClick={toggleMic} disabled={disabled}>
            {listening ? <StopIcon /> : <MicIcon />}
          </button>
        )}
      </div>

      {sheet && (
        <div className="sheet-backdrop" onClick={() => setSheet(false)}>
          <div className="sheet" role="dialog" aria-label={t("attach")} onClick={e => e.stopPropagation()}>
            <button type="button" className="sheet-item" onClick={() => addPhoto(takePhoto)}><CameraIcon /> {t("camera")}</button>
            <button type="button" className="sheet-item" onClick={() => addPhoto(chooseFromGallery)}><ImageIcon /> {t("gallery")}</button>
            <button type="button" className="sheet-item" onClick={() => addPhoto(chooseFile)}><FileIcon /> {t("files")}</button>
          </div>
        </div>
      )}
    </div>
  );
}
