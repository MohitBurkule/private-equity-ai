"""Sideways scanned pages: the turn with the most words wins. SYNTHETIC text only."""
from app.parse import ocr


def test_upright_page_with_enough_words_is_not_turned():
    assert ocr.word_count("Revenue 1,234 EBITDA 210 Headcount 412 Cash 88 Net debt 40 Gross margin 31 Synth year 2026") >= ocr.MIN_WORDS_UPRIGHT


def test_pick_turn_takes_most_words_and_ties_keep_upright():
    up = ("junk", 0.2)
    side = ("Synth Revenue 77 Synth EBITDA 9 Synth Cash 4", 0.9)
    assert ocr.pick_turn({0: up, 90: side, 270: ("x", 0.1), 180: ("y", 0.1)}) == 90
    same = ("a b c", 0.5)
    assert ocr.pick_turn({0: same, 90: same, 270: same, 180: same}) == 0


def test_punctuation_is_not_a_word():
    assert ocr.word_count("| - . , |") == 0
