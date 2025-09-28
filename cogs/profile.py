# cogs/profile.py
import os
import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

DB_PATH = os.getenv("DB_PATH", "pal_bot.sqlite")

# keep in sync with leveling.py’s formula
def level_from_xp(xp: int) -> int:
    return max(1, (xp // 100) + 1)

def progress_to_next(xp: int):
    lvl = level_from_xp(xp)
    base = (lvl - 1) * 100
    nxt = lvl * 100
    return lvl, xp - base, nxt - base

def progress_bar(x_in: int, x_req: int, w: int = 12):
    fill = int((x_in / max(1, x_req)) * w)
    return "█" * fill + "░" * (w - fill)

VERIFIED_MARKERS = {"(Verified)", "Verified"}

class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _get_xp(self, gid: int, uid: int) -> int:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
              CREATE TABLE IF NOT EXISTS leveling (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                xp INTEGER NOT NULL DEFAULT 0,
                last_ts INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(guild_id, user_id)
              )
            """)
            cur = await db.execute("SELECT xp FROM leveling WHERE guild_id=? AND user_id=?", (gid, uid))
            row = await cur.fetchone()
            return int(row[0]) if row else 0

    @app_commands.command(name="profile", description="Show a member’s profile: level, XP, and verified roles.")
    async def profile(self, inter: discord.Interaction, member: discord.Member | None = None):
        member = member or inter.user
        xp = await self._get_xp(inter.guild_id, member.id)
        lvl, xin, xreq = progress_to_next(xp)

        verified_roles = [r.name for r in member.roles if any(m in r.name for m in VERIFIED_MARKERS)]
        other_ranks = [r.name for r in member.roles if not any(m in r.name for m in VERIFIED_MARKERS)
                       and r.name not in ("@everyone",)]

        e = discord.Embed(title=f"🪪 Profile — {member.display_name}", color=discord.Color.blurple())
        e.add_field(name="Level", value=str(lvl), inline=True)
        e.add_field(name="XP", value=str(xp), inline=True)
        e.add_field(name="Progress", value=f"`{progress_bar(xin, xreq, 16)}` {xin}/{xreq}", inline=False)

        if verified_roles:
            e.add_field(name="Verified", value=" • ".join(verified_roles), inline=False)
        if other_ranks:
            # show at most top 5 (position order is not guaranteed here; it’s fine)
            e.add_field(name="Roles", value=", ".join(other_ranks[:5]), inline=False)

        e.set_thumbnail(url=member.display_avatar.url if member.display_avatar else discord.Embed.Empty)
        await inter.response.send_message(embed=e, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))
