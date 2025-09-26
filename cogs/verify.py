import re, discord
from discord import app_commands
from discord.ext import commands
from services.storage import Storage

WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

class VerifyModal(discord.ui.Modal, title="Link your BSC wallet"):
    wallet = discord.ui.TextInput(label="Wallet Address (0x...)", min_length=42, max_length=42)

    def __init__(self, storage: Storage): 
        super().__init__()
        self.storage = storage

    async def on_submit(self, interaction: discord.Interaction):
        w = self.wallet.value.strip()
        if not WALLET_RE.match(w):
            return await interaction.response.send_message("That doesn't look like a valid 0x wallet.", ephemeral=True)
        await self.storage.upsert_wallet(interaction.user.id, w)
        await interaction.response.send_message(f"✅ Saved wallet `{w}`. (Verification pending.)", ephemeral=True)

class Verify(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.storage = Storage()

    async def cog_load(self):
        await self.storage.init()

    @app_commands.command(description="Link your BSC wallet for $PAL perks.")
    async def verifywallet(self, interaction: discord.Interaction):
        await interaction.response.send_modal(VerifyModal(self.storage))

    @app_commands.command(description="Check your linked wallet.")
    async def mywallet(self, interaction: discord.Interaction):
        row = await self.storage.get_wallet(interaction.user.id)
        if not row: 
            return await interaction.response.send_message("No wallet linked yet. Use /verifywallet.", ephemeral=True)
        wallet, verified = row
        await interaction.response.send_message(f"Wallet: `{wallet}` • Verified: {'Yes' if verified else 'No'}", ephemeral=True)

async def setup(bot): await bot.add_cog(Verify(bot))
