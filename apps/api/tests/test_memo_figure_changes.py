"""Figure and claim changes between IC memo drafts, each side keeping its source note. SYNTHETIC figures."""

from app.memo_diff import figure_changes


def test_changed_figure_pairs_old_and_new_with_their_notes():
    prev = "Revenue FY2025 120 [1]\nThe business is asset light [2]"
    cur = "Revenue FY2025 135 [3]\nThe business is asset light [2]"
    out = figure_changes(prev, cur)
    assert out["figure_changes"] == [{"label": "Revenue FY2025 …", "from": ["120"],
                                      "to": ["135"], "notes_from": ["1"], "notes_to": ["3"]}]
    assert out["claim_changes"] == {"added": [], "removed": []}


def test_reworded_claim_is_a_claim_change_and_note_only_edit_is_not_a_figure():
    prev = "Management expects margin recovery [4]\nHeadcount 40 [5]"
    cur = "Management is cautious on margins [6]\nHeadcount 40 [7]"
    out = figure_changes(prev, cur)
    assert out["figure_changes"] == []
    assert out["claim_changes"]["removed"] == ["Management expects margin recovery [4]"]
    assert out["claim_changes"]["added"] == ["Management is cautious on margins [6]"]


def test_label_keeps_years_and_parentheses_and_masks_only_the_changed_figure():
    prev = "- Revenue FY2025: 405.0 (GAAP, USD m) [1]"
    cur = "- Revenue FY2025: 410.0 (GAAP, USD m) [3]"
    out = figure_changes(prev, cur)["figure_changes"]
    assert out == [{"label": "Revenue FY2025: … (GAAP, USD m)", "from": ["405.0"], "to": ["410.0"],
                    "notes_from": ["1"], "notes_to": ["3"]}]
