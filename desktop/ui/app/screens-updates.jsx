// Screen: Updates — installed version, last-checked / last-updated, the version
// the server advertises, a manual check + install, and the update history.

function fmtWhen(iso, t) {
  if (!iso) return t("upd.never");
  try { return new Date(iso).toLocaleString(); } catch (e) { return iso; }
}

function UpdatesScreen() {
  const app = useApp();
  const { t, updates: u } = app;
  const [busy, setBusy] = React.useState(false);

  const buildMode = !u.frozen ? t("upd.dev") : (u.enabled ? t("upd.installed") : t("upd.disabledMode"));
  const newAvail = !!(u.available && u.available !== u.version);

  const doCheck = async () => { setBusy(true); try { await u.checkOnly(); } finally { setBusy(false); } };
  const doInstall = async () => { setBusy(true); try { await u.install(); } finally { setBusy(false); } };

  return (
    <div className="page" data-screen-label="Updates">
      <header className="page-head">
        <h1 className="page-h">{t("nav.updates")}</h1>
        <p className="page-sub">{t("upd.sub")}</p>
      </header>

      <div className="stack">
        <Card
          title={t("upd.current")}
          action={
            u.pending ? <Badge tone="warn">{t("upd.pending")}</Badge> :
            newAvail ? <Badge tone="warn">{t("upd.newAvailable")}</Badge> :
            <Badge tone="ok">{t("upd.upToDate")}</Badge>
          }
        >
          <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 40px", alignItems: "end" }}>
            <div>
              <div className="kv-l" style={{ fontSize: 13, color: "var(--ink-3)" }}>{t("upd.version")}</div>
              <div className="stat-big">v{u.version}</div>
            </div>
            <div className="kv">
              <KRow l={t("upd.mode")} v={buildMode}></KRow>
              <KRow l={t("upd.server")} v={u.url || t("common.none")} mono dim={!u.url}></KRow>
              <KRow l={t("upd.availableV")} v={u.available ? ("v" + u.available) : t("upd.upToDate")} mono={!!u.available}></KRow>
            </div>
          </div>

          <div className="kv" style={{ marginTop: 16 }}>
            <KRow l={t("upd.lastChecked")} v={fmtWhen(u.lastCheckAt, t)} dim={!u.lastCheckAt}></KRow>
            <KRow
              l={t("upd.lastUpdated")}
              v={u.lastUpdateAt ? (fmtWhen(u.lastUpdateAt, t) + (u.lastUpdateVersion ? "  ·  v" + u.lastUpdateVersion : "")) : t("upd.never")}
              dim={!u.lastUpdateAt}
            ></KRow>
          </div>

          {u.lastCheckError ? <p style={{ margin: "10px 0 0", color: "var(--warn)", fontSize: 12.5 }}>{u.lastCheckError}</p> : null}
          {u.pending ? <p style={{ margin: "10px 0 0", color: "var(--warn)", fontSize: 13 }}>{t("upd.pendingMsg")}</p> : null}

          <div className="hstack" style={{ marginTop: 18 }}>
            <Btn variant="ghost" icon="refresh" onClick={doCheck} disabled={busy}>{busy ? t("upd.checking") : t("upd.checkNow")}</Btn>
            <Btn variant="primary" icon="download" onClick={doInstall} disabled={busy || !newAvail}>{t("upd.installNow")}</Btn>
          </div>
          <p style={{ margin: "12px 0 0", color: "var(--ink-3)", fontSize: 12.5 }}>{t("upd.auto")}</p>
        </Card>

        <Card title={t("upd.history")}>
          {(!u.history || u.history.length === 0) ? (
            <p style={{ color: "var(--ink-3)", fontSize: 13, margin: "2px 0" }}>{t("upd.noHistory")}</p>
          ) : (
            <div className="kv">
              {u.history.slice().reverse().map((h, i) => (
                <KRow key={i} l={fmtWhen(h.at, t)} v={"v" + h.version} mono></KRow>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
Object.assign(window, { UpdatesScreen });
