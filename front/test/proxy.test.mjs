// Проверка маршрутизации фронта без среды Workers: `node --test front/test` (#698).
import assert from "node:assert/strict";
import test from "node:test";

import { forward, handle } from "../src/proxy.js";

function settings(extra = {}) {
  const sent = [];
  return {
    sent,
    config: {
      ORIGIN_HOST: "origin.test",
      FRONT_KEY: "key",
      EDGE: {
        fetch: async (url, init) => {
          sent.push({ url: String(url), headers: new Headers(init.headers) });
          return new Response("ok", { headers: { "Cache-Control": "public, max-age=31536000" } });
        },
      },
      ...extra,
    },
  };
}

function cachedStub() {
  const seen = [];
  return { seen, exports: { StaticCache: { fetch: async (request) => (seen.push(request), new Response("cached")) } } };
}

const asked = (path, init = {}) =>
  new Request(`https://front.test${path}`, { headers: { Cookie: "session=secret", Authorization: "Bearer t" }, ...init });

test("статика с включённым кэшем уходит в кэшируемую точку входа без Cookie", async () => {
  const { config, sent } = settings({ STATIC_CACHE: "1" });
  const ctx = cachedStub();

  const answer = await handle(asked("/static/decimus-web.css?v=abc"), config, ctx);

  assert.equal(await answer.text(), "cached");
  assert.equal(ctx.seen.length, 1);
  assert.equal(ctx.seen[0].headers.get("Cookie"), null);
  assert.equal(ctx.seen[0].headers.get("Authorization"), null);
  assert.equal(sent.length, 0, "мимо кэша на сервер не ходили");
});

test("страница под логином кэшируемую точку входа не трогает и несёт Cookie", async () => {
  const { config, sent } = settings({ STATIC_CACHE: "1" });
  const ctx = cachedStub();

  await handle(asked("/inspections"), config, ctx);

  assert.equal(ctx.seen.length, 0);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].headers.get("Cookie"), "session=secret");
});

test("без переменной STATIC_CACHE и не GET путь прежний", async () => {
  const off = settings();
  const ctx = cachedStub();
  await handle(asked("/static/decimus-web.css?v=abc"), off.config, ctx);
  assert.equal(ctx.seen.length, 0);
  assert.equal(off.sent.length, 1);

  const on = settings({ STATIC_CACHE: "1" });
  await handle(asked("/static/upload", { method: "POST", body: "x" }), on.config, ctx);
  assert.equal(ctx.seen.length, 0);
  assert.equal(on.sent.length, 1);
});

test("без точки входа StaticCache (mcp, стенд) статика идёт прежним путём", async () => {
  const { config, sent } = settings({ STATIC_CACHE: "1" });

  await handle(asked("/static/decimus-web.css?v=abc"), config, {});

  assert.equal(sent.length, 1);
});

test("пересылка: ключ фронта, закреплённый хост, отказ без настроек", async () => {
  const { config, sent } = settings();

  await forward(asked("//evil.test/x"), config);
  assert.equal(new URL(sent[0].url).origin, "https://origin.test");
  assert.equal(sent[0].headers.get("X-Decimus-Front-Key"), "key");

  const refused = await forward(asked("/"), { ORIGIN_HOST: "", FRONT_KEY: "" });
  assert.equal(refused.status, 503);
});

// Только туннель (аудит 12.10, F-006/013/090): запроса мимо привязки EDGE нет ни
// при её отсутствии, ни при отказе туннеля — ключ фронта не уходит в интернет.
function noPublicFetch() {
  const calls = [];
  const saved = globalThis.fetch;
  globalThis.fetch = async (...args) => (calls.push(args), new Response("public"));
  return { calls, restore: () => (globalThis.fetch = saved) };
}

test("без привязки EDGE запрос не уходит публичным путём", async () => {
  const net = noPublicFetch();
  try {
    const answer = await forward(asked("/login"), { ORIGIN_HOST: "origin.test", FRONT_KEY: "key" });
    assert.equal(answer.status, 503);
    assert.equal(net.calls.length, 0, "запрос ушёл через интернет");
  } finally {
    net.restore();
  }
});

test("туннель лёг: и GET получает отказ, а не публичный путь", async () => {
  const net = noPublicFetch();
  const broken = { fetch: async () => { throw new Error("tunnel down"); } };
  try {
    for (const method of ["GET", "HEAD", "POST"]) {
      const init = method === "POST" ? { method, body: "x" } : { method };
      const answer = await forward(asked("/login", init), { ORIGIN_HOST: "origin.test", FRONT_KEY: "key", EDGE: broken });
      assert.equal(answer.status, 502, `${method}: не отказ`);
    }
    assert.equal(net.calls.length, 0, "запрос ушёл через интернет");
  } finally {
    net.restore();
  }
});
