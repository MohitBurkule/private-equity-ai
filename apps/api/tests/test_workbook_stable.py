"""A connector's workbook must come out the same bytes on every render, or a re-sync sees a new version and ingests
it again. openpyxl stamps the save time into the core properties and the zip entries, so this runs a second apart."""
import time

from openpyxl import Workbook

from app.connectors.workbook import save_stable


def _render() -> bytes:
    wb = Workbook()
    wb.active["A1"] = "Holder"
    return save_stable(wb)


def test_same_workbook_saved_a_second_later_is_byte_identical():
    first = _render()
    time.sleep(1.1)
    assert _render() == first
