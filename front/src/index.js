// Временный фронт decimus на Cloudflare (D236, #424).
//
// В стране пользователя домен sslip.io заблокирован по решению властей, а
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

const FRONT_KEY_HEADER = "X-Decimus-Front-Key";
const CLIENT_IP_HEADER = "X-Decimus-Client-IP";

export default {
  async fetch(request, env) {
    if (!env.ORIGIN_HOST || !env.FRONT_KEY) {
      // Без настроек не пересылаем вовсе: запрос без ключа выглядел бы на
      // сервере прямым, и счётчик входов свалил бы всех в один адрес.
      return new Response("front is not configured", { status: 503 });
    }
    const front = new URL(request.url);
    const origin = `https://${env.ORIGIN_HOST}`;
    const upstream = new URL(front.pathname + front.search, origin);

    const headers = new Headers(request.headers);
    for (const name of ["Origin", "Referer"]) {
      const value = headers.get(name);
      if (value && (value === front.origin || value.startsWith(front.origin + "/"))) {
        headers.set(name, origin + value.slice(front.origin.length));
      }
    }
    headers.set(FRONT_KEY_HEADER, env.FRONT_KEY);
    headers.set(CLIENT_IP_HEADER, request.headers.get("CF-Connecting-IP") || "");
    headers.delete("Host");

    const hasBody = !["GET", "HEAD"].includes(request.method);
    const response = await fetch(upstream, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      redirect: "manual",
    });

    const location = response.headers.get("Location");
    if (!location || !location.startsWith(origin)) {
      return response;
    }
    const rewritten = new Response(response.body, response);
    rewritten.headers.set("Location", front.origin + location.slice(origin.length));
    return rewritten;
  },
};
