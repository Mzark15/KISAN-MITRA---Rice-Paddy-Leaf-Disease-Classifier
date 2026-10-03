import { useState } from "react";
import { sendFeedback, type Diagnosis } from "../lib/api";
import { getDb } from "../lib/db";
import { t } from "../lib/i18n";
import { ThumbDownIcon, ThumbUpIcon } from "./icons";

/** Photo check result shown as an assistant message. Treatment text comes from the vetted knowledge base. */
export function DiagnosisCard({ messageId, d, feedback }: { messageId: string; d: Diagnosis; feedback?: boolean }) {
  const [sent, setSent] = useState(feedback !== undefined);
  const isNormal = d.disease === "Normal";
  const alternatives = d.top_predictions.slice(1);
  const pct = Math.max(0, Math.min(100, d.confidence));

  async function rate(helpful: boolean) {
    setSent(true);
    await getDb().messages.update(messageId, { feedback: helpful });
    sendFeedback(d.diagnosis_id, helpful).catch(() => {});   // best effort
  }

  return (
    <div className={`diagnosis ${d.safe_to_act ? "" : "uncertain"}`}>
      {d.model_mode === "random" && <div className="badge demo">{t("demoBadge")}</div>}
      <div className="diagnosis-head">
        <h3>{d.disease}</h3>
        <span className="pct">{pct.toFixed(0)}%</span>
      </div>
      <div className="meter" role="meter" aria-label={t("confidence")} aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div style={{ width: `${pct}%` }} />
      </div>

      {!d.safe_to_act && <p className="warn">{isNormal ? t("uncertainHealthy") : t("lowConfidence")}</p>}
      {!d.safe_to_act && alternatives.length > 0 && (
        <p className="small"><strong>{t("otherPossibilities")}:</strong>{" "}
          {alternatives.map(a => `${a.disease} (${a.confidence.toFixed(0)}%)`).join(", ")}</p>
      )}
      {d.treatment.refer_to_kvk && <p className="kvk">{t("kvkBadge")}</p>}

      {isNormal ? (
        d.safe_to_act && <p className="ok">{t("healthy")}</p>
      ) : (
        <dl>
          <dt>{t("cause")}</dt><dd>{d.treatment.cause}</dd>
          <dt>{t("organic")}</dt><dd>{d.treatment.organic_treatment}</dd>
          <dt>{t("chemical")}</dt><dd>{d.treatment.chemical_treatment}</dd>
          {d.treatment.precautions && <><dt>{t("precautions")}</dt><dd>{d.treatment.precautions}</dd></>}
        </dl>
      )}

      <div className="feedback">
        {sent ? (
          <span className="small muted">{t("feedbackThanks")}</span>
        ) : (
          <>
            <button type="button" className="chip" onClick={() => rate(true)}><ThumbUpIcon /> {t("helpful")}</button>
            <button type="button" className="chip" onClick={() => rate(false)}><ThumbDownIcon /> {t("notHelpful")}</button>
          </>
        )}
      </div>
    </div>
  );
}
