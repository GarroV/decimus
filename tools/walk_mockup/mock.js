/* Кликабельный макет мини-аппа обхода: сервер подменён здесь, в браузере.
 * Экран и форма — настоящие скрипты мини-аппа; этот файл отвечает им так же,
 * как отвечает веб: те же адреса, те же формы ответов, те же отказы. */
(function () {
  "use strict";
  var SEED = window.__MOCK_SEED__;
  var STORE = "decimus-walk-mock-v2";
  var LEVELS_REPEAT = ["D1", "D2"];

  function b64ToBlob(dataUrl) {
    var raw = atob(dataUrl.split(",")[1]);
    var buf = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);
    return new Blob([buf], { type: "image/jpeg" });
  }

  function blobToDataUrl(blob) {
    return new Promise(function (ok) {
      var r = new FileReader();
      r.onload = function () { ok(r.result); };
      r.readAsDataURL(blob);
    });
  }

  function initial() {
    var findings = [];
    SEED.payload.zones.forEach(function (z) {
      z.recorded.forEach(function (f) {
        findings.push({
          code: f.code, level: f.level, zone: z.code, text: f.text, comment: f.comment || "",
          repeat: !!f.repeat, photos: f.photos.map(function (p) { return p.ref; }),
        });
      });
    });
    var info = {};
    SEED.payload.info.forEach(function (f) { info[f.code] = f.value || ""; });
    return { findings: findings, info: info, pics: {} };
  }

  function load() {
    try {
      var s = JSON.parse(localStorage.getItem(STORE) || "null");
      if (s && Array.isArray(s.findings)) return s;
    } catch (e) { /* чистый лист */ }
    return initial();
  }

  var S = load();
  function save() {
    try { localStorage.setItem(STORE, JSON.stringify(S)); } catch (e) { /* живёт до перезагрузки */ }
  }

  window.__mockReset = function () {
    try {
      Object.keys(localStorage).forEach(function (k) {
        if (k.indexOf("decimus") === 0 || k.indexOf("walk") !== -1) localStorage.removeItem(k);
      });
    } catch (e) { /* нечего чистить */ }
    location.reload();
  };

  var items = {};
  SEED.payload.items.forEach(function (i) { items[i.code] = i; });

  function payload() {
    var p = JSON.parse(JSON.stringify(SEED.payload));
    p.zones.forEach(function (z) { z.recorded = []; });
    var byZone = {};
    p.zones.forEach(function (z) { byZone[z.code] = z; });
    S.findings.forEach(function (f, i) {
      var item = items[f.code] || { zones: [] };
      var zone = byZone[f.zone];
      if (!zone) return;
      zone.recorded.push({
        n: i + 1, code: f.code, level: f.level, text: f.text, comment: f.comment || "",
        repeat: !!f.repeat,
        unusual: item.zones.length > 0 && item.zones.indexOf(f.zone) === -1,
        photos: f.photos.map(function (r) { return { ref: r, own: true }; }),
      });
    });
    p.zones.forEach(function (z) {
      z.previous.forEach(function (old) {
        old.again = S.findings.some(function (f) {
          return f.code === old.code && f.zone === z.code && f.level !== "D0";
        });
      });
    });
    p.info.forEach(function (f) { f.value = S.info[f.code] || ""; });
    return p;
  }

  function said(key) { return SEED.payload.texts[key] || key; }

  function Refused(message, status) { this.message = message; this.status = status || 422; }

  function json(body, status) {
    return new Response(JSON.stringify(body), {
      status: status || 200, headers: { "Content-Type": "application/json" },
    });
  }

  function cleanText(v, required) {
    if (v === undefined || v === null) v = "";
    if (typeof v !== "string") throw new Refused(said("walk.err.bad_request"));
    v = v.trim();
    if (v.length > 2000) throw new Refused(said("walk.err.too_long"));
    if (required && !v) throw new Refused(said("walk.err.empty_text"));
    return v;
  }

  function refs(list) {
    if (!Array.isArray(list) || !list.length) throw new Refused(said("walk.err.photo_required"));
    list.forEach(function (r) {
      if (!SEED.pics[r] && !S.pics[r]) throw new Refused(said("walk.err.photo_lost"));
    });
    return list.slice();
  }

  function finding(n) {
    var f = S.findings[n - 1];
    if (!f) throw new Refused(said("walk.err.bad_request"));
    return f;
  }

  function taken(code, zone, except, level) {
    // Пару «пункт + зона» занимает только нарушение: замер и рекомендация — нет.
    if (level === "D0" || level === ADVICE) return false;
    return S.findings.some(function (f, i) {
      return i !== except && f.code === code && f.zone === zone && f.level !== "D0" && f.level !== ADVICE;
    });
  }

  // Рекомендация без нарушения (D201): у любого пункта, без класса. Сервер её
  // принимает так же (#375): без кадра, с обязательным текстом.
  var ADVICE = "R";

  function checkLevel(code, level) {
    // Общая заметка (NOTE) — рекомендация без пункта, уходит в конец отчёта.
    if (code === "NOTE" && level === ADVICE) return;
    var item = items[code];
    if (!item) throw new Refused(said("walk.err.bad_request"));
    if (level === ADVICE) return;
    if (item.levels.indexOf(level) === -1) {
      throw new Refused("Для пункта " + code + " класс " + level + " не предусмотрен.");
    }
  }

  var ops = {
    add: function (b) {
      checkLevel(b.code, b.level);
      var advice = b.level === ADVICE;
      var photos = advice && !(b.photos || []).length ? [] : refs(b.photos);
      if (taken(b.code, b.zone, -1, b.level)) throw new Refused("Пункт " + b.code + " в этой зоне уже записан.");
      if (advice && !cleanText(b.text)) throw new Refused(said("walk.sheet.need_advice"));
      S.findings.push({
        code: b.code, level: b.level, zone: b.zone,
        text: cleanText(b.text) || (items[b.code] || {}).q, comment: cleanText(b.comment),
        repeat: b.repeat === true && LEVELS_REPEAT.indexOf(b.level) !== -1, photos: photos,
      });
    },
    edit: function (b) {
      var f = finding(b.n);
      var next = Object.assign({}, f);
      if ("text" in b) next.text = cleanText(b.text, true);
      if ("comment" in b) next.comment = cleanText(b.comment);
      if ("code" in b) next.code = b.code;
      if ("level" in b) next.level = b.level;
      if ("zone" in b) next.zone = b.zone;
      checkLevel(next.code, next.level);
      if (taken(next.code, next.zone, b.n - 1, next.level)) throw new Refused("Пункт " + next.code + " в этой зоне уже записан.");
      var lvlOk = LEVELS_REPEAT.indexOf(next.level) !== -1;
      if (b.repeat === true && !lvlOk) throw new Refused(said("walk.err.repeat_level"));
      if (typeof b.repeat === "boolean") next.repeat = b.repeat;
      else if (f.repeat && !lvlOk) next.repeat = false;
      S.findings[b.n - 1] = next;
    },
    drop: function (b) { finding(b.n); S.findings.splice(b.n - 1, 1); },
    attach: function (b) {
      var f = finding(b.n);
      var r = refs([b.ref])[0];
      if (f.photos.indexOf(r) === -1) f.photos.push(r);
    },
    detach: function (b) {
      var f = finding(b.n);
      if (f.photos.indexOf(b.ref) === -1) throw new Refused("Такого фото у записи нет.");
      if (f.photos.length === 1 && f.level !== ADVICE) throw new Refused("Последнее фото снять нельзя: запись без фото не принимается.");
      f.photos = f.photos.filter(function (r) { return r !== b.ref; });
    },
  };

  function infoValue(kind, raw) {
    if (typeof raw !== "string" || !raw.trim()) throw new Refused(said("walk.err.empty_answer"));
    var v = raw.trim();
    if (kind === "yes_no") return v === "yes" ? said("walk.info.yes") : said("walk.info.no");
    if (kind === "date") {
      var m = v.match(/^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?$/);
      if (!m) throw new Refused(said("walk.err.bad_date"));
      return m[3] + "." + m[2] + "." + m[1] + (m[4] ? " " + m[4] + ":" + m[5] : "");
    }
    return cleanText(v, true);
  }

  function newRef() {
    var hex = "";
    for (var i = 0; i < 32; i++) hex += Math.floor(Math.random() * 16).toString(16);
    return "walk:" + hex;
  }

  /* Поиск пункта (D330). На проде это распознавание бота — модель по кадру и
   * словам. Макет модель не зовёт: ищет пункт по совпадению основ слов с
   * формулировкой пункта, чтобы было видно, как предложения ложатся на форму. */
  function stem(w) { return w.toLowerCase().replace(/ё/g, "е").slice(0, 5); }

  function stems(text) {
    return (text.match(/[а-яёa-z]{3,}/gi) || []).map(stem);
  }

  function suggest(b) {
    var said = stems(b.words || "");
    var pool = SEED.payload.items.filter(function (i) { return !i.measure; });
    var scored = pool.map(function (i) {
      var own = stems(i.q + " " + i.process);
      var hit = said.filter(function (w) { return own.indexOf(w) !== -1; }).length;
      var here = !b.zone || !i.zones.length || i.zones.indexOf(b.zone) !== -1;
      return { item: i, score: hit * 2 + (here ? 1 : 0) };
    }).filter(function (x) { return said.length ? x.score >= 2 : x.score >= 1; });
    scored.sort(function (a, c) { return c.score - a.score; });
    var words = (b.words || "").trim();
    var top = scored.slice(0, 3).map(function (x, k) {
      var lv = x.item.levels.indexOf("D2") !== -1 && /просроч|плесен|грязн|нагар/i.test(words) ? "D2" : x.item.levels[0];
      var zone = b.zone && (!x.item.zones.length || x.item.zones.indexOf(b.zone) !== -1) ? b.zone : (x.item.zones[0] || b.zone);
      return {
        code: x.item.code, level: lv, zone: zone, confidence: Math.max(0.35, 0.9 - k * 0.2),
        wording: words ? words.charAt(0).toUpperCase() + words.slice(1).replace(/\.?$/, ".") : x.item.q,
      };
    });
    return {
      candidates: said.length ? top : top.slice(0, 2),
      question: said.length ? "" : "По одному кадру система уверена меньше — пара слов помогает.",
    };
  }

  function route(path, init) {
    var body = init && init.body;
    if (path === "/mock/data") return Promise.resolve(json(payload()));
    if (path === "/mock/photo") {
      // Кадр уже сжат на телефоне — как на проде; храним его здесь же.
      return blobToDataUrl(body).then(function (url) {
        var ref = newRef();
        S.pics[ref] = url;
        save();
        return json({ ref: ref }, 201);
      });
    }
    var data = {};
    try { data = JSON.parse(body || "{}"); } catch (e) { return Promise.resolve(json({ error: "bad" }, 400)); }
    if (path === "/mock/photo/view") {
      var src = SEED.pics[data.ref] || S.pics[data.ref];
      if (!src) return Promise.resolve(json({ error: "not_found" }, 404));
      return Promise.resolve(new Response(b64ToBlob(src), { headers: { "Content-Type": "image/jpeg" } }));
    }
    try {
      if (path === "/mock/suggest") {
        refs(data.photos);
        // Модель думает дольше сети — так видно «Система ищет пункт…».
        return new Promise(function (ok) { setTimeout(ok, 900); }).then(function () { return json(suggest(data)); });
      }
      if (path === "/mock/finding") {
        var op = ops[data.op];
        if (!op) throw new Refused(said("walk.err.bad_request"), 400);
        var before = JSON.stringify(S.findings);
        try { op(data); } catch (err) { S.findings = JSON.parse(before); throw err; }
      } else if (path === "/mock/info") {
        var field = SEED.payload.info.filter(function (f) { return f.code === data.code; })[0];
        if (!field) throw new Refused(said("walk.err.bad_request"), 400);
        S.info[data.code] = infoValue(field.kind, data.value);
      } else {
        return Promise.resolve(json({ error: "not_found" }, 404));
      }
    } catch (err) {
      if (err instanceof Refused) return Promise.resolve(json({ error: "refused", message: err.message }, err.status));
      throw err;
    }
    save();
    return Promise.resolve(json(payload()));
  }

  var realFetch = window.fetch.bind(window);
  window.fetch = function (url, init) {
    var path = String(url);
    if (path.indexOf("/mock/") !== 0) return realFetch(url, init);
    // Небольшая задержка — как у живой сети, чтобы было видно «Загружается…».
    return new Promise(function (ok) { setTimeout(ok, 250); }).then(function () { return route(path, init); });
  };
})();
