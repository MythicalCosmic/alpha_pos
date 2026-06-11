// Screens: Dashboard (server + heartbeat + license + fiscal + sign-in + updates)
// and License & Subscription. Wired to the live control-server bridge.

/* ================= DASHBOARD ================= */
function DashboardScreen() {
  const app = useApp();
  const { t, server, hb, lic, fiscal, updates, adminCreds } = app;
  const [showPwd, setShowPwd] = React.useState(false);

  const phase = server.phase;
  const statusTitle =
    phase === "on" ? t("dash.serverOn") :
    phase === "starting" ? t("dash.starting") :
    phase === "stopping" ? t("dash.stopping") : t("dash.serverOff");
  const statusSub = phase === "on" ? t("dash.serverOnSub") : phase === "off" ? t("dash.serverOffSub") : " ";

  return (
    <div className="page" data-screen-label="Dashboard">
      <header className="page-head">
        <h1 className="page-h">{t("dash.title")}</h1>
        <p className="page-sub">{t("dash.sub")}</p>
      </header>

      <div className="g12">
        {/* Server hero */}
        <Card style={{ gridColumn: "span 7", display: "flex", alignItems: "center" }} label="Server control">
          <div className="hero-wrap" style={{ width: "100%" }}>
            <button
              className={"power" + (phase === "on" ? " on" : "") + (phase === "starting" || phase === "stopping" ? " busy" : "")}
              onClick={server.toggle}
              disabled={phase === "starting" || phase === "stopping"}
              aria-label={phase === "on" ? "Stop server" : "Start server"}
            >
              <span className="power-ring"></span>
              <Icon name="power" size={34}></Icon>
            </button>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="hero-status">{statusTitle}</div>
              <div className="hero-sub">{statusSub}</div>
              <div style={{ marginTop: 14 }}>
                <EpRow l={t("dash.local")} v={"http://127.0.0.1:" + app.cfg.port}></EpRow>
                <EpRow l={t("dash.network")} v={"http://" + app.cfg.lanIp + ":" + app.cfg.port}></EpRow>
                <div className="ep-row">
                  <span className="ep-l">{t("dash.uptime")}</span>
                  <span className="ep-v">{phase === "on" ? server.uptimeStr : "—"}</span>
                </div>
              </div>
            </div>
          </div>
        </Card>

        {/* Heartbeat */}
        <Card
          title={t("dash.heartbeat")}
          style={{ gridColumn: "span 5" }}
          action={<Badge tone={hb.online ? "ok" : "muted"} pulse={hb.online}>{hb.online ? t("common.online") : t("common.offline")}</Badge>}
        >
          <div className="kv">
            <KRow l={t("dash.controlCenter")} v={app.cfg.controlHost} mono></KRow>
            <KRow l={t("dash.lastBeat")} v={hb.lastBeatStr} dim={!hb.online}></KRow>
            <KRow l={t("dash.pending")} v={hb.pending}></KRow>
            <KRow l={t("dash.lastError")} v={t("common.none")} dim></KRow>
          </div>
          <div style={{ marginTop: 14 }}>
            <Btn variant="ghost" size="sm" icon="refresh" onClick={hb.syncNow} disabled={!hb.online}>{t("dash.syncNow")}</Btn>
          </div>
        </Card>

        {/* License */}
        <Card
          title={t("dash.license")}
          style={{ gridColumn: "span 6" }}
          action={<Badge tone={lic.registered ? "ok" : "warn"}>{lic.registered ? t("common.active") : t("common.unregistered")}</Badge>}
        >
          {lic.registered ? (
            <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 36px", alignItems: "end" }}>
              <div>
                <div className="kv-l" style={{ color: "var(--ink-3)", fontSize: 13 }}>{t("dash.balance")}</div>
                <div className="stat-big">{lic.balance}<span className="unit">UZS</span></div>
              </div>
              <div className="kv">
                <KRow l={t("dash.org")} v={lic.org}></KRow>
                <KRow l={t("dash.plan")} v={lic.plan}></KRow>
                <KRow l={t("dash.expires")} v={lic.expires} mono></KRow>
              </div>
              <div style={{ gridColumn: "1 / -1", marginTop: 14 }}>
                <div className="meter"><i style={{ width: lic.pct + "%" }}></i></div>
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 12, color: "var(--ink-3)" }}>
                  <span>{lic.daysLeft} {t("dash.daysLeft")}</span>
                  <button onClick={() => app.nav("license")} style={{ border: 0, background: "none", padding: 0, font: "inherit", fontSize: 12, fontWeight: 600, color: "var(--accent)", cursor: "pointer" }}>{t("common.manage")} →</button>
                </div>
              </div>
            </div>
          ) : (
            <div>
              <div className="kv">
                <KRow l={t("dash.org")} v="—" dim></KRow>
                <KRow l={t("dash.balance")} v="—" dim></KRow>
                <KRow l={t("dash.expires")} v="—" dim></KRow>
              </div>
              <div style={{ marginTop: 14 }}>
                <Btn variant="primary" size="sm" icon="arrow" onClick={() => app.nav("license")}>{t("dash.registerNow")}</Btn>
              </div>
            </div>
          )}
        </Card>

        {/* Fiscalization mini */}
        <Card title={t("dash.fiscal")} style={{ gridColumn: "span 3" }}>
          <div className="kv">
            <KRow l={t("dash.mode")} v={t("fis." + fiscal.mode)}></KRow>
            <KRow l={t("dash.provider")} v={fiscal.provider} mono></KRow>
            <KRow l={t("dash.confirmedFailed")} v={fiscal.confirmed + " / " + fiscal.failed} mono></KRow>
          </div>
          <div style={{ marginTop: 14 }}>
            <Btn variant="ghost" size="sm" onClick={() => app.nav("fiscal")}>{t("common.manage")}</Btn>
          </div>
        </Card>

        {/* POS sign-in (real admin credentials for this PC) */}
        <Card title={t("dash.signin")} style={{ gridColumn: "span 3" }}>
          <div className="kv">
            <KRow l={t("dash.adminEmail")} v={adminCreds.email || "—"} mono></KRow>
            <KRow l={t("dash.password")} v={adminCreds.password ? (showPwd ? adminCreds.password : "••••••••") : "—"} mono></KRow>
          </div>
          <div className="hstack" style={{ marginTop: 14 }}>
            <Btn variant="ghost" size="sm" icon="eye" onClick={() => setShowPwd(!showPwd)} disabled={!adminCreds.password}>{showPwd ? t("dash.hidePwd") : t("dash.showPwd")}</Btn>
            {adminCreds.password ? <CopyBtn text={adminCreds.password}></CopyBtn> : null}
          </div>
        </Card>

        {/* Self-update */}
        <Card
          title={t("upd.title")}
          style={{ gridColumn: "span 12" }}
          action={updates.pending ? <Badge tone="warn">{t("upd.pending")}</Badge> : <Badge tone="ok">v{updates.version}</Badge>}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
            <div className="kv" style={{ flex: 1, minWidth: 260 }}>
              <KRow l={t("upd.version")} v={"v" + updates.version} mono></KRow>
              <KRow l={t("upd.server")} v={updates.url || t("common.none")} mono dim={!updates.url}></KRow>
              <KRow l={t("upd.mode")} v={updates.frozen ? t("upd.installed") : t("upd.dev")}></KRow>
            </div>
            <Btn variant="primary" icon="download" onClick={updates.check}>{t("upd.check")}</Btn>
          </div>
          {updates.pending && <p style={{ margin: "12px 0 0", color: "var(--warn)", fontSize: 13 }}>{t("upd.pendingMsg")}</p>}
        </Card>
      </div>
    </div>
  );
}

/* ================= LICENSE & SUBSCRIPTION ================= */
const PLANS = [
  { v: "Starter", d: "lic.p1d", price: "90 000" },
  { v: "Standard", d: "lic.p2d", price: "150 000" },
  { v: "Pro", d: "lic.p3d", price: "290 000" },
];

function LicenseScreen() {
  const app = useApp();
  const { t, lic, hb } = app;
  const currentPlan = lic.registered ? (String(lic.plan).split(" ")[0] || "Standard") : null;
  const [sel, setSel] = React.useState(currentPlan);
  const [email, setEmail] = React.useState("");

  React.useEffect(() => { setSel(currentPlan); }, [currentPlan]);

  const apply = () => app.activateLicense({ email: email, plan: sel ? sel.toLowerCase() : null });

  return (
    <div className="page" data-screen-label="License & Subscription">
      <header className="page-head">
        <h1 className="page-h">{t("lic.title")}</h1>
        <p className="page-sub">{t("lic.sub")}</p>
      </header>

      <div className="stack">
        <Card
          title={t("lic.current")}
          action={<Badge tone={lic.registered ? "ok" : "warn"}>{lic.registered ? t("common.active") : t("common.unregistered")}</Badge>}
        >
          {lic.registered ? (
            <div>
              <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr 1.2fr", gap: 36, alignItems: "start" }}>
                <div>
                  <div className="kv-l" style={{ fontSize: 13, color: "var(--ink-3)" }}>{t("dash.org")}</div>
                  <div className="stat-big" style={{ fontSize: 26 }}>{lic.org}</div>
                  <div style={{ color: "var(--ink-3)", fontSize: 13, marginTop: 4 }}>{lic.plan}</div>
                </div>
                <div>
                  <div className="kv-l" style={{ fontSize: 13, color: "var(--ink-3)" }}>{t("dash.balance")}</div>
                  <div className="stat-big" style={{ fontSize: 26 }}>{lic.balance}<span className="unit">UZS</span></div>
                </div>
                <div className="kv">
                  <KRow l={t("dash.expires")} v={lic.expires} mono></KRow>
                  <KRow l={t("lic.heartbeat")} v={hb.online ? hb.lastBeatStr : "—"} mono={hb.online} dim={!hb.online}></KRow>
                </div>
              </div>
              <div style={{ marginTop: 20 }}>
                <div className="meter"><i style={{ width: lic.pct + "%" }}></i></div>
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 12, color: "var(--ink-3)" }}>
                  <span>{lic.daysLeft} {t("dash.daysLeft")}</span>
                  <span className="mono">{lic.expires}</span>
                </div>
              </div>
              <div className="hstack" style={{ marginTop: 18 }}>
                <Btn variant="ghost" size="sm" icon="refresh" onClick={hb.syncNow} disabled={!hb.online}>{t("lic.syncNow")}</Btn>
                <ConfirmBtn variant="danger" icon="trash" label={t("lic.deactivate")} onConfirm={app.deactivateLicense}></ConfirmBtn>
              </div>
            </div>
          ) : (
            <div className="g2" style={{ alignItems: "end" }}>
              <Field l={t("lic.email")} hint={t("lic.needsUrl")}>
                <input className="inp" placeholder="you@business.uz" value={email} onChange={(e) => setEmail(e.target.value)}></input>
              </Field>
              <div className="kv">
                <KRow l={t("dash.org")} v="—" dim></KRow>
                <KRow l={t("dash.balance")} v="—" dim></KRow>
              </div>
            </div>
          )}
        </Card>

        <Card title={t("lic.plansT")}>
          <p style={{ margin: "0 0 14px", color: "var(--ink-3)", fontSize: 13 }}>{t("lic.plansHint")}</p>
          <div className="plan-grid">
            {PLANS.map((p) => {
              const isCur = lic.registered && p.v === currentPlan;
              return (
                <button key={p.v} className={"plan" + (sel === p.v ? " sel" : "")} onClick={() => setSel(p.v)}>
                  {isCur && <span className="pl-badge"><Badge tone="ok">{t("lic.currentPlan")}</Badge></span>}
                  <div className="pl-name">{p.v}</div>
                  <div className="pl-desc">{t(p.d)}</div>
                  <div className="pl-price">{p.price} UZS <span className="mo">{t("lic.mo")}</span></div>
                </button>
              );
            })}
          </div>
          <div style={{ marginTop: 18 }}>
            <Btn variant="primary" icon="arrow" disabled={!sel || (lic.registered ? sel === currentPlan : !email)} onClick={apply}>
              {lic.registered ? t("lic.switch") : t("lic.registerBtn")}
            </Btn>
          </div>
        </Card>
      </div>
    </div>
  );
}
Object.assign(window, { DashboardScreen, LicenseScreen });
