// App shell: titlebar, sidebar, routing, theme/language, and the live wiring to
// the control-server bridge (window.api). Replaces the design prototype's
// simulated state with real calls to desktop/bridge.py.

const DIRECTIONS = ["Porcelain", "Noir", "Atelier"];
const ACCENTS = ["#1e6b4c", "#27486e", "#8a4a2c", "#5b4a7a"];

const NAV = [
  { id: "dashboard", icon: "dashboard", l: "nav.dashboard", screen: () => <DashboardScreen /> },
  { id: "license", icon: "license", l: "nav.license", screen: () => <LicenseScreen /> },
  { id: "notifications", icon: "bell", l: "nav.notifications", screen: () => <NotificationsScreen /> },
  { id: "config", icon: "sliders", l: "nav.config", screen: () => <ConfigScreen /> },
  { id: "tests", icon: "flask", l: "nav.tests", screen: () => <TestsScreen /> },
  { id: "fiscal", icon: "receipt", l: "nav.fiscal", screen: () => <FiscalScreen /> },
];

function fmtClock(d) {
  if (!d) return "—";
  const z = (n) => String(n).padStart(2, "0");
  return z(d.getHours()) + ":" + z(d.getMinutes()) + ":" + z(d.getSeconds());
}
function fmtUptime(s) {
  const z = (n) => String(n).padStart(2, "0");
  return z(Math.floor(s / 3600)) + ":" + z(Math.floor((s % 3600) / 60)) + ":" + z(s % 60);
}
function daysBetween(iso) {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (isNaN(then)) return null;
  return Math.max(0, Math.round((then - Date.now()) / 86400000));
}

function App() {
  /* ---------- look (persisted via the bridge) ---------- */
  const [dir, setDirRaw] = React.useState("porcelain");
  const [accent, setAccentRaw] = React.useState(ACCENTS[0]);
  const [lang, setLangRaw] = React.useState("en");
  const prefsLoaded = React.useRef(false);

  React.useEffect(() => {
    api.get_ui_prefs().then((r) => {
      const p = (r && r.prefs) || {};
      if (p.dir) setDirRaw(p.dir);
      if (p.accent) setAccentRaw(p.accent);
      if (p.lang) setLangRaw(p.lang);
      prefsLoaded.current = true;
    });
  }, []);
  const persist = (patch) => { if (prefsLoaded.current) api.set_ui_prefs(patch); };
  const setDir = (v) => { const d = v.toLowerCase(); setDirRaw(d); persist({ dir: d }); };
  const setAccent = (v) => { setAccentRaw(v); persist({ accent: v }); };
  const setLang = (v) => { const l = v.toLowerCase(); setLangRaw(l); persist({ lang: l }); };

  const t = React.useCallback((k) => window.tr(lang, k), [lang]);

  React.useEffect(() => { document.documentElement.setAttribute("data-dir", dir); }, [dir]);
  React.useEffect(() => {
    if (dir === "porcelain" && accent) document.documentElement.style.setProperty("--accent", accent);
    else document.documentElement.style.removeProperty("--accent");
  }, [dir, accent]);

  /* ---------- navigation + clock ---------- */
  const [page, setPage] = React.useState("dashboard");
  const [tick, setTick] = React.useState(0);
  React.useEffect(() => {
    const id = setInterval(() => setTick((x) => x + 1), 1000);
    return () => clearInterval(id);
  }, []);

  /* ---------- toasts ---------- */
  const [toasts, setToasts] = React.useState([]);
  const toast = (msg) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((ts) => [...ts, { id, msg }]);
    setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), 2600);
  };

  /* ---------- live backend state ---------- */
  const [srv, setSrv] = React.useState({ running: false, port: 8000, lan_ip: "127.0.0.1" });
  const [phase, setPhase] = React.useState("off"); // off | starting | on | stopping
  const [lic, setLic] = React.useState(null);
  const [fiscal, setFiscal] = React.useState({ mode: "off", provider: "mock", confirmed: 0, failed: 0 });
  const [creds, setCreds] = React.useState({ email: "", password: "" });
  const [upd, setUpd] = React.useState({ version: "1.0.0", update_url: "", pending: false, frozen: false });
  const onSinceRef = React.useRef(null);

  const refreshServer = React.useCallback(() => {
    return api.server_status().then((r) => {
      if (!r || r.ok === false) return;
      setSrv(r);
      setPhase((ph) => (ph === "starting" || ph === "stopping") ? ph : (r.running ? "on" : "off"));
      if (r.running && onSinceRef.current == null) onSinceRef.current = Date.now();
      if (!r.running) onSinceRef.current = null;
    });
  }, []);
  const refreshLicense = React.useCallback(() => api.license_status().then((r) => { if (r && r.license) setLic(r.license); }), []);
  const refreshFiscal = React.useCallback(() => api.fiscal_status().then((r) => { if (r && r.fiscal) setFiscal((f) => ({ ...f, ...r.fiscal })); }), []);
  const refreshCreds = React.useCallback(() => api.admin_credentials().then((r) => { if (r && r.ok) setCreds({ email: r.email, password: r.password }); }), []);
  const refreshUpdates = React.useCallback(() => api.update_status().then((r) => { if (r && r.ok) setUpd(r); }), []);
  const refreshAll = React.useCallback(() => {
    refreshServer(); refreshLicense(); refreshFiscal(); refreshCreds(); refreshUpdates();
  }, [refreshServer, refreshLicense, refreshFiscal, refreshCreds, refreshUpdates]);

  React.useEffect(() => { refreshAll(); }, [refreshAll]);
  // Poll the server status often (drives the power button); the rest slowly.
  React.useEffect(() => {
    if (tick > 0 && tick % 4 === 0) refreshServer();
    if (tick > 0 && tick % 20 === 0) { refreshLicense(); refreshUpdates(); }
  }, [tick, refreshServer, refreshLicense, refreshUpdates]);

  /* ---------- server control ---------- */
  const toggleServer = async () => {
    if (phase === "on") {
      setPhase("stopping");
      await api.stop_server();
      onSinceRef.current = null;
      setPhase("off"); refreshServer();
    } else if (phase === "off") {
      setPhase("starting");
      await api.run_setup();
      const r = await api.start_server();
      if (r && r.running) { onSinceRef.current = Date.now(); setPhase("on"); toast(t("dash.serverOn")); }
      else { setPhase("off"); toast((r && r.error) || "Start failed"); }
      refreshAll();
    }
  };

  const uptime = onSinceRef.current ? Math.floor((Date.now() - onSinceRef.current) / 1000) : 0;

  /* ---------- license derived ---------- */
  const registered = !!(lic && lic.status === "ACTIVE");
  const daysLeft = lic ? (lic.days_remaining != null ? lic.days_remaining : daysBetween(lic.expires_at)) : null;
  const pct = daysLeft != null ? Math.max(0, Math.min(100, Math.round((daysLeft / 365) * 100))) : 0;

  const activateLicense = async (over) => {
    const r = await api.license_register(over.email || (lic && lic.email) || "", over.plan || null);
    if (r && r.ok) toast(t("lic.registered")); else toast((r && (r.data && r.data.message)) || t("lic.needsUrl"));
    refreshLicense();
  };
  const deactivateLicense = async () => {
    await api.license_deactivate();
    toast(t("lic.deactivated"));
    refreshLicense();
  };
  const heartbeatNow = async () => {
    const r = await api.license_heartbeat_now();
    toast(r && r.ok ? t("common.justNow") + " · " + t("lic.heartbeat") + " ✓" : t("dash.lastError"));
    refreshLicense();
  };

  /* ---------- fiscal ---------- */
  const setFisMode = async (m) => { setFiscal((f) => ({ ...f, mode: m })); await api.fiscal_set_mode(m); refreshFiscal(); };
  const bumpConfirmed = () => { api.fiscal_test().then(() => refreshFiscal()); };

  const lastBeat = lic && lic.last_heartbeat_at ? new Date(lic.last_heartbeat_at) : null;

  const ctx = {
    t, lang, toast, nav: setPage,
    cfg: { port: srv.port || 8000, lanIp: srv.lan_ip || "127.0.0.1", controlHost: upd.update_url ? upd.update_url.replace(/^https?:\/\//, "").replace(/\/.*$/, "") : (lic && lic.email ? "control center" : "—") },
    server: { phase, toggle: toggleServer, uptimeStr: fmtUptime(uptime) },
    hb: {
      online: phase === "on",
      pending: 0,
      nextIn: 30 - (tick % 30),
      lastBeatStr: lastBeat ? fmtClock(lastBeat) : "—",
      syncNow: heartbeatNow,
    },
    lic: {
      registered,
      org: (lic && lic.org_name) || "—",
      plan: (lic && lic.plan) || (registered ? "Licensed" : "—"),
      expires: (lic && lic.expires_at) ? lic.expires_at.slice(0, 10) : "—",
      daysLeft: daysLeft != null ? daysLeft : "—",
      pct,
      balance: (lic && lic.balance != null) ? lic.balance : "—",
      status: lic && lic.status,
    },
    fiscal: { mode: fiscal.mode, setMode: setFisMode, provider: fiscal.provider || "mock", confirmed: fiscal.confirmed || 0, failed: fiscal.failed || 0, bumpConfirmed },
    adminCreds: creds,
    updates: { version: upd.version, url: upd.update_url, pending: upd.pending, frozen: upd.frozen, check: async () => { const r = await api.check_updates_now(); toast((r && r.message) || ""); refreshUpdates(); } },
    activateLicense, deactivateLicense, refreshAll,
  };

  const active = NAV.find((n) => n.id === page) || NAV[0];

  return (
    <AppCtx.Provider value={ctx}>
      <div className="apb">
        <div className="titlebar">
          <div className="tb-app"><span className="tb-glyph">α</span>Alpha POS Backend</div>
          <div className="tb-spacer"></div>
          <div className="tb-win">
            <button aria-label="Minimize" onClick={() => window.pywebview && window.pywebview.api && null}><svg width="11" height="11" viewBox="0 0 11 11"><path d="M1 5.5h9" stroke="currentColor" strokeWidth="1.2"></path></svg></button>
            <button aria-label="Maximize"><svg width="11" height="11" viewBox="0 0 11 11"><rect x="1.5" y="1.5" width="8" height="8" fill="none" stroke="currentColor" strokeWidth="1.2"></rect></svg></button>
            <button className="tb-close" aria-label="Close" onClick={() => window.close()}><svg width="11" height="11" viewBox="0 0 11 11"><path d="M1.5 1.5l8 8m0-8l-8 8" stroke="currentColor" strokeWidth="1.2"></path></svg></button>
          </div>
        </div>

        <div className="frame">
          <aside className="sidebar">
            <div className="wordmark">
              <div className="wm-name">Alpha POS</div>
              <div className="wm-sub">Backend</div>
            </div>
            <nav className="nav">
              {NAV.map((n) => (
                <button key={n.id} className={"nav-item" + (n.id === page ? " active" : "")} onClick={() => setPage(n.id)}>
                  <Icon name={n.icon}></Icon>{t(n.l)}
                </button>
              ))}
            </nav>
            <div className="side-foot">
              <div className="side-server">
                <span className="dot" style={{ color: phase === "on" ? "var(--ok)" : "var(--ink-3)", background: "currentColor" }}></span>
                <span style={{ flex: 1 }}>{phase === "on" ? t("common.online") : t("common.offline")}</span>
                {phase === "on" && <span className="mono" style={{ fontSize: 11.5, color: "var(--ink-3)" }}>:{srv.port}</span>}
              </div>
              <div className="lang-seg">
                {["EN", "UZ", "RU"].map((L) => (
                  <button key={L} className={lang === L.toLowerCase() ? "active" : ""} onClick={() => setLang(L)}>{L}</button>
                ))}
              </div>
              <ThemeSwitch dir={dir} setDir={setDir} accent={accent} setAccent={setAccent} t={t}></ThemeSwitch>
              <div className="side-ver">v{upd.version} · single-PC install</div>
            </div>
          </aside>

          <main className="main">
            <React.Fragment key={page + lang}>{active.screen()}</React.Fragment>
          </main>
        </div>

        <div className="toast-wrap">
          {toasts.map((x) => (<div key={x.id} className="toast"><span className="dot"></span>{x.msg}</div>))}
        </div>
      </div>
    </AppCtx.Provider>
  );
}

/* Compact theme switcher in the sidebar foot (replaces the prototype's floating
   tweaks panel). Direction + (for Porcelain) accent. */
function ThemeSwitch({ dir, setDir, accent, setAccent, t }) {
  return (
    <div className="theme-switch">
      <div className="ts-seg">
        {DIRECTIONS.map((d) => (
          <button key={d} className={dir === d.toLowerCase() ? "active" : ""} title={d} onClick={() => setDir(d)}>{d[0]}</button>
        ))}
      </div>
      {dir === "porcelain" && (
        <div className="ts-accents">
          {ACCENTS.map((c) => (
            <button key={c} className={"ts-acc" + (accent === c ? " on" : "")} style={{ background: c }} onClick={() => setAccent(c)} aria-label={"Accent " + c}></button>
          ))}
        </div>
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App></App>);
