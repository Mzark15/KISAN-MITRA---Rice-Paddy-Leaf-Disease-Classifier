import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, startOtp, verifyOtp, type OtpStart } from "../lib/auth";
import { PRIVACY_URL } from "../lib/config";
import { errorText, LANGS, setLang, t, useLang, type StringKey } from "../lib/i18n";
import { useBackHandler } from "../lib/native";
import { Logo } from "./icons";

/** Phone number → SMS code. Shown once; afterwards the app opens straight into the chat. */
export function LoginScreen({ message }: { message?: string }) {
  const lang = useLang();
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [otp, setOtp] = useState<OtpStart | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(message ? t(message as StringKey) : "");
  const [resendIn, setResendIn] = useState(0);
  const codeRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (resendIn <= 0) return;
    const timer = setTimeout(() => setResendIn(s => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [resendIn]);

  useBackHandler(otp !== null, () => { setOtp(null); setError(""); });

  const digits = phone.replace(/\D/g, "").replace(/^(91|0)(?=\d{10}$)/, "");

  async function send(e?: FormEvent) {
    e?.preventDefault();
    if (!/^[6-9]\d{9}$/.test(digits)) { setError(t("err_invalid_phone")); return; }
    setBusy(true);
    setError("");
    try {
      const started = await startOtp(`+91${digits}`);
      setOtp(started);
      setCode("");
      setResendIn(started.resend_after || 30);
      setTimeout(() => codeRef.current?.focus(), 50);
    } catch (err) {
      setError(errorText(err instanceof ApiError ? err.code : undefined));
    } finally {
      setBusy(false);
    }
  }

  async function verify(e: FormEvent) {
    e.preventDefault();
    const clean = code.replace(/\D/g, "");
    if (clean.length < 4 || !otp) { setError(t("err_invalid_code")); return; }
    setBusy(true);
    setError("");
    try {
      await verifyOtp(otp, clean);   // the app switches to the chat when the session is saved
    } catch (err) {
      setError(errorText(err instanceof ApiError ? err.code : undefined));
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <div className="login-card">
        <Logo size={64} />
        <div className="lang-pills" role="group" aria-label={t("language")}>
          {LANGS.map(l => (
            <button key={l.code} type="button" className={l.code === lang ? "pill active" : "pill"}
              onClick={() => setLang(l.code)}>{l.label}</button>
          ))}
        </div>
        <h1>{t("loginTitle")}</h1>

        {!otp ? (
          <form onSubmit={send} noValidate>
            <p className="muted">{t("loginSubtitle")}</p>
            <label className="field">
              <span>{t("phoneLabel")}</span>
              <div className="phone-row">
                <span className="cc">+91</span>
                <input type="tel" inputMode="numeric" autoComplete="tel-national" maxLength={14}
                  placeholder="98765 43210" value={phone} onChange={e => setPhone(e.target.value)} autoFocus />
              </div>
            </label>
            <button type="submit" className="primary wide" disabled={busy}>
              {busy ? t("sendingOtp") : t("sendOtpBtn")}
            </button>
          </form>
        ) : (
          <form onSubmit={verify} noValidate>
            <p className="muted">{t("otpSentTo")} <strong>{otp.phone}</strong></p>
            <label className="field">
              <span>{t("otpLabel")}</span>
              <input ref={codeRef} className="otp" type="tel" inputMode="numeric" autoComplete="one-time-code"
                maxLength={8} value={code} onChange={e => setCode(e.target.value)} />
            </label>
            <button type="submit" className="primary wide" disabled={busy}>
              {busy ? t("verifying") : t("verifyBtn")}
            </button>
            <button type="button" className="link" disabled={busy || resendIn > 0} onClick={() => send()}>
              {resendIn > 0 ? t("resendIn", { s: resendIn }) : t("resendBtn")}
            </button>
            <button type="button" className="link" onClick={() => { setOtp(null); setError(""); }}>
              {t("changeNumber")}
            </button>
          </form>
        )}

        <p className="error" role="alert">{error}</p>
        <p className="consent">
          {t("consent")} <a href={PRIVACY_URL} target="_blank" rel="noreferrer">{t("privacyPolicy")}</a>
        </p>
      </div>
    </main>
  );
}
