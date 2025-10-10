import aiosqlite
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

@dataclass
class ReputationEntry:
    id: int
    from_user: int
    to_user: int
    guild_id: int
    points: int
    reason: str
    timestamp: datetime

@dataclass
class Achievement:
    id: str
    name: str
    description: str
    icon: str
    requirement: int
    category: str

class Reputation:
    def __init__(self, db_path: str = "data/pal_bot.sqlite"):
        self.db_path = db_path
        self.achievements = self._init_achievements()
        self.daily_limit = 5  # Max rep points per user per day

    def _init_achievements(self) -> List[Achievement]:
        """Initialize achievement system."""
        return [
            # Reputation achievements
            Achievement("first_rep", "First Impression", "Received your first reputation point", "⭐", 1, "reputation"),
            Achievement("rep_10", "Well Known", "Earned 10 reputation points", "🌟", 10, "reputation"),
            Achievement("rep_50", "Respected", "Earned 50 reputation points", "✨", 50, "reputation"),
            Achievement("rep_100", "Community Leader", "Earned 100 reputation points", "👑", 100, "reputation"),
            Achievement("rep_500", "Legend", "Earned 500 reputation points", "🏆", 500, "reputation"),
            
            # Giving achievements
            Achievement("helper", "Helper", "Gave 10 reputation points to others", "🤝", 10, "giving"),
            Achievement("mentor", "Mentor", "Gave 50 reputation points to others", "🎓", 50, "giving"),
            Achievement("community_builder", "Community Builder", "Gave 100 reputation points to others", "🏗️", 100, "giving"),
            
            # Special achievements
            Achievement("early_adopter", "Early Adopter", "One of the first 100 members", "🚀", 1, "special"),
            Achievement("diamond_hands", "Diamond Hands", "Held PAL tokens for 6 months", "💎", 1, "special"),
            Achievement("whale", "Whale", "Own over 10,000 PAL tokens", "🐋", 1, "special"),
            
            # Activity achievements
            Achievement("active_member", "Active Member", "Sent 100 messages", "💬", 100, "activity"),
            Achievement("super_active", "Super Active", "Sent 1000 messages", "🔥", 1000, "activity"),
            Achievement("no_life", "No Life", "Sent 10000 messages", "📱", 10000, "activity"),
        ]

    async def init(self):
        """Initialize reputation tables."""
        async with aiosqlite.connect(self.db_path) as db:
            # Reputation entries table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS reputation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_user_id INTEGER NOT NULL,
                    to_user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    points INTEGER NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(from_user_id, to_user_id, guild_id)
                )
            """)
            
            # User achievements table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_achievements (
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    achievement_id TEXT NOT NULL,
                    earned_at TEXT NOT NULL,
                    PRIMARY KEY (from_user_id, to_user_id, guild_id)
                )
            """)
            
            await db.commit()
            logging.info("Reputation: initialized")

    async def give_reputation(self, from_user: int, to_user: int, guild_id: int, 
                            points: int, reason: str = "") -> Dict:
        """Give reputation points to a user."""
        if from_user == to_user:
            return {'success': False, 'error': 'Cannot give reputation to yourself'}
        
        # Check daily limit
        today = datetime.now().date()
        daily_given = await self._get_daily_rep_given(from_user, guild_id, today)
        
        if daily_given >= self.daily_limit:
            return {'success': False, 'error': f'Daily reputation limit reached ({self.daily_limit})'}
        
        # Check if already gave rep to this user today
        if await self._gave_rep_today(from_user, to_user, guild_id):
            return {'success': False, 'error': 'Already gave reputation to this user today'}
        
        # Add reputation entry
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO reputation (from_user_id, to_user_id, guild_id, points, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (from_user, to_user, guild_id, points, reason, datetime.now().isoformat()))
            await db.commit()
        
        # Check for new achievements
        new_achievements = await self._check_achievements(to_user, guild_id)
        
        return {
            'success': True, 
            'new_achievements': new_achievements,
            'remaining_daily': self.daily_limit - daily_given - 1
        }

    async def get_user_reputation(self, user_id: int, guild_id: int) -> Dict:
        """Get user's reputation summary."""
        async with aiosqlite.connect(self.db_path) as db:
            # Total received reputation
            async with db.execute("""
                SELECT SUM(points), COUNT(*) FROM reputation
                WHERE to_user_id = ? AND guild_id = ?
            """, (user_id, guild_id)) as cursor:
                received_row = await cursor.fetchone()
                total_received = received_row[0] or 0
                received_count = received_row[1] or 0
            
            # Total given reputation
            async with db.execute("""
                SELECT SUM(points), COUNT(*) FROM reputation
                WHERE from_user_id = ? AND guild_id = ?
            """, (user_id, guild_id)) as cursor:
                given_row = await cursor.fetchone()
                total_given = given_row[0] or 0
                given_count = given_row[1] or 0
            
            # Recent reputation received
            async with db.execute("""
                SELECT from_user_id, points, reason, created_at FROM reputation
                WHERE to_user_id = ? AND guild_id = ?
                ORDER BY created_at DESC LIMIT 5
            """, (user_id, guild_id)) as cursor:
                recent_entries = await cursor.fetchall()
        
        # Get achievements
        achievements = await self.get_user_achievements(user_id, guild_id)
        
        return {
            'total_received': total_received,
            'total_given': total_given,
            'received_count': received_count,
            'given_count': given_count,
            'recent_entries': [
                {
                    'from_user': entry[0],
                    'points': entry[1],
                    'reason': entry[2],
                    'timestamp': entry[3]
                } for entry in recent_entries
            ],
            'achievements': achievements,
            'rank': await self._get_user_rank(user_id, guild_id)
        }

    async def get_leaderboard(self, guild_id: int, limit: int = 10) -> List[Dict]:
        """Get reputation leaderboard."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT to_user_id, SUM(points) as total_rep, COUNT(*) as rep_count
                FROM reputation WHERE guild_id = ?
                GROUP BY to_user_id
                ORDER BY total_rep DESC, rep_count DESC
                LIMIT ?
            """, (guild_id, limit)) as cursor:
                rows = await cursor.fetchall()
                
        leaderboard = []
        for i, row in enumerate(rows, 1):
            user_id, total_rep, rep_count = row
            achievements = await self.get_user_achievements(user_id, guild_id)
            
            leaderboard.append({
                'rank': i,
                'user_id': user_id,
                'total_reputation': total_rep,
                'reputation_count': rep_count,
                'achievement_count': len(achievements)
            })
        
        return leaderboard

    async def get_user_achievements(self, user_id: int, guild_id: int) -> List[Dict]:
        """Get user's earned achievements."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT achievement_id, earned_at FROM user_achievements
                WHERE user_id = ? AND guild_id = ?
                ORDER BY earned_at DESC
            """, (user_id, guild_id)) as cursor:
                earned_achievements = await cursor.fetchall()
        
        user_achievements = []
        for achievement_id, earned_at in earned_achievements:
            achievement = next((a for a in self.achievements if a.id == achievement_id), None)
            if achievement:
                user_achievements.append({
                    'id': achievement.id,
                    'name': achievement.name,
                    'description': achievement.description,
                    'icon': achievement.icon,
                    'category': achievement.category,
                    'earned_at': earned_at
                })
        
        return user_achievements

    async def _check_achievements(self, user_id: int, guild_id: int) -> List[Achievement]:
        """Check for new achievements and award them."""
        new_achievements = []
        user_stats = await self.get_user_reputation(user_id, guild_id)
        
        # Check reputation achievements
        rep_milestones = [
            ("first_rep", 1),
            ("rep_10", 10),
            ("rep_50", 50), 
            ("rep_100", 100),
            ("rep_500", 500)
        ]
        
        for achievement_id, threshold in rep_milestones:
            if (user_stats['total_received'] >= threshold and 
                not await self._has_achievement(user_id, guild_id, achievement_id)):
                
                await self._award_achievement(user_id, guild_id, achievement_id)
                achievement = next(a for a in self.achievements if a.id == achievement_id)
                new_achievements.append(achievement)
        
        # Check giving achievements
        giving_milestones = [
            ("helper", 10),
            ("mentor", 50),
            ("community_builder", 100)
        ]
        
        for achievement_id, threshold in giving_milestones:
            if (user_stats['total_given'] >= threshold and
                not await self._has_achievement(user_id, guild_id, achievement_id)):
                
                await self._award_achievement(user_id, guild_id, achievement_id)
                achievement = next(a for a in self.achievements if a.id == achievement_id)
                new_achievements.append(achievement)
        
        return new_achievements

    async def _has_achievement(self, user_id: int, guild_id: int, achievement_id: str) -> bool:
        """Check if user already has an achievement."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT 1 FROM user_achievements
                WHERE user_id = ? AND guild_id = ? AND achievement_id = ?
            """, (user_id, guild_id, achievement_id)) as cursor:
                return await cursor.fetchone() is not None

    async def _award_achievement(self, user_id: int, guild_id: int, achievement_id: str):
        """Award an achievement to a user."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR IGNORE INTO user_achievements (user_id, guild_id, achievement_id, earned_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, guild_id, achievement_id, datetime.now().isoformat()))
            await db.commit()

    async def _get_daily_rep_given(self, user_id: int, guild_id: int, date) -> int:
        """Get reputation points given by user today."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT SUM(points) FROM reputation
                WHERE from_user_id = ? AND guild_id = ? AND DATE(created_at) = ?
            """, (user_id, guild_id, date.isoformat())) as cursor:
                result = await cursor.fetchone()
                return result[0] or 0

    async def _gave_rep_today(self, from_user: int, to_user: int, guild_id: int) -> bool:
        """Check if user already gave rep to target user today."""
        today = datetime.now().date()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT 1 FROM reputation
                WHERE from_user_id = ? AND to_user_id = ? AND guild_id = ? AND DATE(created_at) = ?
            """, (from_user, to_user, guild_id, today.isoformat())) as cursor:
                return await cursor.fetchone() is not None

    async def _get_user_rank(self, user_id: int, guild_id: int) -> int:
        """Get user's rank in the guild."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT COUNT(*) + 1 FROM (
                    SELECT to_user_id, SUM(points) as total_rep
                    FROM reputation WHERE guild_id = ?
                    GROUP BY to_user_id
                    HAVING total_rep > (
                        SELECT COALESCE(SUM(points), 0)
                        FROM reputation
                        WHERE to_user_id = ? AND guild_id = ?
                    )
                )
            """, (guild_id, user_id, guild_id)) as cursor:
                result = await cursor.fetchone()
                return result[0] or 1