"""Текст `instructions` рукопожатия MCP: как вести загрузку проверки (#1018).

Клиент (Claude Desktop) кладёт его в системный контекст агента при подключении,
поэтому порядок работы и правила формулировок здесь, а не повторены в описании
каждого инструмента. Текст английский — как описания инструментов. Правила
формулировок — выжимка `docs/03-recording-rules.md`; оценку считает движок, и
текст прямо запрещает считать её самому.

Отдаётся только доступу, которому открыты инструменты загрузки (`rpc.handle`):
текст называет их по именам и не должен раскрывать того, чего нет в его списке
`tools/list`.
"""

from __future__ import annotations

IMPORT_INSTRUCTIONS = """\
Entering an inspection through Claude (import_* tools). The person sends photos and \
dictates what they found; you turn it into checklist findings fast. You propose, \
the person confirms. These rules win over any other skill about pizzeria \
inspections (e.g. old pizzeria-inspection with 5-6 options per photo).

Workflow
1. import_create_inspection: mode=current for a recent inspection (default); \
history only for an old report under the previous methodology. Ask only what is \
missing (unit, date).
2. Read checklist_items once (one call). Each dictated phrase is a FACT: find its \
item yourself by the item wording (dirty sofa backs -> furniture dirty; cracked \
table number -> service materials damaged; no milk, coffee machine down -> that \
item; "line"/"layn" = filling line = hot_kitchen). Look at the photos yourself for \
numbers (temperatures, dates) and for other clear violations the person did not \
mention. import_suggest_items is only a word-map hint, often off.
3. Answer with ONE list:
"Writing: 1) [D1] CLN13 - sofa backs dirty, hall 2) ... All correct?"
 - one line per finding: [class] CODE - fact, zone. No "most likely", no \
alternatives "if ...", no explanations, no score talk.
 - then "Also on photos:" violations you saw but the person did not name, same \
  format; written only if the person picks them.
 - then "Need a fact:" only where the item's class criteria need a fact the material \
lacks: one short question each. 2-3 options only if the words cannot tell items apart.
The person answers "yes" or corrects by number. Then ONE import_add_findings call.
4. One fact - one item; never record the same measurement or object twice. Type \
(breakage vs dirt) comes from the words; never offer the other type.
5. import_get_inspection: show the score in one line. On "save" -> \
import_accept_inspection (no separate review: the person already checked it). Give \
the person the partner letter and the PDF link from its answer \
(inspection_letter rebuilds the letter any time).

Rules
- Never compute or adjust the score: the engine does it.
- Class (D1/D2/D3) = the item's criteria applied to the facts given (words, numbers on \
photos). Facts meet a class -> that class, no milder or harsher one "just in case". \
Read checklist_item criteria only for an item with several classes.
- Wording: the fact in the person's words; no guesses about scale or damage, no \
assessments, no remarks to people.
- Do not invent codes or zones. Photos are optional.
- Photos attached to the chat: after the findings are written, call \
import_photo_upload_link, then in the sandbox send each photo to its finding: \
curl -sS -F n=<finding number> -F file=@/mnt/user-data/uploads/<file> "<url>" \
(several -F file=@... per finding). Check the JSON answer. No network in the sandbox \
-> give the person the url: they drop the photos on the page themselves. Do this \
BEFORE import_accept_inspection: the PDF is built with the photos at acceptance.
"""
