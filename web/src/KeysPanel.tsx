import { useEffect, useState } from "react";
import { checkKeys, type Keys, type KeyStatus } from "./api";

type Status = { anthropic?: KeyStatus; kroger?: KeyStatus };

const FIELDS: { key: keyof Keys; label: string; hint: string; link: string; linkText: string; placeholder: string }[] = [
  { key: "anthropic", label: "Anthropic API key", hint: "Plans your week (Claude Haiku + Sonnet), about $0.035 per plan",
    link: "https://console.anthropic.com/settings/keys", linkText: "Get a key", placeholder: "sk-ant-…" },
  { key: "krogerId", label: "Kroger client ID", hint: "Real prices at your nearest Kroger (free developer account)",
    link: "https://developer.kroger.com/", linkText: "Create a Kroger app", placeholder: "your-app-…" },
  { key: "krogerSecret", label: "Kroger client secret", hint: "From the same Kroger app, scope product.compact",
    link: "https://developer.kroger.com/documentation/public/getting-started/quick-start", linkText: "How to", placeholder: "••••••••" },
];

/** Slide-in panel for the student's own API keys. Kept in memory; "Remember" saves them in this browser only. */
export function KeysPanel({ open, onClose, keys, onSave, remember, setRemember, status, setStatus }: {
  open: boolean; onClose: () => void; keys: Keys; onSave: (k: Keys) => void;
  remember: boolean; setRemember: (r: boolean) => void; status: Status; setStatus: (s: Status) => void;
}) {
  const [draft, setDraft] = useState<Keys>(keys);
  const [show, setShow] = useState<Record<string, boolean>>({});
  const [testing, setTesting] = useState(false);

  useEffect(() => { if (open) setDraft(keys); }, [open, keys]);
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [open, onClose]);

  async function saveAndTest() {
    onSave(draft);
    setTesting(true);
    try { setStatus(await checkKeys()); }
    catch {
      const down = { ok: false, message: "couldn't reach the app's server: try again in a moment" };
      setStatus({ anthropic: down, kroger: down });
    } finally { setTesting(false); }
  }

  const badge = (s?: KeyStatus) =>
    !s ? null : s.ok
      ? <span className="kbadge ok">✓ {s.source === "yours" ? "your key works" : "using the server's key"}</span>
      : <span className="kbadge bad">✗ {s.message}</span>;

  return (
    <>
      <div className={`scrim ${open ? "show" : ""}`} onClick={onClose} />
      <aside className={`drawer ${open ? "open" : ""}`} aria-hidden={!open} aria-label="API keys">
        <div className="drawer-head">
          <div><p className="eyebrow">Settings</p><h2>🔑 Your API keys</h2></div>
          <button className="close" onClick={onClose} aria-label="Close">×</button>
        </div>
        <p className="muted small">
          Bring your own keys. They go straight to this app's server with each request, are used for that request only,
          and are never stored or logged there. Leave a field empty to use the server's key (if it has one).
        </p>

        {FIELDS.map((f) => (
          <div key={f.key} className="kfield">
            <div className="kfield-top">
              <label htmlFor={f.key}>{f.label}</label>
              <a href={f.link} target="_blank" rel="noreferrer">{f.linkText} ↗</a>
            </div>
            <div className="kinput">
              <input id={f.key} type={show[f.key] ? "text" : "password"} autoComplete="off" spellCheck={false}
                     placeholder={f.placeholder} value={draft[f.key]}
                     onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value.trim() })} />
              <button type="button" onClick={() => setShow({ ...show, [f.key]: !show[f.key] })}
                      aria-label={show[f.key] ? "Hide" : "Show"}>{show[f.key] ? "🙈" : "👁️"}</button>
            </div>
            <div className="kfield-foot">
              <span className="muted tiny">{f.hint}</span>
              {f.key === "anthropic" && badge(status.anthropic)}
              {f.key === "krogerSecret" && badge(status.kroger)}
            </div>
          </div>
        ))}

        <label className="remember">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          <span className="switch" aria-hidden />
          <span>Remember on this device<small>Saved in this browser only. Don't turn on on a shared computer.</small></span>
        </label>

        <div className="drawer-actions">
          <button className="primary" onClick={saveAndTest} disabled={testing}>{testing ? "Testing…" : "Save & test keys"}</button>
          <button className="ghost" onClick={() => { const empty = { anthropic: "", krogerId: "", krogerSecret: "" }; setDraft(empty); onSave(empty); setStatus({}); }}>
            Clear
          </button>
        </div>
        <p className="muted tiny">Testing is free: it lists Anthropic models and asks Kroger for a token. No plan is made.</p>
      </aside>
    </>
  );
}
