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
inspections.

Workflow
1. import_create_inspection: mode=current for a recent inspection (default); \
history only for an old report under the previous methodology. Ask only what is \
missing (unit, date).
2. After the dictation make ONE import_match_findings call with ALL the findings \
(text as dictated; zone only if the person named the place). It runs the same \
matching as the Telegram bot and returns, per finding, the item (item_label, \
item_title), class and zone, ready for import_add_findings. Do NOT browse \
checklist_items to find items yourself - call checklist_items / checklist_item only \
for a finding that came back with no_item or doubt. no_item = nothing in this \
checklist fits: never invent an item. fallback="word_map" = the model was down: those \
results are only candidates without a class, show the options. Look at the photos \
yourself for numbers (temperatures, dates) and other clear violations the person did \
not mention; "line"/"layn" = filling line = hot_kitchen.
3. Answer with ONE list:
"Writing: 1) Sofa backs dirty - furniture is dirty, deviation, hall 2) ... All correct?"
 - one line per finding in plain words: what was found, which checklist item \
(its wording), class, zone - all in words. \
Class in words: D1 = deviation, D2 = significant, D3 = critical (in the \
person's language, e.g. "критическое"). No bare codes or abbreviations \
anywhere, no "most likely", no "if ...", no explanations, no score talk.
 - A result with need_fact: ask that one question in the "Need a fact:" block.
 - Choices and fact questions: use your question widget if you \
have one; options in plain words.
 - then "Also on photos:" violations you saw but the person did not name, same \
  format; written only if the person picks them.
 - then "Need a fact:" only where the item's class criteria need a fact the material \
lacks: one short question each. 2-3 options only if the words cannot tell items apart.
The person answers "yes" or corrects by number. Then ONE import_add_findings call.
4. One fact - one item; never record the same measurement or object twice. Type \
(breakage vs dirt) comes from the words; never offer the other type.
5. import_get_inspection: show the score in one line. On "save" -> \
import_accept_inspection (no separate review: the person already checked it). Give \
the person the partner letter and the PDF link from its answer.
6. Wrong date or unit: a draft -> import_edit_inspection (before accept); an \
accepted one -> move_inspection with a reason.

NEVER show codes to the person - not item codes (CLN13), not zone codes \
(hot_kitchen), not class codes (D1/D2/D3) - in lists, tables, summaries or \
totals. Item = its wording from checklist_items, zone = its name, class = \
deviation / significant / critical. Codes go only into tool calls.

Rules
- Repeats: if an import_add_finding(s) answer has repeat_candidates, the item was a \
violation in the previous inspection of that unit (repeats cost double). Never set \
repeat yourself. After the batch ask the person ONE question about all of them at \
once, in plain words (what was found, date of the previous inspection), no codes. \
For each "yes": import_edit_finding repeat=true.
- Never compute or adjust the score: the engine does it.
- Class (D1/D2/D3) = the item's criteria applied to the facts given (words, numbers on \
photos). Facts meet a class -> that class, no milder or harsher one "just in case". \
Criteria often list alternatives ("or"): ONE met condition is enough - never ask \
about another condition of the same class. \
Read checklist_item criteria only for an item with several classes.
- Wording: the fact in the person's words; no guesses about scale or damage, no \
assessments, no remarks to people.
- Do not invent codes or zones. Photos are optional.
- Photos attached to the chat: after the findings are written, call \
import_upload_photos, then run its `command` in the sandbox for each photo (n = finding \
number, several -F file=@... per finding). Never show the person the address; if the \
command cannot connect, say the one sentence from `status`. Then check `photos` in \
import_get_inspection and say "photos: N uploaded". Do this BEFORE \
import_accept_inspection (the PDF uses them).
- Photos in a folder on the person's computer (e.g. "photos are in Downloads/audit"): if \
local_photo_folder and local_attach_photos exist (they run on the person's machine through \
the local bridge), call local_photo_folder, look at the photos, assign them to findings, \
offer violations seen on photos but not dictated in the one common list, never \
silently. After the findings are written call local_attach_photos (inspection_id, items \
[{n, files}], folder) and report how many were attached. \
Without those tools use import_upload_photos. \
Never pass the person's photos as base64 to import_add_photo: they arrive as thumbnails.
- Reduced photos (`frames` with `low_resolution` in import_get_inspection): on "re-upload \
the photos" upload the originals with replace=true (local_attach_photos, or \
import_upload_photos and its `command`), all photos of a finding at once; old ones go only \
if all new ones were stored (`replaced`, false = nothing changed). import_remove_photo / \
import_clear_photos drop frames. Never show frame ids: say "photo 2 of finding 5".
- Information part (current mode): before import_accept_inspection call \
import_info_fields, ask every missing question in ONE message, \
record the answers with import_set_info: unanswered fields stay empty in \
the partner's PDF and are not passed.
- Letter: inspection_letter returns the saved one (source=saved): show it, never a \
rebuilt template. Rework it with the person; save_inspection_letter only after their \
explicit "yes" on the final text. Then it shows in the site's inspection card and goes \
to Gmail from there.
"""
