/**
 * Voice: speaking a question (speech-to-text) and reading answers aloud (text-to-speech).
 *
 * Android uses the phone's own engines through native plugins, which support
 * Hindi, Marathi and Indian English and don't depend on the server. The
 * Android WebView has no Web Speech API, so the browser path is web-only.
 */
import { SpeechRecognition } from "@capacitor-community/speech-recognition";
import { TextToSpeech } from "@capacitor-community/text-to-speech";
import { isNative } from "./config";
import { SPEECH_LANG, type Lang } from "./i18n";

export class VoiceError extends Error {
  constructor(public code: "denied" | "unavailable") {
    super(code);
  }
}

type WebRecognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: (e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void;
  onerror: (e: { error: string }) => void;
  onend: () => void;
  start(): void;
  stop(): void;
  abort(): void;
};

function webRecognitionCtor(): (new () => WebRecognition) | null {
  const w = window as unknown as Record<string, unknown>;
  return (w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null) as (new () => WebRecognition) | null;
}

let stopCurrent: (() => void) | null = null;

/**
 * Listen until the speaker pauses. `onPartial` receives the text so far.
 * Resolves with the final text ("" if nothing was heard).
 */
export async function listen(lang: Lang, onPartial: (text: string) => void): Promise<string> {
  stopSpeaking();
  if (isNative) return listenNative(lang, onPartial);

  const Ctor = webRecognitionCtor();
  if (!Ctor) throw new VoiceError("unavailable");
  return new Promise((resolve, reject) => {
    const rec = new Ctor();
    let text = "";
    rec.lang = SPEECH_LANG[lang];
    rec.interimResults = true;
    rec.continuous = false;
    rec.onresult = e => {
      text = Array.from(e.results, r => r[0].transcript).join(" ");
      onPartial(text);
    };
    rec.onerror = e => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") reject(new VoiceError("denied"));
    };
    rec.onend = () => { stopCurrent = null; resolve(text.trim()); };
    stopCurrent = () => rec.stop();
    rec.start();
  });
}

async function listenNative(lang: Lang, onPartial: (text: string) => void): Promise<string> {
  const { available } = await SpeechRecognition.available();
  if (!available) throw new VoiceError("unavailable");

  let perm = await SpeechRecognition.checkPermissions();
  if (perm.speechRecognition !== "granted") perm = await SpeechRecognition.requestPermissions();
  if (perm.speechRecognition !== "granted") throw new VoiceError("denied");

  let text = "";
  const partial = await SpeechRecognition.addListener("partialResults", data => {
    text = data.matches?.[0] ?? text;
    onPartial(text);
  });

  return new Promise((resolve, reject) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      stopCurrent = null;
      partial.remove();
      state.then(h => h.remove());
      resolve(text.trim());
    };
    const state = SpeechRecognition.addListener("listeningState", s => {
      if (s.status === "stopped") finish();
    });
    stopCurrent = () => { SpeechRecognition.stop().finally(finish); };
    SpeechRecognition.start({
      language: SPEECH_LANG[lang],
      partialResults: true,
      popup: false,
      maxResults: 1,
    }).catch(err => {
      if (done) return;
      done = true;
      partial.remove();
      state.then(h => h.remove());
      // "No match" / silence is not an error for the user: they just said nothing.
      if (/no match|didn't understand|no speech/i.test(String(err?.message))) resolve("");
      else reject(err);
    });
  });
}

export function stopListening(): void {
  stopCurrent?.();
}

// ── Reading answers aloud ───────────────────────────────────────────────────

let speakingId = 0;

/** Read text aloud. Resolves when finished or stopped. */
export async function speak(text: string, lang: Lang): Promise<void> {
  stopSpeaking();
  const id = ++speakingId;
  const clean = text.replace(/[*#_`>•]/g, " ");
  if (isNative) {
    try {
      await TextToSpeech.speak({ text: clean, lang: SPEECH_LANG[lang], rate: 0.95 });
    } catch {
      if (lang !== "en" && id === speakingId) {
        // Some phones lack a Marathi voice: Hindi reads Devanagari well enough.
        await TextToSpeech.speak({ text: clean, lang: "hi-IN", rate: 0.95 }).catch(() => {});
      }
    }
    return;
  }
  if (!("speechSynthesis" in window)) return;
  await new Promise<void>(resolve => {
    const utt = new SpeechSynthesisUtterance(clean);
    utt.lang = SPEECH_LANG[lang];
    const voice = speechSynthesis.getVoices().find(v => v.lang === utt.lang);
    if (voice) utt.voice = voice;
    utt.onend = () => resolve();
    utt.onerror = () => resolve();
    speechSynthesis.speak(utt);
  });
}

export function stopSpeaking(): void {
  speakingId++;
  if (isNative) TextToSpeech.stop().catch(() => {});
  else if ("speechSynthesis" in window) speechSynthesis.cancel();
}
