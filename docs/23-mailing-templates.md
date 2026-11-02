# Mailing and document templates

Administration → Letters and notifications shows an editable subject and plain-text body for inspection emails, prescription emails and action-plan emails. The prescription section also switches to its document template. Russian and English are independent. Variables are listed in the editor; expressions, attributes, indexing, conversions and formatting are rejected. Multiline body variables cannot enter subject headers. Preview uses only synthetic example values and does not save or send. Save creates an immutable version with author/time; reset creates another version that uses built-in defaults. Invalid input stays in the editor.

Inspection emails keep the existing engine body templates (plan/clean/empty) and their history. The visible engine-block section remains editable. A separate message template controls the subject and optional wrapping of the confirmed inspection letter through {letter_body}; it never recalculates scores or findings. Built-in/reset preserves the previous subject and rich-text body exactly. Only HQ inspection emails use HQ configuration; partner-space inspection letters retain their prior behaviour. The existing Gmail-draft action consumes the template; no new send action is introduced.

Prescription email templates use the already confirmed subject/body and facts of the selected prescription. The existing explicit Gmail-draft action consumes the configured cover message. A store or rendering failure is handled before creating a draft and before completing the issue transaction. Recipients remain on the prescription, outside template text; global CC remains separate.

The prescription card links to an actual printable document using its heading, confirmed body, creation/issue date, due date, selected pizzerias, directory addresses and visible inspection bases. Built-in wording labels facts neutrally; it adds no legal claims or deadlines. The print page can be printed or saved as PDF in the browser. It does not alter the prescription or its workflow. Access is through the same current reach as the prescription. Partner spaces use the neutral built-in format and cannot read HQ template configuration.

The action-plan card provides Prepare email. Preview and downloadable .eml use facts from the selected in-reach plan, its actual card URL, the configured country To list (blank if absent) and plan-specific HQ CC. Existing in-app plan notifications are unchanged. Downloading a message never sends it or changes plan status.

Migration 0110 extends mailing_templates with a subject and the message slot for inspection/prescription/plan/document, keeping existing body slots and immutable history. Application reads remain HQ/service-only; administrator writes and mailing.manage web guards are retained. Configuration mutations remain blocked in the public demo. Demo pizzeria profile edits follow the existing demo unit-creation policy.

Routes:

- POST /administration/mailings/<kind>/content: save, reset or synthetic preview, mailing.manage.
- GET /actions/prescriptions/<id>/document: actual document, view.actions plus prescription reach.
- GET /actions/requests/<id>/letter: actual plan email preview; download=eml prepares a file, plan.manage plus plan reach.

Tests cover whitelist/header injection, safe markup, explicit reset/version history, old inspection slots, editor permissions, foreign origin, real prescription document/cover consumption, actual plan EML and handled template failures before outbound calls.
