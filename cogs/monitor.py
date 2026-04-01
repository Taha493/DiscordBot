"""
cogs/monitor.py — the async monitoring engine.

Runs a background task that loops over every registered site,
fetches it, diffs it, and fires Discord notifications on changes.
"""

import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

import database as db
from detector import fetch_page, extract_text, hash_content, diff_content
from embeds import build_change_embed, build_down_embed, build_restored_embed
from config import DEFAULT_INTERVAL

logger = logging.getLogger(__name__)


class MonitorCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._down_sites: set[int] = set()   # site IDs currently down
        self.monitor_loop.start()

    def cog_unload(self):
        self.monitor_loop.cancel()

    # ── Main loop ──────────────────────────────

    @tasks.loop(seconds=DEFAULT_INTERVAL)
    async def monitor_loop(self):
        sites = db.get_all_sites()
        if not sites:
            return

        tasks_list = [self._check_site(dict(site)) for site in sites]
        await asyncio.gather(*tasks_list, return_exceptions=True)

    @monitor_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()
        logger.info("Monitor loop ready, starting checks…")

    # ── Per-site check ─────────────────────────

    async def _check_site(self, site: dict):
        site_id = site["id"]
        url = site["url"]
        channel_id = int(site["channel_id"])
        old_hash = site["last_hash"]

        html, status = await fetch_page(url)

        # ── Site is DOWN ──
        if status != 200 or html is None:
            if site_id not in self._down_sites:
                self._down_sites.add(site_id)
                embed = build_down_embed(url, status)
                await self._send_embed(channel_id, embed)
            db.update_site_state(site_id, old_hash or "", status)
            return

        # ── Site is UP — was it down before? ──
        if site_id in self._down_sites:
            self._down_sites.discard(site_id)
            embed = build_restored_embed(url)
            await self._send_embed(channel_id, embed)

        # ── Compute hash of meaningful text ──
        text = extract_text(html)
        new_hash = hash_content(text)

        # First visit — just store baseline
        if old_hash is None:
            db.update_site_state(site_id, new_hash, status)
            logger.info(f"[BASELINE] {url}")
            return

        # No change
        if new_hash == old_hash:
            db.update_site_state(site_id, new_hash, status)
            return

        # ── Change detected ──
        logger.info(f"[CHANGE] {url}")

        # We need old text — re-fetch from stored hash isn't possible,
        # so we store old text in a side table. For simplicity we do a
        # second fetch of the old stored text via a lightweight cache.
        old_text = self._get_cached_text(site_id) or ""
        diff = diff_content(old_text, text)

        detected_at = datetime.now(timezone.utc)
        embed = build_change_embed(
            url=url,
            change_type=diff["change_type"],
            added=diff["added"],
            removed=diff["removed"],
            detected_at=detected_at,
        )

        view = _ChangeView(url)
        await self._send_embed(channel_id, embed, view=view)

        # Log & update state
        db.log_change(site_id, diff["change_type"], diff["summary"])
        db.update_site_state(site_id, new_hash, status)
        self._cache_text(site_id, text)

    # ── Text cache (in-memory, per site) ───────

    _text_cache: dict[int, str] = {}

    def _get_cached_text(self, site_id: int) -> str | None:
        return self._text_cache.get(site_id)

    def _cache_text(self, site_id: int, text: str):
        self._text_cache[site_id] = text

    # ── Send helper ────────────────────────────

    async def _send_embed(self, channel_id: int, embed: discord.Embed, view=None):
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception as e:
                logger.error(f"Cannot find channel {channel_id}: {e}")
                return
        try:
            if view:
                await channel.send(content="@everyone", embed=embed, view=view)
            else:
                await channel.send(content="@everyone", embed=embed)
        except discord.Forbidden:
            logger.error(f"Missing permission to send to channel {channel_id}")
        except Exception as e:
            logger.error(f"Failed to send embed: {e}")

    # ── Public method for slash commands ───────

    async def prime_site(self, site_id: int, url: str):
        """Called after /add — fetch baseline immediately."""
        html, status = await fetch_page(url)
        if html and status == 200:
            text = extract_text(html)
            h = hash_content(text)
            db.update_site_state(site_id, h, status)
            self._cache_text(site_id, text)
            logger.info(f"[PRIMED] {url} status={status}")
        else:
            db.update_site_state(site_id, None, status)


# ── "View Changes" button view ─────────────────────────────────────────────────

class _ChangeView(discord.ui.View):
    def __init__(self, url: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="🔍  View Changes",
            style=discord.ButtonStyle.primary,
            url=url,
        ))
        self.add_item(discord.ui.Button(
            label="🌐  Open Website",
            style=discord.ButtonStyle.secondary,
            url=url,
        ))


async def setup(bot: commands.Bot):
    db.init_db()
    await bot.add_cog(MonitorCog(bot))
