/* Время обхода: серверная исходная точка + монотонное время открытого экрана.
 * Завершённый результат берём только из duration_seconds, не считаем заново.
 * Собственный observer видит штатную замену содержимого #walk; внутренний
 * state/draft и порядок вызова render() остальных модулей не меняются.
 */
(function () {
  "use strict";
  var W = window.DecimusWalk;
  var root = W.root;
  var seen = null;
  var anchor = null;
  var timer = null;

  function stop() {
    if (timer !== null) window.clearInterval(timer);
    timer = null;
  }

  /** Сервер присылает UTC ISO. Не принимать локальные часы и нормализованные даты. */
  function stamp(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)) return null;
    var n = Date.parse(value);
    if (!Number.isFinite(n) || new Date(n).toISOString().slice(0, 19) !== value.slice(0, 19)) return null;
    return n;
  }

  function elapsed(seconds) {
    var n = Math.floor(seconds);
    function pad(v) { return String(v).padStart(2, "0"); }
    return pad(Math.floor(n / 3600)) + ":" + pad(Math.floor(n / 60) % 60) + ":" + pad(n % 60);
  }

  function unknown(box, key) {
    box.textContent = W.tx(key);
    box.classList.add("is-unknown");
  }

  function refresh() {
    stop();
    var d = W.state.data;
    var t = d && d.timing;
    var mount = root.querySelector(".walk-top");
    if (!mount && W.app && W.app.route === "home") mount = root.querySelector(".walk-app__card");
    if (!mount || !t) return;
    var old = mount.querySelector(".walk-timing");
    if (old) old.remove();
    var box = W.el("p", "walk-timing");
    mount.insertBefore(box, mount.children[1] || null);
    if (t.started_at === null || t.started_at === undefined) { unknown(box, "walk.timing.unknown"); return; }
    var start = stamp(t.started_at);
    var finished = t.finished_at !== null && t.finished_at !== undefined;
    var end = finished ? stamp(t.finished_at) : null;
    var finalSeconds = t.duration_seconds;
    var active = !finished && d.state === "active" && !d.sealed;
    if (start === null || (finished && (end === null || end < start || typeof finalSeconds !== "number" || !Number.isFinite(finalSeconds) || finalSeconds < 0)) || (!finished && !active)) {
      unknown(box, "walk.timing.unavailable");
      return;
    }
    if (active && t !== seen) {
      seen = t;
      var server = stamp(t.server_now);
      var now = window.performance && performance.now ? performance.now() : NaN;
      anchor = server === null || server < start || !Number.isFinite(now) ? null : { seconds: (server - start) / 1000, at: now };
    }
    if (active && !anchor) { unknown(box, "walk.timing.unavailable"); return; }
    box.appendChild(W.el("span", "walk-timing__label", W.tx(active ? "walk.timing.active" : "walk.timing.finished")));
    var value = W.el("span", "walk-timing__value");
    value.setAttribute("role", "timer");
    value.setAttribute("aria-live", "off");
    box.appendChild(value);
    function update() {
      if (!box.isConnected) { stop(); return; }
      var delta = active ? (performance.now() - anchor.at) / 1000 : 0;
      if (!Number.isFinite(delta) || delta < 0) { stop(); unknown(box, "walk.timing.unavailable"); return; }
      value.textContent = (active ? "≈ " : "") + elapsed(active ? anchor.seconds + delta : finalSeconds);
    }
    update();
    if (active && !box.classList.contains("is-unknown")) timer = window.setInterval(update, 1000);
  }

  var observer = new MutationObserver(refresh);
  observer.observe(root, { childList: true });
  window.addEventListener("pagehide", stop);
  window.addEventListener("pageshow", refresh);
  refresh();
})();
