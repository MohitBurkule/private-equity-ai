from app.redact import redact


def test_identifiers_are_replaced_with_typed_tokens():
    s = "Contact jane.doe@fund.co.uk or 07700 900123. NI AB123456C. Sort 20-00-00 IBAN GB29 NWBK 6016 1331 9268 19."
    out = redact(s)
    assert "[EMAIL]" in out and "[PHONE]" in out and "[NI_NUMBER]" in out
    assert "[SORT_CODE]" in out and "[IBAN]" in out
    assert "jane" not in out and "07700" not in out


def test_card_needs_valid_luhn():
    assert "[CARD]" in redact("card 4111 1111 1111 1111 on file")
    assert "4111 1111 1111 1112" in redact("ref 4111 1111 1111 1112")


def test_financial_figures_are_untouched():
    s = "Revenue 1,577 and net income (150.5); FY2018 margin 12.3% total 1234567"
    assert redact(s) == s


def test_external_provider_receives_redacted_prompt(monkeypatch):
    from app.llm import RedactingLLM

    seen = {}

    class Inner:
        def complete(self, system, prompt):
            seen["prompt"] = prompt
            return "ok"

    assert RedactingLLM(Inner()).complete("sys", "mail jane@x.co.uk revenue 1,577") == "ok"
    assert seen["prompt"] == "mail [EMAIL] revenue 1,577"
