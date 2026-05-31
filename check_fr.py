from database import SessionLocal
from models import NotificationEventCatalogue, NotificationTemplate, NotificationRoutingRule

db = SessionLocal()
try:
    for et in ["fr_submitted", "fr_approved", "fr_rejected"]:
        cat = db.query(NotificationEventCatalogue).filter_by(event_type=et).first()
        tmpl_count = db.query(NotificationTemplate).filter_by(event_type=et).count()
        rule_count = db.query(NotificationRoutingRule).filter_by(event_type=et).count()
        exists = "YES" if cat else "NO"
        label = cat.label if cat else "MISSING"
        print(et + ": catalogue=" + exists + "  label=" + label + "  templates=" + str(tmpl_count) + "  rules=" + str(rule_count))
finally:
    db.close()
