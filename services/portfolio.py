import aiosqlite
import logging
from datetime import datetime
from typing import List, Dict, Optional

class Portfolio:
    def __init__(self, db_path: str = "data/pal_bot.sqlite"):
        self.db_path = db_path

    async def init(self):
        """Initialize portfolio table."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS portfolio (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    token_symbol TEXT NOT NULL,
                    amount REAL NOT NULL,
                    avg_buy_price REAL NOT NULL,
                    last_updated TEXT NOT NULL,
                    UNIQUE(user_id, guild_id, token_symbol)
                )
            """)
            await db.commit()
            logging.info("Portfolio: initialized")

    async def add_position(self, user_id: int, guild_id: int, token: str, amount: float, price: float):
        """Add or update a portfolio position."""
        async with aiosqlite.connect(self.db_path) as db:
            # Check if position exists
            async with db.execute("""
                SELECT amount, avg_buy_price FROM portfolio
                WHERE user_id = ? AND guild_id = ? AND token_symbol = ?
            """, (user_id, guild_id, token.upper())) as cursor:
                existing = await cursor.fetchone()
            
            if existing:
                # Update existing position (calculate new average)
                old_amount, old_avg = existing
                new_amount = old_amount + amount
                new_avg = ((old_amount * old_avg) + (amount * price)) / new_amount
                
                await db.execute("""
                    UPDATE portfolio SET amount = ?, avg_buy_price = ?, last_updated = ?
                    WHERE user_id = ? AND guild_id = ? AND token_symbol = ?
                """, (new_amount, new_avg, datetime.now().isoformat(), user_id, guild_id, token.upper()))
            else:
                # Create new position
                await db.execute("""
                    INSERT INTO portfolio (user_id, guild_id, token_symbol, amount, avg_buy_price, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (user_id, guild_id, token.upper(), amount, price, datetime.now().isoformat()))
            
            await db.commit()

    async def get_portfolio(self, user_id: int, guild_id: int) -> List[Dict]:
        """Get user's complete portfolio."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT token_symbol, amount, avg_buy_price, last_updated
                FROM portfolio WHERE user_id = ? AND guild_id = ?
                ORDER BY last_updated DESC
            """, (user_id, guild_id)) as cursor:
                rows = await cursor.fetchall()
                return [{
                    'token': row[0],
                    'amount': row[1],
                    'avg_price': row[2],
                    'last_updated': row[3]
                } for row in rows]

    async def calculate_pnl(self, user_id: int, guild_id: int, current_prices: Dict[str, float]) -> Dict:
        """Calculate profit/loss for user's portfolio."""
        portfolio = await self.get_portfolio(user_id, guild_id)
        total_invested = 0
        total_current = 0
        positions = []
        
        for position in portfolio:
            token = position['token']
            amount = position['amount']
            avg_price = position['avg_price']
            current_price = current_prices.get(token, 0)
            
            invested = amount * avg_price
            current_value = amount * current_price
            pnl = current_value - invested
            pnl_percent = (pnl / invested * 100) if invested > 0 else 0
            
            total_invested += invested
            total_current += current_value
            
            positions.append({
                'token': token,
                'amount': amount,
                'avg_price': avg_price,
                'current_price': current_price,
                'invested': invested,
                'current_value': current_value,
                'pnl': pnl,
                'pnl_percent': pnl_percent
            })
        
        total_pnl = total_current - total_invested
        total_pnl_percent = (total_pnl / total_invested * 100) if total_invested > 0 else 0
        
        return {
            'positions': positions,
            'total_invested': total_invested,
            'total_current': total_current,
            'total_pnl': total_pnl,
            'total_pnl_percent': total_pnl_percent
        }