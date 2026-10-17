from app import notify
from app.models import Alert


def test_deal_column_is_authoritative_and_title_is_fallback():
    stored = Alert(kind="deal", severity="warning", title="Acme: no update for 40 days", detail="", dedupe_key="a",
                   deal="Acme Renamed")
    assert notify.alert_deal(stored) == "Acme Renamed"
    legacy = Alert(kind="dd", severity="warning", title="Beta: question overdue", detail="", dedupe_key="b", deal=None)
    assert notify.alert_deal(legacy) == "Beta"
    other = Alert(kind="covenant", severity="warning", title="Gamma: breach", detail="", dedupe_key="c", deal=None)
    assert notify.alert_deal(other) is None
