from __future__ import annotations

import hashlib
import mimetypes
import shutil
import subprocess
import tempfile
from pathlib import Path


def normalize_text(text: str, limit: int) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) > limit:
        raise ValueError("النص أطول من الحد المسموح.")
    return normalized


def store_media(data: bytes, root: Path, *, file_id: str, kind: str, max_bytes: int, filename: str = "") -> dict[str, object]:
    if not data:
        raise ValueError("الملف فارغ.")
    if len(data) > max_bytes:
        raise ValueError("حجم الملف يتجاوز الحد المسموح.")
    digest = hashlib.sha256(data).hexdigest()
    directory = root / "files" / digest[:2]
    directory.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower()[:10] or {"image": ".jpg", "voice": ".ogg", "audio": ".bin", "document": ".bin"}.get(kind, ".bin")
    if kind == "image":
        suffix = ".source"
    path = directory / f"{digest}{suffix}"
    if not path.exists():
        path.write_bytes(data)
    result: dict[str, object] = {"file_id": file_id, "type": kind, "size": len(data), "hash": digest, "local_path": str(path)}
    if kind == "image":
        try:
            from PIL import Image, ImageOps
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail((2048, 2048))
                normalized = directory / f"{digest}.jpg"
                im.save(normalized, "JPEG", quality=88, optimize=True)
                result.update(local_path=str(normalized), normalized_hash=hashlib.sha256(normalized.read_bytes()).hexdigest(), normalized_size=normalized.stat().st_size)
        except ImportError as exc:
            raise ValueError("معالجة الصور غير متاحة؛ ثبّت Pillow.") from exc
        except Exception as exc:
            raise ValueError("تعذر فتح الصورة أو تطبيعها.") from exc
    if kind in {"voice", "audio"}:
        result["mime"] = mimetypes.guess_type(filename or path.name)[0] or {".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/opus", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav"}.get(path.suffix.lower(), "application/octet-stream")
    if kind in {"voice", "audio"} and path.suffix.lower() in {".ogg", ".oga", ".opus"}:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            converted = directory / f"{digest}.wav"
            try:
                subprocess.run([ffmpeg, "-y", "-i", str(path), "-ac", "1", "-ar", "16000", str(converted)], capture_output=True, timeout=60, check=True)
                result.update(local_path=str(converted), normalized_hash=hashlib.sha256(converted.read_bytes()).hexdigest(), normalized_size=converted.stat().st_size, mime="audio/wav")
            except Exception as exc:
                raise ValueError("تعذر تحويل التسجيل الصوتي إلى صيغة مناسبة.") from exc
        else:
            result["mime"] = "audio/ogg"
    return result
