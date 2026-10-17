from openpyxl import Workbook

from app.parse.xlsx import extract_sheets


def test_numeric_cells_carry_their_row_label(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "IS"
    ws.append(["Revenue", 1234])
    ws.append(["Cost of sales", 900])
    p = tmp_path / "a.xlsx"
    wb.save(p)
    text = extract_sheets(p)[0].text
    assert "IS!B1: 1,234 | row: Revenue" in text
    assert "IS!B2: 900 | row: Cost of sales" in text
    assert "IS!A1: Revenue" in text  # the label cell itself stays plain
