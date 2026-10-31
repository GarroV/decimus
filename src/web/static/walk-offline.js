/* Мини-апп обхода: кадры без связи (D442) — подождать на телефоне и уйти сами.
 *
 * В холодильной камере связи нет, а кадр нужен сейчас. Кадр, который не ушёл
 * из-за сети, сжатым ложится в IndexedDB телефона, а форма показывает его
 * «ждёт связи». Уходит он сам: когда вернулась сеть (`online`), когда аудитор
 * вернулся в приложение и по таймеру с нарастающей паузой. Отправка безопасна
 * повторять: ссылка на кадр — отпечаток его байтов (`save_upload`), тот же
 * кадр, пришедший дважды, остаётся одним.
 *
 * Хранится только кадр новой записи: он привязан к черновику формы (ключ
 * черновика + режим). Вернулась связь, форма закрыта — ссылка ложится в
 * черновик в `localStorage`, и при следующем открытии формы кадр уже там.
 * Сама запись связи требует: «Сохранить» ждёт.
 *
 * Предел — по числу, по размеру и по возрасту; что не поместилось или
 * просрочено, аудитору сообщается словами: молча кадр не пропадает.
 */
(function () {
  "use strict";

  var W = window.DecimusWalk;

  var DB_NAME = "decimus-walk-frames";
  var STORE = "frames";
  var MAX_FRAMES = 30;
  var MAX_BYTES = 60 * 1024 * 1024;
  var MAX_AGE_DAYS = 3;
  var DAY_MS = 24 * 60 * 60 * 1000;
  var RETRY_PAUSES_MS = [5000, 15000, 30000, 60000, 120000];
  /** Сервер отказал по существу (кадр не годится, проверки нет или она сдана): ждать нечего. */
  var FINAL_STATUSES = [400, 409, 413, 415, 422];

  var dbPromise = null;
  var timer = null;
  var attempt = 0;
  var busy = false;
  var started = false;
  var consumers = Object.create(null);

  /* ── хранилище ─────────────────────────────────────────────────────── */

  function available() { return !!window.indexedDB; }

  function openDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise(function (resolve, reject) {
      if (!available()) { reject(new Error("unavailable")); return; }
      var req = window.indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = function () { req.result.createObjectStore(STORE, { keyPath: "id" }); };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error || new Error("idb")); };
    });
    dbPromise.catch(function () { dbPromise = null; });
    return dbPromise;
  }

  function run(mode, work) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var t = db.transaction(STORE, mode);
        var req = work(t.objectStore(STORE));
        t.oncomplete = function () { resolve(req ? req.result : undefined); };
        t.onerror = t.onabort = function () { reject(t.error || new Error("idb")); };
      });
    });
  }

  /** Байты кадра без Blob внутри IndexedDB: так надёжнее в WebView телефона. */
  function toBytes(blob) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { resolve(reader.result); };
      reader.onerror = function () { reject(reader.error || new Error("read")); };
      reader.readAsArrayBuffer(blob);
    });
  }

  function fromRow(row) {
    return { id: row.id, key: row.key, run_id: row.run_id, uploaded_ref: row.uploaded_ref, mode: row.mode, at: row.at, bytes: row.bytes.byteLength,
      blob: new Blob([row.bytes], { type: row.type }) };
  }

  function rows() { return run("readonly", function (s) { return s.getAll(); }); }

  function remove(id) {
    return run("readwrite", function (s) { return s.delete(id); }).catch(function () { /* уже нет */ });
  }

  /** Сколько кадров просрочено и снято; о них аудитору сказать. */
  function purgeOld() {
    var limit = Date.now() - MAX_AGE_DAYS * DAY_MS;
    return rows().then(function (all) {
      var old = all.filter(function (r) { return owns(r) && r.at < limit; });
      return Promise.all(old.map(function (r) { return remove(r.id); })).then(function () { return old.length; });
    }).then(function (n) {
      if (n) W.toast(W.tx("walk.offline.expired", { n: n, days: MAX_AGE_DAYS }), "warn");
    }, function () { /* хранилища нет — снимать нечего */ });
  }

  /** Положить кадр новой записи. Отказ — Error с `reason`: "full" или "unavailable". */
  function put(key, mode, blob, runId) {
    return Promise.all([rows(), toBytes(blob)]).then(function (got) {
      var count = got[0].length;
      var total = got[0].reduce(function (sum, r) { return sum + r.bytes.byteLength; }, 0);
      if (count >= MAX_FRAMES || total + got[1].byteLength > MAX_BYTES) throw reasoned("full");
      var row = {
        id: Date.now().toString(36) + Math.random().toString(36).slice(2, 8),
        key: key, run_id: runId, mode: mode, at: Date.now(), type: blob.type || "image/jpeg", bytes: got[1],
      };
      return run("readwrite", function (s) { return s.add(row); }).then(function () { return fromRow(row); });
    }).then(null, function (err) {
      throw err && err.reason ? err : reasoned(err && err.name === "QuotaExceededError" ? "full" : "unavailable");
    });
  }

  function reasoned(reason) {
    var err = new Error(reason);
    err.reason = reason;
    return err;
  }

  /** Кадры черновика (по ключу), старые вперёд. */
  function list(key) {
    return purgeOld().then(rows).then(function (all) {
      return all.filter(function (r) { return r.key === key && owns(r); })
        .sort(function (a, b) { return a.at - b.at; }).map(fromRow);
    }, function () { return []; });
  }

  /* ── отправка ──────────────────────────────────────────────────────── */

  /** Ссылка на кадр — в черновик, когда форма закрыта: открыв её (в том числе по пункту чек-листа),
   *  аудитор увидит кадр готовым. `queued` — кадры, пришедшие уже после закрытия формы. */
  function owns(entry) {
    var data = W.state.data;
    if (!data || !data.run_id || entry.run_id !== data.run_id) return false;
    if (entry.key === data.key + "_draft") return true;
    var prefix = data.key + "_info_";
    return entry.key.indexOf(prefix) === 0 && /^[A-Za-z0-9_-]+$/.test(entry.key.slice(prefix.length));
  }

  function mergeDraft(entry, ref) {
    var draft = W.local.get(entry.key) || {
      run_id: entry.run_id, mode: entry.mode, zone: null, code: null, level: null, text: "", comment: "", repeat: false, words: "", photos: [],
    };
    if (draft.run_id !== entry.run_id) return false;
    var refs = draft.photos || [];
    var queued = draft.queued || [];
    if (refs.indexOf(ref) === -1) refs.push(ref);
    if (queued.indexOf(ref) === -1) queued.push(ref);
    draft.photos = refs;
    draft.queued = queued;
    W.local.set(entry.key, draft);
    var saved = W.local.get(entry.key);
    return !!saved && saved.run_id === entry.run_id && Array.isArray(saved.photos) &&
      saved.photos.indexOf(ref) !== -1;
  }

  /** Persist the upload receipt before local adoption; reload can finish without reuploading. */
  function rememberUploaded(entry, ref) {
    return rows().then(function (all) {
      var row = all.filter(function (r) { return r.id === entry.id; })[0];
      if (!row) return false;
      var updated = Object.assign({}, row, {uploaded_ref: ref});
      return run("readwrite", function (s) { return s.put(updated); }).then(function () { return true; });
    });
  }

  /** Register an active field consumer. Unregistering never deletes its durable draft. */
  function register(key, consumer) {
    var registration = {consumer: consumer, run_id: W.state.data && W.state.data.run_id};
    consumers[key] = registration;
    return function () { if (consumers[key] === registration) delete consumers[key]; };
  }

  function settle(entry, ref) {
    // Keep original bytes until the reference was actually saved on this device.
    if (!mergeDraft(entry, ref)) return Promise.resolve(null);
    var taken = false;
    var registration = consumers[entry.key];
    if (owns(entry) && registration && registration.run_id === entry.run_id) {
      var consumer = registration.consumer;
      taken = !!(typeof consumer === "function" ? consumer(entry, ref) : consumer.uploaded(entry, ref));
    } else if (owns(entry) && entry.key === W.state.data.key + "_draft") {
      taken = !!(W.offline.onUploaded && W.offline.onUploaded(entry, ref));
    }
    return remove(entry.id).then(function () { return taken; });
  }

  /** Отправить всё, что ждёт. Первая же сеть-неудача останавливает: остальным она не лучше. */
  function flush() {
    var sent = 0;
    var dropped = 0;
    return rows().then(function (all) {
      var queue = all.filter(owns).map(fromRow).sort(function (a, b) { return a.at - b.at; });
      function next(i) {
        if (i >= queue.length || navigator.onLine === false || !owns(queue[i])) return Promise.resolve(queue.length - i);
        var entry = queue[i];
        var uploaded = entry.uploaded_ref ? Promise.resolve(entry.uploaded_ref) :
          W.photo.upload(entry.blob, entry.run_id).then(function (ref) {
            return rememberUploaded(entry, ref).then(function (saved) { return saved ? ref : null; });
          });
        return uploaded.then(function (ref) {
          if (!ref) return next(i + 1);
          return settle(entry, ref).then(function (taken) {
            if (taken === null) return queue.length - i;
            if (!taken) sent += 1;
            return next(i + 1);
          });
        }, function (err) {
          if (err && err.code === "run_changed") return queue.length - i;
          if (err && !err.retryable && FINAL_STATUSES.indexOf(err.status) !== -1) {
            dropped += 1;
            return remove(entry.id).then(function () { return next(i + 1); });
          }
          return queue.length - i;
        });
      }
      return next(0);
    }).then(function (left) {
      if (sent) W.toast(W.tx("walk.offline.sent", { n: sent }), "ok");
      if (dropped) W.toast(W.tx("walk.offline.dropped", { n: dropped }), "warn");
      return left;
    });
  }

  function cycle() {
    if (busy) return Promise.resolve();
    clearTimeout(timer);
    timer = null;
    busy = true;
    var inMemory = W.offline.onTick ? W.offline.onTick() : 0;
    return purgeOld().then(function () { return flush(); }).then(function (left) {
      busy = false;
      if (left + inMemory > 0) schedule();
    }, function () {
      busy = false;
      schedule();
    });
  }

  /** Следующая попытка через нарастающую паузу. */
  function schedule() {
    clearTimeout(timer);
    var pause = RETRY_PAUSES_MS[Math.min(attempt, RETRY_PAUSES_MS.length - 1)];
    attempt += 1;
    timer = setTimeout(cycle, pause);
  }

  /** Сеть вернулась или аудитор вернулся в приложение: пробуем сразу, паузы с начала. */
  function kick() {
    attempt = 0;
    return cycle();
  }

  /** Есть что ждать: поставить таймер, если его нет. */
  function watch() {
    if (!timer && !busy) schedule();
  }

  function start() {
    if (started) { kick(); return; }
    started = true;
    window.addEventListener("online", kick);
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") kick();
    });
    kick();
  }

  W.offline = {
    recovery: function (key) { return rows().then(function (all) {
      return all.filter(function (r) { return r.key === key; }).map(fromRow);
    }, function () { return []; }); },
    register: register,
    available: available, put: put, list: list, remove: remove, start: start, kick: kick, watch: watch,
    onUploaded: null, onTick: null,
    limits: { frames: MAX_FRAMES, bytes: MAX_BYTES, days: MAX_AGE_DAYS },
  };
})();
