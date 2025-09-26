import os, aiohttp

DEX_BASE = "https://api.dexscreener.com/latest/dex/tokens"

async def get_token_price(session: aiohttp.ClientSession, token_address: str):
    url = f"{DEX_BASE}/{token_address}"
    async with session.get(url, timeout=20) as r:
        data = await r.json()
    # DexScreener returns list of pairs; pick the one on env chain if possible
    target_chain = os.getenv("DEXSCREENER_CHAIN", "").lower()
    pairs = data.get("pairs") or []
    if target_chain:
        pairs = [p for p in pairs if (p.get("chainId") or "").lower() == target_chain] or pairs
    if not pairs:
        return None
    p = pairs[0]
    return {
        "chain": p.get("chainId"),
        "dex": p.get("dexId"),
        "pairAddress": p.get("pairAddress"),
        "baseToken": p.get("baseToken", {}).get("symbol"),
        "quoteToken": p.get("quoteToken", {}).get("symbol"),
        "priceUsd": p.get("priceUsd"),
        "priceNative": p.get("priceNative"),
        "liquidityUsd": (p.get("liquidity") or {}).get("usd"),
        "fdv": p.get("fdv"),
        "volume24h": (p.get("volume") or {}).get("h24"),
        "url": p.get("url"),
    }
