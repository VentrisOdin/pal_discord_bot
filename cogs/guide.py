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

def get_recruitment_guide() -> str:
    """Get recruitment system guide content"""
    return """
## 🎯 **RECRUITMENT & REFERRAL SYSTEM**

**Grow the community and get rewarded!**

### 📊 **How It Works**
When someone joins using your invite link, you automatically earn:
• **+100 XP** per successful invite
• **Bonus XP** when reaching rank milestones
• **Recognition** in welcome messages
• **Progression** through recruiter ranks

### 🏆 **Recruiter Ranks**
Progress through these epic ranks:

👤 **Newcomer** (0 recruits)
*Just getting started*

🌱 **Scout** (1+ recruits)  
*First successful invite*

🎯 **Recruiter** (5+ recruits)
*Building momentum* • +50 Bonus XP

🔥 **Headhunter** (10+ recruits)
*Serious talent acquisition* • +50 Bonus XP

⭐ **Talent Magnet** (25+ recruits)
*Community growth champion* • +50 Bonus XP

👑 **Legion Builder** (50+ recruits)
*Elite recruiter status* • +50 Bonus XP

🌟 **Palaemon Ambassador** (100+ recruits)
*Legendary community builder* • +50 Bonus XP
**💰 100,000 PAL TOKEN REWARD! 💰**

### 🔗 **Creating Invite Links**

**Method 1: Discord Interface**
1. Right-click your server name
2. Click "Invite People"
3. Customize settings and copy link
4. Share anywhere to get credit!

**Method 2: Bot Command**
Use `/create_invite` for tracked invites:
```
/create_invite max_uses:10 max_age:24
```
• `max_uses` - How many people can use it (0 = unlimited)
• `max_age` - Hours until it expires (0 = never)

### 📋 **Commands**

**User Commands:**
• `/recruiter_stats [user]` - View recruitment achievements
• `/recruiter_leaderboard` - Top 10 recruiters  
• `/top_recruiters` - Hall of Fame (Top 25)
• `/recruiting_stats` - Server statistics
• `/create_invite` - Generate tracked invite links

**Admin Commands:**
• `/pal_rewards_pending` - View pending PAL rewards
• `/pal_rewards_mark_distributed` - Mark rewards as sent

### 🏆 **Hall of Fame Features**

**Top 25 Leaderboard:**
• **Legendary Tier** (Top 5) - The community emperors
• **Champion Tier** (6-15) - Elite recruiters  
• **Hero Tier** (16-25) - Rising stars

**Special Titles:**
• 🥇 **#1 = "THE EMPEROR"** - Ultimate community leader
• 🥈 **#2 = "THE GENERAL"** - Master strategist
• 🥉 **#3 = "THE CAPTAIN"** - Elite commander

### 💰 **PAL Token Rewards**

**100,000 PAL** for reaching **🌟 Palaemon Ambassador** (100+ recruits)

**How it works:**
1. Reach 100 successful recruits
2. Automatic PAL reward logged in system
3. Admin distributes tokens manually
4. Epic server-wide announcement

### 💡 **Pro Tips**

**Maximize Your Recruiting:**
• Share invites on **social media**
• Post in **relevant Discord servers**
• Include in your **Twitter/X bio**
• Share with **friends interested in crypto**

**Best Practices:**
• **Welcome new members** personally
• **Help them get started** with bot commands
• **Explain server rules** and channels
• **Be an awesome community ambassador**

### 🚨 **Important Notes**

• **No self-invites** - You can't invite yourself for XP
• **Active tracking** - System monitors if invitees stay
• **Fair play** - Quality recruiting encouraged over quantity
• **Integration** - Works with existing XP/leveling system

---

*Ready to become a recruiting legend? Use `/create_invite` and start building the Palaemon empire!* 🚀
"""

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
                "• `/recruiter_stats` — view recruiting achievements\n"
                "• `/platypus` — get a random Pal Platypus image!\n"
                "• `/bot_help` — full command index"
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text="You'll receive the full public manual via DM.")
        await inter.response.send_message(embed=embed, ephemeral=True)

        # DM the public manual file
        try:
            if os.path.exists(PUBLIC_MD):
                await inter.user.send(
                    content="📖 Here's the **public user manual** for Palaemon Bot:",
                    file=discord.File(PUBLIC_MD)
                )
            else:
                await inter.user.send("ℹ️ Public manual file not found on the server.")
        except discord.Forbidden:
            await inter.followup.send("⚠️ I couldn't DM you (your DMs might be disabled).", ephemeral=True)

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
                "• `/level_givexp` — give XP for events\n"
                "• `/pal_rewards_pending` — check pending PAL rewards\n\n"
                "**Safety:** give the bot `Manage Channels` + `Manage Roles`; keep bot role above reward/verified roles."
            ),
            color=discord.Color.blurple()
        )
        embed.set_footer(text="You'll receive the full admin manual via DM.")
        await inter.response.send_message(embed=embed, ephemeral=True)

        # DM the full admin manual file
        try:
            if os.path.exists(ADMIN_MD):
                await inter.user.send(
                    content="📕 Here's the **admin manual** (full instructions):",
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
            await inter.followup.send("⚠️ I couldn't DM you the admin manual (your DMs might be disabled).", ephemeral=True)

    # ---------- RECRUITMENT GUIDE ----------
    @GUILD_DEC
    @app_commands.command(name="recruitment_guide", description="📖 Complete guide to the recruitment system")
    async def recruitment_guide(self, inter: discord.Interaction):
        embed = discord.Embed(
            title="🎯 **Recruitment System Guide**",
            description="Learn how to earn XP and PAL tokens by growing our community!",
            color=discord.Color.purple()
        )
        embed.set_footer(text="You'll receive the full recruitment guide via DM.")
        await inter.response.send_message(embed=embed, ephemeral=True)

        # Send recruitment guide via DM
        try:
            recruitment_content = get_recruitment_guide()
            
            # Split content if too long for single embed
            if len(recruitment_content) > 4000:
                # First part
                embed1 = discord.Embed(
                    title="🎯 **RECRUITMENT SYSTEM GUIDE** 🎯", 
                    description=recruitment_content[:4000],
                    color=discord.Color.purple()
                )
                embed1.set_footer(text="📖 Recruitment Guide • Page 1/2")
                await inter.user.send(embed=embed1)
                
                # Second part
                embed2 = discord.Embed(
                    description=recruitment_content[4000:],
                    color=discord.Color.purple()
                )
                embed2.set_footer(text="📖 Recruitment Guide • Page 2/2")
                await inter.user.send(embed=embed2)
            else:
                embed = discord.Embed(
                    title="🎯 **RECRUITMENT SYSTEM GUIDE** 🎯",
                    description=recruitment_content,
                    color=discord.Color.purple()
                )
                await inter.user.send(embed=embed)
                
        except discord.Forbidden:
            await inter.followup.send("⚠️ I couldn't DM you the guide (your DMs might be disabled).", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Guide(bot))
