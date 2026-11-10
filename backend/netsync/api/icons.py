"""Search over the Dashboard Icons index (https://dashboardicons.com) for widget logos.

The index (tree.json + metadata.json) is fetched from GitHub and cached in memory for a day,
so the browser never talks to GitHub and a search costs nothing."""

import asyncio
import logging
import time

import httpx
from fastapi import APIRouter, HTTPException, Query

from netsync.api.deps import CurrentUser

log = logging.getLogger(__name__)
router = APIRouter(prefix="/icons", tags=["icons"])

RAW = "https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main"
CDN = "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons"
TTL = 24 * 3600
FORMATS = ("svg", "png", "webp")

_cache: dict = {"at": 0.0, "icons": []}
_lock = asyncio.Lock()


def logo_src(logo: str) -> str | None:
    """'di:google' -> CDN svg url, 'di:google.png' -> png; https URLs pass through."""
    if logo.startswith("di:"):
        slug, _, fmt = logo[3:].partition(".")
        fmt = fmt or "svg"
        return f"{CDN}/{fmt}/{slug}.{fmt}"
    return logo if logo.startswith("https://") else None


def logo_alt(logo: str) -> str:
    if logo.startswith("di:"):
        return logo[3:].partition(".")[0].replace("-", " ").title()
    return ""


def build_index(tree: dict, metadata: dict) -> list[dict]:
    """[{slug, name, formats, aliases, logo}] - logo is the value to store on a widget."""
    files: dict[str, set[str]] = {}
    for fmt in FORMATS:
        for f in tree.get(fmt, []) or []:
            if isinstance(f, str) and f.endswith("." + fmt):
                files.setdefault(f[: -len(fmt) - 1], set()).add(fmt)
    icons = []
    for slug, fmts in files.items():
        meta = metadata.get(slug) or {}
        formats = [f for f in FORMATS if f in fmts]
        best = "svg" if "svg" in fmts else formats[0]
        icons.append({
            "slug": slug, "name": slug.replace("-", " ").title(), "formats": formats,
            "aliases": [a for a in meta.get("aliases", []) if isinstance(a, str)][:8],
            "logo": f"di:{slug}" if best == "svg" else f"di:{slug}.{best}",
            "src": f"{CDN}/{best}/{slug}.{best}",
        })
    icons.sort(key=lambda i: i["slug"])
    return icons


def search(icons: list[dict], q: str, limit: int) -> list[dict]:
    q = q.strip().lower().replace(" ", "-")
    if not q:
        return icons[:limit]
    qs = q.replace("-", " ")

    def rank(i: dict) -> int | None:
        if i["slug"] == q:
            return 0
        if i["slug"].startswith(q):
            return 1
        if any(a.lower() == qs for a in i["aliases"]):
            return 2
        if q in i["slug"]:
            return 3
        if any(qs in a.lower() for a in i["aliases"]):
            return 4
        return None

    hits = [(r, i) for i in icons if (r := rank(i)) is not None]
    hits.sort(key=lambda x: (x[0], len(x[1]["slug"]), x[1]["slug"]))
    return [i for _, i in hits[:limit]]


async def get_index() -> list[dict]:
    if _cache["icons"] and time.monotonic() - _cache["at"] < TTL:
        return _cache["icons"]
    async with _lock:
        if _cache["icons"] and time.monotonic() - _cache["at"] < TTL:
            return _cache["icons"]
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
                tree, meta = await asyncio.gather(c.get(f"{RAW}/tree.json"), c.get(f"{RAW}/metadata.json"))
                tree.raise_for_status()
                meta.raise_for_status()
            _cache["icons"] = build_index(tree.json(), meta.json())
            _cache["at"] = time.monotonic()
        except Exception as e:
            log.warning("dashboard icons index unavailable: %s", e)
            if not _cache["icons"]:
                raise HTTPException(503, "Dashboard Icons index is unavailable (no internet access?)") from e
            _cache["at"] = time.monotonic() - TTL + 600  # keep the stale copy, retry in 10 min
    return _cache["icons"]


@router.get("")
async def icons(user: CurrentUser, q: str = Query("", max_length=64), limit: int = Query(48, ge=1, le=200)):
    return search(await get_index(), q, limit)
