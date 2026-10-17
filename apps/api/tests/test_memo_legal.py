from app.flagship import detect_doc_type
from app.memo import Memo, add_legal


def test_legal_flags_are_cited_in_the_memo_section():
    m = Memo("Acme")
    add_legal(m, [{"text": "Assignment restricted: check consent.", "document_id": "abcdef1234", "page": 3,
                   "quote": "Tenant shall not assign this Lease without consent."}])
    assert m.legal == ['Assignment restricted: check consent. [abcdef12 p.3: "Tenant shall not assign this Lease without consent."]']


def test_no_flags_is_said_out_loud_not_silently_dropped():
    m = Memo("Acme")
    add_legal(m, [])
    assert m.legal == ["No legal red flags in this document under the playbook (rules only)."]


def test_lease_and_employment_are_detected_from_the_head_of_the_document():
    assert detect_doc_type([(1, "COMMERCIAL LEASE AGREEMENT between Landlord and Tenant")]) == "lease"
    assert detect_doc_type([(1, "EMPLOYMENT AGREEMENT between the Company and the Executive")]) == "employment"
