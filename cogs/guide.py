# cogs/guide.py
import os
import discord
from discord.ext import commands
from discord import app_commands

_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DEC = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

PUBLIC_MD = os.getenv("PUBLIC_GUIDE_PATH", "bot_guide_public.md")
ADMIN_MD  = os.getenv("ADMIN_GUIDE_PATH",  "bot_guide_admin.md")

def has_manage_server(inter: discord.Interaction) -> bool:
    perms = inter.user.guild_permissions
    return perms.manage_guild or perms.administrator

class Guide(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---------- PUBLIC GUIDE ----------
    @GUILD_DEC
    @app_commands.command(name="guide", description="How to use the Palaemon Bot (public quick-start).")
    async def guide(self, inter: discord.Interaction):
        embed = discord.Embed(
            title="📖 Palaemon Bot – Quick Guide",
            description=(
                "Welcome! This bot posts **disaster alerts**, shows **token prices**, and boosts community engagement.\n\n"
                "**Try these:**\n"
                "• `/disasters_now` — fetch latest disaster items\n"
                "• `/status` — watcher status\n"
                "• `/price` — $PAL or any token price\n"
                "• `/subscribe` — opt into alerts\n"
                "• `/profile` — view your XP level & verified roles\n"
                "• `/daily` — claim daily XP bonus\n"
                "• `/raid_new` — start a social push (if enabled)\n"
                "• `/bot_help` — full command index"
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text="You’ll receive the full public manual via DM.")
        await inter.response.send_message(embed=embed, ephemeral=True)

        # DM the public manual file
        try:
            if os.path.exists(PUBLIC_MD):
                await inter.user.send(
                    content="📖 Here’s the **public user manual** for Palaemon Bot:",
                    file=discord.File(PUBLIC_MD)
                )
            else:
                await inter.user.send("ℹ️ Public manual file not found on the server.")
        except discord.Forbidden:
            await inter.followup.send("⚠️ I couldn’t DM you (your DMs might be disabled).", ephemeral=True)

    # ---------- ADMIN GUIDE ----------
    @GUILD_DEC
    @app_commands.command(name="admin_guide", description="(Staff) Admin quick-start + full manual.")
    async def admin_guide(self, inter: discord.Interaction):
        if not has_manage_server(inter):
            return await inter.response.send_message("🚫 Staff only (Manage Server).", ephemeral=True)

        embed = discord.Embed(
            title="🛠️ Palaemon Bot – Admin Guide (Quick Start)",
            description=(
                "**Core admin commands:**\n"
                "• `/announce` — post announcement embed\n"
                "• `/debug` — view runtime config\n"
                "• `/roles_bootstrap` — create core & ladder roles\n"
                "• `/settings_show` / `/settings_set` — live config\n"
                "• `/verify_queue` `/verify_approve` `/verify_deny` — pro role workflow\n"
                "• `/raid_new` `/raid_ping` `/raid_status` `/raid_done` — social pushes\n"
                "• `/level_givexp` — give XP for events\n\n"
                "**Safety:** give the bot `Manage Channels` + `Manage Roles`; keep bot role above reward/verified roles."
            ),
            color=discord.Color.blurple()
        )
        embed.set_footer(text="You’ll receive the full admin manual via DM.")
        await inter.response.send_message(embed=embed, ephemeral=True)

        # DM the full admin manual file
        try:
            if os.path.exists(ADMIN_MD):
                await inter.user.send(
                    content="📕 Here’s the **admin manual** (full instructions):",
                    file=discord.File(ADMIN_MD)
                )
            else:
                # Fallback: if admin manual missing, try to send public manual
                if os.path.exists(PUBLIC_MD):
                    await inter.user.send(
                        content="⚠️ Admin manual not found. Sending the public manual instead:",
                        file=discord.File(PUBLIC_MD)
                    )
                else:
                    await inter.user.send("⚠️ No manual files found on the server.")
        except discord.Forbidden:
            await inter.followup.send("⚠️ I couldn’t DM you the admin manual (your DMs might be disabled).", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Guide(bot))
