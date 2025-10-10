import discord
from discord.ext import commands, tasks
from discord import app_commands
from services.news_ai import NewsAI
from services.reputation import Reputation
from services.user_prefs import UserPrefs
import logging
from datetime import datetime

class News(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.news_ai = NewsAI()
        self.reputation = Reputation()
        self.user_prefs = UserPrefs()

    async def cog_load(self):
        await self.news_ai.init()
        await self.reputation.init()
        await self.user_prefs.init()
        logging.info("News: loaded")

    async def cog_unload(self):
        await self.news_ai.close()

    @app_commands.command(name="news", description="Get AI-summarized crypto news")
    @app_commands.describe(topic="Specific topic to search for (optional)")
    async def news(self, interaction: discord.Interaction, topic: str = None):
        await interaction.response.defer()
        
        try:
            keywords = [topic] if topic else ['crypto', 'defi', 'blockchain']
            articles = await self.news_ai.fetch_crypto_news(keywords, limit=5)
            
            if not articles:
                await interaction.followup.send("📰 No recent news found. Try again later!")
                return
            
            embed = discord.Embed(
                title="📰 Latest Crypto News",
                description=f"AI-curated news {f'about **{topic}**' if topic else 'from the crypto world'}",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            for i, article in enumerate(articles[:3], 1):
                sentiment_emoji = {"positive": "📈", "negative": "📉", "neutral": "📊"}[article.sentiment]
                
                embed.add_field(
                    name=f"{sentiment_emoji} {article.title[:80]}{'...' if len(article.title) > 80 else ''}",
                    value=f"**{article.summary[:150]}{'...' if len(article.summary) > 150 else ''}**\n"
                          f"🏷️ **Keywords:** {', '.join(article.keywords[:3])}\n"
                          f"📊 **Sentiment:** {article.sentiment.title()}\n"
                          f"🔗 [Read More]({article.url})",
                    inline=False
                )
            
            embed.set_footer(text=f"Relevance scores: {', '.join([f'{a.relevance_score:.1%}' for a in articles[:3]])}")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logging.exception(f"Error fetching news: {e}")
            await interaction.followup.send("❌ Error fetching news. Please try again later.")

    @app_commands.command(name="sentiment", description="Get current market sentiment analysis")
    async def sentiment(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            sentiment_data = await self.news_ai.get_market_sentiment()
            
            # Choose color based on sentiment
            color_map = {
                'bullish': discord.Color.green(),
                'bearish': discord.Color.red(),
                'neutral': discord.Color.yellow()
            }
            
            embed = discord.Embed(
                title="📊 Market Sentiment Analysis",
                description=f"Overall sentiment is **{sentiment_data['overall'].upper()}** 🎯",
                color=color_map[sentiment_data['overall']],
                timestamp=sentiment_data['last_updated']
            )
            
            # Sentiment breakdown
            percentages = sentiment_data['percentages']
            embed.add_field(
                name="📈 Sentiment Breakdown",
                value=f"**Positive:** {percentages['positive']:.1f}%\n"
                      f"**Negative:** {percentages['negative']:.1f}%\n"
                      f"**Neutral:** {percentages['neutral']:.1f}%",
                inline=True
            )
            
            # Sentiment bar visualization
            pos_bar = "🟢" * int(percentages['positive'] // 10)
            neg_bar = "🔴" * int(percentages['negative'] // 10)
            neu_bar = "🟡" * int(percentages['neutral'] // 10)
            
            embed.add_field(
                name="📊 Visual Breakdown",
                value=f"**Positive:** {pos_bar}\n"
                      f"**Negative:** {neg_bar}\n"
                      f"**Neutral:** {neu_bar}",
                inline=True
            )
            
            embed.add_field(
                name="📰 Analysis Based On",
                value=f"**{sentiment_data['article_count']} recent articles**\nFrom major crypto news sources",
                inline=False
            )
            
            embed.set_footer(text="Sentiment updates every hour • Use /news for latest articles")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logging.exception(f"Error analyzing sentiment: {e}")
            await interaction.followup.send("❌ Error analyzing sentiment. Please try again later.")

    @app_commands.command(name="trending", description="See what's trending in crypto")
    async def trending(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            trending_topics = await self.news_ai.get_trending_topics()
            
            if not trending_topics:
                await interaction.followup.send("📈 No trending topics found right now!")
                return
            
            embed = discord.Embed(
                title="🔥 Trending in Crypto",
                description="Hot topics from recent news analysis",
                color=discord.Color.orange(),
                timestamp=datetime.now()
            )
            
            for i, topic in enumerate(trending_topics[:8], 1):
                fire_count = "🔥" * min(int(topic['trending_score'] * 5), 5)
                embed.add_field(
                    name=f"#{i} {topic['topic'].upper()}",
                    value=f"{fire_count}\n**{topic['mentions']} mentions**",
                    inline=True
                )
            
            embed.set_footer(text="Based on keyword frequency in recent crypto news")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logging.exception(f"Error getting trending topics: {e}")
            await interaction.followup.send("❌ Error getting trending topics. Please try again later.")

    @app_commands.command(name="rep", description="Give reputation points to a community member")
    @app_commands.describe(
        user="User to give reputation to",
        points="Points to give (1-3)",
        reason="Reason for giving reputation"
    )
    async def rep(self, interaction: discord.Interaction, user: discord.Member, 
                  points: int = 1, reason: str = ""):
        
        if points < 1 or points > 3:
            await interaction.response.send_message(
                "❌ You can only give 1-3 reputation points at a time!", 
                ephemeral=True
            )
            return
        
        if len(reason) > 200:
            await interaction.response.send_message(
                "❌ Reason must be 200 characters or less!", 
                ephemeral=True
            )
            return
        
        result = await self.reputation.give_reputation(
            interaction.user.id, user.id, interaction.guild_id, points, reason
        )
        
        if not result['success']:
            await interaction.response.send_message(
                f"❌ {result['error']}", 
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="⭐ Reputation Given!",
            description=f"**+{points} reputation** to {user.mention}",
            color=discord.Color.gold()
        )
        
        if reason:
            embed.add_field(name="💬 Reason", value=reason, inline=False)
        
        embed.add_field(
            name="📊 Daily Limit", 
            value=f"**{result['remaining_daily']} points** remaining today",
            inline=True
        )
        
        # Show new achievements
        if result['new_achievements']:
            achievement_text = "\n".join([
                f"{a.icon} **{a.name}** - {a.description}" 
                for a in result['new_achievements']
            ])
            embed.add_field(
                name="🏆 New Achievements Unlocked!",
                value=achievement_text,
                inline=False
            )
        
        await interaction.response.send_message(embed=embed)
        
        # Notify the user if they received achievements (and haven't opted out)
        if result['new_achievements'] and not await self.user_prefs.is_dm_opt_out(user.id, interaction.guild_id):
            try:
                dm_embed = discord.Embed(
                    title="🏆 Achievement Unlocked!",
                    description=f"You earned new achievements in **{interaction.guild.name}**!",
                    color=discord.Color.gold()
                )
                
                for achievement in result['new_achievements']:
                    dm_embed.add_field(
                        name=f"{achievement.icon} {achievement.name}",
                        value=achievement.description,
                        inline=False
                    )
                
                await user.send(embed=dm_embed)
            except:
                pass  # User might have DMs disabled

    @app_commands.command(name="reputation", description="View reputation stats for yourself or another user")
    @app_commands.describe(user="User to check reputation for (optional)")
    async def reputation_stats(self, interaction: discord.Interaction, user: discord.Member = None):
        target_user = user or interaction.user
        
        user_stats = await self.reputation.get_user_reputation(target_user.id, interaction.guild_id)
        
        embed = discord.Embed(
            title=f"⭐ Reputation Stats for {target_user.display_name}",
            color=discord.Color.gold()
        )
        
        embed.set_thumbnail(url=target_user.display_avatar.url)
        
        embed.add_field(
            name="📊 Overview",
            value=f"**Total Rep:** {user_stats['total_received']} points\n"
                  f"**Rank:** #{user_stats['rank']} in server\n"
                  f"**Given:** {user_stats['total_given']} points to others",
            inline=False
        )
        
        if user_stats['achievements']:
            achievement_text = "\n".join([
                f"{a['icon']} **{a['name']}**" 
                for a in user_stats['achievements'][:8]
            ])
            if len(user_stats['achievements']) > 8:
                achievement_text += f"\n*... and {len(user_stats['achievements']) - 8} more*"
            
            embed.add_field(
                name=f"🏆 Achievements ({len(user_stats['achievements'])})",
                value=achievement_text,
                inline=False
            )
        
        if user_stats['recent_entries']:
            recent_text = ""
            for entry in user_stats['recent_entries'][:3]:
                from_user = self.bot.get_user(entry['from_user'])
                from_name = from_user.display_name if from_user else "Unknown User"
                reason_text = f" - {entry['reason']}" if entry['reason'] else ""
                recent_text += f"**+{entry['points']}** from {from_name}{reason_text}\n"
            
            embed.add_field(
                name="📝 Recent Reputation",
                value=recent_text,
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=(user != interaction.user))

    @app_commands.command(name="leaderboard", description="View the server reputation leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        leaderboard = await self.reputation.get_leaderboard(interaction.guild_id, limit=10)
        
        if not leaderboard:
            await interaction.response.send_message(
                "📭 No reputation data yet! Start giving rep with `/rep`", 
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="🏆 Reputation Leaderboard",
            description=f"Top reputation holders in **{interaction.guild.name}**",
            color=discord.Color.gold(),
            timestamp=datetime.now()
        )
        
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        
        leaderboard_text = ""
        for entry in leaderboard:
            user = self.bot.get_user(entry['user_id'])
            user_name = user.display_name if user else "Unknown User"
            
            medal = medals[entry['rank'] - 1] if entry['rank'] <= 10 else "🏅"
            leaderboard_text += f"{medal} **#{entry['rank']}** {user_name}\n"
            leaderboard_text += f"     ⭐ {entry['total_reputation']} rep • 🏆 {entry['achievement_count']} achievements\n\n"
        
        embed.description = f"{embed.description}\n\n{leaderboard_text}"
        embed.set_footer(text="Give reputation with /rep • View your stats with /reputation")
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(News(bot))