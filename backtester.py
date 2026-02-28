#!/usr/bin/env python3
"""
Comprehensive Backtester for 15-Minute BTC Strategy

Runs all bot strategies against historical tick data.
Tests with ACTUAL Kalshi prices to determine viability.

Usage:
    python backtester.py [--data-path PATH] [--output-dir PATH]
"""

import os
import sys
import csv
import json
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

# Add config to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'config'))
from persistence_odds import (
    PERSISTENCE_BY_MINUTE,
    calculate_edge,
    get_persistence_rate,
)
from bot_configs import (
    ALL_BOTS,
    FIXED_MINUTE_BOTS,
    DYNAMIC_EDGE_BOTS,
    SENTIMENT_BOTS,
    kalshi_fee,
    get_bot_count,
)

# =============================================================================
# DATA LOADING
# =============================================================================

def load_tick_data(filepath: str) -> List[dict]:
    """Load second-by-second tick data"""
    ticks = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip rows with zero BTC price (scraper was broken)
            btc_price = float(row.get('btc_price', 0) or 0)
            if btc_price == 0:
                continue

            # Skip rows with zero strike (window not properly initialized)
            strike = float(row.get('strike_price', 0) or 0)
            if strike == 0:
                continue

            ticks.append({
                'timestamp': row.get('timestamp_utc') or row.get('timestamp'),
                'window_id': row.get('window_id'),
                'ticker': row.get('ticker'),
                'strike_price': strike,
                'secs_left': float(row.get('secs_left', 0) or 0),
                'mins_left': float(row.get('mins_left', 0) or 0),
                'btc_price': btc_price,
                'btc_vs_strike': row.get('btc_vs_strike'),
                'yes_ask': int(row.get('yes_ask', 0) or 0),
                'yes_bid': int(row.get('yes_bid', 0) or 0),
                'no_ask': int(row.get('no_ask', 0) or 0),
                'no_bid': int(row.get('no_bid', 0) or 0),
                'spread': int(row.get('spread', 0) or 0),
            })
    return ticks

def load_window_results(filepath: str) -> Dict[str, dict]:
    """Load window settlement results"""
    results = {}
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            window_id = row.get('window_id')
            if window_id:
                results[window_id] = {
                    'result': row.get('result', '').lower(),  # 'yes' or 'no'
                    'result_direction': row.get('result_direction'),  # 'UP' or 'DOWN'
                    'strike_price': float(row.get('strike_price', 0) or 0),
                }
    return results

def group_ticks_by_window(ticks: List[dict]) -> Dict[str, List[dict]]:
    """Group ticks by window_id"""
    windows = defaultdict(list)
    for tick in ticks:
        windows[tick['window_id']].append(tick)
    # Sort ticks within each window by time
    for window_id in windows:
        windows[window_id].sort(key=lambda x: x['secs_left'], reverse=True)
    return dict(windows)

# =============================================================================
# BOT STATE MANAGEMENT
# =============================================================================

class BotState:
    """Track state for a single bot across all windows"""

    def __init__(self, bot_id: str, config: dict):
        self.bot_id = bot_id
        self.config = config
        self.bankroll = config.get('starting_bankroll', 1000)
        self.initial_bankroll = self.bankroll
        self.trades: List[dict] = []
        self.wins = 0
        self.losses = 0
        self.total_wagered = 0
        self.total_fees = 0
        self.current_streak = 0
        self.max_win_streak = 0
        self.max_loss_streak = 0
        self.pending_trade: Optional[dict] = None

    def should_enter(self, tick: dict, window_result: Optional[dict]) -> Tuple[bool, Optional[dict]]:
        """Determine if bot should enter a trade on this tick"""
        raise NotImplementedError("Subclasses must implement")

    def execute_trade(self, tick: dict, direction: str, price_cents: int, bet_size: float):
        """Record a trade entry"""
        fee = kalshi_fee(price_cents)
        contracts = int(bet_size / (price_cents / 100))

        self.pending_trade = {
            'timestamp': tick['timestamp'],
            'window_id': tick['window_id'],
            'ticker': tick.get('ticker'),
            'strike': tick['strike_price'],
            'btc_price': tick['btc_price'],
            'mins_left': tick['mins_left'],
            'direction': direction,  # 'YES' or 'NO'
            'entry_price': price_cents,
            'contracts': contracts,
            'bet_size': bet_size,
            'fee': fee * contracts / 100,
        }
        self.total_wagered += bet_size

    def settle_trade(self, result: str):
        """Settle the pending trade based on window result"""
        if not self.pending_trade:
            return

        trade = self.pending_trade
        won = (trade['direction'].lower() == result.lower())

        if won:
            profit = trade['contracts'] - trade['bet_size'] - trade['fee']
            self.wins += 1
            self.current_streak = max(0, self.current_streak) + 1
            self.max_win_streak = max(self.max_win_streak, self.current_streak)
        else:
            profit = -trade['bet_size'] - trade['fee']
            self.losses += 1
            self.current_streak = min(0, self.current_streak) - 1
            self.max_loss_streak = max(self.max_loss_streak, abs(self.current_streak))

        self.bankroll += profit
        self.total_fees += trade['fee']

        trade['outcome'] = 'win' if won else 'loss'
        trade['profit'] = profit
        trade['bankroll_after'] = self.bankroll
        self.trades.append(trade)
        self.pending_trade = None

    def get_stats(self) -> dict:
        """Get summary statistics for this bot"""
        total_trades = self.wins + self.losses
        return {
            'bot_id': self.bot_id,
            'name': self.config.get('name', self.bot_id),
            'description': self.config.get('description', ''),
            'total_trades': total_trades,
            'wins': self.wins,
            'losses': self.losses,
            'win_rate': self.wins / total_trades * 100 if total_trades > 0 else 0,
            'initial_bankroll': self.initial_bankroll,
            'final_bankroll': self.bankroll,
            'total_profit': self.bankroll - self.initial_bankroll,
            'roi': (self.bankroll - self.initial_bankroll) / self.initial_bankroll * 100,
            'total_wagered': self.total_wagered,
            'total_fees': self.total_fees,
            'max_win_streak': self.max_win_streak,
            'max_loss_streak': self.max_loss_streak,
        }

# =============================================================================
# BOT IMPLEMENTATIONS
# =============================================================================

class FixedMinuteBot(BotState):
    """Series 1: Only bets at a specific minute"""

    def should_enter(self, tick: dict, window_result: Optional[dict]) -> Tuple[bool, Optional[dict]]:
        if self.pending_trade:
            return False, None

        target_minute = self.config['target_minute']
        mins_left = tick['mins_left']
        target_mins_left = 14 - target_minute

        # Check if we're at the target minute (within 30 sec window)
        if not (target_mins_left - 0.5 <= mins_left <= target_mins_left + 0.5):
            return False, None

        # Check if market is tradeable
        btc_price = tick['btc_price']
        strike = tick['strike_price']
        is_above = btc_price > strike

        # Determine which side to bet
        if is_above:
            # BTC is above strike - bet YES (betting it stays above)
            price = tick['yes_ask']
            direction = 'YES'
        else:
            # BTC is below strike - bet NO (betting it stays below)
            price = tick['no_ask']
            direction = 'NO'

        # Skip if no price available (market closed)
        if price == 0 or price >= 100:
            return False, None

        # Calculate edge
        true_prob = self.config['true_probability']
        implied_prob = price / 100
        edge = true_prob - implied_prob

        # Check minimum edge requirement
        min_edge = self.config.get('min_edge', 0)
        if edge < min_edge:
            return False, None

        # Check max price
        max_price = self.config.get('max_price_cents', 100)
        if price > max_price:
            return False, None

        return True, {
            'direction': direction,
            'price': price,
            'edge': edge,
        }

class DynamicEdgeBot(BotState):
    """Series 2: Waits for minimum time, then looks for edge threshold"""

    def should_enter(self, tick: dict, window_result: Optional[dict]) -> Tuple[bool, Optional[dict]]:
        if self.pending_trade:
            return False, None

        mins_left = tick['mins_left']
        min_wait = self.config['min_wait_minutes']

        # Check if enough time has passed
        # min_wait=2 means we need to wait until 12 minutes left (minute 2 of window)
        if mins_left > (14 - min_wait):
            return False, None

        # Don't enter with less than 1 minute left
        if mins_left < 1:
            return False, None

        # Determine current minute in window
        current_minute = int(14 - mins_left)
        if current_minute < 1 or current_minute > 13:
            return False, None

        # Get true probability for current minute
        true_prob = get_persistence_rate(current_minute)
        if true_prob is None:
            return False, None

        # Determine direction and price
        btc_price = tick['btc_price']
        strike = tick['strike_price']
        is_above = btc_price > strike

        if is_above:
            price = tick['yes_ask']
            direction = 'YES'
        else:
            price = tick['no_ask']
            direction = 'NO'

        if price == 0 or price >= 100:
            return False, None

        # Calculate edge
        implied_prob = price / 100
        edge = true_prob - implied_prob

        # Check edge threshold
        min_edge = self.config['min_edge']
        if edge < min_edge:
            return False, None

        return True, {
            'direction': direction,
            'price': price,
            'edge': edge,
        }

class SentimentBot(BotState):
    """Series 3: Bets with the crowd based on market odds"""

    def should_enter(self, tick: dict, window_result: Optional[dict]) -> Tuple[bool, Optional[dict]]:
        if self.pending_trade:
            return False, None

        mins_left = tick['mins_left']
        min_wait = self.config['min_wait_minutes']

        # Check if enough time has passed
        if mins_left > (14 - min_wait):
            return False, None

        if mins_left < 0.5:  # Don't enter too close to expiry
            return False, None

        # Get market odds
        yes_price = tick['yes_ask']
        no_price = tick['no_ask']

        if yes_price == 0 or no_price == 0:
            return False, None

        # Find the favorite (higher priced side is the market's expected winner)
        # If YES is 70c, market thinks 70% chance price ends ABOVE strike
        # If NO is 70c, market thinks 70% chance price ends BELOW strike

        threshold = self.config['odds_threshold']

        # Bet on whichever side the market favors
        if yes_price >= threshold:
            # Market favors YES (above strike)
            direction = 'YES'
            price = yes_price
        elif no_price >= threshold:
            # Market favors NO (below strike)
            direction = 'NO'
            price = no_price
        else:
            # Neither side hits threshold
            return False, None

        if price >= 100:
            return False, None

        return True, {
            'direction': direction,
            'price': price,
            'edge': None,  # Sentiment bots don't calculate edge
        }

# =============================================================================
# BACKTESTER ENGINE
# =============================================================================

def create_bot(bot_id: str, config: dict) -> BotState:
    """Factory function to create appropriate bot type"""
    if bot_id.startswith('s1_'):
        return FixedMinuteBot(bot_id, config)
    elif bot_id.startswith('s2_'):
        return DynamicEdgeBot(bot_id, config)
    elif bot_id.startswith('s3_'):
        return SentimentBot(bot_id, config)
    else:
        raise ValueError(f"Unknown bot type: {bot_id}")

def run_backtest(
    tick_data_path: str,
    results_path: str,
    output_dir: str = "results"
) -> dict:
    """
    Run backtest with all bots against historical data

    Returns dict with summary results
    """
    print("=" * 70)
    print("15-MINUTE BTC STRATEGY BACKTESTER")
    print("=" * 70)

    # Load data
    print(f"\nLoading tick data from: {tick_data_path}")
    ticks = load_tick_data(tick_data_path)
    print(f"Loaded {len(ticks):,} ticks")

    print(f"\nLoading window results from: {results_path}")
    window_results = load_window_results(results_path)
    print(f"Loaded {len(window_results)} window results")

    # Group ticks by window
    windows = group_ticks_by_window(ticks)
    print(f"Found {len(windows)} unique windows")

    # Initialize all bots
    print(f"\nInitializing {get_bot_count()} bots...")
    bots = {bot_id: create_bot(bot_id, config) for bot_id, config in ALL_BOTS.items()}

    # Run simulation
    print("\nRunning simulation...")
    windows_processed = 0
    windows_with_trades = 0

    for window_id, window_ticks in windows.items():
        result = window_results.get(window_id)
        if not result:
            continue  # Skip windows without settlement data

        windows_processed += 1
        any_trades = False

        # Process each tick in the window
        for tick in window_ticks:
            # Check each bot
            for bot_id, bot in bots.items():
                should_enter, trade_info = bot.should_enter(tick, result)
                if should_enter and trade_info:
                    bet_size = bot.config.get('bet_size', 10)

                    # Handle scaled betting
                    if bot.config.get('scale_with_edge') and trade_info.get('edge'):
                        edge = trade_info['edge']
                        base = bot.config.get('base_bet_size', 10)
                        max_bet = bot.config.get('max_bet_size', 50)
                        # Scale: 10% edge = base, 30% edge = max
                        scale = min(1, max(0, (edge - 0.10) / 0.20))
                        bet_size = base + scale * (max_bet - base)

                    bot.execute_trade(tick, trade_info['direction'], trade_info['price'], bet_size)
                    any_trades = True

        # Settle all pending trades for this window
        for bot in bots.values():
            if bot.pending_trade:
                bot.settle_trade(result['result'])

        if any_trades:
            windows_with_trades += 1

    # Generate results
    print(f"\nProcessed {windows_processed} windows, {windows_with_trades} had trades")

    # Compile statistics
    results = []
    for bot_id, bot in bots.items():
        stats = bot.get_stats()
        results.append(stats)

    # Sort by profit
    results.sort(key=lambda x: x['total_profit'], reverse=True)

    # Save results
    os.makedirs(output_dir, exist_ok=True)

    # Save detailed results as JSON
    json_path = os.path.join(output_dir, 'backtest_results.json')
    with open(json_path, 'w') as f:
        json.dump({
            'metadata': {
                'tick_data_path': tick_data_path,
                'results_path': results_path,
                'windows_processed': windows_processed,
                'windows_with_trades': windows_with_trades,
                'total_bots': len(bots),
                'run_timestamp': datetime.now().isoformat(),
            },
            'bot_results': results,
        }, f, indent=2)
    print(f"\nDetailed results saved to: {json_path}")

    # Save summary CSV
    csv_path = os.path.join(output_dir, 'backtest_summary.csv')
    with open(csv_path, 'w', newline='') as f:
        if results:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
    print(f"Summary CSV saved to: {csv_path}")

    # Print top performers
    print("\n" + "=" * 70)
    print("TOP 20 PERFORMERS")
    print("=" * 70)
    print(f"{'Bot ID':<40} {'Trades':>7} {'Win%':>7} {'Profit':>10} {'ROI':>8}")
    print("-" * 70)
    for stats in results[:20]:
        print(f"{stats['bot_id']:<40} {stats['total_trades']:>7} {stats['win_rate']:>6.1f}% ${stats['total_profit']:>9.2f} {stats['roi']:>7.1f}%")

    # Print worst performers
    print("\n" + "=" * 70)
    print("BOTTOM 10 PERFORMERS")
    print("=" * 70)
    for stats in results[-10:]:
        print(f"{stats['bot_id']:<40} {stats['total_trades']:>7} {stats['win_rate']:>6.1f}% ${stats['total_profit']:>9.2f} {stats['roi']:>7.1f}%")

    # Summary by series
    print("\n" + "=" * 70)
    print("SUMMARY BY SERIES")
    print("=" * 70)

    for series_name, prefix in [("Series 1 (Fixed-Minute)", "s1_"),
                                 ("Series 2 (Dynamic Edge)", "s2_"),
                                 ("Series 3 (Sentiment)", "s3_")]:
        series_bots = [r for r in results if r['bot_id'].startswith(prefix)]
        if series_bots:
            profitable = sum(1 for r in series_bots if r['total_profit'] > 0)
            avg_profit = sum(r['total_profit'] for r in series_bots) / len(series_bots)
            best = max(series_bots, key=lambda x: x['total_profit'])
            print(f"\n{series_name}:")
            print(f"  Bots: {len(series_bots)}, Profitable: {profitable} ({profitable/len(series_bots)*100:.0f}%)")
            print(f"  Avg Profit: ${avg_profit:.2f}")
            print(f"  Best: {best['bot_id']} (${best['total_profit']:.2f}, {best['win_rate']:.1f}% win rate)")

    return {
        'results': results,
        'windows_processed': windows_processed,
        'windows_with_trades': windows_with_trades,
    }

# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backtest 15-minute BTC strategy")
    parser.add_argument('--tick-data', default='../data-2-27-26/Kalshi - 15 Minute Scraper - Second By Second - tick_data.csv',
                        help='Path to tick data CSV')
    parser.add_argument('--results', default='../data-2-27-26/Kalshi - 15 Minute Scraper - Second By Second - window_results.csv',
                        help='Path to window results CSV')
    parser.add_argument('--output-dir', default='results', help='Output directory')

    args = parser.parse_args()

    run_backtest(args.tick_data, args.results, args.output_dir)
