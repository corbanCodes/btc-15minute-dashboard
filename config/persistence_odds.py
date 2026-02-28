"""
Persistence Odds - Proven from 5 years of BTC data (137,206 windows)

These are the TRUE probabilities that if BTC is above/below strike at minute X,
it will STAY that way at expiration.

Source: five-year-analysis/results/master_analysis.csv
"""

# Minute -> (mins_left, persistence_rate, max_consecutive_losses)
PERSISTENCE_BY_MINUTE = {
    0:  (14, 0.5012, 15),   # At window open - basically coin flip
    1:  (13, 0.5869, 14),   # 13 min left: 58.7% stays
    2:  (12, 0.6258, 14),   # 12 min left: 62.6% stays
    3:  (11, 0.6565, 9),    # 11 min left: 65.7% stays
    4:  (10, 0.6812, 10),   # 10 min left: 68.1% stays
    5:  (9, 0.7128, 10),    # 9 min left: 71.3% stays
    6:  (8, 0.7407, 11),    # 8 min left: 74.1% stays
    7:  (7, 0.7674, 8),     # 7 min left: 76.7% stays
    8:  (6, 0.7920, 8),     # 6 min left: 79.2% stays
    9:  (5, 0.8143, 6),     # 5 min left: 81.4% stays
    10: (4, 0.8408, 5),     # 4 min left: 84.1% stays
    11: (3, 0.8695, 5),     # 3 min left: 87.0% stays
    12: (2, 0.8992, 4),     # 2 min left: 89.9% stays
    13: (1, 0.9318, 4),     # 1 min left: 93.2% stays
    14: (0, 1.0000, 0),     # At close - always stays (trivial)
}

def get_persistence_rate(minute_in_window):
    """Get the probability that direction persists from this minute to close"""
    if minute_in_window not in PERSISTENCE_BY_MINUTE:
        return None
    return PERSISTENCE_BY_MINUTE[minute_in_window][1]

def get_mins_left(minute_in_window):
    """Get minutes remaining at this checkpoint"""
    if minute_in_window not in PERSISTENCE_BY_MINUTE:
        return None
    return PERSISTENCE_BY_MINUTE[minute_in_window][0]

def get_max_losses(minute_in_window):
    """Get the maximum consecutive losses observed at this entry point"""
    if minute_in_window not in PERSISTENCE_BY_MINUTE:
        return None
    return PERSISTENCE_BY_MINUTE[minute_in_window][2]

def calculate_edge(minute_in_window, market_price_cents):
    """
    Calculate edge: true probability - implied probability from market price

    Args:
        minute_in_window: 0-13 (which minute of the 15-min window)
        market_price_cents: price in cents (e.g., 65 = 65c = 65% implied)

    Returns:
        edge as decimal (0.10 = 10% edge)
    """
    true_prob = get_persistence_rate(minute_in_window)
    if true_prob is None:
        return None

    implied_prob = market_price_cents / 100
    return true_prob - implied_prob

def get_breakeven_price(minute_in_window, fee_rate=0.02):
    """
    Get the maximum price you can pay and still have positive expected value

    Args:
        minute_in_window: which minute checkpoint
        fee_rate: fee as decimal (0.02 = 2%)

    Returns:
        breakeven price in cents
    """
    true_prob = get_persistence_rate(minute_in_window)
    if true_prob is None:
        return None

    # After fees, need: true_prob * (100 - fee) > price * (1 + fee)
    # Simplified: breakeven = true_prob * 100 / (1 + fee)
    return int(true_prob * 100 / (1 + fee_rate))

# Convenience: edge thresholds
EDGE_THRESHOLDS = {
    'minimum': 0.05,      # 5% edge - barely worth it
    'decent': 0.10,       # 10% edge - reasonable
    'good': 0.15,         # 15% edge - solid opportunity
    'excellent': 0.20,    # 20% edge - great opportunity
    'amazing': 0.30,      # 30% edge - rare, take max position
}
