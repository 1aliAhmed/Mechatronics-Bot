from __future__ import annotations

import html
import logging
import re
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

IMAGE_MARKER = re.compile(r"\[صورة:\s*([^\]]+)\]")
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
ALLOWED_HOSTS = {"upload.wikimedia.org", "commons.wikimedia.org"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def extract_queries(markdown: str) -> list[str]:
    return [query.strip() for query in IMAGE_MARKER.findall(markdown or "") if query.strip()]


def strip_markers(markdown: str) -> str:
    return IMAGE_MARKER.sub("", markdown or "")


def embed_images(markdown: str, images: list[dict]) -> str:
    """Replace the first N markers with markdown image lines, drop the rest."""
    remaining = list(images)

    def replace(match: re.Match[str]) -> str:
        if not remaining:
            return ""
        item = remaining.pop(0)
        caption = item.get("caption") or "صورة توضيحية"
        credit = ""
        if item.get("source"):
            credit = f"\n*المصدر: [Wikimedia Commons]({item['source']}) — {item.get('license') or 'Wikimedia Commons'}*"
        return f"![{caption}]({item['filename']}){credit}"

    return IMAGE_MARKER.sub(replace, markdown or "")


def _clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def _pick_page(payload: dict) -> dict | None:
    pages = (payload.get("query") or {}).get("pages") or {}
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        if url:
            return {"page": page, "info": info, "url": url}
    return None


def _safe_suffix(url: str) -> str:
    suffix = Path(url.split("?", 1)[0]).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"


async def fetch_commons_image(query: str, folder: Path, index: int, client: httpx.AsyncClient | None = None) -> dict | None:
    """Search Wikimedia Commons and download one thumbnailed image (free licenses only)."""
    owned = client is None
    client = client or httpx.AsyncClient(timeout=12.0, follow_redirects=True)
    try:
        response = await client.get(
            COMMONS_API,
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"filetype:bitmap {query}",
                "gsrnamespace": "6",
                "gsrlimit": "5",
                "prop": "imageinfo",
                "iiprop": "url|size|extmetadata",
                "iiurlwidth": "1000",
            },
            headers={"User-Agent": "megatronics-bot/1.0 (study document builder)"},
        )
        response.raise_for_status()
        chosen = _pick_page(response.json())
        if chosen is None:
            return None
        info = chosen["info"]
        host = (info.get("thumburl") or info.get("url") or "").split("/", 3)[2] if "//" in (info.get("thumburl") or info.get("url") or "") else ""
        if host not in ALLOWED_HOSTS:
            log.warning("Commons image host not allowed: %s", host)
            return None
        download = await client.get(chosen["url"], headers={"User-Agent": "megatronics-bot/1.0 (study document builder)"})
        download.raise_for_status()
        content = download.content
        if not content or len(content) > MAX_IMAGE_BYTES:
            return None
        folder.mkdir(parents=True, exist_ok=True)
        filename = f"web-{index:02d}{_safe_suffix(chosen['url'])}"
        (folder / filename).write_bytes(content)
        meta = info.get("extmetadata") or {}
        license_name = _clean_text((meta.get("LicenseShortName") or {}).get("value", "")) or "Wikimedia Commons"
        artist = _clean_text((meta.get("Artist") or {}).get("value", ""))
        credit_url = info.get("descriptionurl") or "https://commons.wikimedia.org/"
        caption = f"{query[:70]} (Wikimedia Commons — {license_name}{', ' + artist[:40] if artist else ''})"
        return {"filename": filename, "caption": caption, "license": license_name, "source": credit_url}
    except Exception:
        log.info("Commons fetch failed for %r", query, exc_info=True)
        return None
    finally:
        if owned:
            await client.aclose()
