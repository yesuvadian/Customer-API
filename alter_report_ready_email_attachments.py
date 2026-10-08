"""
ALTER: attach the generated report file to every "*_report_ready" email and
drop the broken download link.

The seeded report-ready email templates linked to {{download_url}}, which is
a relative path (/reports/download/<file>) — email clients render it as
"http:///reports/download/..." (no host), and the endpoint behind it needs
the app's bearer token anyway, so the link could never work from an inbox.

This sets NotificationTemplate.attachment_vars on those templates so the
report file itself is attached (NotificationService reads it straight off
disk from the ReportLog the event was fired for — same file, same name,
PDF or Excel), and rewrites the link sentence in the body to say so.

Safe to run multiple times.

Usage:
    python alter_report_ready_email_attachments.py
"""

from __future__ import annotations

from database import SessionLocal
from models import NotificationTemplate

# var_key deliberately NOT a context variable: an empty value makes
# NotificationService fall through to "generate from source" (the ReportLog),
# instead of treating the value as a URL to fetch.
ATTACHMENT_VARS = [{"var_key": "report_attachment", "type": "excel", "source_type": "report_log"}]

OLD_LINK = "<p><a href='{{download_url}}'>Download the report</a> from SEACMS (login required).</p>"
NEW_TEXT = ("<p>The report is attached to this email. It is also available in "
            "SEACMS under Reporting Center &rarr; Log.</p>")


def main() -> None:
    db = SessionLocal()
    try:
        templates = (
            db.query(NotificationTemplate)
            .filter(
                NotificationTemplate.event_type.like("%report_ready"),
                NotificationTemplate.channel == "email",
            )
            .all()
        )
        changed = 0
        for t in templates:
            touched = False
            if t.attachment_vars != ATTACHMENT_VARS:
                t.attachment_vars = ATTACHMENT_VARS
                touched = True
            if t.body_template and OLD_LINK in t.body_template:
                t.body_template = t.body_template.replace(OLD_LINK, NEW_TEXT)
                touched = True
            if touched:
                changed += 1
                print(f"[OK] {t.event_type} ({'org' if t.organization_id else 'global'})")
        db.commit()
        print(f"\n{changed} of {len(templates)} report-ready email template(s) updated.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
