from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import shutil
import time
from pathlib import Path

import fitz
from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.ai.providers import OpenRouter
from app.ai.queue import JobQueue
from app.quota import QuotaService, quota_message
from app.config import Settings
from app.db import Database
from app.render.pdf import render_pdf
from app.security import is_community_admin
from app.source_images import embed_images, extract_queries, fetch_commons_image, strip_markers

log = logging.getLogger(__name__)
router = Router()
MAX_SOURCE_PAGES = 200


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def document_title(markdown: str) -> str:
    return next((re.sub(r"^#{1,6}\s*", "", line).strip() for line in markdown.splitlines() if line.strip().startswith("#")), "")


def document_filename(markdown: str, suffix: str) -> str:
    """Telegram-facing file name derived from the document title."""
    title = document_title(markdown) or "مادة دراسية"
    name = re.sub(r'[\\/:*?"<>|\r\n\t#]+', " ", title)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name[:70] or "مادة دراسية") + suffix


TEXT_LAYER_MIN_CHARS = 120
MIN_RASTER_PIXELS = 90 * 90


def page_text_layer(path: str, index: int) -> str | None:
    """Extract a page's embedded text layer; None when absent or too thin to trust."""
    try:
        with fitz.open(path) as document:
            if index > document.page_count:
                return None
            text = document[index - 1].get_text("text").strip()
    except Exception:
        return None
    return text if len(text) >= TEXT_LAYER_MIN_CHARS else None


def fast_page_text(path: str, index: int) -> str | None:
    """Text layer for pages that need no vision: no real raster image and enough text."""
    try:
        with fitz.open(path) as document:
            if index > document.page_count:
                return None
            page = document[index - 1]
            text = page.get_text("text").strip()
            if len(text) < TEXT_LAYER_MIN_CHARS:
                return None
            for item in page.get_images(full=True):
                width, height = int(item[2] or 0), int(item[3] or 0)
                if width * height >= MIN_RASTER_PIXELS:
                    return None
    except Exception:
        return None
    return text


def page_origin(source_paths: list[str], limit_hint: int | None, index: int) -> tuple[str, int] | None:
    """Map a global page index (as iter_pages yields them) to (source path, page number)."""
    cursor = index
    for source in source_paths:
        local = Path(source)
        if local.suffix.lower() == ".pdf":
            with fitz.open(local) as document:
                limit = min(limit_hint or MAX_SOURCE_PAGES, len(document))
                if cursor <= limit:
                    return source, cursor
                cursor -= limit
        else:
            if cursor == 1:
                return source, 1
            cursor -= 1
    return None


async def run_bounded(items, worker, limit: int = 4) -> None:
    """Run worker(item) for a lazy iterable with at most `limit` tasks in flight."""
    pending: list[asyncio.Task] = []
    for item in items:
        pending.append(asyncio.create_task(worker(item)))
        if len(pending) >= limit:
            await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            pending = [task for task in pending if not task.done()]
    if pending:
        await asyncio.wait(pending)


def requested_page_limit(caption: str) -> int | None:
    match = re.search(r"(?:first|أول|اول)\s*(\d{1,4})\s*(?:pages?|صفح)", caption or "", flags=re.IGNORECASE)
    if not match:
        return None
    return max(1, min(int(match.group(1)), MAX_SOURCE_PAGES))


PRESET_KEYS = frozenset({"summary", "notes", "explain", "exercise", "flash"})


def caption_preset(caption: str) -> bool:
    head = (caption or "").strip().split(maxsplit=1)[0] if (caption or "").strip() else ""
    key = head[1:].split("@")[0].lower() if head.startswith("/") else ""
    return key in PRESET_KEYS


def count_pages(source_paths: list[str], limit_hint: int | None) -> tuple[int, tuple[int, int] | None]:
    total, truncated = 0, None
    for source in source_paths:
        local = Path(source)
        if local.suffix.lower() == ".pdf":
            with fitz.open(local) as document:
                limit = min(limit_hint or MAX_SOURCE_PAGES, len(document))
                if len(document) > limit:
                    truncated = (limit, len(document))
                total += limit
        else:
            total += 1
    return total, truncated


def iter_pages(source_paths: list[str], limit_hint: int | None):
    """Yield one page image at a time so only a single page stays in memory."""
    for source in source_paths:
        local = Path(source)
        if local.suffix.lower() == ".pdf":
            with fitz.open(local) as document:
                limit = min(limit_hint or MAX_SOURCE_PAGES, len(document))
                for index in range(limit):
                    yield document[index].get_pixmap(dpi=150, alpha=False).tobytes("png")
        else:
            yield local.read_bytes()


def resolve_doc_digest(db: Database, token: str) -> str | None:
    cleaned = (token or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{8,64}", cleaned):
        return None
    row = db.one("SELECT hash FROM docs WHERE hash=? OR hash LIKE ? ORDER BY rowid DESC LIMIT 1", (cleaned, cleaned + "%"))
    return str(row["hash"]) if row else None


def redo_source_paths(db: Database, digest: str) -> tuple[str, list[str]]:
    """Resolve the source file list for a document; revised documents point at their parent."""
    row = db.one("SELECT source FROM docs WHERE hash=?", (digest,))
    raw = str(row["source"] or "") if row else ""
    if raw.startswith("["):
        return digest, json.loads(raw)
    if raw:
        parent = db.one("SELECT source FROM docs WHERE hash=?", (raw,))
        if parent and str(parent["source"] or "").startswith("["):
            return raw, json.loads(str(parent["source"]))
    return digest, []


def doc_keyboard(digest: str) -> InlineKeyboardMarkup:
    token = digest[:32]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="نشر", callback_data=f"doc:publish:{token}"), InlineKeyboardButton(text="طلب تعديل", callback_data=f"doc:revise:{token}"), InlineKeyboardButton(text="إعادة", callback_data=f"doc:redo:{token}")],
    ])


def save_page_preview(image: bytes, folder: Path, index: int) -> Path:
    """Downscale a page image to a compact JPEG for the PDF figures appendix."""
    from io import BytesIO

    from PIL import Image

    folder.mkdir(parents=True, exist_ok=True)
    with Image.open(BytesIO(image)) as page:
        converted = page.convert("RGB")
        if converted.width > 1400:
            ratio = 1400 / converted.width
            converted = converted.resize((1400, max(1, int(converted.height * ratio))))
        target = folder / f"page-{index:03d}.jpg"
        converted.save(target, format="JPEG", quality=78)
    return target


async def apply_revision(settings: Settings, db: Database, provider: OpenRouter, audit: AuditLogger | None, digest: str, instruction: str, chat_id: int | None = None, user_id: int | None = None) -> tuple[str, Path] | None:
    doc = db.one("SELECT markdown FROM docs WHERE hash=?", (digest,))
    if not doc:
        return None
    material = str(doc["markdown"] or "")
    if len(material) > settings.max_text_chars:
        material = material[: settings.max_text_chars]
    revised, _ = await provider.chat(settings.chat_model, [{"role": "system", "content": revision_instructions()}, {"role": "user", "content": f"المادة:\n{material}\n\nالملاحظات:\n{instruction}"}], temperature=0.2)
    new_hash = hashlib.sha256((digest + instruction + revised).encode()).hexdigest()
    artifacts = settings.data_dir / "files" / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    md, pdf = artifacts / f"{new_hash}.md", artifacts / f"{new_hash}.pdf"
    md.write_text(revised, encoding="utf-8")
    figures: list[Path] = []
    if settings.source_image_limit:
        pages_dir = artifacts / f"pages-{digest}"
        if not pages_dir.is_dir():
            source_row = db.one("SELECT source FROM docs WHERE hash=?", (digest,))
            parent = str(source_row["source"] or "") if source_row else ""
            if re.fullmatch(r"[0-9a-f]{64}", parent) and (artifacts / f"pages-{parent}").is_dir():
                pages_dir = artifacts / f"pages-{parent}"
        if pages_dir.is_dir():
            figures = sorted(pages_dir.glob("page-*.jpg"))
    work = artifacts / f"work-{new_hash}"
    artifact = pdf if await asyncio.to_thread(render_pdf, revised, pdf, work, title=document_title(revised) or None, figures=figures or None) else md
    shutil.rmtree(work, ignore_errors=True)
    db.execute("INSERT OR REPLACE INTO docs(hash,artifact,markdown,source) VALUES(?,?,?,?)", (new_hash, str(artifact), revised, digest))
    if user_id:
        db.add_usage(user_id)
    if audit:
        audit.record("incoming", chat_id=chat_id, user_id=user_id, kind="revision", content=instruction, file_refs=[digest])
        audit.record("outgoing", chat_id=chat_id, user_id=user_id, kind="revision", content=revised, file_refs=[str(artifact)], model=settings.chat_model)
    return new_hash, artifact


STYLE_PATH = Path(__file__).parents[2] / "prompts" / "source_style.md"
SIMPLIFY_PATH = Path(__file__).parents[2] / "prompts" / "source_simplify.md"


def load_style_spec() -> str:
    try:
        return STYLE_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def load_simplify_spec() -> str:
    try:
        return SIMPLIFY_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def source_instructions(directive: str = "", mode: str = "faithful") -> str:
    if mode == "simplify":
        instruction = "بسّط تفريغ المصدر إلى مستند دراسي سهل الفهم بالعربية، بعناوين وجداول ومعادلات LaTeX بسيطة. أخرج محتوى المستند فقط."
        spec = load_simplify_spec()
    else:
        instruction = "حوّل تفريغ المصدر إلى Markdown نظيف بالعربية، بعناوين وجداول ومعادلات LaTeX. لا تحذف المحتوى ولا تضف معلومات. أخرج محتوى المستند فقط."
        spec = load_style_spec()
    if spec:
        instruction += "\n\n" + spec
    if directive:
        instruction += "\n\nتعليمات المشرف (لها الأولوية عند التعارض مع قواعد التغطية): " + directive
    return instruction


def revision_instructions() -> str:
    instruction = "عدّل المادة بناءً على ملاحظات المشرف مع الحفاظ على الحقائق. أخرج المادة المعدّلة فقط دون أي شرح أو مقدمة."
    spec = load_style_spec()
    if spec:
        instruction += "\n\n" + spec
    return instruction


async def transcribe_page(provider: OpenRouter, model: str, index: int, image: bytes, attempts: int = 3) -> tuple[str, dict] | None:
    prompt = f"استخرج النص بدقة من الصفحة {index}. حافظ على المعادلات والجداول. أخرج النص فقط."
    for attempt in range(attempts):
        try:
            text, response = await asyncio.wait_for(provider.vision(model, prompt, image), timeout=150)
            if text and text.strip():
                return text, response
            log.warning("Vision call for page %s returned empty content (attempt %s/%s)", index, attempt + 1, attempts)
        except Exception:
            log.warning("Vision call for page %s failed (attempt %s/%s)", index, attempt + 1, attempts, exc_info=True)
        await asyncio.sleep(5 * (attempt + 1))
    return None


def install_clean(settings: Settings, db: Database, audit: AuditLogger, provider: OpenRouter, queue: JobQueue | None = None, bot=None) -> Router:
    jobs = queue or JobQueue(db)
    album_lock = asyncio.Lock()
    quota = QuotaService(db, settings)

    async def handle_source(payload: dict) -> None:
        digest = payload["hash"]
        source_paths = payload["paths"]
        captions = payload.get("caption", "")
        limit_hint = requested_page_limit(captions)
        cap = payload.get("limit_hint")
        if cap:
            limit_hint = min(limit_hint, cap) if limit_hint else cap
        total, truncated = count_pages(source_paths, limit_hint)
        artifacts = settings.data_dir / "files" / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        pages_dir = artifacts / f"pages-{digest}"
        shutil.rmtree(pages_dir, ignore_errors=True)
        transcripts, vision_responses = [], []
        failed_pages = 0
        page_texts: dict[int, str] = {}
        completed = 0
        fast_pages = 0
        vision_pages = 0

        async def transcribe_one(item) -> None:
            nonlocal failed_pages, completed, fast_pages, vision_pages
            index, image = item
            if settings.source_image_limit and index <= settings.source_image_limit:
                await asyncio.to_thread(save_page_preview, image, pages_dir, index)
            origin = await asyncio.to_thread(page_origin, source_paths, limit_hint, index)
            text = None
            if origin and origin[0].lower().endswith(".pdf"):
                text = await asyncio.to_thread(fast_page_text, origin[0], origin[1])
            if text is not None:
                page_texts[index] = text
                fast_pages += 1
            else:
                vision_pages += 1
                result = await transcribe_page(provider, settings.vision_model, index, image)
                if result is None:
                    fallback = await asyncio.to_thread(page_text_layer, origin[0], origin[1]) if origin else None
                    if fallback:
                        page_texts[index] = fallback
                    else:
                        failed_pages += 1
                        page_texts[index] = "(تعذر تفريغ هذه الصفحة)"
                else:
                    text, response = result
                    vision_responses.append(response)
                    page_texts[index] = text
            completed += 1
            if payload.get("job_id"):
                db.set_job_progress(int(payload["job_id"]), f"{completed}/{total}")

        await run_bounded(enumerate(iter_pages(source_paths, limit_hint), 1), transcribe_one)
        transcripts = [f"## الصفحة {index}\n{page_texts[index]}" for index in sorted(page_texts)]
        rough = "\n\n".join(transcripts)
        mode = payload.get("mode") or "faithful"
        structured, model_response = await provider.chat(settings.chat_model, [{"role": "system", "content": source_instructions(payload.get("directive") or "", mode)}, {"role": "user", "content": (captions + "\n\n" if captions else "") + rough}], temperature=0.1)
        fetched_images: list[dict] = []
        images_dir = artifacts / f"webimg-{digest}"
        if mode == "simplify" and settings.source_web_image_limit:
            shutil.rmtree(images_dir, ignore_errors=True)
            for index, query in enumerate(extract_queries(structured)[: settings.source_web_image_limit], 1):
                found = await fetch_commons_image(query, images_dir, index)
                if found:
                    found["path"] = str(images_dir / found["filename"])
                    fetched_images.append(found)
            if fetched_images:
                structured = embed_images(structured, fetched_images)
            structured = strip_markers(structured)
        md, pdf = artifacts / f"{digest}.md", artifacts / f"{digest}.pdf"
        md.write_text(structured, encoding="utf-8")
        title = document_title(structured)
        if not title and captions.strip():
            title = captions.strip().splitlines()[0].strip()
        figures = sorted(pages_dir.glob("page-*.jpg")) if settings.source_image_limit else []
        work = artifacts / f"work-{digest}"
        if fetched_images:
            work.mkdir(parents=True, exist_ok=True)
            for item in fetched_images:
                shutil.copyfile(item["path"], work / item["filename"])
        produced_pdf = await asyncio.to_thread(render_pdf, structured, pdf, work, title=title or None, figures=figures or None)
        shutil.rmtree(work, ignore_errors=True)
        artifact = pdf if produced_pdf else md
        db.execute("INSERT OR REPLACE INTO docs(hash,artifact,markdown,source) VALUES(?,?,?,?)", (digest, str(artifact), structured, json.dumps(source_paths, ensure_ascii=False)))
        if bot:
            public = bool(payload.get("public"))
            keyboard = None if public else doc_keyboard(digest)
            notes = []
            if truncated:
                notes.append(f"شملت المعالجة أول {truncated[0]} صفحة من أصل {truncated[1]}؛ أرسل «أول N صفحات» لغير ذلك")
            if failed_pages:
                notes.append(f"تعذر تفريغ {failed_pages} صفحة")
            if not produced_pdf:
                notes.append("تعذر تجهيز PDF؛ المرفق Markdown")
            if settings.source_image_limit and total > settings.source_image_limit:
                notes.append(f"أُدرجت أول {settings.source_image_limit} صورة من المصدر في ملحق الصور")
            note = " (" + "؛ ".join(notes) + ")." if notes else ""
            if public:
                caption = "جهّزت نسخة مبسّطة من المصدر." if mode == "simplify" else "جهّزت نسخة منظمة من المصدر."
            else:
                caption = "جهّزت نسخة مبسّطة من المصدر؛ راجعها قبل النشر." if mode == "simplify" else "جهّزت نسخة منظمة من المصدر؛ راجعها قبل النشر."
            filename = document_filename(structured, Path(artifact).suffix or ".pdf")
            await bot.send_document(payload["chat_id"], __import__("aiogram").types.FSInputFile(artifact, filename=filename), caption=caption + note, reply_markup=keyboard)
        audit.record("outgoing", chat_id=payload.get("chat_id"), user_id=payload.get("user_id"), kind="source", content=structured, file_refs=[str(artifact)], model=settings.chat_model, params={"vision_model": settings.vision_model, "pages": total, "fast_pages": fast_pages, "vision_pages": vision_pages, "vision_usage": [r.get("usage", {}) for r in vision_responses], "structure_usage": model_response.get("usage", {})})

    jobs.register("source", handle_source)

    async def admin_only(message: Message) -> bool:
        if not message.from_user:
            return False
        if await is_community_admin(settings, db, message.bot, message.from_user.id):
            return True
        await message.answer("ميزة تحويل المصادر إلى مستندات متاحة لمشرفي المجتمع فقط.")
        return False

    async def submit(message: Message, files: list[tuple[str, str, str]]) -> None:
        if not message.from_user:
            return
        is_admin = await is_community_admin(settings, db, message.bot, message.from_user.id)
        if not is_admin:
            retry = quota.consume(message.from_user.id)
            if retry:
                await message.answer(quota_message(settings, retry))
                return
        row = db.one("SELECT value FROM settings WHERE key=?", (f"preset:{message.from_user.id}",))
        preset = str(row["value"]) if row else ""
        directive = {"summary": "بسّط الشرح لأهم أفكار المصدر بلغة واضحة وسهلة.", "notes": "حوّل المصدر إلى ملاحظات دراسية منظمة.", "explain": "اشرح محتوى المصدر خطوة بخطوة.", "exercise": "أنشئ تمريناً تدريجياً من محتوى المصدر.", "flash": "أنشئ بطاقات سؤال وجواب من محتوى المصدر."}.get(preset)
        mode = "simplify" if preset == "summary" else "faithful"
        if row:
            db.execute("DELETE FROM settings WHERE key=?", (f"preset:{message.from_user.id}",))
        paths: list[str] = []
        digests: list[str] = []
        try:
            folder = settings.data_dir / "files" / "sources"
            folder.mkdir(parents=True, exist_ok=True)
            for file_id, filename, mime in files:
                path = folder / f"{message.chat.id}-{message.message_id}-{len(paths)}-{re.sub(r'[^\w.\-]', '_', filename)[:80]}"
                await message.bot.download(file_id, destination=path)
                if path.stat().st_size > settings.max_media_bytes:
                    raise ValueError("حجم المصدر يتجاوز الحد المسموح.")
                paths.append(str(path))
                digests.append(sha256_file(path))
            digest = hashlib.sha256("".join(digests).encode()).hexdigest()
            for path, (file_id, _, _) in zip(paths, files):
                p = Path(path)
                data = p.read_bytes()
                kind = "image" if p.suffix.lower() not in {".pdf"} else "document"
                record = {"file_id": file_id, "type": kind, "size": len(data), "hash": sha256_file(p), "local_path": path}
                db.record_message(message_id=message.message_id, chat_id=message.chat.id, user_id=message.from_user.id, session_user_id=message.from_user.id, kind="source", text=message.caption or "", attachment=record)
            job_id = await jobs.submit("source", {"hash": digest, "paths": paths, "caption": message.caption or "", "chat_id": message.chat.id, "user_id": message.from_user.id, "directive": directive or "", "mode": mode, "public": not is_admin, "limit_hint": settings.public_source_pages if not is_admin else None})
            if is_admin:
                await message.answer(f"استلمت المصدر وسأعمل عليه في الخلفية. لمتابعة الحالة (/source_status {job_id}).")
            else:
                await message.answer("استلمت المصدر وسأعمل عليه في الخلفية وسأرسل لك النتيجة هنا.")
            audit.record("incoming", chat_id=message.chat.id, user_id=message.from_user.id, kind="source", content=message.caption or "", file_refs=paths, params={"job_id": job_id, "directive": directive or ""})
        except Exception as exc:
            for path in paths:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass
            await message.answer(str(exc)[:300] if isinstance(exc, ValueError) else "تعذّر حفظ المصدر أو وضعه في قائمة المعالجة.")
            audit.record("incoming", chat_id=message.chat.id, user_id=message.from_user.id, kind="source_error", content=str(exc)[:500], file_refs=paths)

    @router.message(F.chat.type == "private", F.document, F.media_group_id == None)
    async def document(message: Message) -> None:
        doc = message.document
        is_pdf = bool(doc and (doc.mime_type == "application/pdf" or (doc.file_name or "").lower().endswith(".pdf")))
        if doc and not is_pdf and doc.mime_type and doc.mime_type.startswith("image/") and message.from_user:
            if not await is_community_admin(settings, db, message.bot, message.from_user.id):
                # Guest users: image files are study images, not source pages.
                raise SkipHandler()
        if is_pdf:
            await submit(message, [(doc.file_id, doc.file_name or "source.pdf", "application/pdf")])
        elif doc and doc.mime_type and doc.mime_type.startswith("image/"):
            await submit(message, [(doc.file_id, doc.file_name or "source.jpg", doc.mime_type)])

    @router.message(F.chat.type == "private", F.media_group_id)
    async def album(message: Message) -> None:
        # Telegram album updates arrive separately; aggregate by group id in persistent storage.
        from aiogram.types import InputMediaPhoto
        file = message.photo[-1] if message.photo else message.document
        if not file or not message.from_user:
            return
        pending = db.one("SELECT value FROM settings WHERE key=?", (f"preset:{message.from_user.id}",))
        if caption_preset(message.caption) or (pending and str(pending["value"]) in PRESET_KEYS):
            # A study action was requested: let the admin window treat the album as study images.
            raise SkipHandler()
        if not await is_community_admin(settings, db, message.bot, message.from_user.id):
            # Guest users: albums are study images, not source pages.
            raise SkipHandler()
        group = str(message.media_group_id)
        key = f"album:{message.chat.id}:{group}"
        async with album_lock:
            old = db.one("SELECT value FROM settings WHERE key=?", (key,))
            items = json.loads(old["value"]) if old else []
            items.append({"file_id": file.file_id, "name": getattr(message.document, "file_name", None) or f"album-{message.message_id}.jpg", "mime": getattr(message.document, "mime_type", None) or "image/jpeg", "message_id": message.message_id, "user_id": message.from_user.id, "caption": message.caption or ""})
            db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, json.dumps(items, ensure_ascii=False)))
        await asyncio.sleep(1.5)
        async with album_lock:
            row = db.one("SELECT value FROM settings WHERE key=?", (key,))
            if not row:
                return
            items = json.loads(row["value"])
            db.execute("DELETE FROM settings WHERE key=?", (key,))
        await submit(message, [(item["file_id"], item["name"], item["mime"]) for item in items])

    async def publish_targets(callback, token: str) -> list:
        """Buttons for every group/channel where the bot can post a document."""
        buttons = []
        rows = db.all("SELECT chat_id,title,chat_type FROM chats ORDER BY title")
        for row in rows:
            chat_id = int(row["chat_id"])
            try:
                member = await callback.bot.get_chat_member(chat_id, callback.bot.id)
            except Exception:
                continue
            status = member.status
            if str(row["chat_type"]) == "channel":
                allowed = status in {"administrator", "creator"}
            else:
                allowed = status in {"administrator", "creator", "member"}
            if not allowed:
                continue
            label = str(row["title"]) or str(chat_id)
            if chat_id == settings.community_chat_id:
                label = "المجتمع الرئيسي: " + label
            elif str(row["chat_type"]) == "channel":
                label = "قناة: " + label
            buttons.append([InlineKeyboardButton(text=label[:60], callback_data=f"doc:publish:{token}:{chat_id}")])
        return buttons[:20]

    @router.callback_query(F.data.startswith("doc:"))
    async def approval(callback) -> None:
        if not callback.message or not callback.data or not callback.from_user:
            return
        if not await is_community_admin(settings, db, callback.bot, callback.from_user.id):
            await callback.answer("هذه الإجراءات لمشرفي المجتمع فقط.", show_alert=True)
            return
        try:
            _, action, token, *rest = callback.data.split(":")
            digest = resolve_doc_digest(db, token)
            doc = db.one("SELECT artifact,markdown FROM docs WHERE hash=?", (digest,)) if digest else None
            if not doc:
                await callback.answer("لم أجد الملف.", show_alert=True)
            elif action == "publish":
                if not Path(doc["artifact"]).is_file():
                    await callback.answer("الملف غير متوفر حالياً.", show_alert=True)
                    return
                if not rest:
                    buttons = await publish_targets(callback, token)
                    if not buttons:
                        await callback.answer("لا توجد جهات يمكن للبوت النشر فيها حالياً.", show_alert=True)
                        return
                    await callback.message.answer("اختر جهة النشر:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
                    await callback.answer()
                    return
                chat_id = int(rest[0])
                try:
                    filename = document_filename(str(doc["markdown"] or ""), Path(doc["artifact"]).suffix or ".pdf")
                    await callback.bot.send_document(chat_id, __import__("aiogram").types.FSInputFile(doc["artifact"], filename=filename), caption="مادة دراسية بعد مراجعة المشرفين")
                except Exception:
                    log.warning("Could not publish document %s to %s", digest, chat_id, exc_info=True)
                    await callback.answer("تعذر النشر في هذه الجهة.", show_alert=True)
                    return
                audit.record("outgoing", chat_id=chat_id, user_id=callback.from_user.id, kind="publish", content="نشر مستند", file_refs=[str(doc["artifact"])])
                await callback.answer("تم النشر.")
            elif action in {"revise", "redo"}:
                if action == "redo":
                    root, paths = redo_source_paths(db, digest)
                    available = [path for path in paths if Path(path).is_file()]
                    if not available:
                        await callback.answer("الملف المصدر الأصلي لم يعد متوفراً؛ أعد إرساله.", show_alert=True)
                    else:
                        await jobs.submit("source", {"hash": root, "paths": available, "chat_id": callback.message.chat.id, "user_id": callback.from_user.id})
                        await callback.answer("أُعيدت المعالجة إلى قائمة المهام.")
                else:
                    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (f"docrevise:{callback.from_user.id}", digest))
                    await callback.answer("أرسل الآن ملاحظاتك في رسالة وسأعيد تجهيز المادة.")
        except Exception:
            log.exception("Document approval failed")
            await callback.answer("تعذر تنفيذ الطلب.", show_alert=True)

    @router.message(F.chat.type == "private", F.text.startswith("/source_status"))
    async def source_status(message: Message) -> None:
        if not await admin_only(message):
            return
        job_id = (message.text or "").split(maxsplit=1)[-1]
        if job_id.isdigit():
            row = db.one("SELECT id,status,error,progress FROM jobs WHERE id=? AND kind='source'", (int(job_id),))
            if not row:
                await message.answer("لم أجد المهمة.")
                return
        else:
            row = db.one("SELECT id,status,error,progress FROM jobs WHERE kind='source' ORDER BY id DESC LIMIT 1")
            if not row:
                await message.answer("لا توجد مهام مصادر بعد؛ أرسل PDF أو صوراً وسأعالجها.")
                return
        status_map = {"pending": "في الانتظار", "running": "قيد التنفيذ", "done": "مكتملة", "failed": "فشلت"}
        status = status_map.get(str(row["status"]), str(row["status"]))
        detail = f" — {row['progress']}" if row["progress"] and str(row["status"]) == "running" else ""
        if str(row["status"]) == "failed" and row["error"]:
            await message.answer(f"حالة المهمة {row['id']}: {status}\nالسبب: {str(row['error'])[:300]}")
        else:
            await message.answer(f"حالة المهمة {row['id']}: {status}{detail}")

    @router.message(F.chat.type == "private", F.text.startswith("/revise"))
    async def revise(message: Message) -> None:
        if not await admin_only(message):
            return
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3:
            await message.answer("أرسل ملاحظاتك هكذا: (/revise رمز المادة ثم الملاحظات).")
            return
        digest = resolve_doc_digest(db, parts[1])
        result = await apply_revision(settings, db, provider, audit, digest or "", parts[2], message.chat.id, message.from_user.id if message.from_user else None)
        if result is None:
            await message.answer("لم أجد المادة.")
            return
        new_hash, artifact = result
        row = db.one("SELECT markdown FROM docs WHERE hash=?", (new_hash,))
        filename = document_filename(str(row["markdown"] if row else ""), Path(artifact).suffix or ".pdf")
        await message.answer_document(__import__("aiogram").types.FSInputFile(artifact, filename=filename), caption="نسخة معدّلة جاهزة؛ راجعها قبل النشر.", reply_markup=doc_keyboard(new_hash))
    return router
