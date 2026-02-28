"""
Bot Configurations - All paper trading bot strategies

Series 1: Fixed-Minute Bots (14 bots)
    - Each focuses on ONE specific minute
    - Only bets when edge is positive at their minute

Series 2: Dynamic Edge Bots
    - Wait for X minutes, then bet when edge >= threshold
    - Multiple variations with different thresholds

Series 3: Sentiment Bots
    - Bet with the crowd (direction Kalshi implies)
    - Test various entry criteria based on market odds
"""

try:
    from persistence_odds import PERSISTENCE_BY_MINUTE
except ImportError:
    from config.persistence_odds import PERSISTENCE_BY_MINUTE

# =============================================================================
# FEE CONFIGURATION
# =============================================================================

KALSHI_FEE_RATE = 0.07  # 7% fee on expected profit
POLYMARKET_FEE_RATE = 0.0156  # 1.56% max on 15-min crypto

def kalshi_fee(price_cents):
    """Calculate Kalshi fee for a given price"""
    if price_cents <= 0 or price_cents >= 100:
        return 0
    p = price_cents / 100
    return KALSHI_FEE_RATE * p * (1 - p) * 100  # Returns fee in cents

def polymarket_fee(price_cents):
    """Calculate Polymarket fee for a given price"""
    if price_cents <= 0 or price_cents >= 100:
        return 0
    p = price_cents / 100
    # Polymarket uses similar formula but lower rate
    return POLYMARKET_FEE_RATE * p * (1 - p) * 100

# =============================================================================
# SERIES 1: FIXED-MINUTE BOTS
# =============================================================================
# Each bot focuses on exactly ONE minute checkpoint
# Only enters if:
#   1. We're at their target minute
#   2. There's positive edge (price < breakeven)
#   3. Market is open for trading

FIXED_MINUTE_BOTS = {}
for minute in range(1, 14):  # Minutes 1-13 (skip 0, too risky; skip 14, no time)
    mins_left, persistence, max_losses = PERSISTENCE_BY_MINUTE[minute]
    FIXED_MINUTE_BOTS[f"fixed_min_{minute}"] = {
        "name": f"Fixed Minute {minute}",
        "description": f"Only bets at minute {minute} ({mins_left} min left). Persistence: {persistence*100:.1f}%",
        "target_minute": minute,
        "mins_left": mins_left,
        "true_probability": persistence,
        "max_price_cents": int(persistence * 100 * 0.95),  # 5% buffer below breakeven
        "min_edge": 0.03,  # At least 3% edge required
        "starting_bankroll": 1000,
        "bet_size": 10,  # $10 flat bet
    }

# =============================================================================
# SERIES 2: DYNAMIC EDGE BOTS
# =============================================================================
# Wait for X minutes to pass, then look for edge >= threshold
# More sophisticated - can enter at any minute after minimum wait

DYNAMIC_EDGE_BOTS = {}

# Variations: wait 2, 3, 4, 5 minutes before looking
for wait_minutes in [2, 3, 4, 5]:
    # At each wait time, test different edge thresholds
    for edge_pct in [5, 10, 12, 15, 20, 25, 30, 40]:
        edge = edge_pct / 100
        bot_id = f"dynamic_wait{wait_minutes}_edge{edge_pct}"
        DYNAMIC_EDGE_BOTS[bot_id] = {
            "name": f"Dynamic Wait {wait_minutes}m, Edge {edge_pct}%",
            "description": f"Waits {wait_minutes} min, then enters when edge >= {edge_pct}%",
            "min_wait_minutes": wait_minutes,
            "min_edge": edge,
            "starting_bankroll": 1000,
            "bet_size": 10,
        }

# Special dynamic bots: scale bet size with edge
DYNAMIC_EDGE_BOTS["dynamic_scaled_wait3"] = {
    "name": "Dynamic Scaled (Wait 3m)",
    "description": "Waits 3 min, scales bet size with edge (more edge = bigger bet)",
    "min_wait_minutes": 3,
    "min_edge": 0.05,
    "scale_with_edge": True,
    "base_bet_size": 10,
    "max_bet_size": 50,
    "starting_bankroll": 1000,
}

DYNAMIC_EDGE_BOTS["dynamic_scaled_wait5"] = {
    "name": "Dynamic Scaled (Wait 5m)",
    "description": "Waits 5 min, scales bet size with edge",
    "min_wait_minutes": 5,
    "min_edge": 0.10,
    "scale_with_edge": True,
    "base_bet_size": 10,
    "max_bet_size": 50,
    "starting_bankroll": 1000,
}

# =============================================================================
# SERIES 3: SENTIMENT BOTS
# =============================================================================
# These bots ignore our persistence curve entirely
# Instead, they bet WITH the crowd (whatever direction Kalshi implies)
# Question: Does following market sentiment work?

SENTIMENT_BOTS = {}

# Variations: enter when market odds hit X threshold
for odds_threshold in [55, 60, 65, 70, 75, 80, 85, 90, 95]:
    for min_wait in [0, 1, 2, 3, 5, 7, 10]:
        bot_id = f"sentiment_odds{odds_threshold}_wait{min_wait}"
        SENTIMENT_BOTS[bot_id] = {
            "name": f"Sentiment {odds_threshold}c (Wait {min_wait}m)",
            "description": f"Bets WITH the favorite when YES/NO hits {odds_threshold}c, after {min_wait} min",
            "odds_threshold": odds_threshold,
            "min_wait_minutes": min_wait,
            "starting_bankroll": 1000,
            "bet_size": 10,
        }

# Special: always bet the favorite at any time
SENTIMENT_BOTS["sentiment_always_favorite"] = {
    "name": "Always Favorite",
    "description": "Always bets the favored side regardless of time or odds",
    "odds_threshold": 51,  # Just needs to be > 50
    "min_wait_minutes": 0,
    "starting_bankroll": 1000,
    "bet_size": 10,
}

# =============================================================================
# ALL BOTS COMBINED
# =============================================================================

ALL_BOTS = {
    **{f"s1_{k}": v for k, v in FIXED_MINUTE_BOTS.items()},
    **{f"s2_{k}": v for k, v in DYNAMIC_EDGE_BOTS.items()},
    **{f"s3_{k}": v for k, v in SENTIMENT_BOTS.items()},
}

def get_bot_count():
    """Get total number of bots configured"""
    return len(ALL_BOTS)

def get_bots_by_series(series):
    """Get bots for a specific series (1, 2, or 3)"""
    prefix = f"s{series}_"
    return {k: v for k, v in ALL_BOTS.items() if k.startswith(prefix)}

# Print summary when imported
if __name__ == "__main__":
    print(f"Series 1 (Fixed-Minute): {len(FIXED_MINUTE_BOTS)} bots")
    print(f"Series 2 (Dynamic Edge): {len(DYNAMIC_EDGE_BOTS)} bots")
    print(f"Series 3 (Sentiment): {len(SENTIMENT_BOTS)} bots")
    print(f"TOTAL: {get_bot_count()} bots")
