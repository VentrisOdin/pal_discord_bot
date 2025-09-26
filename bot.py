# bot.py
import os
import logging
from dotenv import load_dotenv
import discord
from discord.ext import commands
from discord import app_commands

# ---------- Env & setup ----------
load_dotenv()
TOKEN = (os.getenv("DISCORD_TOKEN") or "").strip()

GUILD_ID_STR = (os.getenv("GUILD_ID") or "").strip()
GUILD_ID = int(GUILD_ID_STR) if GUILD_ID_STR.isdigit() else None
GUILD = discord.Object(id=GUILD_ID) if GUILD_ID else None

# Intents: enable what you actually need
intents = discord.Intents.default()
intents.message_content = True   # needed for some utilities & debugging
intents.members = True           # required for role assignment / joins / reaction-role lookups

# Bot
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Minimal text fallback (debugging convenience) ----------
@bot.command(name="ping")
async def ping_text(ctx: commands.Context):
    await ctx.reply("🏓 Pong! (text command)")

# ---------- Global app command error handler ----------
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    try:
        if isinstance(error, app_commands.CommandOnCooldown):
            return await interaction.response.send_message(
                f"⏳ Slow down — try again in {error.retry_after:.1f}s.", ephemeral=True
            )
        if isinstance(error, app_commands.MissingPermissions):
            return await interaction.response.send_message("🚫 You lack permissions for that.", ephemeral=True)
        if isinstance(error, app_commands.CheckFailure):
            return await interaction.response.send_message("🚫 You can’t run that here.", ephemeral=True)
        # Fallback
        logging.exception("Slash command error", exc_info=error)
        if interaction.response.is_done():
            await interaction.followup.send("⚠️ Something went wrong.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Something went wrong.", ephemeral=True)
    except Exception:
        logging.exception("Error while handling app command error")

# ---------- Cog loading ----------
COGS = [
    # core/admin
    "cogs.admin",            # /announce /debug /ids
    "cogs.settings_admin",   # /settings_show /settings_set
    # features
    "cogs.market",           # /price /price_debug
    "cogs.disasters",        # auto loops + /disasters_now /status
    "cogs.welcome",          # welcome messages
    "cogs.utilities",        # /uptime /members /rolecount
    "cogs.moderation",       # roles/purge/kick/ban/slowmode
    "cogs.subscriptions",    # /subscribe /unsubscribe (safe self-roles)
    "cogs.help",             # /help
    "cogs.polls",            # /poll /poll_close
    "cogs.reaction_roles",   # /rr_add /rr_remove + listeners
    "cogs.price_alerts",     # /alert_set /alert_list /alert_clear + loop
    "cogs.raids",            # /raid_new /raid_ping /raid_status /raid_done /raid_end /raid_set
    # optional (uncomment if you actually have it)
    # "cogs.verify",
]

async def load_all_cogs():
    for ext in COGS:
        try:
            await bot.load_extension(ext)
            logging.info("Loaded cog: %s", ext)
        except Exception as e:
            logging.warning("Could not load cog %s: %s", ext, e)

@bot.event
async def setup_hook():
    await load_all_cogs()

# ---------- Guild-scoped /ping for instant availability ----------
@bot.tree.command(name="ping", description="Check if the bot is alive.", guild=GUILD)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong!", ephemeral=True)

# ---------- Sync on ready with graceful fallback ----------
@bot.event
async def on_ready():
    # Nice presence
    try:
        await bot.change_presence(activity=discord.Game(name="/help"))
    except Exception:
        pass

    try:
        if GUILD:
            await bot.tree.sync(guild=GUILD)
            logging.info("Slash commands synced to guild %s.", GUILD_ID)
        else:
            await bot.tree.sync()
            logging.info("Slash commands synced globally.")
    except discord.Forbidden:
        logging.warning("Guild sync forbidden/missing access. Falling back to GLOBAL sync.")
        try:
            await bot.tree.sync()
            logging.info("Slash commands synced globally (fallback).")
        except Exception as e:
            logging.exception("Global sync failed as well.", exc_info=e)
    except Exception as e:
        logging.exception("Slash sync failed", exc_info=e)

    logging.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)

# ---------- Entrypoint ----------
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Missing DISCORD_TOKEN (check .env)")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s %(message)s")
    bot.run(TOKEN)
