// Временный фронт decimus на Cloudflare (D236, #424).
//
// В стране пользователя домен служебный домен заблокирован по решению властей, а
// адрес Cloudflare — нет. Worker принимает запрос на своём адресе и пересылает
// его на сервер как есть; ответ возвращает как есть. Своей логики у него нет.
//
// Три правки по дороге, и все три — чтобы сервер не заметил посредника:
//  1. Origin/Referer со своего адреса переписываются на адрес сервера — иначе
//     админка отбивала бы каждую форму как пришедшую с чужого сайта. Чужой
//     Origin уходит нетронутым и получает тот же отказ, что и без фронта.
//  2. Адрес посетителя уходит отдельным заголовком вместе с ключом фронта.
//     Вход площадки (Caddy) верит этому адресу ТОЛЬКО при верном ключе — иначе
//     любой мог бы назваться чужим адресом, а счётчик неудачных входов считает
//     попытки по адресу.
//  3. Location с адресом сервера переписывается на адрес фронта, чтобы
//     переход не уводил человека обратно на заблокированный домен.
//
// До сервера Worker идёт ТОЛЬКО туннелем (привязка EDGE — Workers VPC, D304,
// D518): запрос попадает прямо в Caddy на VPS, и имя служебного домена в пути
// не участвует — ни его DNS, ни его доступность. Имя остаётся только SNI и
// Host, по которым Caddy выбирает сайт. Публичного запасного пути нет: туннель
// лёг или привязки нет — отказ 502/503, а не запрос через интернет. Caddy со
// своей стороны принимает сайты decimus только из туннеля.

const FRONT_KEY_HEADER = "X-Decimus-Front-Key";
const CLIENT_IP_HEADER = "X-Decimus-Client-IP";
const STATIC_PREFIX = "/static/";

// Статика админки (#698). Запрос идёт на сервер через привязку EDGE (туннель), а
// такой подзапрос мимо кэша Cloudflare: каждый файл доходил до VPS (TTFB CSS
// 210–440 мс при `Cache-Control: public, max-age=31536000`). Кэш Worker'а
// (Workers Caching) работает и на workers.dev, и решает по `Cache-Control`
// ответа, поэтому статика уходит в отдельную точку входа `StaticCache`
// (index.js) с включённым кэшем; остальное идёт как прежде, мимо кэша: страницы
// под логином в общий кэш попасть не должны. Включается переменной
// STATIC_CACHE=1 — у mcp и стенда её нет, их путь не меняется.
export function isStaticRequest(request, config) {
  if (config.STATIC_CACHE !== "1" || request.method !== "GET") return false;
  return new URL(request.url).pathname.startsWith(STATIC_PREFIX);
}

// В кэшируемую точку входа уходит запрос без личных данных: файл статики одинаков
// для всех, а Cookie и Authorization заставили бы кэш пропускать запрос.
export function withoutCredentials(request) {
  const bare = new Request(request);
  for (const name of ["Cookie", "Authorization"]) bare.headers.delete(name);
  return bare;
}

export async function handle(request, config, ctx) {
  const cached = ctx && ctx.exports && ctx.exports.StaticCache;
  if (cached && isStaticRequest(request, config)) {
    return cached.fetch(withoutCredentials(request));
  }
  return forward(request, config);
}

export async function forward(request, config) {
  if (!config.ORIGIN_HOST || !config.FRONT_KEY || !config.EDGE) {
    // Без настроек не пересылаем вовсе: запрос без ключа выглядел бы на
    // сервере прямым, и счётчик входов свалил бы всех в один адрес; без
    // туннеля идти некуда — публичного пути нет (D518).
    return new Response("front is not configured", { status: 503 });
  }
  const front = new URL(request.url);
  const origin = `https://${config.ORIGIN_HOST}`;
  // Хост сервера закреплён, а не собран из пути: `new URL("//evil.com/x", origin)`
  // читает путь как адрес другого сайта, и запрос ушёл бы туда вместе с
  // ключом фронта. Путь только присваивается, итог сверяется ещё раз.
  const upstream = new URL(origin);
  upstream.pathname = front.pathname.replace(/^\/+/, "/");
  upstream.search = front.search;
  if (upstream.origin !== origin) {
    return new Response("bad request", { status: 400 });
  }

  const headers = new Headers(request.headers);
  for (const name of ["Origin", "Referer"]) {
    const value = headers.get(name);
    if (value && (value === front.origin || value.startsWith(front.origin + "/"))) {
      headers.set(name, origin + value.slice(front.origin.length));
    }
  }
  headers.set(FRONT_KEY_HEADER, config.FRONT_KEY);
  headers.set(CLIENT_IP_HEADER, request.headers.get("CF-Connecting-IP") || "");
  headers.delete("Host");

  const hasBody = !["GET", "HEAD"].includes(request.method);
  let response;
  try {
    response = await config.EDGE.fetch(upstream, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      redirect: "manual",
    });
  } catch (error) {
    // Повтора нет ни у какого запроса: исключение туннеля не говорит, дошёл ли
    // запрос до сервера, а публичного пути больше нет (D518). Повторить решает
    // человек.
    console.error("tunnel failed", String(error));
    return new Response("upstream unavailable, please retry", { status: 502 });
  }

  const location = response.headers.get("Location");
  if (!location || !location.startsWith(origin)) {
    return response;
  }
  const rewritten = new Response(response.body, response);
  rewritten.headers.set("Location", front.origin + location.slice(origin.length));
  return rewritten;
}
