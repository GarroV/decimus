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
    hint: root.getAttribute("data-hint"),
    translate: root.getAttribute("data-translate"),
    voice: root.getAttribute("data-voice"),
    app: root.getAttribute("data-app"),
    start: root.getAttribute("data-start"),
  };

  W.inTelegram = function () { return !!(tg && tg.initData); };

  W.supports = function (version) {
    return !!(tg && tg.initData && tg.isVersionAtLeast && tg.isVersionAtLeast(version));
  };

  /* Личное значение: CloudStorage Telegram (6.9+), иначе localStorage. Ответа
     облака нет за CLOUD_WAIT_MS — берётся localStorage, а не вечное «…» (#636). */
  var CLOUD_WAIT_MS = 2500;

  function localGet(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }

  W.storedGet = function (key, done) {
    if (!(W.supports("6.9") && tg.CloudStorage)) { done(localGet(key)); return; }
    var settled = false;
    var finish = function (value) {
      if (settled) { return; }
      settled = true;
      done(value);
    };
    var timer = setTimeout(function () { finish(localGet(key)); }, CLOUD_WAIT_MS);
    try {
      tg.CloudStorage.getItem(key, function (err, value) {
        clearTimeout(timer);
        finish(err ? null : value);
      });
    } catch (e) {
      clearTimeout(timer);
      finish(localGet(key));
    }
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

  /** Пометить элемент подсказкой: долгое нажатие покажет `walk.hint.<ключ>` (`walk-hints.js`). */
  W.hinted = function (node, key) {
    node.setAttribute("data-hint", key);
    return node;
  };

  W.button = function (cls, text, onClick) {
    var b = W.el("button", cls, text);
    b.type = "button";
    if (onClick) b.addEventListener("click", onClick);
    return b;
  };

  /** Значок-контур 24×24 (штрих, цвет — от текста). Декоративный: смысл несёт подпись рядом. */
  var ICONS = {
    camera: ["M4 8h3l1.6-2.4h6.8L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z",
      "M12 16.4a3.4 3.4 0 1 0 0-6.8 3.4 3.4 0 0 0 0 6.8z"],
    check: ["M5 12.5l4.5 4.5L19 7.5"],
    gallery: ["M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z",
      "M3 16l5-5 4 4 3-3 6 6", "M15.5 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z"],
    mic: ["M12 3a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z", "M6 11a6 6 0 0 0 12 0", "M12 17v4"]
  };

  W.icon = function (name, cls) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", "walk-icon" + (cls ? " " + cls : ""));
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    ICONS[name].forEach(function (d) {
      var path = document.createElementNS(ns, "path");
      path.setAttribute("d", d);
      svg.appendChild(path);
    });
    return svg;
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

  /** POST с подписью Telegram. Ответ — { ok, status, body } или отказ сети.
   *  `signal` — необязательный AbortSignal: обрыв по сроку (кадры на слабой связи, D442). */
  W.post = function (url, body, contentType, signal, runId) {
    var headers = { "X-Telegram-Init-Data": (tg && tg.initData) || "" };
    headers["Content-Type"] = contentType || "application/json";
    if (runId !== undefined) headers["X-Walk-Run-Id"] = runId;
    return fetch(url, {
      method: "POST",
      headers: headers,
      body: contentType ? body : JSON.stringify(body),
      credentials: "omit",
      signal: signal || undefined,
    }).then(function (r) {
      var type = r.headers.get("Content-Type") || "";
      if (type.indexOf("application/json") === -1) {
        return r.blob().then(function (blob) { return { ok: r.ok, status: r.status, body: blob }; });
      }
      return r.json().then(function (json) { return { ok: r.ok, status: r.status, body: json }; });
    });
  };

  W.api = W.api || {};
  /** Identity is captured before asynchronous work, never taken from a later run. */
  W.api.write = function (url, body, runId, contentType, signal) {
    if (runId === undefined && body && Object.prototype.hasOwnProperty.call(body, "run_id")) runId = body.run_id;
    if (runId === undefined && W.state.data) runId = W.state.data.run_id;
    if (url === W.urls.photo) return W.post(url, body, contentType, signal, runId);
    var payload = body;
    if ((url === W.urls.finding || url === W.urls.info) && runId !== undefined) {
      payload = Object.assign({}, body, {run_id: runId});
    }
    return W.post(url, payload, contentType, signal);
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
  /** Уведомление. `action` — { label, run }: ссылка в нём, живёт дольше. */
  W.toast = function (text, tone, action) {
    var node = document.getElementById("walk-toast");
    if (!node) {
      node = W.el("div", "walk-toast");
      node.id = "walk-toast";
      node.setAttribute("role", "status");
      document.body.appendChild(node);
    }
    node.textContent = text;
    if (action) {
      node.appendChild(document.createTextNode(" "));
      node.appendChild(W.button("walk-toast__action", action.label, function () {
        node.className = "walk-toast";
        action.run();
      }));
    }
    node.className = "walk-toast is-shown" + (tone ? " walk-toast--" + tone : "") + (action ? " has-action" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { node.className = "walk-toast"; }, action ? 6000 : 2600);
  };
})();
