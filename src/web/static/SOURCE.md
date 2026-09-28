# Откуда здесь CSS и как увидеть, что он отстал

Файлы `dodo-ds.css` и `decimus-domain.css` — **копии**, а не оригиналы.
Оригинал живёт в дизайн-системе линейки `GarroV/forma` и правится только там
(решение D136). Правка здесь молча разведёт три продукта, у которых общий
пользователь.

| Файл здесь | Оригинал в `forma` | Коммит-источник |
|---|---|---|
| `dodo-ds.css` | `dodo/core/dodo-ds.css` | `f70045d` |
| `decimus-domain.css` | `dodo/decimus/domain.css` | `f70045d` |
| `fonts/*.woff2` (13 файлов) | `dodo/core/fonts/` | `f70045d` |
| `icons.json` | `dodo/core/icons.json` | `f70045d` |

Копия обновлена 28.09.2026 раскаткой `python tools/spread.py --apply --to=decimus=<worktree>`
из клона `forma`: эталоном линейки стал Swarm Brain — палитра, Golos Text + IBM
Plex Mono, радиусы, левая и выдвижная панели, набор иконок (D228 здесь, запись
от 28.09.2026 в `dodo/docs/decisions.md` там). Отпечатки скопированного:

```
c9a7553f5599550a1408e1d75aa2ea4c5eb2af0f7cf1598ea7c0c40007c586dd  dodo-ds.css
1ffcb01978cdccc944efffb8e34ceccc33df5a23357c805568c50695708a2db5  decimus-domain.css
eb0a543c0105e06f99e7c7f439c542039737c8dc940a62e266d306b38ae41be3  icons.json
70cf502d77aa23c8a573db8853f20a8db705d18414d170f257a9e939113aad47  fonts/golos-text-cyrillic-ext.woff2
17d048ca05cb1218af3c0d6dcdf882989e6d1cc5dcb598ea50eaf54850ff7229  fonts/golos-text-cyrillic.woff2
05befabe4813f41238ce6ea4f5ecd6b758591e9ef2f303a9932bff68ba66dc66  fonts/golos-text-latin-ext.woff2
9a69d0aa4734c4022224c002a3d944a702e0204972a49d892789f5668b922c2a  fonts/golos-text-latin.woff2
7635422bd10ddbbcb0e0caa1154b928298f5c8319b8c00b30978d4395f4783ce  fonts/ibm-plex-mono-cyrillic-400.woff2
1d89462e86cb8e87e7e9d6f6635605bd7c3081baca6caaecee84916bf7b60edc  fonts/ibm-plex-mono-cyrillic-500.woff2
2b05a8695c7f9f4abd7178b279646a3b005a8ce57546bef6fd145f25d131e0aa  fonts/ibm-plex-mono-cyrillic-600.woff2
08949f728dc52d528e69b1667d15c89a5686a4ee9a296ff90983985f99c380f7  fonts/ibm-plex-mono-latin-400.woff2
01d285447409c8a588692162439a038b8cbd7871309ee20267b0d2d91c6e8e22  fonts/ibm-plex-mono-latin-500.woff2
0d1f0b8d0722224e32e9f28261bdc86c79115be73444ae5eceb73976a1bcdf83  fonts/ibm-plex-mono-latin-600.woff2
6bc0f226a5b7884a8170e3f62c63d7675609d4631bdc5931b5cdab81821f00eb  fonts/ibm-plex-mono-latin-ext-400.woff2
6bb06407c97584b0867a959e05e8874693bfeb8c317de190811c51598f2d99ea  fonts/ibm-plex-mono-latin-ext-500.woff2
32057cf50dd14bdb21a2c93766c4a2c43e4abe688ea3922df3203cac7751a98b  fonts/ibm-plex-mono-latin-ext-600.woff2
```

Проверить расхождение — одной командой из корня репозитория:

```bash
diff -u src/web/static/dodo-ds.css        ~/Documents/projects/forma/dodo/core/dodo-ds.css
diff -u src/web/static/decimus-domain.css ~/Documents/projects/forma/dodo/decimus/domain.css
```

Разошлось — обновляется копия, а не оригинал, и в этой таблице меняется коммит.

**Папка эталона владельца — источник ЗАМЫСЛА, а не файлов.** Прототип оттуда
(`Бриф системы аудитов Decimus`) с 23.09.2026 задаёт канон визуала, и `forma`
приведена к нему; но сверяться по-прежнему нужно с `forma`, потому что копию
кладёт её раскатка, а прототип живёт в другом формате и своими токенами.

## Шрифты приезжают файлами — и это единственный способ их увидеть

Тринадцать файлов в `fonts/` (Golos Text, IBM Plex Mono) — тоже копии, кладёт их та же раскатка. Ядро просит их
через `@font-face` относительными путями, поэтому каталог обязан лежать РЯДОМ с
`dodo-ds.css`; перенесёте один — перенесите оба.

**Здесь раньше стояло обратное, и это стоило владельцу впечатления от работы.**
До 24.09.2026 в этом файле было написано, что шрифты не приезжают намеренно:
стенд, мол, закрытый, наружу ходить незачем, а страница и без них читается.
Читается она действительно, но выглядит при этом прежней — браузер молча берёт
системное начертание, и половина нового визуала (типографика) не приезжает
вовсе. Владелец открыл стенд и сказал, что нового визуала не видит; он был
прав, а рассуждение выше — рационализацией нехватки файлов.

Теперь файлы свои, а не ссылка на `fonts.googleapis.com`: внутренний инструмент
не должен сообщать внешней стороне, кто и когда открыл экран, площадка живёт за
Tailscale, и отказ внешней ссылки так же тих, как отсутствие файла. Начертания
переменные, подмножества разделены `unicode-range` — на латинском экране
кириллица не скачивается. Вместе 104 КБ на все шесть.

Сторож `forma` (`python tools/guard.py check`) краснеет, если ядро просит файл,
которого нет, или если лежит файл, которого никто не просит.

## `decimus-web.css`

Третий файл — **не копия**, это тонкий слой продукта: он только связывает
токены `forma` с разметкой этих экранов (лента «в разработке», метка буквы
оценки, сетка карточки). Своих цветов, шрифтов и радиусов в нём нет — всё
через `var(--…)` ядра.
