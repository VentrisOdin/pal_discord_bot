import aiosqlite
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Optional
import aiohttp

class PriceAlerts:
    def __init__(self, db_path: str = "data/pal_bot.sqlite"):
        self.db_path = db_path
        self._session: aiohttp.ClientSession | None = None

    async def init(self):
        """Initialize price alerts table."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS price_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    token_symbol TEXT NOT NULL,
                    target_price REAL NOT NULL,
                    condition TEXT NOT NULL, -- 'above' or 'below'
                    created_at TEXT NOT NULL,
                    triggered BOOLEAN DEFAULT FALSE
                )
            """)
            await db.commit()
            logging.info("PriceAlerts: initialized")

    async def add_alert(self, user_id: int, guild_id: int, token: str, price: float, condition: str):
        """Add a price alert for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO price_alerts (user_id, guild_id, token_symbol, target_price, condition, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, guild_id, token.upper(), price, condition, datetime.now().isoformat()))
            await db.commit()

    async def get_user_alerts(self, user_id: int, guild_id: int) -> List[Dict]:
        """Get all active alerts for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT id, token_symbol, target_price, condition, created_at
                FROM price_alerts
                WHERE user_id = ? AND guild_id = ? AND triggered = FALSE
                ORDER BY created_at DESC
            """, (user_id, guild_id)) as cursor:
                rows = await cursor.fetchall()
                return [{
                    'id': row[0],
                    'token': row[1],
                    'price': row[2],
                    'condition': row[3],
                    'created': row[4]
                } for row in rows]

    async def check_alerts(self, current_prices: Dict[str, float]) -> List[Dict]:
        """Check all alerts against current prices."""
        triggered_alerts = []
        async with aiosqlite.connect(self.db_path) as db:
            for token, price in current_prices.items():
                # Get alerts for this token
                async with db.execute("""
                    SELECT id, user_id, guild_id, target_price, condition
                    FROM price_alerts
                    WHERE token_symbol = ? AND triggered = FALSE
                """, (token.upper(),)) as cursor:
                    alerts = await cursor.fetchall()
                
                for alert in alerts:
                    alert_id, user_id, guild_id, target_price, condition = alert
                    triggered = False
                    
                    if condition == 'above' and price >= target_price:
                        triggered = True
                    elif condition == 'below' and price <= target_price:
                        triggered = True
                    
                    if triggered:
                        # Mark as triggered
                        await db.execute("""
                            UPDATE price_alerts SET triggered = TRUE WHERE id = ?
                        """, (alert_id,))
                        
                        triggered_alerts.append({
                            'user_id': user_id,
                            'guild_id': guild_id,
                            'token': token,
                            'target_price': target_price,
                            'current_price': price,
                            'condition': condition
                        })
            
            await db.commit()
        
        return triggered_alerts

    async def remove_alert(self, alert_id: int, user_id: int) -> bool:
        """Remove a specific alert."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                DELETE FROM price_alerts WHERE id = ? AND user_id = ?
            """, (alert_id, user_id))
            await db.commit()
            return cursor.rowcount > 0