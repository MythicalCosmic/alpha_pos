// Bridge to the local control server. `api.<method>(...args)` POSTs to
// /api/<method> with the args as a JSON array and resolves with the JSON
// result. The per-launch control token is required on every call. Never
// throws — a transport failure resolves to {ok:false, error}.
(function () {
  var TOKEN = window.__CONTROL_TOKEN__ || "";
  window.api = new Proxy({}, {
    get: function (_, name) {
      return function () {
        var args = Array.prototype.slice.call(arguments);
        return fetch("/api/" + name, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Control-Token": TOKEN },
          body: JSON.stringify(args),
        })
          .then(function (r) { return r.json(); })
          .catch(function (e) { return { ok: false, error: String(e) }; });
      };
    },
  });
})();
