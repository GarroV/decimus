"""Technical evidence appendix from the frozen inspection input, without scoring."""

from html import escape

TEXTS = {
    "ru": {
        "title": "Техническое состояние",
        "absent": "В этой проверке явное подтверждение технического состояния не собиралось.",
        "coverage": "Проверено {checked} из {total}. Без ответа: {pending}.",
        "note": (
            "Подтверждения относятся к дате проверки. "
            "Нарушения учтены в основном разделе один раз."
        ),
        "pending": "Не проверено",
        "ok": "Проверено — исправно",
        "issue": "Нарушение",
        "na": "Не применимо",
        "recorded": "Данные зафиксированы",
        "finding": "Запись № {n}",
    },
    "en": {
        "title": "Technical condition",
        "absent": "This inspection did not collect explicit technical confirmations.",
        "coverage": "Checked {checked} of {total}. Unanswered: {pending}.",
        "note": (
            "Confirmations describe the inspection date. "
            "Violations are counted once in the main section."
        ),
        "pending": "Not checked",
        "ok": "Checked — working",
        "issue": "Violation",
        "na": "Not applicable",
        "recorded": "Evidence recorded",
        "finding": "Record #{n}",
    },
    "tr": {
        "title": "Teknik durum",
        "absent": "Bu denetimde açık teknik durum onayları toplanmadı.",
        "coverage": "{total} kontrolün {checked} tanesi kontrol edildi. Yanıtsız: {pending}.",
        "note": "Onaylar denetim tarihini gösterir. Uygunsuzluklar ana bölümde bir kez sayılır.",
        "pending": "Kontrol edilmedi",
        "ok": "Kontrol edildi — çalışıyor",
        "issue": "Uygunsuzluk",
        "na": "Uygulanamaz",
        "recorded": "Kanıt kaydedildi",
        "finding": "Kayıt #{n}",
    },
}


def _text(row, name, lang):
    return next(
        (
            str(row.get(f"{name}_{code}"))
            for code in (lang, "en", "ru")
            if row.get(f"{name}_{code}")
        ),
        str(row.get(name) or ""),
    )


def render(snapshot, lang, zones):
    """Pending, not applicable and absent evidence are never displayed as good."""
    t = TEXTS[lang]
    h = [f'<h2 class="sec-findings">{escape(t["title"])}</h2>']
    if not isinstance(snapshot, dict) or not snapshot.get("enabled"):
        return "".join(h) + f'<p class="note">{escape(t["absent"])}</p>'
    rows = [r for r in snapshot.get("checks", []) if isinstance(r, dict)]
    pending = sum(r.get("status") not in t or r.get("status") == "pending" for r in rows)
    h.append(
        "<p>"
        + escape(
            t["coverage"].format(checked=len(rows) - pending, total=len(rows), pending=pending)
        )
        + "</p>"
    )
    h.append(f'<p class="note">{escape(t["note"])}</p>')
    for row in rows:
        status = row.get("status")
        if status not in {"pending", "ok", "issue", "na", "recorded"}:
            status = "pending"
        title = _text(row, "title", lang)
        h.append('<div class="f"><div class="h">' + escape(title) + "</div>")
        h.append(
            '<div class="m">'
            + escape(str(zones.get(row.get("zone"), row.get("zone") or "")))
            + " · "
            + escape(t[status])
            + "</div>"
        )
        if row.get("reason"):
            h.append('<div class="c">' + escape(str(row["reason"])) + "</div>")
        for n in row.get("finding_numbers") or []:
            if isinstance(n, int) and not isinstance(n, bool) and n > 0:
                h.append(f'<a href="#finding-{n}">' + escape(t["finding"].format(n=n)) + "</a> ")
        h.append("</div>")
    return "".join(h)
