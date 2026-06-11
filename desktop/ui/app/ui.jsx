// Shared UI primitives + icon set for Alpha POS Backend
const AppCtx = React.createContext(null);
const useApp = () => React.useContext(AppCtx);

/* ---------- Icons (1.5px stroke, 18px default) ---------- */
function Icon({ name, size = 17 }) {
  const p = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round", strokeLinejoin: "round" };
  const paths = {
    dashboard: <g {...p}><rect x="3" y="3" width="7" height="7" rx="1.5"></rect><rect x="14" y="3" width="7" height="7" rx="1.5"></rect><rect x="3" y="14" width="7" height="7" rx="1.5"></rect><rect x="14" y="14" width="7" height="7" rx="1.5"></rect></g>,
    license: <g {...p}><circle cx="8.5" cy="9" r="4.5"></circle><path d="M11.7 12.2 20 20.5M16 16.5l2-2M13.5 14l1.8-1.8"></path></g>,
    bell: <g {...p}><path d="M18 9a6 6 0 1 0-12 0c0 5-2 6-2 6h16s-2-1-2-6"></path><path d="M10.3 19a2 2 0 0 0 3.4 0"></path></g>,
    sliders: <g {...p}><path d="M4 7h10M18 7h2M4 12h2M10 12h10M4 17h10M18 17h2"></path><circle cx="16" cy="7" r="2"></circle><circle cx="8" cy="12" r="2"></circle><circle cx="16" cy="17" r="2"></circle></g>,
    flask: <g {...p}><path d="M10 3v6L4.7 17.6A2 2 0 0 0 6.4 21h11.2a2 2 0 0 0 1.7-3.4L14 9V3"></path><path d="M8.5 3h7M7.5 14h9"></path></g>,
    receipt: <g {...p}><path d="M5 3h14v18l-2.3-1.5L14.4 21l-2.4-1.5L9.6 21l-2.3-1.5L5 21V3z"></path><path d="M9 8h6M9 12h6"></path></g>,
    power: <g {...p} strokeWidth="2"><path d="M12 3v8"></path><path d="M6.3 6.5a8 8 0 1 0 11.4 0"></path></g>,
    copy: <g {...p}><rect x="9" y="9" width="11" height="11" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></g>,
    check: <g {...p} strokeWidth="2"><path d="M4.5 12.5 10 18 19.5 6.5"></path></g>,
    refresh: <g {...p}><path d="M20 11a8 8 0 0 0-15.3-2M4 13a8 8 0 0 0 15.3 2"></path><path d="M4 5v4h4M20 19v-4h-4"></path></g>,
    eye: <g {...p}><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"></path><circle cx="12" cy="12" r="2.8"></circle></g>,
    send: <g {...p}><path d="M21 3 10.5 13.5M21 3l-7 18-3.5-7.5L3 10l18-7z"></path></g>,
    arrow: <g {...p}><path d="M5 12h14M13 6l6 6-6 6"></path></g>,
    warn: <g {...p}><path d="M12 3 2.5 20h19L12 3z"></path><path d="M12 10v4.5M12 17.5v.2"></path></g>,
    trash: <g {...p}><path d="M4 7h16M9 7V5a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 5v2M6.5 7l1 13h9l1-13"></path></g>,
    globe: <g {...p}><circle cx="12" cy="12" r="9"></circle><path d="M3 12h18M12 3c2.7 2.6 4 5.8 4 9s-1.3 6.4-4 9c-2.7-2.6-4-5.8-4-9s1.3-6.4 4-9z"></path></g>,
    download: <g {...p}><path d="M12 3v11M7.5 10.5 12 15l4.5-4.5"></path><path d="M4 17v2.5A1.5 1.5 0 0 0 5.5 21h13a1.5 1.5 0 0 0 1.5-1.5V17"></path></g>,
    upload: <g {...p}><path d="M12 14V3M7.5 7.5 12 3l4.5 4.5"></path><path d="M4 17v2.5A1.5 1.5 0 0 0 5.5 21h13a1.5 1.5 0 0 0 1.5-1.5V17"></path></g>,
    heart: <g {...p}><path d="M3 12h4l2-5 3.5 10L15 9l1.5 3H21"></path></g>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">{paths[name] || null}</svg>;
}

/* ---------- Primitives ---------- */
function Card({ title, action, children, tone, style, label }) {
  return (
    <section className={"card" + (tone ? " tone-" + tone : "")} style={style} aria-label={label || title}>
      {(title || action) && (
        <div className="card-head">
          <h3 className="card-t">{title}</h3>
          {action || null}
        </div>
      )}
      {children}
    </section>
  );
}

function KRow({ l, v, mono, dim, badge }) {
  return (
    <div className="kv-row">
      <span className="kv-l">{l}</span>
      {badge ? badge : <span className={"kv-v" + (mono ? " mono" : "") + (dim ? " dim" : "")}>{v}</span>}
    </div>
  );
}

function Badge({ tone = "muted", children, pulse }) {
  return (
    <span className={"badge " + tone}>
      <i className={"dot" + (pulse ? " pulse" : "")}></i>
      {children}
    </span>
  );
}

function Btn({ variant = "ghost", size, icon, children, ...rest }) {
  return (
    <button className={"btn btn-" + variant + (size ? " btn-" + size : "")} {...rest}>
      {icon ? <Icon name={icon} size={15}></Icon> : null}
      {children}
    </button>
  );
}

function Field({ l, hint, children, style }) {
  return (
    <label className="field" style={style}>
      {l ? <span className="field-l">{l}</span> : null}
      {children}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}

function Seg({ options, value, onChange }) {
  return (
    <div className="seg" role="tablist">
      {options.map((o) => (
        <button key={o.v} className={o.v === value ? "active" : ""} onClick={() => onChange(o.v)} role="tab" aria-selected={o.v === value}>
          {o.l}
        </button>
      ))}
    </div>
  );
}

function Switch({ on, onChange }) {
  return <button className={"switch" + (on ? " on" : "")} onClick={() => onChange(!on)} role="switch" aria-checked={on}></button>;
}

function CopyBtn({ text }) {
  const [copied, setCopied] = React.useState(false);
  const app = useApp();
  return (
    <button
      className={"copy-btn" + (copied ? " copied" : "")}
      title={app.t("common.copy")}
      onClick={() => {
        try { navigator.clipboard && navigator.clipboard.writeText(text); } catch (e) {}
        setCopied(true);
        app.toast(app.t("common.copied"));
        setTimeout(() => setCopied(false), 1600);
      }}
    >
      <Icon name={copied ? "check" : "copy"} size={14}></Icon>
    </button>
  );
}

function EpRow({ l, v, copy }) {
  return (
    <div className="ep-row">
      <span className="ep-l">{l}</span>
      <span className="ep-v">{v}</span>
      {copy !== false ? <CopyBtn text={String(v)}></CopyBtn> : null}
    </div>
  );
}

/* Confirm-twice button for destructive actions */
function ConfirmBtn({ variant, icon, label, onConfirm }) {
  const app = useApp();
  const [armed, setArmed] = React.useState(false);
  React.useEffect(() => {
    if (!armed) return;
    const id = setTimeout(() => setArmed(false), 3000);
    return () => clearTimeout(id);
  }, [armed]);
  return (
    <Btn
      variant={variant}
      icon={icon}
      onClick={() => {
        if (armed) { setArmed(false); onConfirm(); }
        else setArmed(true);
      }}
    >
      {armed ? app.t("common.confirm") : label}
    </Btn>
  );
}

Object.assign(window, { AppCtx, useApp, Icon, Card, KRow, Badge, Btn, Field, Seg, Switch, CopyBtn, EpRow, ConfirmBtn });
