"""
embeds.py — builds Discord embeds that match the design in the screenshot:

  🚨 Website Update Detected!
  🔵 Site: example.com
  🕐 Change Detected: 3 minutes ago
  🔍 Page: /contact.html
  💬 Change Type: Content Modified
  ─────────────────────
  Changes Detected:
  – New Text Added:
     + "We have updated our business hours…"
"""

import discord
from datetime import datetime, timezone
from detector import get_domain, get_page_path


def build_change_embed(
    url: str,
    change_type: str,
    added: list[str],
    removed: list[str],
    detected_at: datetime | None = None,
) -> discord.Embed:
    if detected_at is None:
        detected_at = datetime.now(timezone.utc)

    # Relative time string
    delta = datetime.now(timezone.utc) - detected_at
    seconds = int(delta.total_seconds())
    if seconds < 60:
        time_str = f"{seconds} second{'s' if seconds != 1 else ''} ago"
    elif seconds < 3600:
        m = seconds // 60
        time_str = f"{m} minute{'s' if m != 1 else ''} ago"
    else:
        h = seconds // 3600
        time_str = f"{h} hour{'s' if h != 1 else ''} ago"

    embed = discord.Embed(
        title="⚠️  Website Update Detected!",
        color=0xE74C3C,          # red, matching the screenshot
    )

    embed.add_field(
        name="",
        value=(
            f"🔵  **Site:** {get_domain(url)}\n"
            f"🕐  **Change Detected:** {time_str}\n"
            f"🔍  **Page:** `{get_page_path(url)}`\n"
            f"💬  **Change Type:** {change_type}"
        ),
        inline=False,
    )

    # Separator line
    embed.add_field(name="\u200b", value="─" * 38, inline=False)

    # Changes block
    changes_text = "**Changes Detected:**\n"

    if added:
        changes_text += "\n**– New Text Added:**\n"
        for line in added[:3]:
            short = (line[:180] + "…") if len(line) > 180 else line
            changes_text += f'```diff\n+ "{short}"\n```'

    if removed:
        changes_text += "\n**– Text Removed:**\n"
        for line in removed[:3]:
            short = (line[:180] + "…") if len(line) > 180 else line
            changes_text += f'```diff\n- "{short}"\n```'

    if not added and not removed:
        changes_text += "\nGeneral content change detected."

    # Discord field value cap is 1024 chars
    if len(changes_text) > 1024:
        changes_text = changes_text[:1020] + "…"

    embed.add_field(name="", value=changes_text, inline=False)
    embed.set_footer(text=f"Monitored URL: {url}")
    embed.timestamp = detected_at

    return embed


def build_down_embed(url: str, status_code: int) -> discord.Embed:
    embed = discord.Embed(
        title="🔴  Site Down / Unreachable!",
        color=0x992D22,
    )
    embed.add_field(
        name="",
        value=(
            f"🔵  **Site:** {get_domain(url)}\n"
            f"🕐  **Detected:** just now\n"
            f"🔍  **URL:** `{url}`\n"
            f"⚡  **HTTP Status:** {status_code if status_code else 'No response'}"
        ),
        inline=False,
    )
    embed.set_footer(text="The site will be rechecked on the next cycle.")
    embed.timestamp = datetime.now(timezone.utc)
    return embed


def build_restored_embed(url: str) -> discord.Embed:
    embed = discord.Embed(
        title="✅  Site is Back Online!",
        color=0x2ECC71,
    )
    embed.add_field(
        name="",
        value=(
            f"🔵  **Site:** {get_domain(url)}\n"
            f"🕐  **Restored:** just now\n"
            f"🔍  **URL:** `{url}`"
        ),
        inline=False,
    )
    embed.timestamp = datetime.now(timezone.utc)
    return embed


def build_list_embed(sites: list, guild_name: str) -> discord.Embed:
    embed = discord.Embed(
        title="📋  Monitored Sites",
        description=f"Guild: **{guild_name}**",
        color=0x3498DB,
    )
    if not sites:
        embed.add_field(name="", value="No sites are being monitored yet.\nUse `/add` to start.", inline=False)
        return embed

    for i, site in enumerate(sites, 1):
        status_icon = "🟢" if site["last_status"] == 200 else ("🔴" if site["last_status"] else "⚪")
        label = site["label"] or get_domain(site["url"])
        embed.add_field(
            name=f"{i}. {status_icon} {label}",
            value=(
                f"**URL:** {site['url']}\n"
                f"**Interval:** every {site['interval']}s\n"
                f"**Status:** {site['last_status'] or 'Not checked yet'}"
            ),
            inline=False,
        )
    return embed