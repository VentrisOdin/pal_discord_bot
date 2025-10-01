import os
import aiosqlite
from datetime import datetime, timezone, timedelta  # Add timedelta here
import discord
from discord.ext import commands
from discord import app_commands

_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DEC = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

DB_PATH = os.getenv("DB_PATH", "pal_bot.sqlite")

# Referral rewards configuration
INVITE_XP_REWARD = int(os.getenv("INVITE_XP_REWARD", "100"))  # XP for successful invite
RECRUITER_XP_BONUS = int(os.getenv("RECRUITER_XP_BONUS", "50"))  # Bonus XP per milestone
WELCOME_CHANNEL_ID = int(os.getenv("GENERAL_CHANNEL_ID", "0") or 0)

# Recruiter rank thresholds
RECRUITER_RANKS = {
    1: {"name": "🌱 Scout", "emoji": "🌱", "color": 0x90EE90},
    5: {"name": "🎯 Recruiter", "emoji": "🎯", "color": 0x4169E1},
    10: {"name": "🔥 Headhunter", "emoji": "🔥", "color": 0xFF4500},
    25: {"name": "⭐ Talent Magnet", "emoji": "⭐", "color": 0xFFD700},
    50: {"name": "👑 Legion Builder", "emoji": "👑", "color": 0x9370DB},
    100: {"name": "🌟 Palaemon Ambassador", "emoji": "🌟", "color": 0xFF1493}
}

# Top rank reward
TOP_RANK_PAL_REWARD = 100000  # 100k PAL tokens for reaching max rank
PAL_REWARD_CHANNEL_ID = int(os.getenv("GENERAL_CHANNEL_ID", "0") or 0)  # Where to announce PAL rewards

def get_recruiter_rank(successful_invites: int):
    """Get current recruiter rank based on successful invites"""
    current_rank = {"name": "👤 Newcomer", "emoji": "👤", "color": 0x808080}
    next_threshold = None
    
    for threshold in sorted(RECRUITER_RANKS.keys()):
        if successful_invites >= threshold:
            current_rank = RECRUITER_RANKS[threshold]
        else:
            next_threshold = threshold
            break
    
    return current_rank, next_threshold

class Referrals(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Track recent joins to match with invites
        self.recent_invites = {}

    async def cog_load(self):
        await self.init_db()
        print("Referrals cog loaded - tracking invites...")

    async def init_db(self):
        """Initialize referral tracking tables"""
        async with aiosqlite.connect(DB_PATH) as db:
            # Track who invited whom
            await db.execute("""
                CREATE TABLE IF NOT EXISTS referrals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    inviter_id INTEGER NOT NULL,
                    invited_id INTEGER NOT NULL,
                    invited_at INTEGER NOT NULL,
                    xp_awarded INTEGER DEFAULT 0,
                    still_member INTEGER DEFAULT 1
                )
            """)
            
            # Track invite codes and their creators
            await db.execute("""
                CREATE TABLE IF NOT EXISTS invite_tracking (
                    guild_id INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    inviter_id INTEGER NOT NULL,
                    uses INTEGER DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, code)
                )
            """)
            
            # Recruiter stats and achievements  
            await db.execute("""
                CREATE TABLE IF NOT EXISTS recruiter_stats (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    total_invites INTEGER DEFAULT 0,
                    successful_invites INTEGER DEFAULT 0,
                    total_xp_earned INTEGER DEFAULT 0,
                    current_rank TEXT DEFAULT 'Newcomer',
                    last_milestone INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            
            # PAL token rewards tracking
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pal_rewards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    awarded_at INTEGER NOT NULL,
                    distributed INTEGER DEFAULT 0
                )
            """)
            
            await db.commit()

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Cache invite info when bot joins a guild"""
        await self.cache_invites(guild)

    @commands.Cog.listener()
    async def on_ready(self):
        """Cache invites for all guilds on startup"""
        for guild in self.bot.guilds:
            await self.cache_invites(guild)

    async def cache_invites(self, guild):
        """Cache current invite info"""
        try:
            invites = await guild.invites()
            self.recent_invites[guild.id] = {invite.code: invite.uses for invite in invites}
            print(f"Cached {len(invites)} invites for {guild.name}")
        except discord.Forbidden:
            print(f"No permission to fetch invites for {guild.name}")
        except Exception as e:
            print(f"Error caching invites for {guild.name}: {e}")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Track who invited the new member and award XP"""
        if member.bot:
            return
            
        guild = member.guild
        print(f"New member joined: {member.display_name} in {guild.name}")
        
        try:
            # Get current invites
            current_invites = await guild.invites()
            cached_invites = self.recent_invites.get(guild.id, {})
            
            # Find which invite was used
            inviter_id = None
            used_invite = None
            
            for invite in current_invites:
                cached_uses = cached_invites.get(invite.code, 0)
                if invite.uses > cached_uses:
                    inviter_id = invite.inviter.id if invite.inviter else None
                    used_invite = invite
                    print(f"Invite used: {invite.code} by {invite.inviter.display_name if invite.inviter else 'Unknown'}")
                    break
            
            # Update cache
            self.recent_invites[guild.id] = {inv.code: inv.uses for inv in current_invites}
            
            if inviter_id and inviter_id != member.id:  # Don't reward self-invites
                await self.record_referral(guild.id, inviter_id, member.id, used_invite.code if used_invite else "unknown")
                await self.award_invite_xp(guild, inviter_id, member)
            else:
                print(f"No valid inviter found for {member.display_name}")
                
        except discord.Forbidden:
            print(f"Can't track invites in {guild.name} - missing permissions")
        except Exception as e:
            print(f"Error tracking invite: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Update referral status when someone leaves"""
        if member.bot:
            return
            
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE referrals 
                SET still_member = 0 
                WHERE guild_id = ? AND invited_id = ?
            """, (member.guild.id, member.id))
            await db.commit()
            print(f"Marked {member.display_name} as left in referral tracking")

    async def record_referral(self, guild_id: int, inviter_id: int, invited_id: int, invite_code: str):
        """Record a successful referral"""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO referrals (guild_id, inviter_id, invited_id, invited_at)
                VALUES (?, ?, ?, ?)
            """, (guild_id, inviter_id, invited_id, int(datetime.now(timezone.utc).timestamp())))
            
            # Update recruiter stats
            await db.execute("""
                INSERT OR REPLACE INTO recruiter_stats 
                (guild_id, user_id, total_invites, successful_invites)
                VALUES (?, ?, 
                    COALESCE((SELECT total_invites FROM recruiter_stats WHERE guild_id = ? AND user_id = ?), 0) + 1,
                    COALESCE((SELECT successful_invites FROM recruiter_stats WHERE guild_id = ? AND user_id = ?), 0) + 1
                )
            """, (guild_id, inviter_id, guild_id, inviter_id, guild_id, inviter_id))
            
            await db.commit()
            print(f"Recorded referral: {inviter_id} invited {invited_id}")

    async def award_invite_xp(self, guild: discord.Guild, inviter_id: int, new_member: discord.Member):
        """Award XP to the inviter and check for rank ups"""
        inviter = guild.get_member(inviter_id)
        if not inviter:
            print(f"Inviter {inviter_id} not found in guild")
            return

        try:
            # Import XP function from leveling cog
            from .leveling import add_xp
            await add_xp(guild.id, inviter_id, INVITE_XP_REWARD, reason="successful_invite")
            print(f"Awarded {INVITE_XP_REWARD} XP to {inviter.display_name} for invite")
            
        except ImportError:
            print("Leveling cog not available - XP not awarded")
            
        # Get updated stats
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT successful_invites, total_xp_earned, last_milestone 
                FROM recruiter_stats 
                WHERE guild_id = ? AND user_id = ?
            """, (guild.id, inviter_id))
            result = await cur.fetchone()
            
            if result:
                successful_invites, total_xp_earned, last_milestone = result
                current_rank, next_threshold = get_recruiter_rank(successful_invites)
                
                # Check for milestone bonuses
                milestone_bonus = 0
                new_milestone = last_milestone
                pal_reward_earned = False
                
                for threshold in sorted(RECRUITER_RANKS.keys()):
                    if successful_invites >= threshold > last_milestone:
                        milestone_bonus += RECRUITER_XP_BONUS
                        new_milestone = threshold
                        
                        # Check if they reached the TOP rank (Palaemon Ambassador)
                        if threshold == 100 and last_milestone < 100:
                            pal_reward_earned = True
                            await self.award_pal_tokens(guild, inviter, TOP_RANK_PAL_REWARD)
                
                # Award milestone bonus
                if milestone_bonus > 0:
                    try:
                        from .leveling import add_xp
                        await add_xp(guild.id, inviter_id, milestone_bonus, reason="recruiter_milestone")
                        print(f"Milestone bonus: {milestone_bonus} XP to {inviter.display_name}")
                    except ImportError:
                        pass
                    
                    # Update milestone tracking
                    await db.execute("""
                        UPDATE recruiter_stats 
                        SET current_rank = ?, last_milestone = ?, total_xp_earned = total_xp_earned + ?
                        WHERE guild_id = ? AND user_id = ?
                    """, (current_rank["name"], new_milestone, INVITE_XP_REWARD + milestone_bonus, guild.id, inviter_id))
                else:
                    await db.execute("""
                        UPDATE recruiter_stats 
                        SET current_rank = ?, total_xp_earned = total_xp_earned + ?
                        WHERE guild_id = ? AND user_id = ?
                    """, (current_rank["name"], INVITE_XP_REWARD, guild.id, inviter_id))
                
                await db.commit()
                
                # Send celebration message
                await self.send_invite_celebration(guild, inviter, new_member, successful_invites, current_rank, milestone_bonus > 0, pal_reward_earned)

    async def award_pal_tokens(self, guild: discord.Guild, recipient: discord.Member, amount: int):
        """Award PAL tokens to a user (placeholder - integrate with your token system)"""
        # TODO: Integrate with actual PAL token distribution system
        # This could be:
        # - Database record for manual distribution
        # - Integration with wallet system
        # - Smart contract interaction
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO pal_rewards (guild_id, user_id, amount, reason, awarded_at, distributed)
                VALUES (?, ?, ?, ?, ?, 0)
            """, (guild.id, recipient.id, amount, "recruiter_top_rank", int(datetime.now(timezone.utc).timestamp())))
            await db.commit()
        
        print(f"PAL reward logged: {amount} PAL for {recipient.display_name} (top rank achievement)")
        
        # Send announcement
        channel = guild.get_channel(PAL_REWARD_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title="🌟 **LEGENDARY PAL REWARD!** 🌟",
                description=f"""
**{recipient.mention} has achieved the ultimate rank!**

🏆 **PALAEMON AMBASSADOR** status unlocked!
💰 **{amount:,} PAL tokens** earned!

*The ultimate community builder has been rewarded!*
                """,
                color=0xFF1493  # Hot pink for legendary
            )
            embed.set_footer(text="💫 Recruit 100+ members to earn this legendary reward!")
            await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Update referral status when someone leaves"""
        if member.bot:
            return
            
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE referrals 
                SET still_member = 0 
                WHERE guild_id = ? AND invited_id = ?
            """, (member.guild.id, member.id))
            await db.commit()
            print(f"Marked {member.display_name} as left in referral tracking")

    async def record_referral(self, guild_id: int, inviter_id: int, invited_id: int, invite_code: str):
        """Record a successful referral"""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO referrals (guild_id, inviter_id, invited_id, invited_at)
                VALUES (?, ?, ?, ?)
            """, (guild_id, inviter_id, invited_id, int(datetime.now(timezone.utc).timestamp())))
            
            # Update recruiter stats
            await db.execute("""
                INSERT OR REPLACE INTO recruiter_stats 
                (guild_id, user_id, total_invites, successful_invites)
                VALUES (?, ?, 
                    COALESCE((SELECT total_invites FROM recruiter_stats WHERE guild_id = ? AND user_id = ?), 0) + 1,
                    COALESCE((SELECT successful_invites FROM recruiter_stats WHERE guild_id = ? AND user_id = ?), 0) + 1
                )
            """, (guild_id, inviter_id, guild_id, inviter_id, guild_id, inviter_id))
            
            await db.commit()
            print(f"Recorded referral: {inviter_id} invited {invited_id}")

    async def award_invite_xp(self, guild: discord.Guild, inviter_id: int, new_member: discord.Member):
        """Award XP to the inviter and check for rank ups"""
        inviter = guild.get_member(inviter_id)
        if not inviter:
            print(f"Inviter {inviter_id} not found in guild")
            return

        try:
            # Import XP function from leveling cog
            from .leveling import add_xp
            await add_xp(guild.id, inviter_id, INVITE_XP_REWARD, reason="successful_invite")
            print(f"Awarded {INVITE_XP_REWARD} XP to {inviter.display_name} for invite")
            
        except ImportError:
            print("Leveling cog not available - XP not awarded")
            
        # Get updated stats
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT successful_invites, total_xp_earned, last_milestone 
                FROM recruiter_stats 
                WHERE guild_id = ? AND user_id = ?
            """, (guild.id, inviter_id))
            result = await cur.fetchone()
            
            if result:
                successful_invites, total_xp_earned, last_milestone = result
                current_rank, next_threshold = get_recruiter_rank(successful_invites)
                
                # Check for milestone bonuses
                milestone_bonus = 0
                new_milestone = last_milestone
                pal_reward_earned = False
                
                for threshold in sorted(RECRUITER_RANKS.keys()):
                    if successful_invites >= threshold > last_milestone:
                        milestone_bonus += RECRUITER_XP_BONUS
                        new_milestone = threshold
                        
                        # Check if they reached the TOP rank (Palaemon Ambassador)
                        if threshold == 100 and last_milestone < 100:
                            pal_reward_earned = True
                            await self.award_pal_tokens(guild, inviter, TOP_RANK_PAL_REWARD)
                
                # Award milestone bonus
                if milestone_bonus > 0:
                    try:
                        from .leveling import add_xp
                        await add_xp(guild.id, inviter_id, milestone_bonus, reason="recruiter_milestone")
                        print(f"Milestone bonus: {milestone_bonus} XP to {inviter.display_name}")
                    except ImportError:
                        pass
                    
                    # Update milestone tracking
                    await db.execute("""
                        UPDATE recruiter_stats 
                        SET current_rank = ?, last_milestone = ?, total_xp_earned = total_xp_earned + ?
                        WHERE guild_id = ? AND user_id = ?
                    """, (current_rank["name"], new_milestone, INVITE_XP_REWARD + milestone_bonus, guild.id, inviter_id))
                else:
                    await db.execute("""
                        UPDATE recruiter_stats 
                        SET current_rank = ?, total_xp_earned = total_xp_earned + ?
                        WHERE guild_id = ? AND user_id = ?
                    """, (current_rank["name"], INVITE_XP_REWARD, guild.id, inviter_id))
                
                await db.commit()
                
                # Send celebration message
                await self.send_invite_celebration(guild, inviter, new_member, successful_invites, current_rank, milestone_bonus > 0, pal_reward_earned)

    async def send_invite_celebration(self, guild: discord.Guild, inviter: discord.Member, 
                                     new_member: discord.Member, total_invites: int, 
                                     current_rank: dict, rank_up: bool, pal_reward: bool = False):
        """Send celebration message for successful invite"""
        channel = guild.get_channel(WELCOME_CHANNEL_ID)
        if not channel:
            channel = guild.system_channel
        
        if not channel:
            print("No welcome channel found for celebration message")
            return

        embed = discord.Embed(
            title="🎉 **NEW RECRUIT WELCOMED!** 🎉",
            color=current_rank["color"]
        )
        
        embed.add_field(
            name="👋 **Welcome**",
            value=f"{new_member.mention} joined the ranks!",
            inline=True
        )
        
        embed.add_field(
            name="🎯 **Recruited By**", 
            value=f"{inviter.mention}\n{current_rank['emoji']} {current_rank['name']}",
            inline=True
        )
        
        embed.add_field(
            name="📊 **Recruiter Stats**",
            value=f"**Total Recruits:** {total_invites}\n**XP Earned:** +{INVITE_XP_REWARD}",
            inline=True
        )
        
        if rank_up:
            embed.add_field(
                name="🏆 **RANK UP!**",
                value=f"🎊 **{current_rank['name']}** achieved!\n+{RECRUITER_XP_BONUS} Bonus XP!",
                inline=False
            )
        
        if pal_reward:
            embed.add_field(
                name="💰 **LEGENDARY PAL REWARD!**",
                value=f"🌟 **{TOP_RANK_PAL_REWARD:,} PAL TOKENS EARNED!** 🌟\n*Ultimate rank achieved!*",
                inline=False
            )
        
        embed.set_footer(text="💫 Keep recruiting to climb the ranks!")
        embed.timestamp = datetime.now(timezone.utc)
        
        try:
            await channel.send(embed=embed)
            print(f"Sent celebration message for {new_member.display_name}")
        except Exception as e:
            print(f"Failed to send celebration message: {e}")

    @GUILD_DEC
    @app_commands.command(name="recruiter_stats", description="📊 View your recruiting achievements and stats")
    async def recruiter_stats(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT successful_invites, total_xp_earned, current_rank, last_milestone
                FROM recruiter_stats 
                WHERE guild_id = ? AND user_id = ?
            """, (interaction.guild_id, target.id))
            result = await cur.fetchone()
            
            # Get list of people they recruited
            cur = await db.execute("""
                SELECT invited_id, invited_at, still_member
                FROM referrals 
                WHERE guild_id = ? AND inviter_id = ?
                ORDER BY invited_at DESC
            """, (interaction.guild_id, target.id))
            invites = await cur.fetchall()

        if not result:
            successful_invites = 0
            total_xp_earned = 0
            current_rank_name = "👤 Newcomer"
        else:
            successful_invites, total_xp_earned, current_rank_name, _ = result

        current_rank, next_threshold = get_recruiter_rank(successful_invites)
        
        embed = discord.Embed(
            title=f"{current_rank['emoji']} **{target.display_name}'s Recruiter Profile**",
            color=current_rank["color"]
        )
        
        embed.add_field(
            name="🏅 **Current Rank**",
            value=current_rank["name"],
            inline=True
        )
        
        embed.add_field(
            name="👥 **Successful Recruits**", 
            value=str(successful_invites),
            inline=True
        )
        
        embed.add_field(
            name="⭐ **Total XP Earned**",
            value=f"{total_xp_earned:,}",
            inline=True
        )
        
        if next_threshold:
            needed = next_threshold - successful_invites
            next_rank = RECRUITER_RANKS[next_threshold]
            embed.add_field(
                name="🎯 **Next Rank**",
                value=f"{next_rank['emoji']} {next_rank['name']}\n({needed} more recruits needed)",
                inline=False
            )
        else:
            embed.add_field(
                name="👑 **Status**", 
                value="**MAXIMUM RANK ACHIEVED!** 🌟",
                inline=False
            )
        
        # Recent recruits
        if invites:
            recent = invites[:5]  # Last 5 recruits
            active_count = sum(1 for inv in invites if inv[2])  # still_member = 1
            recruit_text = []
            
            for invited_id, invited_at, still_member in recent:
                member = interaction.guild.get_member(invited_id)
                name = member.display_name if member else f"<@{invited_id}>"
                status = "✅" if still_member else "❌"
                recruit_text.append(f"{status} {name}")
            
            embed.add_field(
                name=f"👥 **Recent Recruits** ({active_count}/{len(invites)} still active)",
                value="\n".join(recruit_text) if recruit_text else "None yet",
                inline=False
            )
        
        embed.set_footer(text="🎯 Recruit more members to climb the ranks!")
        await interaction.response.send_message(embed=embed)

    @GUILD_DEC
    @app_commands.command(name="recruiter_leaderboard", description="🏆 View the top recruiters in the server")
    async def recruiter_leaderboard(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT user_id, successful_invites, total_xp_earned, current_rank
                FROM recruiter_stats 
                WHERE guild_id = ? AND successful_invites > 0
                ORDER BY successful_invites DESC, total_xp_earned DESC
                LIMIT 10
            """, (interaction.guild_id,))
            results = await cur.fetchall()

        if not results:
            embed = discord.Embed(
                title="🏆 **Recruiter Leaderboard**",
                description="No recruiters yet! Be the first to invite someone!",
                color=discord.Color.blue()
            )
            return await interaction.response.send_message(embed=embed)

        embed = discord.Embed(
            title="🏆 **TOP RECRUITERS** 🏆",
            description="*The legends who build our community!*",
            color=discord.Color.gold()
        )
        
        leaderboard_text = []
        for i, (user_id, invites, xp, rank_name) in enumerate(results, 1):
            member = interaction.guild.get_member(user_id)
            name = member.display_name if member else f"<@{user_id}>"
            
            # Medal emojis for top 3
            if i == 1:
                medal = "🥇"
            elif i == 2:
                medal = "🥈" 
            elif i == 3:
                medal = "🥉"
            else:
                medal = f"{i}."
                
            current_rank, _ = get_recruiter_rank(invites)
            leaderboard_text.append(f"{medal} **{name}**\n{current_rank['emoji']} {invites} recruits • {xp:,} XP")
        
        embed.description += f"\n\n{chr(10).join(leaderboard_text)}"
        embed.set_footer(text="🎯 Start recruiting to join the leaderboard!")
        
        await interaction.response.send_message(embed=embed)

    @GUILD_DEC
    @app_commands.command(name="create_invite", description="🔗 Create a tracked invite link for recruiting")
    @app_commands.describe(max_uses="Maximum uses (0 = unlimited)", max_age="Expire after hours (0 = never)")
    async def create_invite(self, interaction: discord.Interaction, max_uses: int = 0, max_age: int = 0):
        try:
            # Convert hours to seconds
            max_age_seconds = max_age * 3600 if max_age > 0 else 0
            
            invite = await interaction.channel.create_invite(
                max_uses=max_uses if max_uses > 0 else None,
                max_age=max_age_seconds if max_age_seconds > 0 else None,
                reason=f"Tracking invite created by {interaction.user.display_name}"
            )
            
            embed = discord.Embed(
                title="🔗 **Recruitment Link Created!**",
                description=f"**Your tracking invite:** {invite.url}",
                color=discord.Color.green()
            )
            
            embed.add_field(name="📊 **Settings**", value=f"Max uses: {'Unlimited' if max_uses == 0 else max_uses}\nExpires: {'Never' if max_age == 0 else f'{max_age} hours'}", inline=True)
            embed.add_field(name="🎯 **Rewards**", value=f"**+{INVITE_XP_REWARD} XP** per successful invite", inline=True)
            embed.set_footer(text="Share this link to get credit for new members!")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to create invites in this channel.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to create invite: {e}", ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="pal_rewards_pending", description="📋 [Admin] View pending PAL token rewards")
    async def pal_rewards_pending(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("🚫 **Admin only** - Manage Server permission required.", ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT user_id, amount, reason, awarded_at, id
                FROM pal_rewards 
                WHERE guild_id = ? AND distributed = 0
                ORDER BY awarded_at DESC
            """, (interaction.guild_id,))
            pending = await cur.fetchall()

        if not pending:
            embed = discord.Embed(
                title="📋 **PAL Rewards - Pending Distribution**",
                description="✅ **No pending rewards!** All PAL tokens have been distributed.",
                color=discord.Color.green()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        embed = discord.Embed(
            title="💰 **PAL Rewards - Pending Distribution**",
            description=f"**{len(pending)}** rewards awaiting distribution:",
            color=discord.Color.gold()
        )
        
        total_pending = 0
        reward_list = []
        
        for user_id, amount, reason, awarded_at, reward_id in pending:
            member = interaction.guild.get_member(user_id)
            name = member.display_name if member else f"<@{user_id}>"
            
            # Convert timestamp to readable date
            awarded_date = datetime.fromtimestamp(awarded_at, timezone.utc).strftime("%Y-%m-%d")
            
            reward_list.append(f"**{name}**\n💰 {amount:,} PAL • {reason}\n📅 {awarded_date} • ID: `{reward_id}`")
            total_pending += amount
        
        embed.add_field(
            name="🏆 **Rewards List**",
            value="\n\n".join(reward_list[:10]),  # Limit to 10 to avoid embed limits
            inline=False
        )
        
        embed.add_field(
            name="📊 **Summary**",
            value=f"**Total Pending:** {total_pending:,} PAL\n**Recipients:** {len(pending)} users",
            inline=True
        )
        
        embed.set_footer(text="Use /pal_rewards_mark_distributed to mark as distributed")
        
        if len(pending) > 10:
            embed.add_field(
                name="⚠️ **Note**",
                value=f"Showing first 10 of {len(pending)} pending rewards",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="pal_rewards_mark_distributed", description="✅ [Admin] Mark PAL reward as distributed")
    @app_commands.describe(reward_id="The reward ID to mark as distributed")
    async def pal_rewards_mark_distributed(self, interaction: discord.Interaction, reward_id: int):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("🚫 **Admin only** - Manage Server permission required.", ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Check if reward exists and is pending
            cur = await db.execute("""
                SELECT user_id, amount, reason, distributed 
                FROM pal_rewards 
                WHERE id = ? AND guild_id = ?
            """, (reward_id, interaction.guild_id))
            reward = await cur.fetchone()
            
            if not reward:
                return await interaction.response.send_message(f"❌ **Reward ID {reward_id} not found** in this server.", ephemeral=True)
            
            user_id, amount, reason, distributed = reward
            
            if distributed:
                return await interaction.response.send_message(f"⚠️ **Reward ID {reward_id} already marked as distributed.**", ephemeral=True)
            
            # Mark as distributed
            await db.execute("""
                UPDATE pal_rewards 
                SET distributed = 1 
                WHERE id = ?
            """, (reward_id,))
            await db.commit()
        
        member = interaction.guild.get_member(user_id)
        name = member.display_name if member else f"<@{user_id}>"
        
        embed = discord.Embed(
            title="✅ **PAL Reward Marked Distributed**",
            description=f"**Recipient:** {name}\n**Amount:** {amount:,} PAL\n**Reason:** {reason}\n**ID:** `{reward_id}`",
            color=discord.Color.green()
        )
        embed.set_footer(text="Reward successfully marked as distributed")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="top_recruiters", description="🏆 Hall of Fame - Top 25 recruiters of all time")
    async def top_recruiters(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT user_id, successful_invites, total_xp_earned, current_rank
                FROM recruiter_stats 
                WHERE guild_id = ? AND successful_invites > 0
                ORDER BY successful_invites DESC, total_xp_earned DESC
                LIMIT 25
            """, (interaction.guild_id,))
            results = await cur.fetchall()

        if not results:
            embed = discord.Embed(
                title="🏆 **HALL OF FAME - TOP RECRUITERS**",
                description="No recruiters yet! Be the first to build the Palaemon community!",
                color=discord.Color.blue()
            )
            return await interaction.response.send_message(embed=embed)

        # Create main leaderboard embed
        embed = discord.Embed(
            title="🏆 **HALL OF FAME - TOP 25 RECRUITERS** 🏆",
            description="*The legends who built our community from the ground up!*",
            color=discord.Color.gold()
        )
        
        # Split into tiers for better visual organization
        legends = []  # Top 5
        champions = []  # 6-15
        heroes = []  # 16-25
        
        for i, (user_id, invites, xp, rank_name) in enumerate(results, 1):
            member = interaction.guild.get_member(user_id)
            name = member.display_name if member else f"<@{user_id}>"
            
            current_rank, _ = get_recruiter_rank(invites)
            
            # Create entry text
            if i == 1:
                medal = "🥇"
                entry = f"👑 **{name}** - **THE EMPEROR**\n{current_rank['emoji']} {invites} recruits • {xp:,} XP"
            elif i == 2:
                medal = "🥈"
                entry = f"💎 **{name}** - **THE GENERAL**\n{current_rank['emoji']} {invites} recruits • {xp:,} XP"
            elif i == 3:
                medal = "🥉"
                entry = f"⭐ **{name}** - **THE CAPTAIN**\n{current_rank['emoji']} {invites} recruits • {xp:,} XP"
            elif i <= 5:
                medal = "🏆"
                entry = f"🔥 **{name}**\n{current_rank['emoji']} {invites} recruits • {xp:,} XP"
            elif i <= 15:
                medal = f"🌟"
                entry = f"**{name}**\n{current_rank['emoji']} {invites} recruits • {xp:,} XP"
            else:
                medal = f"⭐"
                entry = f"**{name}** • {current_rank['emoji']} {invites} • {xp:,} XP"
            
            # Sort into tiers
            if i <= 5:
                legends.append(f"{medal} **#{i}** {entry}")
            elif i <= 15:
                champions.append(f"{medal} **#{i}** {entry}")
            else:
                heroes.append(f"{medal} **#{i}** {entry}")
        
        # Add tiers to embed
        if legends:
            embed.add_field(
                name="👑 **LEGENDARY TIER** (Top 5)",
                value="\n\n".join(legends),
                inline=False
            )
        
        if champions:
            embed.add_field(
                name="🏆 **CHAMPION TIER** (6-15)",
                value="\n\n".join(champions),
                inline=False
            )
        
        if heroes:
            embed.add_field(
                name="⭐ **HERO TIER** (16-25)",
                value="\n\n".join(heroes),
                inline=False
            )
        
        # Add summary statistics
        total_recruits = sum(row[1] for row in results)  # Sum of successful_invites
        total_xp_awarded = sum(row[2] for row in results)  # Sum of total_xp_earned
        
        embed.add_field(
            name="📊 **Community Impact**",
            value=(
                f"**Total Members Recruited:** {total_recruits:,}\n"
                f"**Total XP Awarded:** {total_xp_awarded:,}\n"
                f"**Active Recruiters:** {len(results)}"
            ),
            inline=True
        )
        
        # Check for PAL rewards earned
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("""
                SELECT COUNT(*), SUM(amount) 
                FROM pal_rewards 
                WHERE guild_id = ? AND reason = 'recruiter_top_rank'
            """, (interaction.guild_id,))
            pal_stats = await cur.fetchone()
        
        if pal_stats and pal_stats[0] > 0:
            embed.add_field(
                name="💰 **PAL Rewards Earned**",
                value=f"**{pal_stats[0]}** Ambassadors\n**{pal_stats[1]:,}** PAL distributed",
                inline=True
            )
        
        embed.set_footer(text="🎯 Use /create_invite to start your recruiting journey!")
        embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/123456789.png")  # Add trophy image if you have one
        
        await interaction.response.send_message(embed=embed)

    @GUILD_DEC
    @app_commands.command(name="recruiting_stats", description="📊 Server recruiting statistics and milestones")
    async def recruiting_stats(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            # Get overall statistics
            cur = await db.execute("""
                SELECT 
                    COUNT(DISTINCT user_id) as total_recruiters,
                    SUM(successful_invites) as total_recruits,
                    SUM(total_xp_earned) as total_xp,
                    AVG(successful_invites) as avg_recruits
                FROM recruiter_stats 
                WHERE guild_id = ? AND successful_invites > 0
            """, (interaction.guild_id,))
            overall_stats = await cur.fetchone()
            
            # Get rank distribution
            rank_counts = {}
            for threshold in RECRUITER_RANKS.keys():
                cur = await db.execute("""
                    SELECT COUNT(*) 
                    FROM recruiter_stats 
                    WHERE guild_id = ? AND successful_invites >= ? AND successful_invites < ?
                """, (interaction.guild_id, threshold, threshold * 2 if threshold < 100 else 999))
                count = await cur.fetchone()
                rank_counts[threshold] = count[0] if count else 0
            
            # Get PAL rewards
            cur = await db.execute("""
                SELECT COUNT(*), SUM(amount), COUNT(*) - SUM(distributed) 
                FROM pal_rewards 
                WHERE guild_id = ? AND reason = 'recruiter_top_rank'
            """, (interaction.guild_id,))
            pal_stats = await cur.fetchone()
            
            # Get recent activity (last 30 days)
            thirty_days_ago = int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp())
            cur = await db.execute("""
                SELECT COUNT(*) 
                FROM referrals 
                WHERE guild_id = ? AND invited_at > ?
            """, (interaction.guild_id, thirty_days_ago))
            recent_recruits = await cur.fetchone()

        if not overall_stats or overall_stats[0] == 0:
            embed = discord.Embed(
                title="📊 **Server Recruiting Statistics**",
                description="No recruiting activity yet! Use `/create_invite` to get started!",
                color=discord.Color.blue()
            )
            return await interaction.response.send_message(embed=embed)

        total_recruiters, total_recruits, total_xp, avg_recruits = overall_stats
        
        embed = discord.Embed(
            title="📊 **PALAEMON RECRUITING STATISTICS** 📊",
            description="*Building the strongest community in crypto!*",
            color=discord.Color.purple()
        )
        
        # Overall stats
        embed.add_field(
            name="🌟 **Overall Impact**",
            value=(
                f"**Total Recruiters:** {total_recruiters}\n"
                f"**Members Recruited:** {total_recruits}\n"
                f"**XP Distributed:** {total_xp:,}\n"
                f"**Average per Recruiter:** {avg_recruits:.1f}"
            ),
            inline=True
        )
        
        # Recent activity
        embed.add_field(
            name="🔥 **Recent Activity (30 days)**",
            value=f"**New Recruits:** {recent_recruits[0] if recent_recruits else 0}",
            inline=True
        )
        
        # PAL rewards
        if pal_stats and pal_stats[0] > 0:
            embed.add_field(
                name="💰 **PAL Rewards**",
                value=(
                    f"**Ambassadors:** {pal_stats[0]}\n"
                    f"**PAL Distributed:** {pal_stats[1]:,}\n"
                    f"**Pending:** {pal_stats[2]} rewards"
                ),
                inline=True
            )
        
        # Rank distribution
        rank_text = []
        for threshold in sorted(RECRUITER_RANKS.keys()):
            rank_info = RECRUITER_RANKS[threshold]
            count = rank_counts.get(threshold, 0)
            if count > 0:
                rank_text.append(f"{rank_info['emoji']} **{rank_info['name']}:** {count}")
        
        if rank_text:
            embed.add_field(
                name="🏅 **Rank Distribution**",
                value="\n".join(rank_text),
                inline=False
            )
        
        embed.set_footer(text="💫 Every recruit makes Palaemon stronger!")
        embed.timestamp = datetime.now(timezone.utc)
        
        await interaction.response.send_message(embed=embed)