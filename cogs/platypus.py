# cogs/platypus.py
import os
import random
import datetime
from typing import Optional, List

import discord
from discord.ext import commands, tasks
from discord import app_commands

# --- Config ---
_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DEC = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

GENERAL_CHANNEL_ID = int(os.getenv("GENERAL_CHANNEL_ID", "0") or 0)

# Allow override via env; else default to ../platypus_images
_DEFAULT_IMAGES_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "platypus_images")
)
IMAGES_DIR = os.getenv("PLATYPUS_IMAGES_DIR", _DEFAULT_IMAGES_DIR)

UTC = datetime.timezone.utc


class Platypus(commands.Cog):
    """Pal Platypus: daily drop at 09:00 UTC + random on demand."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_path: Optional[str] = None  # prevent immediate repeats
        if not self.daily_post.is_running():
            self.daily_post.start()

    # --- Lifecycle ---------------------------------------------------------
    def cog_unload(self):
        if self.daily_post.is_running():
            self.daily_post.cancel()

    async def cog_load(self):
        # Helpful log to confirm images folder
        print(f"[Platypus] Using images dir: {IMAGES_DIR}")

    # --- Helpers -----------------------------------------------------------
    def _list_images(self) -> List[str]:
        if not os.path.isdir(IMAGES_DIR):
            return []
        files = [
            os.path.join(IMAGES_DIR, f)
            for f in os.listdir(IMAGES_DIR)
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))
            and os.path.isfile(os.path.join(IMAGES_DIR, f))
        ]
        return files

    def _random_image(self) -> Optional[str]:
        files = self._list_images()
        if not files:
            return None
        # Avoid posting identical file twice in a row when possible
        if self._last_path and len(files) > 1:
            candidates = [p for p in files if p != self._last_path]
        else:
            candidates = files
        choice = random.choice(candidates)
        self._last_path = choice
        return choice

    # --- Commands ----------------------------------------------------------
    @GUILD_DEC
    @app_commands.command(name="platypus", description="🦆 Get a random Pal Platypus image!")
    async def platypus_slash(self, interaction: discord.Interaction):
        """Send a random Pal Platypus image via slash command."""
        path = self._random_image()
        if not path:
            return await interaction.response.send_message(
                "⚠️ No platypus images found. (Ask an admin to populate the folder.)",
                ephemeral=True,
            )

        messages = [
            "🦆 **Pal Platypus spotted!**",
            "🌟 **Daily dose of Platypus magic!**",
            "🎯 **Legendary Platypus appears!**",
            "💫 **Pal Platypus blessing incoming!**",
            "🔥 **Epic Platypus moment!**",
        ]

        await interaction.response.send_message(
            content=random.choice(messages),
            file=discord.File(path),
        )

    @commands.command(name="platypus")
    async def platypus_text(self, ctx: commands.Context):
        """Text command version of platypus."""
        path = self._random_image()
        if not path:
            return await ctx.send("⚠️ No platypus images found.")

        messages = [
            "🦆 **Pal Platypus spotted!**",
            "🌟 **Daily dose of Platypus magic!**",
            "🎯 **Legendary Platypus appears!**",
            "💫 **Pal Platypus blessing incoming!**",
            "🔥 **Epic Platypus moment!**",
        ]

        await ctx.send(content=random.choice(messages), file=discord.File(path))

    # --- Scheduler ---------------------------------------------------------
    @tasks.loop(time=datetime.time(hour=9, minute=0, tzinfo=UTC))
    async def daily_post(self):
        """Post a platypus image daily at 09:00 UTC in GENERAL_CHANNEL_ID."""
        await self.bot.wait_until_ready()

        if not GENERAL_CHANNEL_ID:
            print("[Platypus] No GENERAL_CHANNEL_ID set for daily post.")
            return

        channel = self.bot.get_channel(GENERAL_CHANNEL_ID)
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            print(f"[Platypus] Channel {GENERAL_CHANNEL_ID} not found or not text-capable.")
            return

        path = self._random_image()
        if not path:
            print("[Platypus] No images found for daily post.")
            return

        daily_messages = [
            "🦆 **Daily Pal Platypus drop!** *(09:00 UTC)*",
            "🌅 **Good morning Palaemon! Your daily Platypus is here!**",
            "⏰ **Daily Platypus ritual activated!** *Right on schedule!*",
            "🎁 **Today's Platypus blessing has arrived!**",
            "☀️ **Rise and shine with Pal Platypus!** *(Daily 09:00 UTC)*",
        ]
        try:
            await channel.send(content=random.choice(daily_messages), file=discord.File(path))
            print(f"[Platypus] Daily posted at {datetime.datetime.now(UTC).isoformat()}")
        except Exception as e:
            print(f"[Platypus] Failed to post daily image: {e}")

    @daily_post.before_loop
    async def before_daily(self):
        await self.bot.wait_until_ready()
        nxt = self.daily_post.next_iteration
        if nxt:
            print(f"[Platypus] Next scheduled daily: {nxt.astimezone(UTC).isoformat()}")

# --- Setup -------------------------------------------------------------------
async def setup(bot: commands.Bot):
    await bot.add_cog(Platypus(bot))
    # If a single guild is specified, sync faster (no global propagation wait)
    try:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            await bot.tree.sync(guild=guild)
            print(f"[Platypus] Slash commands synced to guild {GUILD_ID}.")
        else:
            # Global sync if no guild forced
            await bot.tree.sync()
            print("[Platypus] Slash commands globally synced.")
    except Exception as e:
        print(f"[Platypus] Slash command sync failed: {e}")
