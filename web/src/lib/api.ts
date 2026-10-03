import { API_BASE } from "./config";
import { apiFetch, apiJson, ApiError } from "./auth";
import type { Lang } from "./i18n";

export interface Treatment {
  cause: string;
  severity_levels: string[];
  organic_treatment: string;
  chemical_treatment: string;
  precautions?: string | null;
  refer_to_kvk: boolean;
}

export interface Diagnosis {
  disease: string;
  confidence: number;
  treatment: Treatment;
  diagnosis_id: string;
  model_mode: string;
  safe_to_act: boolean;
  low_confidence_message?: string | null;
  top_predictions: { disease: string; confidence: number }[];
}

export interface DiagnosisContext {
  disease: string;
  confidence: number;
  safe_to_act: boolean;
  alternatives: string[];
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface DiseaseInfo extends Treatment {
  name: string;
}

export function contextFrom(d: Diagnosis): DiagnosisContext {
  return {
    disease: d.disease,
    confidence: d.confidence,
    safe_to_act: d.safe_to_act,
    alternatives: d.top_predictions.slice(1).map(p => p.disease),
  };
}

export function diagnose(photo: Blob, language: Lang, village?: string): Promise<Diagnosis> {
  const form = new FormData();
  form.append("image", photo, "leaf.jpg");
  form.append("language", language);
  if (village) form.append("village", village);
  return apiJson<Diagnosis>("/diagnose", { method: "POST", body: form });
}

export async function chat(
  message: string,
  language: Lang,
  history: ChatTurn[],
  context: DiagnosisContext | null,
  signal?: AbortSignal,
): Promise<string> {
  const data = await apiJson<{ reply: string }>("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      language,
      conversation_history: history,
      ...(context ? { diagnosis_context: context } : {}),
    }),
    signal,
  });
  return data.reply;
}

export async function sendFeedback(diagnosisId: string, helpful: boolean): Promise<void> {
  await apiJson("/diagnose/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ diagnosis_id: diagnosisId, helpful }),
  });
}

/** Server text-to-speech (Bhashini). Returns null when the server doesn't offer it. */
export async function serverSpeech(text: string, language: Lang): Promise<Blob | null> {
  try {
    const res = await apiFetch("/voice/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, language }),
    });
    return res.ok ? await res.blob() : null;
  } catch {
    return null;
  }
}

const DISEASES_CACHE = "km_diseases_v1";

/** Disease reference list (public). Cached so the library works offline. */
export async function loadDiseases(): Promise<DiseaseInfo[]> {
  try {
    const res = await fetch(`${API_BASE}/diseases`);
    if (!res.ok) throw new ApiError("generic", res.status);
    const data = (await res.json()) as { diseases: DiseaseInfo[] };
    try { localStorage.setItem(DISEASES_CACHE, JSON.stringify(data.diseases)); } catch { /* ignore */ }
    return data.diseases;
  } catch (err) {
    try {
      const cached = localStorage.getItem(DISEASES_CACHE);
      if (cached) return JSON.parse(cached) as DiseaseInfo[];
    } catch { /* ignore */ }
    throw err;
  }
}
