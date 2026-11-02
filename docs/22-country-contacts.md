# Country and pizzeria contacts

Administration → Countries reuses the existing developer, partner-space and report-language forms. The main card additionally contains country mailing recipients and pizzeria addresses/partner contacts. Contract data is preserved under the additional collapsible section.

Pizzeria edits change only address, partner name and partner email. The form selects an authoritative country/unit key; submitted names, Dodo IDs and statuses cannot change identity. Existing imported dates, status, area, seats and source metadata remain intact. A directory entry without a source profile receives a minimal profile when contacts are first saved. New pizzeria creation accepts partner email before any directory mutation. Invalid fields do not change stored data. Existing contact mutations require HQ space.manage, country reach and same origin; partner spaces cannot use them.

Country mailing recipients are an explicit To override for new prescriptions, independent of partner email, contract contacts, remembered recipients of previous prescriptions and global HQ CC. No message is sent by these forms. A configured empty list intentionally leaves To blank. The separate reset action removes the override and restores the previous defaults: contract contacts, otherwise the last issued prescription recipients. If configuration cannot be read, old addresses are not silently substituted. Issuing a prescription does not rewrite explicit configuration.

Migration 0111 stores this override in country_mailing_recipients. Application reads are restricted to HQ/service space; writes use the existing administrator connection and mailing.manage web permission. Partners cannot read the table. Existing country_recipients remains the legacy memory of issued prescriptions and is not migrated or deleted.

Routes:

- POST /country/<code>/unit-profile: contact-only update, space.manage plus country reach.
- POST /country/<code>/settings/recipients: save explicit list or reset=1, mailing.manage plus country reach.
- Existing developer, partner, report-language and contract routes remain compatible.

Regression coverage: tests/test_web_country_contacts.py and tests/test_db_country_contacts.py, plus existing unit creation/country/contract tests. The database tests use temporary databases on the documented remote test PostgreSQL instance, never production.

Main D690 country contacts are the primary partner/mailing editor. RX/plan inherit the main mailing directory when no advanced override exists; an explicit empty override still suppresses every fallback. The advanced editor is collapsed. Unit creation retains its existing unit.create permission; editing administrative contact fields requires space.manage.
