from __future__ import annotations

from app.db import Database
from app.filters.engine import WordFilter
from app.flows.moderation import create_filter, moderation_action


def make_filter() -> WordFilter:
    return WordFilter({"en": ["sample", "blocked phrase"], "ar": ["قلم"]})


def test_english_whole_word_and_casefold():
    matcher = make_filter()
    assert matcher.match("SAMPLE") == "sample"
    assert matcher.match("this is a blocked phrase!") == "blocked phrase"
    assert matcher.match("samples") is None
    assert matcher.match("sampler") is None
    assert matcher.match("resample") is None


def test_arabic_script_boundaries_avoid_short_root_traps():
    matcher = make_filter()
    assert matcher.match("هذا قلم.") == "قلم"
    assert matcher.match("القلم") is None
    assert matcher.match("قلمي") is None


def test_dry_run_selects_log_only_action():
    assert moderation_action(True) == "log"
    assert moderation_action(False) == "enforce"


def test_add_and_remove_are_in_memory_only():
    matcher = make_filter()
    assert matcher.add("newterm")
    assert not matcher.add("NEWTERM")
    assert matcher.match("NEWTERM") == "newterm"
    assert matcher.remove("newterm")
    assert matcher.match("newterm") is None
    assert not matcher.remove("newterm")


def test_filter_is_seeded_from_the_database(tmp_path):
    db = Database(tmp_path / "bot.db")
    db.execute("INSERT OR IGNORE INTO blocked_words(language,word) VALUES(?,?)", ("en", "sample"))
    db.execute("INSERT OR IGNORE INTO blocked_words(language,word) VALUES(?,?)", ("ar", "مثال"))
    matcher = create_filter(None, db)
    assert matcher.match("a sample") == "sample"
    assert matcher.match("samples") is None
    assert matcher.match("كلمة مثال هنا") == "مثال"
    assert matcher.match("مثالك") is None
    assert matcher.match("المثال") is None
