# Country and pizzeria contacts

Administration → Countries reuses the existing developer, partner-space and report-language forms. The main card additionally contains the country mailing list and pizzeria addresses/partner contacts. Contract data is preserved under the additional collapsible section.

Pizzeria edits change only address, partner name and partner email. The form selects an authoritative country/unit key; submitted names, Dodo IDs and statuses cannot change identity. Existing imported dates, status, area, seats and source metadata remain intact. A directory entry without a source profile receives a minimal profile when contacts are first saved. New pizzeria creation accepts partner email before any directory mutation. Invalid fields do not change stored data. Existing contact mutations require HQ space.manage, country reach and same origin; partner spaces cannot use them.

The country mailing list is the `country_contacts` rows of kind `mailing`, edited one address at a time in the main country card (the only block titled "Mailing recipients"). It is the single source of the auto-filled To in the Gmail draft of a prescription or action plan when the inspection has no address of its own (`country_contacts.mailing_to`: deduplicated, in creation order). No message is sent by these forms or by the draft: the person sends. An empty list falls back to the contract (DKK) contacts, then to remembered recipients of previous prescriptions. If the list cannot be read, old addresses are not silently substituted.

Migration 0112 once stored a free-text override in country_mailing_recipients; migration 0116 drops that table (empty on production) together with the override form and the `settings/recipients` route. Existing country_recipients remains the legacy memory of issued prescriptions and is not migrated or deleted.

Routes:

- POST /country/<code>/unit-profile: contact-only update, space.manage plus country reach.
- Existing developer, partner, report-language and contract routes remain compatible.

Regression coverage: tests/test_web_country_contacts.py and tests/test_db_country_contacts.py, plus existing unit creation/country/contract tests. The database tests use temporary databases on the documented remote test PostgreSQL instance, never production.

Main D690 country contacts are the primary partner/mailing editor. RX/plan inherit the main mailing directory when no advanced override exists; an explicit empty override still suppresses every fallback. The advanced editor is collapsed. Unit creation retains its existing unit.create permission; editing administrative contact fields requires space.manage.
