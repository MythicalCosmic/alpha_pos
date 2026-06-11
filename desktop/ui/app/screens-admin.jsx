// Screens: Notifications (per-chat-per-category routing) + Configuration
// (sectioned grid + import/export .env). Wired to the live control bridge.

/* ================= NOTIFICATIONS ================= */
function EventRow({ k, on, onToggle }) {
  const app = useApp();
  return (
    <div className="ev-row">
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="ev-name">{app.t("ev." + k)}</div>
        <div className="ev-desc">{app.t("ev." + k + "D")}</div>
      </div>
      <Switch on={on} onChange={onToggle}></Switch>
    </div>
  );
}

function NotificationsScreen() {
  const app = useApp();
  const { t } = app;
  const [types, setTypes] = React.useState(["order_paid", "daily", "contract", "document", "system"]);
  const [recipients, setRecipients] = React.useState([]);
  const [selId, setSelId] = React.useState(null);
  const [newId, setNewId] = React.useState("");
  const [brand, setBrand] = React.useState("Alpha POS");
  const [token, setToken] = React.useState("");
  const [botSet, setBotSet] = React.useState(false);
  const loaded = React.useRef(false);

  React.useEffect(() => {
    api.notif_settings().then((r) => {
      if (r && r.ok) { setBrand(r.brand_name || "Alpha POS"); setBotSet(!!r.bot_token_set); }
    });
    api.notif_routing().then((r) => {
      if (r && r.ok) {
        setTypes(r.types || types);
        setRecipients(r.recipients || []);
        if (r.recipients && r.recipients.length) setSelId(r.recipients[0].cid);
      }
      loaded.current = true;
    });
  }, []);

  // Persist routing whenever the recipient list changes (after the first load).
  const persist = (list) => { if (loaded.current) api.set_notif_routing(list); };
  const commit = (list) => { setRecipients(list); persist(list); };

  const sel = recipients.find((r) => r.cid === selId) || recipients[0];
  const update = (cid, fn) => commit(recipients.map((r) => (r.cid === cid ? fn(r) : r)));

  const addRecipient = () => {
    const cid = newId.replace(/\D/g, "");
    if (!cid || recipients.some((r) => r.cid === cid)) return;
    const ev = {}; types.forEach((tp) => (ev[tp] = true));
    const list = [...recipients, { cid, label: "Chat " + cid.slice(-4), events: ev }];
    commit(list);
    setSelId(cid); setNewId(""); app.toast(t("ntf.added"));
  };
  const removeRecipient = (cid) => {
    const next = recipients.filter((r) => r.cid !== cid);
    if (next.length && cid === selId) setSelId(next[0].cid);
    commit(next); app.toast(t("ntf.removed"));
  };

  const saveBot = () => {
    api.save_notif_settings(token || null, null, brand).then((r) => {
      if (r && r.ok) { app.toast(t("common.saved")); setToken(""); setBotSet(botSet || !!token); }
      else app.toast((r && r.error) || "Save failed");
    });
  };

  return (
    <div className="page" data-screen-label="Notifications">
      <header className="page-head">
        <h1 className="page-h">{t("ntf.title")}</h1>
        <p className="page-sub">{t("ntf.sub")}</p>
      </header>

      <div className="stack">
        <Card title={t("ntf.telegram")} action={<Badge tone={botSet ? "ok" : "muted"}>{botSet ? t("ntf.tokenStatus") : t("common.no")}</Badge>}>
          <div className="g2">
            <Field l={t("ntf.botToken")} hint={t("ntf.botTokenHint")}>
              <input className="inp mono" type="password" placeholder={botSet ? "•••••••• (set — blank keeps it)" : "paste bot token"} value={token} onChange={(e) => setToken(e.target.value)}></input>
            </Field>
            <Field l={t("ntf.brand")}>
              <input className="inp" value={brand} onChange={(e) => setBrand(e.target.value)}></input>
            </Field>
          </div>
          <div className="hstack" style={{ marginTop: 16 }}>
            <Btn variant="primary" onClick={saveBot}>{t("ntf.saveTg")}</Btn>
            <Btn variant="ghost" icon="send" onClick={() => api.telegram_test().then((r) => app.toast(r && r.ok ? t("ntf.testSent") : (r && r.error) || "Failed"))}>{t("ntf.sendTest")}</Btn>
          </div>
        </Card>

        <Card title={t("ntf.recipients")}>
          {recipients.length === 0 ? (
            <p style={{ color: "var(--ink-3)", fontSize: 13, margin: "4px 0 14px" }}>{t("ntf.empty")}</p>
          ) : null}
          <div className="md">
            <div>
              <div className="rcp-list">
                {recipients.map((r) => {
                  const n = Object.values(r.events || {}).filter(Boolean).length;
                  return (
                    <button key={r.cid} className={"rcp" + (r.cid === selId ? " sel" : "")} onClick={() => setSelId(r.cid)}>
                      <span className="rc-ava">{((r.label || "#")[0] || "#").toUpperCase()}</span>
                      <span style={{ minWidth: 0 }}>
                        <span className="rc-name" style={{ display: "block" }}>{r.label || ("Chat " + r.cid.slice(-4))}</span>
                        <span className="rc-id">{r.cid}</span>
                      </span>
                      <span className="rc-count">{n}/{types.length}</span>
                    </button>
                  );
                })}
              </div>
              <div className="hstack" style={{ marginTop: 12 }}>
                <input className="inp mono" placeholder={t("ntf.addPh")} value={newId} onChange={(e) => setNewId(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addRecipient()} style={{ flex: 1 }}></input>
                <Btn variant="ghost" onClick={addRecipient} disabled={!newId.trim()}>{t("ntf.addChat")}</Btn>
              </div>
            </div>

            {sel && (
              <div style={{ borderLeft: "1px solid var(--line)", paddingLeft: 20, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "flex-end", gap: 14, flexWrap: "wrap" }}>
                  <Field l={t("ntf.labelL")} style={{ flex: 1, minWidth: 160 }}>
                    <input className="inp" value={sel.label || ""} onChange={(e) => update(sel.cid, (r) => ({ ...r, label: e.target.value }))}></input>
                  </Field>
                  <Field l={t("ntf.chatId")} style={{ width: 170 }}>
                    <div className="hstack" style={{ gap: 6 }}>
                      <input className="inp mono" value={sel.cid} readOnly style={{ flex: 1 }}></input>
                      <CopyBtn text={sel.cid}></CopyBtn>
                    </div>
                  </Field>
                  <ConfirmBtn variant="danger" icon="trash" label={t("ntf.removeChat")} onConfirm={() => removeRecipient(sel.cid)}></ConfirmBtn>
                </div>

                <div className="sec-l" style={{ marginTop: 20 }}>{t("ntf.receives")}</div>
                <div>
                  {types.map((k) => (
                    <EventRow key={k + sel.cid} k={k} on={!!(sel.events || {})[k]} onToggle={(v) => update(sel.cid, (r) => ({ ...r, events: { ...r.events, [k]: v } }))}></EventRow>
                  ))}
                </div>
                <div style={{ marginTop: 16 }}>
                  <Btn variant="ghost" icon="send" onClick={() => api.send_test_to_chat(sel.cid).then((r) => app.toast(r && r.ok ? t("ntf.testSent") + " → " + (sel.label || sel.cid) : (r && r.error) || "Failed"))}>{t("ntf.sendThis")}</Btn>
                </div>
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

/* ================= CONFIGURATION ================= */
// Sectioned layout mirroring config_store.CONFIG_FIELDS. Values + which keys are
// secret come from api.get_config(); save/import/export round-trip the .env.
const CFG_SECTIONS = [
  { t: "cfg.general", fields: [["BRANCH_ID", "text"], ["DEPLOYMENT_MODE", ["local", "cloud"]], ["PORT", "text"]] },
  { t: "cfg.sync", fields: [["CLOUD_SYNC_URL", "text"], ["SYNC_ENABLED", ["True", "False"]], ["CLOUD_SYNC_TOKEN", "secret"]] },
  { t: "cfg.licensing", fields: [["LICENSE_CONTROL_CENTER_URL", "text"], ["ALPHA_POS_UPDATE_URL", "text"]] },
  { t: "cfg.telegram", fields: [["TELEGRAM_WEBHOOK_SECRET", "secret"]] },
  { t: "cfg.ai", fields: [["AI_PROVIDER", ["claude", "gemini"]], ["ANTHROPIC_API_KEY", "secret"], ["ANTHROPIC_MODEL", "text"], ["GEMINI_API_KEY", "secret"], ["GEMINI_MODEL", "text"]] },
  { t: "cfg.fiscal", hint: "cfg.fiscalHint", fields: [["FISCALIZATION_MODE", ["off", "mock", "sandbox", "live"]], ["FISCAL_PROVIDER", ["mock", "multikassa"]], ["FISCAL_TIN", "text"], ["FISCAL_PROVIDER_URL", "text"], ["FISCAL_VAT_PERCENT", "text"], ["FISCAL_MERCHANT_ID", "text"], ["FISCAL_SECRET", "secret"]] },
];

function parseEnv(text) {
  const out = {};
  (text || "").split(/\r?\n/).forEach((line) => {
    const s = line.trim();
    if (!s || s[0] === "#" || s.indexOf("=") < 0) return;
    const i = s.indexOf("=");
    out[s.slice(0, i).trim()] = s.slice(i + 1).trim();
  });
  return out;
}

function ConfigScreen() {
  const app = useApp();
  const { t } = app;
  const [vals, setVals] = React.useState({});
  const [secrets, setSecrets] = React.useState([]);
  const fileRef = React.useRef(null);

  const load = React.useCallback(() => {
    api.get_config().then((r) => {
      if (r && r.ok) { setVals(r.config || {}); setSecrets(r.secret_keys || []); }
    });
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const set = (k, v) => setVals((o) => ({ ...o, [k]: v }));
  const isSecret = (k) => secrets.indexOf(k) >= 0;

  const save = () => api.save_config(vals).then((r) => app.toast(r && r.ok ? t("cfg.savedToast") + (r.restart_required ? " · " + t("cfg.restart") : "") : (r && r.error) || "Failed"));

  const exportEnv = async () => {
    const r = await api.export_config();
    if (!r || !r.ok) { app.toast("Export failed"); return; }
    const lines = ["# Alpha POS — exported configuration"];
    Object.keys(r.config).sort().forEach((k) => lines.push(k + "=" + (r.config[k] == null ? "" : r.config[k])));
    try {
      const blob = new Blob([lines.join("\n") + "\n"], { type: "text/plain" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = r.filename || "alpha-pos.env";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    } catch (e) {}
    app.toast(t("cfg.exported"));
  };

  const onImportFile = (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const obj = parseEnv(String(reader.result || ""));
      api.import_config(obj).then((r) => {
        if (r && r.ok) { app.toast(t("cfg.imported")); load(); } else app.toast((r && r.error) || "Import failed");
      });
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  const renderField = (key, type) => {
    if (Array.isArray(type)) {
      return (
        <Field l={key} key={key}>
          <select className="inp" value={vals[key] != null ? vals[key] : type[0]} onChange={(e) => set(key, e.target.value)}>
            {type.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </Field>
      );
    }
    const secret = type === "secret" || isSecret(key);
    return (
      <Field l={key} key={key}>
        <input className="inp mono" type={secret ? "password" : "text"} value={vals[key] != null ? vals[key] : ""} placeholder={secret ? "•••••••• (blank keeps it)" : ""} onChange={(e) => set(key, e.target.value)}></input>
      </Field>
    );
  };

  return (
    <div className="page" data-screen-label="Configuration">
      <header className="page-head" style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div>
          <h1 className="page-h">{t("cfg.title")}</h1>
          <p className="page-sub">{t("cfg.sub")}</p>
        </div>
        <div className="hstack">
          <input type="file" accept=".env,text/plain" ref={fileRef} style={{ display: "none" }} onChange={onImportFile}></input>
          <Btn variant="ghost" icon="upload" onClick={() => fileRef.current && fileRef.current.click()}>{t("cfg.import")}</Btn>
          <Btn variant="ghost" icon="download" onClick={exportEnv}>{t("cfg.export")}</Btn>
          <Btn variant="primary" onClick={save}>{t("cfg.saveBtn")}</Btn>
        </div>
      </header>

      <div className="cfg-grid">
        {CFG_SECTIONS.map((sec) => (
          <Card title={t(sec.t)} key={sec.t}>
            {sec.hint ? <p style={{ margin: "0 0 14px", color: "var(--ink-3)", fontSize: 12.5 }}>{t(sec.hint)}</p> : null}
            <div className={sec.fields.length > 1 ? "g2" : "stack"} style={{ gap: 14 }}>
              {sec.fields.map(([k, ty]) => renderField(k, ty))}
            </div>
          </Card>
        ))}

        <Card title={t("cfg.flushT")} tone="warn">
          <p style={{ margin: "0 0 16px", color: "var(--ink-2)", fontSize: 13, textWrap: "pretty" }}>{t("cfg.flushD")}</p>
          <ConfirmBtn variant="warn" icon="refresh" label={t("cfg.flushBtn")} onConfirm={() => api.flush_database(true).then((r) => app.toast(r && r.ok ? t("cfg.flushed") : (r && r.error) || "Failed"))}></ConfirmBtn>
        </Card>

        <Card title={t("cfg.dangerT")} tone="danger">
          <p style={{ margin: "0 0 16px", color: "var(--ink-2)", fontSize: 13, textWrap: "pretty" }}>{t("cfg.dangerD")}</p>
          <ConfirmBtn variant="danger" icon="trash" label={t("cfg.dangerBtn")} onConfirm={() => api.factory_reset(true).then((r) => app.toast(r && r.ok ? (r.message || "Done") : (r && r.error) || "Failed"))}></ConfirmBtn>
        </Card>
      </div>
    </div>
  );
}

Object.assign(window, { NotificationsScreen, ConfigScreen });
