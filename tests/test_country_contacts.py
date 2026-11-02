"""Country contacts are people and recipients, separate from access spaces."""

import pytest

from src.db.country_contacts import ContactError, Fields, clean


def test_partner_name_and_email_are_independent_of_space() -> None:
    assert clean(Fields("partner", "  Anna   Example  ", "owner@example.com")) == Fields(
        "partner", "Anna Example", "owner@example.com"
    )
    assert clean(Fields("partner", "Anna Example", "")).email == ""


@pytest.mark.parametrize(
    "fields",
    [
        Fields("space", "Demo", "owner@example.com"),
        Fields("partner", "", ""),
        Fields("mailing", "Anna", ""),
        Fields("mailing", "", "not-email"),
        Fields("mailing", "", "one@example.com, two@example.com"),
        Fields("mailing", "", "one@example.com\r\nBcc:other@example.com"),
        Fields("mailing", "", "group:other@example.com"),
        Fields("partner", "Anna\x00Example", "owner@example.com"),
        Fields("partner", "A" * 201, "owner@example.com"),
    ],
)
def test_invalid_contact_is_rejected_before_storage(fields: Fields) -> None:
    with pytest.raises(ContactError):
        clean(fields)


def test_mailing_contact_requires_one_valid_address_but_name_is_optional() -> None:
    assert clean(Fields("mailing", "", "owner+audit@example.com")) == Fields(
        "mailing", "", "owner+audit@example.com"
    )
