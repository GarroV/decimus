/* Мини-апп обхода: общее для всех частей экрана (#418, D312).
 *
 * Части подключаются по порядку (`walk.html`): core → photo → sheet → walk.
 * Общаются через одно пространство имён `window.DecimusWalk`, а не через
 * глобальные переменные: так видно, кто чем пользуется.
 *
 * Что здесь решено:
 * - строки — только из ответа сервера (`texts`), своих в скриптах нет;
 * - разметка — через textContent, без innerHTML: формулировки приходят из
 *   слов аудитора и методики, а не из нашего кода;
 * - подписанная строка Telegram уходит заголовком: тело занято кадром или
 *   JSON, а в адресе она осела бы в журналах прокси.
 */
(function () {
  "use strict";

  var tg = window.Telegram && window.Telegram.WebApp;
  var root = document.getElementById("walk");
  var W = (window.DecimusWalk = window.DecimusWalk || {});

  W.tg = tg;
  W.root = root;
  W.state = { data: null, marks: { z: [], f: [] }, open: null };
  W.urls = {
    data: root.getAttribute("data-endpoint"),
    photo: root.getAttribute("data-photo"),
    photoView: root.getAttribute("data-photo-view"),
    finding: root.getAttribute("data-finding"),
    info: root.getAttribute("data-info"),
    suggest: root.getAttribute("data-suggest"),
    app: root.getAttribute("data-app"),
  };

  W.inTelegram = function () { return !!(tg && tg.initData); };

  W.supports = function (version) {
    return !!(tg && tg.initData && tg.isVersionAtLeast && tg.isVersionAtLeast(version));
  };

  W.tx = function (key, params) {
    var d = W.state.data;
    var s = (d && d.texts && d.texts[key]) || key;
    Object.keys(params || {}).forEach(function (p) { s = s.split("{" + p + "}").join(String(params[p])); });
    return s;
  };

  W.el = function (tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  };

  W.button = function (cls, text, onClick) {
    var b = W.el("button", cls, text);
    b.type = "button";
    if (onClick) b.addEventListener("click", onClick);
    return b;
  };

  W.level = function (code) {
    return W.el("span", "walk-level walk-level--" + String(code).toLowerCase(), code);
  };

  W.haptic = function (kind) {
    if (!tg || !tg.HapticFeedback) return;
    if (kind === "success" || kind === "error") tg.HapticFeedback.notificationOccurred(kind);
    else tg.HapticFeedback.impactOccurred("light");
  };

  W.day = function (iso) {
    var d = new Date(iso + "T12:00:00");
    try {
      return d.toLocaleDateString(W.state.data.lang, { day: "numeric", month: "long" });
    } catch (e) {
      return iso;
    }
  };

  /* ── сервер ────────────────────────────────────────────────────────── */

  /** POST с подписью Telegram. Ответ — { ok, status, body } или отказ сети. */
  W.post = function (url, body, contentType) {
    var headers = { "X-Telegram-Init-Data": (tg && tg.initData) || "" };
    headers["Content-Type"] = contentType || "application/json";
    return fetch(url, {
      method: "POST",
      headers: headers,
      body: contentType ? body : JSON.stringify(body),
      credentials: "omit",
    }).then(function (r) {
      var type = r.headers.get("Content-Type") || "";
      if (type.indexOf("application/json") === -1) {
        return r.blob().then(function (blob) { return { ok: r.ok, status: r.status, body: blob }; });
      }
      return r.json().then(function (json) { return { ok: r.ok, status: r.status, body: json }; });
    });
  };

  /* ── черновик и личные пометки: per-viewer, переживают закрытие окна ── */

  W.local = {
    get: function (key) {
      try { return JSON.parse(window.localStorage.getItem(key) || "null"); } catch (e) { return null; }
    },
    set: function (key, value) {
      try { window.localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* живёт до закрытия */ }
    },
    drop: function (key) {
      try { window.localStorage.removeItem(key); } catch (e) { /* нечего снимать */ }
    },
  };

  /* ── всплывающая строка «Записано» / отказ ─────────────────────────── */

  var toastTimer = null;
  W.toast = function (text, tone) {
    var node = document.getElementById("walk-toast");
    if (!node) {
      node = W.el("div", "walk-toast");
      node.id = "walk-toast";
      node.setAttribute("role", "status");
      document.body.appendChild(node);
    }
    node.textContent = text;
    node.className = "walk-toast is-shown" + (tone ? " walk-toast--" + tone : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { node.className = "walk-toast"; }, 2600);
  };
})();
