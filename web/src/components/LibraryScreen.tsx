import { useEffect, useState } from "react";
import { loadDiseases, type DiseaseInfo } from "../lib/api";
import { t } from "../lib/i18n";
import { BackIcon } from "./icons";

/** Disease reference: works offline after the first load. */
export function LibraryScreen({ onBack }: { onBack: () => void }) {
  const [diseases, setDiseases] = useState<DiseaseInfo[] | null>(null);
  const [error, setError] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    loadDiseases().then(setDiseases).catch(() => setError(true));
  }, []);

  const q = query.trim().toLowerCase();
  const items = (diseases ?? []).filter(d => d.name.toLowerCase().includes(q));

  return (
    <div className="screen library">
      <header className="topbar">
        <button type="button" className="icon-btn" aria-label={t("back")} onClick={onBack}><BackIcon /></button>
        <h1 className="title">{t("library")}</h1>
      </header>
      <div className="scroll">
        <input className="search" type="search" placeholder={t("search")} value={query} onChange={e => setQuery(e.target.value)} />
        {error && !diseases && <p className="muted">{t("loadError")}</p>}
        {diseases && items.length === 0 && <p className="muted">{t("noMatch")} “{query}”</p>}
        {items.map(d => (
          <details key={d.name} className="card disease">
            <summary>{d.name}{d.refer_to_kvk && <span className="kvk-tag">KVK</span>}</summary>
            <dl>
              <dt>{t("cause")}</dt><dd>{d.cause}</dd>
              {d.severity_levels?.length > 0 && <><dt>{t("severity")}</dt><dd>{d.severity_levels.join(" / ")}</dd></>}
              <dt>{t("organic")}</dt><dd>{d.organic_treatment}</dd>
              <dt>{t("chemical")}</dt><dd>{d.chemical_treatment}</dd>
              {d.precautions && <><dt>{t("precautions")}</dt><dd>{d.precautions}</dd></>}
            </dl>
          </details>
        ))}
      </div>
    </div>
  );
}
