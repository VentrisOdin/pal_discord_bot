# cogs/polls.py
import os, re, asyncio
import discord
from discord.ext import commands
from discord import app_commands

_GUILD_ID = int(os.getenv("GUILD_ID") or 0) or None
GUILD_DEC = app_commands.guilds(_GUILD_ID) if _GUILD_ID else (lambda f: f)

NUM_EMOJI = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]

class Polls(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @GUILD_DEC
    @app_commands.command(name="poll", description="Create a quick emoji poll.")
    @app_commands.describe(
        question="The poll question",
        options="Comma-separated options (max 10)",
        minutes="Auto-close in N minutes (optional)"
    )
    async def poll(self, inter: discord.Interaction, question: str, options: str, minutes: int | None = None):
        opts = [o.strip() for o in options.split(",") if o.strip()][:10]
        if len(opts) < 2:
            return await inter.response.send_message("Give at least 2 options.", ephemeral=True)

        desc = "\n".join(f"{NUM_EMOJI[i]} {opt}" for i, opt in enumerate(opts))
        e = discord.Embed(title=f"📊 {question}", description=desc)
        msg = await inter.channel.send(embed=e)
        for i in range(len(opts)):
            await msg.add_reaction(NUM_EMOJI[i])

        await inter.response.send_message(f"Poll created (ID: `{msg.id}`).", ephemeral=True)

        if minutes and minutes > 0:
            async def closer():
                await asyncio.sleep(minutes * 60)
                await self._close_and_tally(inter.channel, msg.id)
            self.bot.loop.create_task(closer())

    @GUILD_DEC
    @app_commands.command(name="poll_close", description="Close a poll and show results.")
    @app_commands.describe(message_id="Message ID of the poll")
    async def poll_close(self, inter: discord.Interaction, message_id: str):
        await inter.response.defer(ephemeral=True, thinking=True)
        await self._close_and_tally(inter.channel, int(message_id))
        await inter.followup.send("Poll closed.", ephemeral=True)

    async def _close_and_tally(self, channel: discord.abc.Messageable, message_id: int):
        try:
            msg = await channel.fetch_message(message_id)
        except Exception:
            return
        if not msg.embeds:
            return
        e = msg.embeds[0]
        counts = {}
        for r in msg.reactions:
            if str(r.emoji) in NUM_EMOJI:
                try:
                    counts[str(r.emoji)] = r.count - 1  # minus the bot/self
                except Exception:
                    counts[str(r.emoji)] = 0
        lines = []
        for line in (e.description or "").splitlines():
            m = re.match(r"^(.️⃣|.⃣|[\u0031-\u0039]\ufe0f?\u20e3|🔟)\s+(.*)$", line)
            if not m: continue
            emo, text = m.group(1), m.group(2)
            n = counts.get(emo, 0)
            lines.append(f"{emo} **{text}** — `{n}`")

        res = discord.Embed(title=f"📊 Results — {e.title.replace('📊','').strip()}", description="\n".join(lines))
        await msg.reply(embed=res)
