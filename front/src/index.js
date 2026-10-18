// Временный фронт decimus на Cloudflare (D236, #424): точка входа Worker'а.
// Вся логика пересылки — в proxy.js (там же её проверка без среды Workers).
import { WorkerEntrypoint } from "cloudflare:workers";

import { forward, handle } from "./proxy.js";

// Точка входа с включённым кэшем Worker'а (wrangler.admin.template.jsonc, #698):
// ответ статики с `Cache-Control: public, max-age=…` отдаётся с края без
// похода на сервер. Только статика и только без Cookie (proxy.js: handle).
export class StaticCache extends WorkerEntrypoint {
  fetch(request) {
    return forward(request, this.env);
  }
}

export default {
  fetch: (request, config, ctx) => handle(request, config, ctx),
};
