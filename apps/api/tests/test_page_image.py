import pymupdf

from app.page_image import render_page


def _pdf(lines: list[str]) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(lines):
        page.insert_text((72, 100 + 20 * i), line)
    data = doc.tobytes()
    doc.close()
    return data


def test_quote_is_highlighted_on_its_page():
    pdf = _pdf(["Cover page", "Net sales $ 32,136 $ 32,765 $ 31,657"])
    png, highlighted = render_page(pdf, 1, "Net sales $ 32,136 $ 32,765")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert highlighted is True


def test_quote_not_on_page_is_reported_not_marked():
    pdf = _pdf(["Cover page", "Net sales $ 32,136"])
    png, highlighted = render_page(pdf, 1, "Total assets 44,659")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert highlighted is False


def test_wrapped_quote_matches_its_leading_words():
    pdf = _pdf(["Operating income 6,174 7,207"])
    _, highlighted = render_page(pdf, 1, "Operating income 6,174 7,207 and a trailing phrase not on the page")
    assert highlighted is True


def test_table_row_marks_the_quote_words_across_columns():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Net income $ 19,881 Other 1")
    page.insert_text((300, 100), "$ 74,039")
    pdf = doc.tobytes()
    doc.close()
    _, highlighted = render_page(pdf, 1, "Net income $ 19,881 $ 74,039 $ 79,082")
    assert highlighted is True
