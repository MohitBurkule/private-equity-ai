from fastapi.testclient import TestClient

from app.ddq import Question, answer
from app.main import app
from tests.helpers import new_tenant

c = TestClient(app)


def acc():
    return {"board_meeting_frequency": [{"value": "quarterly", "source": {
                "document_id": "d1", "page": 3, "quote": "boards meet quarterly"}}],
            "concentration_limit": [{"value": "15% of commitments", "source": {
                "document_id": "d2", "page": 7, "quote": "15%"}}]}


def test_answers_only_where_a_rule_matches_and_cites_it():
    out = answer([Question("1", "Portfolio", "How often do portfolio company boards meet?"),
                  Question("2", "Portfolio", "What is the concentration limit per company?"),
                  Question("3", "Team", "Describe key person arrangements.")], acc())
    assert out[0]["status"] == "answered" and out[0]["answer"] == "quarterly"
    assert out[0]["source"] == {"document_id": "d1", "page": 3, "quote": "boards meet quarterly"}
    assert out[1]["answer"] == "15% of commitments"
    assert out[2] == {"id": "3", "section": "Team", "question": "Describe key person arrangements.",
                      "status": "unanswered", "reason": "no accepted firm rule matched"}


def test_too_little_overlap_is_unanswered_not_guessed():
    out = answer([Question("9", "Legal", "Is the fund registered in Luxembourg?")], acc())
    assert out[0]["status"] == "unanswered"


def test_endpoint_counts_and_hides_rules_from_unseen_documents():
    h = new_tenant(c, "ddq1")
    r = c.post("/ddq/answer", headers=h, json={"questions": [
        {"id": "1", "section": "P", "text": "How often do portfolio company boards meet?"}]})
    assert r.status_code == 200 and r.json()["answered"] == 0 and r.json()["unanswered"] == 1
