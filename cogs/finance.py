import discord
from discord.ext import commands, tasks
from discord import app_commands
from services.price_alerts import PriceAlerts
from services.portfolio import Portfolio
from services.user_prefs import UserPrefs
import aiohttp
import asyncio
import os
import logging

class Finance(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.price_alerts = PriceAlerts()
        self.portfolio = Portfolio()
        self.user_prefs = UserPrefs()
        self._session: aiohttp.ClientSession | None = None
        self._current_prices: dict[str, float] = {}
        
    async def cog_load(self):
        try:
            await self.price_alerts.init()
            logging.info("PriceAlerts: initialized")
        except Exception as e:
            logging.error(f"PriceAlerts init failed: {e}")
            
        try:
            await self.portfolio.init()
            logging.info("Portfolio: initialized")
        except Exception as e:
            logging.error(f"Portfolio init failed: {e}")
            
        try:
            await self.user_prefs.init()
            logging.info("UserPrefs: initialized")
        except Exception as e:
            logging.error(f"UserPrefs init failed: {e}")
            
        self._session = aiohttp.ClientSession()
        
        # Start price monitoring
        if not self.monitor_prices.is_running():
            self.monitor_prices.start()
            logging.info("Finance: price monitoring started")

    async def cog_unload(self):
        if self._session:
            await self._session.close()
        if self.monitor_prices.is_running():
            self.monitor_prices.cancel()

    @tasks.loop(minutes=1)  # Check prices every minute
    async def monitor_prices(self):
        """Monitor prices and trigger alerts."""
        try:
            # Fetch current prices (implement your price API here)
            await self._fetch_current_prices()
            
            # Check all alerts
            triggered = await self.price_alerts.check_alerts(self._current_prices)
            
            # Send alert notifications
            for alert in triggered:
                await self._send_price_alert(alert)
                
        except Exception as e:
            logging.exception(f"Error monitoring prices: {e}")

    async def _fetch_current_prices(self):
        """Fetch current prices from your API."""
        # Implement your price fetching logic here
        # This is a placeholder - replace with real API calls
        try:
            # Example: fetch PAL price from your DEX/API
            self._current_prices['PAL'] = 0.045  # Replace with real price fetch
            # Add more tokens as needed
        except Exception as e:
            logging.exception(f"Error fetching prices: {e}")

    async def _send_price_alert(self, alert):
        """Send price alert notification to user."""
        try:
            user = self.bot.get_user(alert['user_id'])
            if not user:
                return
                
            # Check if user opted out of DMs
            if await self.user_prefs.is_dm_opt_out(alert['user_id'], alert['guild_id']):
                return
                
            embed = discord.Embed(
                title="🚨 Price Alert Triggered!",
                color=discord.Color.gold()
            )
            
            condition_text = "above" if alert['condition'] == 'above' else "below"
            embed.add_field(
                name=f"{alert['token']} Price Alert",
                value=f"**Target:** ${alert['target_price']:.6f} ({condition_text})\n"
                      f"**Current:** ${alert['current_price']:.6f}\n"
                      f"**Condition:** Price went {condition_text} your target!",
                inline=False
            )
            
            embed.set_footer(text="Set more alerts with /price_alert")
            
            await user.send(embed=embed)
            
        except Exception as e:
            logging.exception(f"Error sending price alert: {e}")

    @app_commands.command(name="price_alert", description="Set a price alert for a token")
    @app_commands.describe(
        token="Token symbol (e.g., PAL)",
        price="Target price to alert at",
        condition="Alert when price goes 'above' or 'below' target"
    )
    async def price_alert(self, interaction: discord.Interaction, token: str, price: float, condition: str):
        if condition.lower() not in ['above', 'below']:
            await interaction.response.send_message(
                "❌ Condition must be 'above' or 'below'", ephemeral=True
            )
            return
            
        if price <= 0:
            await interaction.response.send_message(
                "❌ Price must be greater than 0", ephemeral=True
            )
            return
            
        await self.price_alerts.add_alert(
            interaction.user.id, 
            interaction.guild_id, 
            token.upper(), 
            price, 
            condition.lower()
        )
        
        embed = discord.Embed(
            title="✅ Price Alert Set!",
            description=f"You'll be notified when **{token.upper()}** goes **{condition.lower()}** **${price:.6f}**",
            color=discord.Color.green()
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="alerts", description="View your active price alerts")
    async def alerts(self, interaction: discord.Interaction):
        user_alerts = await self.price_alerts.get_user_alerts(interaction.user.id, interaction.guild_id)
        
        if not user_alerts:
            await interaction.response.send_message(
                "📭 You have no active price alerts.\nSet one with `/price_alert`", 
                ephemeral=True
            )
            return
            
        embed = discord.Embed(
            title="🔔 Your Active Price Alerts",
            color=discord.Color.blue()
        )
        
        for alert in user_alerts[:10]:  # Limit to 10 alerts
            condition_emoji = "📈" if alert['condition'] == 'above' else "📉"
            embed.add_field(
                name=f"{condition_emoji} {alert['token']}",
                value=f"**Target:** ${alert['price']:.6f} ({alert['condition']})\n"
                      f"**Created:** {alert['created'][:10]}",
                inline=True
            )
        
        embed.set_footer(text="Remove alerts with /remove_alert <id>")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="portfolio", description="Add tokens to your portfolio tracking")
    @app_commands.describe(
        action="'add' to add tokens, 'view' to see portfolio, 'pnl' for profit/loss",
        token="Token symbol (required for 'add')",
        amount="Amount of tokens (required for 'add')", 
        price="Price you bought at (required for 'add')"
    )
    async def portfolio(self, interaction: discord.Interaction, action: str, 
                       token: str = None, amount: float = None, price: float = None):
        
        if action.lower() == "add":
            if not all([token, amount, price]):
                await interaction.response.send_message(
                    "❌ For 'add' action, you need: token, amount, and price", 
                    ephemeral=True
                )
                return
                
            if amount <= 0 or price <= 0:
                await interaction.response.send_message(
                    "❌ Amount and price must be greater than 0", 
                    ephemeral=True
                )
                return
                
            await self.portfolio.add_position(
                interaction.user.id, interaction.guild_id, token, amount, price
            )
            
            embed = discord.Embed(
                title="✅ Portfolio Updated!",
                description=f"Added **{amount:,.2f} {token.upper()}** at **${price:.6f}**",
                color=discord.Color.green()
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        elif action.lower() == "view":
            portfolio_data = await self.portfolio.get_portfolio(interaction.user.id, interaction.guild_id)
            
            if not portfolio_data:
                await interaction.response.send_message(
                    "📭 Your portfolio is empty.\nAdd positions with `/portfolio add`", 
                    ephemeral=True
                )
                return
                
            embed = discord.Embed(
                title="💼 Your Portfolio",
                color=discord.Color.blue()
            )
            
            for position in portfolio_data[:10]:
                embed.add_field(
                    name=f"💎 {position['token']}",
                    value=f"**Amount:** {position['amount']:,.2f}\n"
                          f"**Avg Price:** ${position['avg_price']:.6f}\n"
                          f"**Value:** ${position['amount'] * position['avg_price']:,.2f}",
                    inline=True
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        elif action.lower() == "pnl":
            pnl_data = await self.portfolio.calculate_pnl(
                interaction.user.id, interaction.guild_id, self._current_prices
            )
            
            if not pnl_data['positions']:
                await interaction.response.send_message(
                    "📭 Your portfolio is empty.\nAdd positions with `/portfolio add`", 
                    ephemeral=True
                )
                return
                
            color = discord.Color.green() if pnl_data['total_pnl'] >= 0 else discord.Color.red()
            pnl_emoji = "📈" if pnl_data['total_pnl'] >= 0 else "📉"
            
            embed = discord.Embed(
                title=f"{pnl_emoji} Portfolio P&L",
                color=color
            )
            
            embed.add_field(
                name="📊 Total Summary",
                value=f"**Invested:** ${pnl_data['total_invested']:,.2f}\n"
                      f"**Current Value:** ${pnl_data['total_current']:,.2f}\n"
                      f"**P&L:** ${pnl_data['total_pnl']:,.2f} ({pnl_data['total_pnl_percent']:+.2f}%)",
                inline=False
            )
            
            for pos in pnl_data['positions'][:8]:  # Show top 8 positions
                pnl_emoji = "📈" if pos['pnl'] >= 0 else "📉"
                embed.add_field(
                    name=f"{pnl_emoji} {pos['token']}",
                    value=f"**P&L:** ${pos['pnl']:,.2f} ({pos['pnl_percent']:+.2f}%)\n"
                          f"**Current:** ${pos['current_price']:.6f}",
                    inline=True
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        else:
            await interaction.response.send_message(
                "❌ Action must be 'add', 'view', or 'pnl'", 
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(Finance(bot))