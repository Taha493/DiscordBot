"""
detector.py — fetches pages using a real Chromium browser (Playwright).
Stealth patches hide all automation fingerprints so any website works.
"""

import hashlib
import difflib
import re
import logging
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from config import REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

# ── Stealth JS ────────────────────────────────────────────────────────────────
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
window.chrome = { runtime: {} };
const _origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (params) =>
    params.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : _origQuery(params);
"""

# ── Fetch ─────────────────────────────────────────────────────────────────────

async def fetch_page(url: str) -> tuple[Optional[str], int]:
    """
    Opens a real headless Chromium browser, loads the page (JS rendered),
    returns (html, status_code). Bypasses bot detection on any website.
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-infobars",
                    "--disable-extensions",
                    "--window-size=1920,1080",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                timezone_id="America/New_York",
                java_script_enabled=True,
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Upgrade-Insecure-Requests": "1",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1",
                },
            )
            await context.add_init_script(_STEALTH_JS)

            page = await context.new_page()
            status_code = 200

            async def _on_response(response):
                nonlocal status_code
                try:
                    if response.request.resource_type == "document":
                        status_code = response.status
                except Exception:
                    pass

            page.on("response", _on_response)

            try:
                await page.goto(url, timeout=REQUEST_TIMEOUT * 1000, wait_until="domcontentloaded")
                await page.wait_for_timeout(2500)   # let JS-heavy pages render
            except PlaywrightTimeout:
                logger.warning(f"[TIMEOUT] {url}")
                await browser.close()
                return None, 0

            html = await page.content()
            await browser.close()

            return (html, 200) if status_code in (200, 0) else (None, status_code)

    except Exception as e:
        logger.error(f"[FETCH ERROR] {url} — {e}")
        return None, 0


# ── Text extraction ───────────────────────────────────────────────────────────

_IGNORE_TAGS = {
    "script", "style", "noscript", "head", "meta", "link",
    "svg", "path", "img", "video", "audio", "iframe", "canvas",
    "nav", "footer", "header"
}


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_IGNORE_TAGS):
        tag.decompose()
    lines = []
    for element in soup.find_all(string=True):
        text = element.strip()
        if text and len(text) > 1:
            lines.append(text)
    return "\n".join(lines)


def hash_content(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Diff ──────────────────────────────────────────────────────────────────────

def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def diff_content(old_text: str, new_text: str) -> dict:
    old_lines = [_clean_line(l) for l in old_text.splitlines() if _clean_line(l)]
    new_lines = [_clean_line(l) for l in new_text.splitlines() if _clean_line(l)]

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    added, removed = [], []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            added.extend(new_lines[j1:j2])
        elif tag == "delete":
            removed.extend(old_lines[i1:i2])
        elif tag == "replace":
            removed.extend(old_lines[i1:i2])
            added.extend(new_lines[j1:j2])

    if added and not removed:
        change_type = "New Text Added"
    elif removed and not added:
        change_type = "Text Removed"
    else:
        change_type = "Content Modified"

    def fmt(lines, cap=3):
        out = [l[:200] + ("…" if len(l) > 200 else "") for l in lines[:cap]]
        if len(lines) > cap:
            out.append(f"… and {len(lines) - cap} more line(s)")
        return out

    summary_parts = []
    if added:
        summary_parts.append("New Text Added:\n" + "\n".join(f'  + "{l}"' for l in fmt(added)))
    if removed:
        summary_parts.append("Text Removed:\n" + "\n".join(f'  - "{l}"' for l in fmt(removed)))

    return {
        "change_type": change_type,
        "added": added[:10],
        "removed": removed[:10],
        "summary": "\n".join(summary_parts) or "General content change detected.",
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_page_path(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query[:50]
    return path


def get_domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or url