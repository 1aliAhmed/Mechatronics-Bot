from __future__ import annotations

import glob
import os
import shutil
import tempfile

from app.audit import AuditLogger
from app.db import Database
from app.flows.visuals import cleanup_image, render_visual


def test_audit_record_never_raises(tmp_path):
    db = Database(tmp_path / "a.db")
    audit = AuditLogger(db, tmp_path / "logs")
    shutil.rmtree(tmp_path / "logs")
    audit.record("outgoing", chat_id=1, user_id=2, kind="test", content="hello")


def test_cleanup_image_removes_render_directory(tmp_path):
    directory = tmp_path / "visual-render-test"
    directory.mkdir()
    image = directory / "visual.png"
    image.write_bytes(b"x")
    cleanup_image(image)
    assert not directory.exists()


def test_failed_render_cleans_temp_directory():
    pattern = os.path.join(tempfile.gettempdir(), "visual-render-*")
    before = set(glob.glob(pattern))
    try:
        render_visual("def broken(:", kind="python")
    except Exception:
        pass
    else:
        raise AssertionError("expected the render to fail")
    after = set(glob.glob(pattern))
    assert after <= before
