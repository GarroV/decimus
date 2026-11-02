"""Explicit products, separate lines, revision binding and human-only application."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_selected_level import CFG, method

from src.db.fingerprint import compute_fingerprint
from src.domain import add_finding, get_state, score, set_reading, start_inspection
from src.domain.errors import ValidationError
from src.domain.findings import edit_finding
from src.domain.measurement_sets import (
    MeasurementSetConflict,
    bound_scope,
    delete_set,
    public_sets,
    save_set,
    scope_for,
)
from src.domain.revisions import finding_revision
from src.recognize.selected_level import prepare_selected_level, recheck_measurement_scope


def setup(domain_env, tmp_path, monkeypatch):
    method(tmp_path, monkeypatch, "## CLN05\nSynthetic criterion: request missing product facts.\n")
    start_inspection(1, unit="Synthetic", kind="planned", report_lang="ru")
    for value in (2.0, 3.0, 4.0):
        add_finding(1, "INF10", "D0", "hot_kitchen", "Confirmed product reading", reading_c=value)


def group(*ns, ident="a", product="b"):
    state = get_state(1)
    return dict(
        schema=1,
        id=ident * 32,
        revision=None,
        code="CLN05",
        zone="hot_kitchen",
        line_label="Explicit line " + ident,
        confirmed=True,
        products=[
            dict(
                id=product * 32,
                label="Confirmed product",
                facts="Category stated by human",
                confirmed_product=True,
                sources=[dict(n=n, revision=finding_revision(state.finding(n))) for n in ns],
            )
        ],
    )


def save(value):
    return save_set(1, value, run_id=get_state(1).run_id)


def scope(saved):
    return scope_for(
        get_state(1),
        code="CLN05",
        zone="hot_kitchen",
        set_id=saved["id"],
        set_revision=saved["revision"],
    )


def test_multiple_measurements_one_product_and_independent_lines(domain_env, tmp_path, monkeypatch):
    setup(domain_env, tmp_path, monkeypatch)
    first = save(group(1, 2))
    assert save(group(1, 2)) == first  # retried initial save
    second = save(group(3, ident="c", product="d"))
    state = get_state(1)
    lines = scope(first).data["lines"]
    assert len(lines) == 2 and all(len(line["products"]) == 1 for line in lines)
    assert [s["reading_c"] for s in lines[0]["products"][0]["sources"]] == [2, 3]
    assert (
        scope(first).context
        == bound_scope(state, scope(first).context, code="CLN05", zone="hot_kitchen").context
    )
    assert len(state.findings) == 3 and all(f.level == "D0" for f in state.findings)
    result = score(1)
    assert compute_fingerprint(state, result, tenant_code=state.tenant) == compute_fingerprint(
        replace(state, measurement_sets={}), result, tenant_code=state.tenant
    )
    delete_set(1, second["id"], revision=second["revision"], run_id=state.run_id)
    assert len(scope(first).data["lines"]) == 1


@pytest.mark.parametrize(
    "change", ["product", "zone", "duplicate", "revision", "run", "violation", "reading"]
)
def test_unconfirmed_cross_zone_duplicate_and_stale_rejected(
    domain_env, tmp_path, monkeypatch, change
):
    setup(domain_env, tmp_path, monkeypatch)
    value = group(1)
    run = get_state(1).run_id
    if change == "product":
        value["products"][0]["confirmed_product"] = False
    elif change == "zone":
        value["zone"] = "fridge"
    elif change == "duplicate":
        value["products"][0]["sources"] *= 2
    elif change == "revision":
        value["products"][0]["sources"][0]["revision"] = "0" * 64
    elif change == "run":
        run = "other-run"
    elif change == "violation":
        f = add_finding(1, "CLN05", "D1", "hot_kitchen", "Violation", reading_c=2)
        value["products"][0]["sources"] = [dict(n=f.n, revision=finding_revision(f))]
    elif change == "reading":
        set_reading(1, 1, None)
        value["products"][0]["sources"][0]["revision"] = finding_revision(get_state(1).finding(1))
    with pytest.raises(ValidationError):
        save_set(1, value, run_id=run)
    assert get_state(1).measurement_sets == {}


def test_source_cannot_be_counted_in_two_lines(domain_env, tmp_path, monkeypatch):
    setup(domain_env, tmp_path, monkeypatch)
    save(group(1))
    with pytest.raises(ValidationError):
        save(group(1, ident="c", product="d"))
    with pytest.raises(ValidationError):
        save(group(2, ident="c"))


def test_scope_invalidation_on_sibling_inventory_and_source_changes(
    domain_env, tmp_path, monkeypatch
):
    setup(domain_env, tmp_path, monkeypatch)
    first = save(group(1))
    context = scope(first).context
    save(group(2, ident="c", product="d"))
    with pytest.raises(MeasurementSetConflict):
        bound_scope(get_state(1), context, code="CLN05", zone="hot_kitchen")
    context = scope(first).context
    set_reading(1, 3, 5)  # even an unselected new/changed measurement invalidates proposal
    with pytest.raises(MeasurementSetConflict):
        bound_scope(get_state(1), context, code="CLN05", zone="hot_kitchen")
    set_reading(1, 1, 6)
    with pytest.raises(MeasurementSetConflict):
        scope(first)
    assert public_sets(get_state(1))[0]["stale"] is True


def prepared(saved):
    return prepare_selected_level(
        1,
        code="CLN05",
        zone="hot_kitchen",
        words="",
        photo_refs=[],
        photos=[],
        selection_revision="1",
        settings=CFG,
        measurement_set_id=saved["id"],
        measurement_set_revision=saved["revision"],
    )


def test_selected_proposal_preserves_full_criterion_and_rechecks_sources(
    domain_env, tmp_path, monkeypatch
):
    setup(domain_env, tmp_path, monkeypatch)
    first = save(group(1, 2))
    before = deepcopy(get_state(1))
    p = prepared(first)
    assert "Synthetic criterion: request missing product facts." in p.ask.question
    assert '"reading_c": 2.0' in p.ask.question and '"reading_c": 3.0' in p.ask.question
    assert get_state(1) == before
    set_reading(1, 1, 9)
    with pytest.raises(MeasurementSetConflict):
        recheck_measurement_scope(p, get_state(1))


def class_context(saved):
    state = get_state(1)
    return dict(
        run_id=state.run_id,
        checklist_version=state.checklist_version,
        code="CLN05",
        zone="hot_kitchen",
        photo_refs=[],
        clarifications=[],
        measurement_context=scope(saved).context,
    )


def test_confirmed_application_edits_unique_finding_and_preserves_evidence(
    domain_env, tmp_path, monkeypatch
):
    setup(domain_env, tmp_path, monkeypatch)
    saved = save(group(1, 2))
    target = add_finding(1, "CLN05", "D1", "hot_kitchen", "Existing violation")
    context = class_context(saved)
    kwargs = dict(
        level="D2",
        class_context=context,
        source_revision=finding_revision(target),
        request_id="a" * 32,
    )
    changed = edit_finding(1, target.n, **kwargs)
    assert changed.level == "D2"
    state = get_state(1)
    event = state.finding_history[-1]
    assert event["measurement_context"]["lines"][0]["products"][0]["sources"][0]["reading_c"] == 2
    assert edit_finding(1, target.n, **kwargs) == changed
    assert len(get_state(1).finding_history) == len(state.finding_history)
    set_reading(1, 1, 8)
    before = get_state(1)
    with pytest.raises(MeasurementSetConflict):
        edit_finding(
            1,
            target.n,
            level="D3",
            class_context=context,
            source_revision=finding_revision(changed),
        )
    assert get_state(1) == before and get_state(1).finding(target.n).level == "D2"


def test_measurement_source_cannot_be_its_own_target(domain_env, tmp_path, monkeypatch):
    setup(domain_env, tmp_path, monkeypatch)
    saved = save(group(1))
    before = get_state(1)
    with pytest.raises(ValidationError, match="Целевая запись"):
        edit_finding(1, 1, code="CLN05", level="D1", class_context=class_context(saved))
    assert get_state(1) == before


def test_new_target_is_human_applied_once_and_snapshot_survives_source_edit(
    domain_env, tmp_path, monkeypatch
):
    from src.domain.errors import EngineError

    setup(domain_env, tmp_path, monkeypatch)
    saved = save(group(1))
    context = class_context(saved)
    target = add_finding(
        1, "CLN05", "D2", "hot_kitchen", "Human confirmed violation", class_context=context
    )
    with pytest.raises(EngineError):
        add_finding(1, "CLN05", "D2", "hot_kitchen", "Duplicate", class_context=context)
    state = get_state(1)
    assert len([f for f in state.findings if f.code == "CLN05"]) == 1
    snapshot = deepcopy(state.finding_history[-1]["measurement_context"])
    set_reading(1, 1, 8)
    assert get_state(1).finding(target.n).level == "D2"
    assert (
        get_state(1).finding_history[len(state.finding_history) - 1]["measurement_context"]
        == snapshot
    )


@pytest.mark.parametrize(
    "change", ["schema", "confirmed", "extra", "products", "boolean_n", "facts"]
)
def test_strict_bounded_set_input(domain_env, tmp_path, monkeypatch, change):
    setup(domain_env, tmp_path, monkeypatch)
    value = group(1)
    if change == "schema":
        value["schema"] = True
    elif change == "confirmed":
        value["confirmed"] = False
    elif change == "extra":
        value["reading_c"] = 99
    elif change == "products":
        value["products"] *= 31
    elif change == "boolean_n":
        value["products"][0]["sources"][0]["n"] = True
    elif change == "facts":
        value["products"][0]["facts"] = "x" * 501
    with pytest.raises(ValidationError):
        save(value)
    assert get_state(1).measurement_sets == {}


def test_existing_target_free_form_classification_words_are_preserved_exactly(
    domain_env, tmp_path, monkeypatch
):
    setup(domain_env, tmp_path, monkeypatch)
    saved = save(group(1))
    target = add_finding(
        1, "CLN05", "D1", "hot_kitchen", "Violation", words="Original source words"
    )
    words = "  Human supplemental fact\n\t".ljust(1000, "x")
    assert len(words) == 1000
    kwargs = dict(
        level="D2",
        class_context=class_context(saved),
        context_words=words,
        source_revision=finding_revision(target),
        request_id="e" * 32,
    )
    after = edit_finding(1, target.n, **kwargs)
    state = get_state(1)
    event = state.finding_history[-1]
    assert event["clarifications"] == []
    assert event["classification_words"] == words
    assert after.words == target.words == "Original source words"
    assert event["after"][0]["words"] == target.words
    assert edit_finding(1, target.n, **kwargs) == after
    assert get_state(1).finding_history == state.finding_history


@pytest.mark.parametrize("words", [123, "x" * 1001, "invalid\x00fact", "invalid\x7ffact"])
def test_invalid_classification_words_cannot_change_target(
    domain_env, tmp_path, monkeypatch, words
):
    setup(domain_env, tmp_path, monkeypatch)
    saved = save(group(1))
    target = add_finding(
        1, "CLN05", "D1", "hot_kitchen", "Violation", words="Original source words"
    )
    before = get_state(1)
    with pytest.raises(ValidationError):
        edit_finding(
            1, target.n, level="D2", class_context=class_context(saved), context_words=words
        )
    assert get_state(1) == before


def test_classification_words_require_bound_class_context(domain_env, tmp_path, monkeypatch):
    setup(domain_env, tmp_path, monkeypatch)
    target = add_finding(1, "CLN05", "D1", "hot_kitchen", "Violation")
    before = get_state(1)
    with pytest.raises(ValidationError):
        edit_finding(1, target.n, level="D2", context_words="Unbound facts")
    assert get_state(1) == before
