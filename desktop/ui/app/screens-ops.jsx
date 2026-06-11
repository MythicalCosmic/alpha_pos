// Screens: Tests (real self-tests via the bridge) + Fiscalization.

/* ================= TESTS ================= */
// Each tile maps to a real bridge method; running it times the call and shows
// OK / failed with the round-trip in ms.
const LOCAL_TESTS = [
  { name: "tests.t1", icon: "power", method: "test_server_connection" },
  { name: "tests.t2", icon: "arrow", method: "send_mock_sync" },
  { name: "tests.t3", icon: "copy", method: "fetch_mock_sync" },
  { name: "tests.t4", icon: "send", method: "telegram_test" },
  { name: "tests.t5", icon: "bell", method: "send_fake_notification" },
  { name: "tests.t6", icon: "receipt", method: "fiscal_test" },
];
const CLOUD_TESTS = [
  { name: "tests.t7", icon: "globe", method: "cloud_test_connection" },
  { name: "tests.t8", icon: "refresh", method: "cloud_sync_now" },
  { name: "tests.t9", icon: "flask", method: "cloud_pull" },
];

function TestTile({ test, state, onRun }) {
  const app = useApp();
  const running = state === "running";
  const done = state && state !== "running";
  const ok = done && state.ok;
  return (
    <div className={"tile" + (done && ok ? " pass" : "") + (done && !ok ? " fail" : "")}>
      <span className="ti-ico"><Icon name={test.icon} size={17}></Icon></span>
      <div className="ti-name">{app.t(test.name)}</div>
      <div className="ti-desc">{app.t(test.name + "d")}</div>
      <div className="ti-foot">
        <span className="ti-res">
          {running && <span className="spinner"></span>}
          {done && (<React.Fragment><Icon name={ok ? "check" : "warn"} size={13}></Icon>{ok ? "OK" : (app.t("tests.failed") || "FAIL")} · {state.ms} ms</React.Fragment>)}
        </span>
        <Btn variant="ghost" size="sm" onClick={onRun} disabled={running}>{app.t("common.run")}</Btn>
      </div>
    </div>
  );
}

function TestsScreen() {
  const app = useApp();
  const { t } = app;
  const [results, setResults] = React.useState({});
  const all = [...LOCAL_TESTS, ...CLOUD_TESTS];

  const run = (tt) => {
    setResults((r) => ({ ...r, [tt.name]: "running" }));
    const start = (window.performance && performance.now) ? performance.now() : Date.now();
    api[tt.method]().then((res) => {
      const ms = Math.round(((window.performance && performance.now) ? performance.now() : Date.now()) - start);
      const ok = !!(res && res.ok !== false);
      setResults((r) => ({ ...r, [tt.name]: { ok, ms } }));
    });
  };
  const runAll = () => all.forEach((tt, i) => setTimeout(() => run(tt), i * 250));
  const passedCount = all.filter((tt) => { const s = results[tt.name]; return s && s !== "running" && s.ok; }).length;

  return (
    <div className="page" data-screen-label="Tests">
      <header className="page-head" style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 16 }}>
        <div>
          <h1 className="page-h">{t("tests.title")}</h1>
          <p className="page-sub">{t("tests.sub")}</p>
        </div>
        <div className="hstack">
          {passedCount > 0 && <span className="mono" style={{ fontSize: 12.5, color: "var(--ok)" }}>{passedCount} / {all.length} {t("tests.passed")}</span>}
          <Btn variant="primary" icon="flask" onClick={runAll}>{t("common.runAll")}</Btn>
        </div>
      </header>

      <div className="sec-l">{t("tests.local")}</div>
      <div className="tile-grid">
        {LOCAL_TESTS.map((tt) => <TestTile key={tt.name} test={tt} state={results[tt.name]} onRun={() => run(tt)}></TestTile>)}
      </div>

      <div className="sec-l" style={{ marginTop: 28 }}>{t("tests.cloud")}</div>
      <p style={{ margin: "0 0 12px", color: "var(--ink-3)", fontSize: 13, maxWidth: "78ch", textWrap: "pretty" }}>{t("tests.cloudHint")}</p>
      <div className="tile-grid">
        {CLOUD_TESTS.map((tt) => <TestTile key={tt.name} test={tt} state={results[tt.name]} onRun={() => run(tt)}></TestTile>)}
      </div>
    </div>
  );
}

/* ================= FISCALIZATION ================= */
function FiscalScreen() {
  const app = useApp();
  const { t, fiscal } = app;
  const [testing, setTesting] = React.useState(false);

  const runTest = () => {
    setTesting(true);
    api.fiscal_test().then((r) => {
      setTesting(false);
      fiscal.bumpConfirmed();
      app.toast(r && r.ok ? t("fis.testOk") : (r && r.error) || "Failed");
    });
  };

  const yn = (v) => <Badge tone={v ? "ok" : "muted"}>{v ? t("common.yes") : t("common.no")}</Badge>;

  return (
    <div className="page" data-screen-label="Fiscalization">
      <header className="page-head">
        <h1 className="page-h">{t("fis.title")} <span style={{ color: "var(--ink-3)" }}>· Soliq</span></h1>
        <p className="page-sub">{t("fis.sub")}</p>
      </header>

      <div className="g12">
        <Card title={t("fis.mode")} style={{ gridColumn: "span 6" }}>
          <Seg
            value={fiscal.mode}
            onChange={fiscal.setMode}
            options={[
              { v: "off", l: t("fis.off") },
              { v: "mock", l: t("fis.mock") },
              { v: "sandbox", l: t("fis.sandbox") },
              { v: "live", l: t("fis.live") },
            ]}
          ></Seg>
          <div style={{ marginTop: 18 }}>
            <Btn variant="primary" icon="receipt" onClick={runTest} disabled={testing}>{testing ? t("common.running") : t("fis.runTest")}</Btn>
          </div>
        </Card>

        <Card title={t("fis.status")} style={{ gridColumn: "span 6" }}>
          <div className="kv">
            <KRow l={t("fis.enabled")} badge={yn(fiscal.mode !== "off")}></KRow>
            <KRow l={t("fis.provider")} v={fiscal.provider} mono></KRow>
            <KRow l={t("fis.cf")} v={fiscal.confirmed + " / " + fiscal.failed} mono></KRow>
          </div>
        </Card>
      </div>
    </div>
  );
}

Object.assign(window, { TestsScreen, FiscalScreen });
