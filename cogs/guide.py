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

    # ---------- RECRUITMENT GUIDE ----------
    @GUILD_DEC
    @app_commands.command(name="recruitment_guide", description="Guide to the recruitment system.")
    async def recruitment_guide(self, inter: discord.Interaction):
        embed = discord.Embed(
            title="🎯 **RECRUITMENT SYSTEM** 🎯",
            description=(
                "**Grow the community and get rewarded!**\n\n"
                "### 📊 **How It Works**\n"
                "When someone joins using your invite link, you automatically earn:\n"
                "• **+100 XP** per successful invite\n"
                "• **Bonus XP** when reaching rank milestones\n"
                "• **Recognition** in welcome messages\n"
                "• **Progression** through recruiter ranks\n\n"
                "### 🏆 **Recruiter Ranks**\n"
                "Progress through these epic ranks:\n\n"
                "👤 **Newcomer** (0 recruits) - *Just getting started*\n\n"
                "🌱 **Scout** (1+ recruits)  - *First successful invite*\n\n"
                "🎯 **Recruiter** (5+ recruits) - *Building momentum* • +50 Bonus XP\n\n"
                "🔥 **Headhunter** (10+ recruits) - *Serious talent acquisition* • +50 Bonus XP\n\n"
                "⭐ **Talent Magnet** (25+ recruits) - *Community growth champion* • +50 Bonus XP\n\n"
                "👑 **Legion Builder** (50+ recruits) - *Elite recruiter status* • +50 Bonus XP\n\n"
                "🌟 **Palaemon Ambassador** (100+ recruits) - *Legendary community builder* • +50 Bonus XP\n\n"
                "### 🔗 **Creating Invite Links**\n\n"
                "**Method 1: Discord Interface**\n"
                "1. Right-click your server name\n"
                "2. Click \"Invite People\"\n"
                "3. Customize settings and copy link\n"
                "4. Share anywhere to get credit!\n\n"
                "**Method 2: Bot Command**\n"
                "Use `/create_invite` for tracked invites:\n"
                "```\n"
                "/create_invite max_uses:10 max_age:24\n"
                "```\n"
                "• `max_uses` - How many people can use it (0 = unlimited)\n"
                "• `max_age` - Hours until it expires (0 = never)\n\n"
                "### 📋 **Commands**\n\n"
                "**`/recruiter_stats [user]`**\n"
                "• View recruitment achievements\n"
                "• See current rank and progress\n"
                "• Check recent successful invites\n"
                "• Track XP earned from recruiting\n\n"
                "**`/recruiter_leaderboard`**\n"
                "• Top 10 recruiters in the server\n"
                "• See who's building the community\n"
                "• Competitive rankings with medals\n\n"
                "**`/create_invite`**\n"
                "• Generate tracked invite links\n"
                "• Customize expiration and usage limits\n"
                "• Get guaranteed credit for invites\n\n"
                "### 🎉 **Rewards & Recognition**\n\n"
                "**Immediate Rewards:**\n"
                "• **100 XP** per successful invite\n"
                "• **Welcome message** credits you publicly\n"
                "• **Rank progression** tracked automatically\n\n"
                "**Milestone Bonuses:**\n"
                "• **+50 XP** each time you reach a new rank\n"
                "• **Special recognition** in celebration messages\n"
                "• **Visual rank badges** in your stats\n\n"
                "**Community Impact:**\n"
                "• **Build the Palaemon community**\n"
                "• **Help new members feel welcome**\n"
                "• **Earn respect as a community leader**\n\n"
                "### 💡 **Pro Tips**\n\n"
                "**Maximize Your Recruiting:**\n"
                "• Share invites on **social media**\n"
                "• Post in **relevant Discord servers**\n"
                "• Include in your **Twitter/X bio**\n"
                "• Share with **friends interested in crypto**\n\n"
                "**Best Practices:**\n"
                "• **Welcome new members** personally\n"
                "• **Help them get started** with bot commands\n"
                "• **Explain server rules** and channels\n"
                "• **Be an awesome community ambassador**\n\n"
                "**Track Your Success:**\n"
                "• Use `/recruiter_stats` regularly\n"
                "• Check who's still active with green ✅\n"
                "• See your progress toward next rank\n"
                "• Monitor your total XP earnings\n\n"
                "### 🚨 **Important Notes**\n\n"
                "• **No self-invites** - You can't invite yourself for XP\n"
                "• **Active tracking** - System monitors if invitees stay\n"
                "• **Fair play** - Quality recruiting encouraged over quantity\n"
                "• **Integration** - Works with existing XP/leveling system\n\n"
                "### 🌟 **Why Recruit?**\n\n"
                "**Build Community:**\n"
                "Every new member makes Palaemon stronger and more vibrant.\n\n"
                "**Earn Recognition:**\n"
                "Top recruiters get respect and special status in the community.\n\n"
                "**Level Up Fast:**\n"
                "Recruiting is one of the fastest ways to earn XP and climb ranks.\n\n"
                "**Make Friends:**\n"
                "Help new members settle in and build lasting connections.\n\n"
                "**Grow the Movement:**\n"
                "More members = stronger community = better for everyone!\n\n"
                "---\n\n"
                "*Ready to become a recruiting legend? Use `/create_invite` and start building the Palaemon empire!* 🚀"
            ),
            color=discord.Color.purple()
        )
        embed.set_footer(text="📖 Palaemon Bot Guide • Page 6/8")
        await inter.response.send_message(embed=embed, ephemeral=True)

        # DM the recruitment guide file
        try:
            if os.path.exists(RECRUITMENT_MD):
                await inter.user.send(
                    content="📖 Here’s the **recruitment guide** for Palaemon Bot:",
                    file=discord.File(RECRUITMENT_MD)
                )
            else:
                await inter.user.send("ℹ️ Recruitment guide file not found on the server.")
        except discord.Forbidden:
            await inter.followup.send("⚠️ I couldn’t DM you (your DMs might be disabled).", ephemeral=True)

    async def send_guide(self, user: discord.User, guide_type: str = "user"):
        """Send comprehensive guide via DM"""
        try:
            # Add recruitment section
            recruitment_content = get_recruitment_guide()
            
            embed = discord.Embed(
                title="🎯 **RECRUITMENT SYSTEM** 🎯", 
                description=recruitment_content[:4000],  # Discord embed limit
                color=discord.Color.purple()
            )
            embed.set_footer(text="📖 Palaemon Bot Guide • Page 6/8")
            await user.send(embed=embed)
            
            # If content is longer than 4000 chars, send additional embeds
            if len(recruitment_content) > 4000:
                remaining = recruitment_content[4000:]
                embed2 = discord.Embed(
                    description=remaining[:4000],
                    color=discord.Color.purple()
                )
                embed2.set_footer(text="📖 Palaemon Bot Guide • Page 6b/8")
                await user.send(embed=embed2)

        except discord.Forbidden:
            return "❌ **DM Failed** - Enable DMs to receive the guide."
        except Exception as e:
            return f"❌ **Error:** {e}"

    # Also update your help command to mention recruitment:

    @GUILD_DEC
    @app_commands.command(name="help", description="Get help with bot commands")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🤖 **Palaemon Bot Commands**",
            description="Here are all available commands organized by category:",
            color=discord.Color.blue()
        )
        
        # Add recruitment section to help
        embed.add_field(
            name="🎯 **Recruitment & Growth**",
            value=(
                "`/recruiter_stats` - View your recruitment achievements\n"
                "`/recruiter_leaderboard` - Top community recruiters\n" 
                "`/create_invite` - Create tracked invite links\n"
                "*Earn XP by bringing new members to Palaemon!*"
            ),
            inline=False
        )
        
        # ... rest of help content ...
