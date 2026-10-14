from __future__ import annotations

from app.flows.moderation import mute_label, mute_seconds


def test_mute_ladder_starts_at_third_strike():
    assert mute_seconds(1) is None
    assert mute_seconds(2) is None
    assert mute_seconds(3) == 15 * 60
    assert mute_seconds(4) == 30 * 60
    assert mute_seconds(5) == 24 * 3600
    assert mute_seconds(9) == 24 * 3600


def test_mute_labels():
    assert mute_label(15 * 60) == "15 دقيقة"
    assert mute_label(30 * 60) == "30 دقيقة"
    assert mute_label(24 * 3600) == "24 ساعة"
