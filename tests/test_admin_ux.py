from __future__ import annotations

from app.db import Database
from app.flows.admin import (
    PRESETS,
    menu_action_from_callback,
    preset_key,
    preset_reply_text,
    preset_request,
    split_preset_caption,
)


def test_no_content_preset_gives_contextual_prompt_and_persists(tmp_path):
    text, prompt = preset_request("summary", "/summary")
    assert text == ""
    assert prompt == "أرسل الآن ما تريد تلخيصه: نص أو صورة أو تسجيل."

    db = Database(tmp_path / "bot.db")
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (preset_key(42), "summary"))
    # A new database instance sees pending actions after a restart.
    restarted = Database(tmp_path / "bot.db")
    row = restarted.one("SELECT value FROM settings WHERE key=?", (preset_key(42),))
    assert row is not None and row["value"] == "summary"
    assert preset_reply_text(row["value"]) == prompt
    assert PRESETS[row["value"]]


def test_menu_callback_routes_each_action():
    expected = {
        "summary", "notes", "explain", "exercise", "flash", "visual", "new", "help"
    }
    assert {menu_action_from_callback(f"menu:{action}") for action in expected} == expected
    assert menu_action_from_callback("menu:unknown") is None
    assert menu_action_from_callback("other:summary") is None
    assert menu_action_from_callback(None) is None


def test_preset_command_in_caption_drives_attachment_flow():
    assert split_preset_caption("/flash") == ("", PRESETS["flash"])
    assert split_preset_caption("/flash@MechatronicsAIBot extra") == ("extra", PRESETS["flash"])
    assert split_preset_caption("plain caption") == ("plain caption", "")
    assert split_preset_caption("") == ("", "")
