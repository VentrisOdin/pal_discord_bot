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

OWNER_ID_STR = (os.getenv("OWNER_ID") or "").strip()
OWNER_ID = int(OWNER_ID_STR) if OWNER_ID_STR.isdigit() else None

# Channels from env (optional; we’ll create if missing)
GENERAL_CHANNEL_ID = int(os.getenv("GENERAL_CHANNEL_ID", "0") or 0)
DISASTER_CHANNEL_ID = int(os.getenv("DISASTER_CHANNEL_ID", "0") or 0)
VERIFY_REVIEW_CHANNEL_ID = int(os.getenv("VERIFY_REVIEW_CHANNEL_ID", "0") or 0)

# Intents: enable what you actually need
intents = discord.Intents.default()
intents.message_content = True   # for utilities/leveling XP, etc.
intents.members = True           # required for welcomes/roles

# Bot
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Minimal text fallback (debugging convenience) ----------
@bot.command(name="ping")
async def ping_text(ctx: commands.Context):
    await ctx.reply("🏓 Pong! (text command)")

# ---------- Global app command error handler ----------
@bot.tree.error
async def on_app_command_error(inter: discord.Interaction, error: app_commands.AppCommandError):
    try:
        if isinstance(error, app_commands.CommandOnCooldown):
            return await inter.response.send_message(
                f"⏳ Slow down — try again in {error.retry_after:.1f}s.", ephemeral=True
            )
        if isinstance(error, app_commands.MissingPermissions):
            return await inter.response.send_message("🚫 You lack permissions for that.", ephemeral=True)
        if isinstance(error, app_commands.CheckFailure):
            return await inter.response.send_message("🚫 You can’t run that here.", ephemeral=True)
        # Fallback
        logging.exception("Slash command error", exc_info=error)
        if inter.response.is_done():
            await inter.followup.send("⚠️ Something went wrong.", ephemeral=True)
        else:
            await inter.response.send_message("⚠️ Something went wrong.", ephemeral=True)
    except Exception:
        logging.exception("Error while handling app command error")

# ---------- Utility: ensure channels exist ----------
async def ensure_text_channel(guild: discord.Guild, desired_id: int, default_name: str, topic: str | None = None) -> int:
    """
    Returns the channel ID (existing or newly-created).
    If desired_id is set but not found, creates a new channel with default_name.
    If desired_id is 0, tries to find by name; if missing, creates.
    """
    # 1) If ID points to an existing channel, use it
    if desired_id:
        ch = guild.get_channel(desired_id)
        if isinstance(ch, discord.TextChannel):
            return ch.id
        logging.warning("Configured channel ID %s not found; will attempt to create #%s", desired_id, default_name)

    # 2) Try by name
    existing = discord.utils.get(guild.text_channels, name=default_name)
    if isinstance(existing, discord.TextChannel):
        return existing.id

    # 3) Create
    try:
        overwrites = None  # keep default perms
        ch = await guild.create_text_channel(name=default_name, overwrites=overwrites, topic=topic or "")
        logging.info("Created channel #%s (ID %s). Add this to .env.", ch.name, ch.id)
        return ch.id
    except discord.Forbidden:
        logging.error("I lack permissions to create #%s. Give me Manage Channels.", default_name)
    except Exception as e:
        logging.exception("Failed to create #%s: %s", default_name, e)
    return 0

async def ensure_core_channels(guild: discord.Guild):
    global GENERAL_CHANNEL_ID, DISASTER_CHANNEL_ID, VERIFY_REVIEW_CHANNEL_ID

    GENERAL_CHANNEL_ID = await ensure_text_channel(
        guild, GENERAL_CHANNEL_ID, default_name="general",
        topic="General chat and welcome messages."
    ) or GENERAL_CHANNEL_ID

    DISASTER_CHANNEL_ID = await ensure_text_channel(
        guild, DISASTER_CHANNEL_ID, default_name="disaster-alerts",
        topic="Live disaster alerts posted by the bot."
    ) or DISASTER_CHANNEL_ID

    VERIFY_REVIEW_CHANNEL_ID = await ensure_text_channel(
        guild, VERIFY_REVIEW_CHANNEL_ID, default_name="verification-review",
        topic="Private staff channel: review /verify requests."
    ) or VERIFY_REVIEW_CHANNEL_ID

    # Log the final values so you can paste them into .env
    logging.info("Channel map — GENERAL=%s  DISASTERS=%s  VERIFY_REVIEW=%s",
                 GENERAL_CHANNEL_ID, DISASTER_CHANNEL_ID, VERIFY_REVIEW_CHANNEL_ID)

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
    "cogs.raids",            # /raid_* tools
    "cogs.roles_setup",      # /roles_bootstrap auto-creates core + ladder roles
    "cogs.leveling",         # XP system with daily, streaks, titles, boosts
    "cogs.verify",           # /verify flow (pro roles)
    "cogs.profile",          # /profile shows XP + verified roles
    "cogs.guide",

    # optional
    # "cogs.verify" already included above if you enabled verify flow
    # "cogs.health" owner-only diag/reload if you add it later
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
    # Presence
    try:
        await bot.change_presence(activity=discord.Game(name="/help"))
    except Exception:
        pass

    # Ensure core channels exist
    if GUILD_ID:
        g = bot.get_guild(GUILD_ID)
        if g:
            await ensure_core_channels(g)
        else:
            logging.warning("Guild %s not found in cache. Is the bot invited?", GUILD_ID)

    # Sync slash commands
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
