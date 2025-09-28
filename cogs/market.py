# cogs/market.py
import os
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands

_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DEC = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

PAL_TOKEN = os.getenv("PAL_TOKEN_ADDRESS", "0xad20315b89E89E900FB21d7Ea158079c1A764a59")
PAL_PAIR = os.getenv("PAL_PAIR_ADDRESS", "0x239eB1236AF3A9b76fce9E8efa9b17C15eBD6a9E")
CHAIN = os.getenv("DEXSCREENER_CHAIN", "bsc")

class Market(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_pal_price_pancakeswap(self):
        """Try PancakeSwap API for PAL price"""
        try:
            url = f"https://api.pancakeswap.info/api/v2/tokens/{PAL_TOKEN}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    print(f"PancakeSwap API status: {response.status}")
                    if response.status == 200:
                        data = await response.json()
                        print(f"PancakeSwap data: {data}")
                        price = data.get("data", {}).get("price")
                        if price:
                            return {
                                "price": price,
                                "source": "PancakeSwap"
                            }
        except Exception as e:
            print(f"PancakeSwap API error: {e}")
        return None

    async def get_pal_price_dexscreener(self, query: str):
        """Try DexScreener API"""
        try:
            # Try search first
            url = f"https://api.dexscreener.com/latest/dex/search/?q={query}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    print(f"DexScreener API status: {response.status}")
                    if response.status == 200:
                        data = await response.json()
                        pairs = data.get("pairs", [])
                        print(f"DexScreener found {len(pairs)} pairs")
                        
                        # Filter for BSC PAL tokens
                        for pair in pairs:
                            if (pair.get("chainId") == "bsc" and 
                                pair.get("baseToken", {}).get("address", "").lower() == PAL_TOKEN.lower()):
                                return {
                                    "price": pair.get("priceUsd"),
                                    "source": "DexScreener",
                                    "pair": pair
                                }
        except Exception as e:
            print(f"DexScreener API error: {e}")
        return None

    @GUILD_DEC
    @app_commands.command(name="price", description="Get token price")
    @app_commands.describe(token="Token symbol (PAL) or contract address")
    async def price(self, interaction: discord.Interaction, token: str = "PAL"):
        await interaction.response.defer()
        
        # Special handling for PAL
        if token.upper() == "PAL" or token.lower() == PAL_TOKEN.lower():
            # Try both APIs
            ds_result = await self.get_pal_price_dexscreener("PAL")
            ps_result = await self.get_pal_price_pancakeswap()
            
            # If we got a price from either source
            if ds_result and ds_result.get("price"):
                price = ds_result["price"]
                source = "DexScreener"
            elif ps_result and ps_result.get("price"):
                price = ps_result["price"]
                source = "PancakeSwap"
            else:
                # No price found, show helpful message
                embed = discord.Embed(
                    title="💰 PAL Price",
                    description="**Price data temporarily unavailable from APIs**\n\n" +
                               "PAL is actively trading but not accessible via price APIs right now.",
                    color=discord.Color.orange()
                )
                embed.add_field(
                    name="📊 View Live Price", 
                    value=f"[DexScreener Chart](https://dexscreener.com/bsc/{PAL_PAIR})",
                    inline=False
                )
                embed.add_field(
                    name="🔄 Alternative",
                    value="Try `/price WBNB` to test if price feeds are working",
                    inline=False
                )
                embed.set_footer(text="This is a known issue with low-volume tokens on DexScreener API")
                return await interaction.followup.send(embed=embed)
            
            # Format price
            try:
                price_float = float(price)
                if price_float < 0.01:
                    price_text = f"${price_float:.8f}"
                else:
                    price_text = f"${price_float:.4f}"
            except:
                price_text = f"${price}"
            
            embed = discord.Embed(
                title="💰 PAL Price",
                description=f"**{price_text}**",
                color=discord.Color.green()
            )
            embed.add_field(
                name="📊 Chart",
                value=f"[View on DexScreener](https://dexscreener.com/bsc/{PAL_PAIR})",
                inline=True
            )
            embed.set_footer(text=f"Source: {source}")
            
        else:
            # Handle other tokens
            result = await self.get_pal_price_dexscreener(token)
            if not result or not result.get("price"):
                embed = discord.Embed(
                    title="❌ Token Not Found",
                    description=f"No price data found for `{token}`\n\n" +
                               "**Try:**\n" +
                               "• Full contract address (0x...)\n" +
                               "• Different token symbol\n" +
                               "• `/price PAL` for our main token",
                    color=discord.Color.red()
                )
                return await interaction.followup.send(embed=embed)
            
            price = result["price"]
            try:
                price_float = float(price)
                if price_float < 0.01:
                    price_text = f"${price_float:.8f}"
                else:
                    price_text = f"${price_float:.4f}"
            except:
                price_text = f"${price}"
            
            embed = discord.Embed(
                title=f"💰 {token.upper()} Price",
                description=f"**{price_text}**",
                color=discord.Color.green()
            )
            embed.set_footer(text="Source: DexScreener")
        
        await interaction.followup.send(embed=embed)

    @GUILD_DEC  
    @app_commands.command(name="price_debug", description="Debug token price lookup")
    @app_commands.describe(token="Token to debug")
    async def price_debug(self, interaction: discord.Interaction, token: str = "PAL"):
        await interaction.response.defer()
        
        embed = discord.Embed(title=f"🔍 Debug: {token}", color=discord.Color.blue())
        embed.add_field(name="PAL Token Address", value=PAL_TOKEN, inline=False)
        embed.add_field(name="PAL Pair Address", value=PAL_PAIR, inline=False)
        embed.add_field(name="Chain", value=CHAIN, inline=False)
        
        # Test both APIs for PAL
        if token.upper() == "PAL":
            ds_result = await self.get_pal_price_dexscreener(token)
            ps_result = await self.get_pal_price_pancakeswap()
            
            embed.add_field(
                name="DexScreener API", 
                value="✅ Found" if ds_result else "❌ No data",
                inline=True
            )
            embed.add_field(
                name="PancakeSwap API", 
                value="✅ Found" if ps_result else "❌ No data",
                inline=True
            )
        
        embed.add_field(
            name="📊 Manual Check", 
            value=f"[DexScreener Website](https://dexscreener.com/bsc/{PAL_PAIR})",
            inline=False
        )
        embed.add_field(
            name="💡 Tip",
            value="Low volume tokens often don't appear in APIs even when trading",
            inline=False
        )
        
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Market(bot))
