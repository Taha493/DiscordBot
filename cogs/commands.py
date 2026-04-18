"""
cogs/commands.py — slash commands: /add  /remove  /list  /help  /status
"""

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from config import MAX_SITES, DEFAULT_INTERVAL, MIN_INTERVAL
from embeds import build_list_embed
from detector import get_domain

logger = logging.getLogger(__name__)

URL_RE = re.compile(
    r"^https?://"
    r"(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+"
    r"[A-Z]{2,}"
    r"(?::\d+)?(?:/[^\s]*)?$",
    re.IGNORECASE,
)


def _validate_url(url: str) -> str | None:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url if URL_RE.match(url) else None


async def _safe_respond(
    interaction: discord.Interaction,
    content: str = None,
    embed: discord.Embed = None,
    ephemeral: bool = True,
):
    """
    Always works regardless of whether the interaction has been
    deferred or not. Checks state and picks the right method.
    """
    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                content=content, embed=embed, ephemeral=ephemeral
            )
        else:
            await interaction.response.send_message(
                content=content, embed=embed, ephemeral=ephemeral
            )
    except Exception as e:
        logger.error(f"[RESPOND ERROR] {e}")


class CommandsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ─────────────────────────────────────────
    #  /add
    # ─────────────────────────────────────────
    @app_commands.command(name="add", description="Start monitoring a website")
    @app_commands.describe(
        url="Full URL of the website to monitor (e.g. https://example.com)",
        label="Friendly name for this site (optional)",
        interval="Check interval in seconds (default 30, min 10)",
        channel="Channel to send alerts to (defaults to current channel)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def add(
        self,
        interaction: discord.Interaction,
        url: str,
        label: str | None = None,
        interval: int = DEFAULT_INTERVAL,
        channel: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        clean_url = _validate_url(url)
        if not clean_url:
            await interaction.followup.send(
                "❌ Invalid URL. Please include `https://` and a valid domain.",
                ephemeral=True
            )
            return

        guild_id = str(interaction.guild_id)

        if db.count_sites(guild_id) >= MAX_SITES:
            await interaction.followup.send(
                f"❌ You've reached the limit of **{MAX_SITES} sites** per server.\n"
                f"Remove a site with `/remove` before adding a new one.",
                ephemeral=True
            )
            return

        if db.site_exists(guild_id, clean_url):
            await interaction.followup.send(
                f"⚠️ `{clean_url}` is already being monitored.",
                ephemeral=True
            )
            return

        interval = max(MIN_INTERVAL, interval)
        target_channel = channel or interaction.channel
        friendly_label = label or get_domain(clean_url)

        site_id = db.add_site(
            guild_id=guild_id,
            channel_id=str(target_channel.id),
            url=clean_url,
            label=friendly_label,
            interval=interval,
            added_by=str(interaction.user),
        )

        monitor_cog = self.bot.cogs.get("MonitorCog")
        if monitor_cog:
            await monitor_cog.prime_site(site_id, clean_url)

        await interaction.followup.send(
            f"✅ Now monitoring **{friendly_label}**\n"
            f"🔗 `{clean_url}`\n"
            f"📢 Alerts → {target_channel.mention}\n"
            f"⏱️ Check interval: every **{interval}s**",
            ephemeral=True,
        )

    # ─────────────────────────────────────────
    #  /remove
    # ─────────────────────────────────────────
    @app_commands.command(name="remove", description="Stop monitoring a website")
    @app_commands.describe(url="URL of the site to remove")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer(ephemeral=True)

        clean_url = _validate_url(url) or url.strip()
        guild_id = str(interaction.guild_id)

        if db.remove_site(guild_id, clean_url):
            await interaction.followup.send(
                f"🗑️ Removed **{clean_url}** from monitoring.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"❌ `{clean_url}` was not found in your monitored sites.\n"
                f"Use `/list` to see all active sites.",
                ephemeral=True
            )

    # ─────────────────────────────────────────
    #  /list
    # ─────────────────────────────────────────
    @app_commands.command(name="list", description="Show all monitored websites")
    async def list_sites(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        sites = db.get_sites(guild_id)
        embed = build_list_embed(
            [dict(s) for s in sites],
            interaction.guild.name
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────
    #  /status
    # ─────────────────────────────────────────
    @app_commands.command(name="status", description="Check the current status of all monitored sites")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        sites = db.get_sites(guild_id)

        if not sites:
            await interaction.followup.send(
                "No sites monitored yet. Use `/add` to start.",
                ephemeral=True
            )
            return

        lines = []
        for s in sites:
            icon = "🟢" if s["last_status"] == 200 else ("🔴" if s["last_status"] else "⚪")
            label = s["label"] or get_domain(s["url"])
            lines.append(f"{icon} **{label}** — status `{s['last_status'] or 'pending'}`")

        embed = discord.Embed(title="📡 Site Status", color=0x3498DB)
        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────
    #  /help
    # ─────────────────────────────────────────
    @app_commands.command(name="help", description="Show all bot commands")
    async def help_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            title="🤖 Site Monitor Bot — Help",
            description="A 24/7 website change & uptime monitor.",
            color=0x5865F2,
        )
        embed.add_field(
            name="/add `url` `[label]` `[interval]` `[channel]`",
            value="Start monitoring a website. Interval defaults to 30s (min 10s).",
            inline=False,
        )
        embed.add_field(name="/remove `url`", value="Stop monitoring a website.", inline=False)
        embed.add_field(name="/list", value="Show all monitored sites.", inline=False)
        embed.add_field(name="/status", value="Quick up/down status for all sites.", inline=False)
        embed.add_field(name="/help", value="Show this help message.", inline=False)
        embed.set_footer(text=f"Max {MAX_SITES} sites per server.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────
    #  Error handler
    # ─────────────────────────────────────────
    @add.error
    @remove.error
    async def permission_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.MissingPermissions):
            await _safe_respond(
                interaction,
                content="❌ You need **Manage Server** permission to use this command."
            )
        else:
            logger.error(f"Command error: {error}")
            await _safe_respond(interaction, content="⚠️ An unexpected error occurred.")


async def setup(bot: commands.Bot):
    await bot.add_cog(CommandsCog(bot))
