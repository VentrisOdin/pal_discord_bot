import aiohttp
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json
import re
from dataclasses import dataclass

@dataclass
class NewsArticle:
    title: str
    summary: str
    url: str
    source: str
    sentiment: str  # 'positive', 'negative', 'neutral'
    relevance_score: float
    published_at: datetime
    keywords: List[str]

class NewsAI:
    def __init__(self):
        self._session: aiohttp.ClientSession | None = None
        self.news_sources = {
            'crypto_news': 'https://cryptonews.net/api/v1/category/altcoin',
            'coindesk': 'https://www.coindesk.com/arc/outboundfeeds/rss/',
            'cointelegraph': 'https://cointelegraph.com/rss',
            'decrypt': 'https://decrypt.co/feed'
        }

    async def init(self):
        """Initialize the news AI service."""
        self._session = aiohttp.ClientSession()
        logging.info("NewsAI: initialized")

    async def close(self):
        """Clean up resources."""
        if self._session:
            await self._session.close()

    async def fetch_crypto_news(self, keywords: List[str] = None, limit: int = 10) -> List[NewsArticle]:
        """Fetch and analyze crypto news."""
        if not keywords:
            keywords = ['crypto', 'defi', 'blockchain', 'bitcoin', 'ethereum']
            
        all_articles = []
        
        # Simulate news fetching (replace with real RSS/API feeds)
        mock_articles = [
            {
                'title': 'DeFi Protocol Launches New Yield Farming Opportunities',
                'summary': 'A new DeFi protocol has launched innovative yield farming strategies with APYs up to 200%.',
                'url': 'https://example.com/defi-yield',
                'source': 'CryptoDeFi News',
                'published': datetime.now() - timedelta(hours=2)
            },
            {
                'title': 'Major Exchange Lists Promising Altcoin',
                'summary': 'Binance announces listing of a revolutionary new token focused on disaster prediction.',
                'url': 'https://example.com/altcoin-listing',
                'source': 'CoinTelegraph',
                'published': datetime.now() - timedelta(hours=6)
            },
            {
                'title': 'Blockchain Technology Helps Predict Natural Disasters',
                'summary': 'New research shows how blockchain and AI can improve disaster prediction accuracy by 40%.',
                'url': 'https://example.com/blockchain-disasters',
                'source': 'TechCrunch',
                'published': datetime.now() - timedelta(hours=12)
            }
        ]
        
        for article_data in mock_articles[:limit]:
            # Analyze sentiment (simplified - use real AI service in production)
            sentiment = self._analyze_sentiment(article_data['summary'])
            relevance = self._calculate_relevance(article_data['title'] + ' ' + article_data['summary'], keywords)
            article_keywords = self._extract_keywords(article_data['title'] + ' ' + article_data['summary'])
            
            article = NewsArticle(
                title=article_data['title'],
                summary=article_data['summary'],
                url=article_data['url'],
                source=article_data['source'],
                sentiment=sentiment,
                relevance_score=relevance,
                published_at=article_data['published'],
                keywords=article_keywords
            )
            
            all_articles.append(article)
        
        # Sort by relevance and recency
        all_articles.sort(key=lambda x: (x.relevance_score, x.published_at), reverse=True)
        return all_articles

    def _analyze_sentiment(self, text: str) -> str:
        """Simple sentiment analysis (replace with real AI in production)."""
        positive_words = ['bullish', 'pump', 'moon', 'gains', 'profit', 'surge', 'rally', 'breakthrough']
        negative_words = ['bearish', 'dump', 'crash', 'loss', 'decline', 'fall', 'scam', 'hack']
        
        text_lower = text.lower()
        positive_count = sum(1 for word in positive_words if word in text_lower)
        negative_count = sum(1 for word in negative_words if word in text_lower)
        
        if positive_count > negative_count:
            return 'positive'
        elif negative_count > positive_count:
            return 'negative'
        else:
            return 'neutral'

    def _calculate_relevance(self, text: str, keywords: List[str]) -> float:
        """Calculate relevance score based on keyword matching."""
        text_lower = text.lower()
        matches = sum(1 for keyword in keywords if keyword.lower() in text_lower)
        return min(matches / len(keywords), 1.0)

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract important keywords from text."""
        crypto_keywords = ['defi', 'nft', 'dao', 'yield', 'staking', 'bridge', 'swap', 'liquidity', 
                          'governance', 'tokenomics', 'airdrop', 'ido', 'dex', 'cefi']
        
        text_lower = text.lower()
        found_keywords = [kw for kw in crypto_keywords if kw in text_lower]
        return found_keywords[:5]  # Limit to top 5

    async def get_market_sentiment(self) -> Dict:
        """Analyze overall market sentiment."""
        articles = await self.fetch_crypto_news(limit=20)
        
        sentiment_counts = {'positive': 0, 'negative': 0, 'neutral': 0}
        for article in articles:
            sentiment_counts[article.sentiment] += 1
        
        total = len(articles)
        sentiment_percentages = {
            'positive': (sentiment_counts['positive'] / total * 100) if total > 0 else 0,
            'negative': (sentiment_counts['negative'] / total * 100) if total > 0 else 0,
            'neutral': (sentiment_counts['neutral'] / total * 100) if total > 0 else 0
        }
        
        # Determine overall sentiment
        if sentiment_percentages['positive'] > 50:
            overall = 'bullish'
        elif sentiment_percentages['negative'] > 50:
            overall = 'bearish'
        else:
            overall = 'neutral'
        
        return {
            'overall': overall,
            'percentages': sentiment_percentages,
            'article_count': total,
            'last_updated': datetime.now()
        }

    async def get_trending_topics(self) -> List[Dict]:
        """Get trending topics from recent news."""
        articles = await self.fetch_crypto_news(limit=30)
        
        keyword_counts = {}
        for article in articles:
            for keyword in article.keywords:
                keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1
        
        # Sort by frequency
        trending = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)
        
        return [
            {
                'topic': topic,
                'mentions': count,
                'trending_score': min(count / 5, 1.0)  # Normalize to 0-1
            }
            for topic, count in trending[:10]
        ]