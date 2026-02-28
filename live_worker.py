#!/usr/bin/env python3
"""
Live Multi-Bot Paper Trading Worker

Runs ALL bots simultaneously against live Kalshi data.
Reports results to Google Sheets in real-time.

Each bot gets its own tab + summary tab tracks all bots.
Bots can go negative (no busting) - just track the losses.

Usage:
    python live_worker.py [--sheets-id ID] [--no-sheets]
"""

import os
import sys
import time
import json
import requests
from datetime import datetime, timezone
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

# Add config to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'config'))
from persistence_odds import get_persistence_rate, calculate_edge
from bot_configs import (
    ALL_BOTS,
    FIXED_MINUTE_BOTS,
    DYNAMIC_EDGE_BOTS,
    SENTIMENT_BOTS,
    kalshi_fee,
    get_bot_count,
)

# =============================================================================
# CONFIGURATION
# =============================================================================

KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
SERIES_TICKER = "KXBTC15M"

# Kraken is closest to CF Benchmarks (what Kalshi likely uses for settlement)
KRAKEN_API = "https://api.kraken.com/0/public/Ticker"
# Binance.US as fallback (regular binance.com blocked in US)
BINANCE_US_API = "https://api.binance.us/api/v3/ticker/price"

# How often to log status (seconds)
STATUS_LOG_INTERVAL = 30
SHEETS_FLUSH_INTERVAL = 10  # Batch writes to sheets
STATE_FILE = 'bot_state.json'  # For web dashboard

# =============================================================================
# BOT STATE (Live Version)
# =============================================================================

class LiveBotState:
    """Track live state for a single bot"""

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
        self.traded_windows = set()  # Track which windows we've traded
        self.skipped_windows: List[dict] = []  # Track why we skipped windows
        self.last_skip_reason: str = None  # Most recent skip reason

    def get_series(self) -> str:
        if self.bot_id.startswith('s1_'):
            return 'fixed_minute'
        elif self.bot_id.startswith('s2_'):
            return 'dynamic_edge'
        elif self.bot_id.startswith('s3_'):
            return 'sentiment'
        return 'unknown'

    def get_stats(self) -> dict:
        total_trades = self.wins + self.losses
        return {
            'bot_id': self.bot_id,
            'name': self.config.get('name', self.bot_id),
            'series': self.get_series(),
            'total_trades': total_trades,
            'wins': self.wins,
            'losses': self.losses,
            'win_rate': self.wins / total_trades * 100 if total_trades > 0 else 0,
            'bankroll': self.bankroll,
            'total_profit': self.bankroll - self.initial_bankroll,
            'roi': (self.bankroll - self.initial_bankroll) / self.initial_bankroll * 100,
            'total_wagered': self.total_wagered,
            'total_fees': self.total_fees,
            'current_streak': self.current_streak,
            'max_win_streak': self.max_win_streak,
            'max_loss_streak': self.max_loss_streak,
            'pending': bool(self.pending_trade),
        }

# =============================================================================
# BOT LOGIC
# =============================================================================

def check_fixed_minute_entry(bot: LiveBotState, tick: dict) -> Optional[dict]:
    """Check if fixed-minute bot should enter. Returns trade_info or None with skip reason tracked."""
    window_id = tick['window_id']

    if bot.pending_trade:
        bot.last_skip_reason = "Already has pending trade"
        return None

    if window_id in bot.traded_windows:
        bot.last_skip_reason = "Already traded this window"
        return None

    target_minute = bot.config['target_minute']
    mins_left = tick['mins_left']
    target_mins_left = 14 - target_minute

    # Check if we're at the target minute (within 30 sec window)
    if not (target_mins_left - 0.5 <= mins_left <= target_mins_left + 0.5):
        current_min = int(14 - mins_left)
        bot.last_skip_reason = f"Waiting for minute {target_minute} (currently min {current_min})"
        return None

    btc_price = tick['btc_price']
    strike = tick['strike_price']
    is_above = btc_price > strike

    if is_above:
        price = tick['yes_ask']
        direction = 'YES'
    else:
        price = tick['no_ask']
        direction = 'NO'

    if price == 0:
        bot.last_skip_reason = f"No market price available ({direction} ask = 0)"
        return None

    if price >= 100:
        bot.last_skip_reason = f"Price too high ({direction} @ {price}c = 100%)"
        return None

    true_prob = bot.config['true_probability']
    implied_prob = price / 100
    edge = true_prob - implied_prob

    min_edge = bot.config.get('min_edge', 0)
    if edge < min_edge:
        bot.last_skip_reason = f"Edge too low ({edge*100:.1f}% < {min_edge*100:.1f}% min)"
        return None

    max_price = bot.config.get('max_price_cents', 100)
    if price > max_price:
        bot.last_skip_reason = f"Price exceeds max ({price}c > {max_price}c)"
        return None

    bot.last_skip_reason = None  # Clear - we're trading!
    return {'direction': direction, 'price': price, 'edge': edge}

def check_dynamic_edge_entry(bot: LiveBotState, tick: dict) -> Optional[dict]:
    """Check if dynamic edge bot should enter"""
    window_id = tick['window_id']

    if bot.pending_trade:
        bot.last_skip_reason = "Already has pending trade"
        return None

    if window_id in bot.traded_windows:
        bot.last_skip_reason = "Already traded this window"
        return None

    mins_left = tick['mins_left']
    min_wait = bot.config['min_wait_minutes']
    current_minute = int(14 - mins_left)

    if mins_left > (14 - min_wait):
        bot.last_skip_reason = f"Waiting {min_wait} min before entry (currently min {current_minute})"
        return None
    if mins_left < 1:
        bot.last_skip_reason = "Window ending (<1 min left)"
        return None

    if current_minute < 1 or current_minute > 13:
        bot.last_skip_reason = f"Invalid minute ({current_minute})"
        return None

    true_prob = get_persistence_rate(current_minute)
    if true_prob is None:
        bot.last_skip_reason = f"No persistence data for minute {current_minute}"
        return None

    btc_price = tick['btc_price']
    strike = tick['strike_price']
    is_above = btc_price > strike

    if is_above:
        price = tick['yes_ask']
        direction = 'YES'
    else:
        price = tick['no_ask']
        direction = 'NO'

    if price == 0:
        bot.last_skip_reason = f"No market price ({direction} ask = 0)"
        return None

    if price >= 100:
        bot.last_skip_reason = f"Price at 100% ({direction} @ {price}c)"
        return None

    implied_prob = price / 100
    edge = true_prob - implied_prob

    min_edge = bot.config['min_edge']
    if edge < min_edge:
        bot.last_skip_reason = f"Edge {edge*100:.1f}% < {min_edge*100:.1f}% threshold"
        return None

    bot.last_skip_reason = None
    return {'direction': direction, 'price': price, 'edge': edge}

def check_sentiment_entry(bot: LiveBotState, tick: dict) -> Optional[dict]:
    """Check if sentiment bot should enter"""
    window_id = tick['window_id']

    if bot.pending_trade:
        bot.last_skip_reason = "Already has pending trade"
        return None

    if window_id in bot.traded_windows:
        bot.last_skip_reason = "Already traded this window"
        return None

    mins_left = tick['mins_left']
    min_wait = bot.config['min_wait_minutes']
    current_minute = int(14 - mins_left)

    if mins_left > (14 - min_wait):
        bot.last_skip_reason = f"Waiting {min_wait} min (currently min {current_minute})"
        return None
    if mins_left < 0.5:
        bot.last_skip_reason = "Window ending (<30 sec left)"
        return None

    yes_price = tick['yes_ask']
    no_price = tick['no_ask']

    if yes_price == 0 or no_price == 0:
        bot.last_skip_reason = f"No market prices (YES={yes_price}c, NO={no_price}c)"
        return None

    threshold = bot.config['odds_threshold']

    if yes_price >= threshold:
        direction = 'YES'
        price = yes_price
    elif no_price >= threshold:
        direction = 'NO'
        price = no_price
    else:
        bot.last_skip_reason = f"No strong sentiment (YES={yes_price}c, NO={no_price}c < {threshold}c threshold)"
        return None

    if price >= 100:
        bot.last_skip_reason = f"Price at 100% ({direction} @ {price}c)"
        return None

    bot.last_skip_reason = None
    return {'direction': direction, 'price': price, 'edge': None}

def execute_trade(bot: LiveBotState, tick: dict, trade_info: dict):
    """Execute a paper trade for a bot"""
    direction = trade_info['direction']
    price = trade_info['price']

    bet_size = bot.config.get('bet_size', 10)

    # Handle scaled betting
    if bot.config.get('scale_with_edge') and trade_info.get('edge'):
        edge = trade_info['edge']
        base = bot.config.get('base_bet_size', 10)
        max_bet = bot.config.get('max_bet_size', 50)
        scale = min(1, max(0, (edge - 0.10) / 0.20))
        bet_size = base + scale * (max_bet - base)

    fee = kalshi_fee(price)
    contracts = int(bet_size / (price / 100))

    bot.pending_trade = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'window_id': tick['window_id'],
        'ticker': tick.get('ticker'),
        'strike': tick['strike_price'],
        'btc_price': tick['btc_price'],
        'mins_left': tick['mins_left'],
        'direction': direction,
        'entry_price': price,
        'contracts': contracts,
        'bet_size': bet_size,
        'fee': fee * contracts / 100,
        'edge': trade_info.get('edge'),
    }
    bot.total_wagered += bet_size
    bot.traded_windows.add(tick['window_id'])

def settle_trade(bot: LiveBotState, result: str):
    """Settle a bot's pending trade"""
    if not bot.pending_trade:
        return

    trade = bot.pending_trade
    won = (trade['direction'].lower() == result.lower())

    if won:
        profit = trade['contracts'] - trade['bet_size'] - trade['fee']
        bot.wins += 1
        bot.current_streak = max(0, bot.current_streak) + 1
        bot.max_win_streak = max(bot.max_win_streak, bot.current_streak)
    else:
        profit = -trade['bet_size'] - trade['fee']
        bot.losses += 1
        bot.current_streak = min(0, bot.current_streak) - 1
        bot.max_loss_streak = max(bot.max_loss_streak, abs(bot.current_streak))

    bot.bankroll += profit
    bot.total_fees += trade['fee']

    trade['outcome'] = 'win' if won else 'loss'
    trade['profit'] = profit
    trade['bankroll_after'] = bot.bankroll
    bot.trades.append(trade)
    bot.pending_trade = None

    return trade

# =============================================================================
# DATA FETCHING
# =============================================================================

def get_btc_price_kraken() -> Optional[float]:
    """Get BTC price from Kraken (closest to CF Benchmarks)"""
    try:
        resp = requests.get(KRAKEN_API, params={"pair": "XBTUSD"}, timeout=5)
        data = resp.json()
        # Kraken returns last trade price in 'c' field (first element)
        return float(data['result']['XXBTZUSD']['c'][0])
    except:
        return None

def get_btc_price_binance() -> Optional[float]:
    """Fallback: Get BTC price from Binance.US"""
    try:
        resp = requests.get(BINANCE_US_API, params={"symbol": "BTCUSD"}, timeout=5)
        return float(resp.json()['price'])
    except:
        return None

def get_btc_price() -> Optional[float]:
    """Try Kraken first, fallback to Binance.US"""
    price = get_btc_price_kraken()
    if price is None:
        price = get_btc_price_binance()
    return price

def api_get(endpoint: str, params: dict = None) -> Optional[dict]:
    """Make Kalshi API request"""
    try:
        resp = requests.get(f"{KALSHI_API}/{endpoint}", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except:
        return None

def get_active_market() -> Optional[dict]:
    """Get current active 15-minute market"""
    data = api_get("events", {"series_ticker": SERIES_TICKER, "status": "open"})
    if not data or not data.get('events'):
        return None
    event = data['events'][0]
    markets = api_get("markets", {"event_ticker": event['event_ticker']})
    if not markets or not markets.get('markets'):
        return None
    return markets['markets'][0]

def get_market_details(ticker: str) -> Optional[dict]:
    """Get detailed market info"""
    data = api_get(f"markets/{ticker}")
    return data.get('market') if data else None

def get_settled_markets(limit: int = 20) -> List[dict]:
    """Get recently settled markets"""
    data = api_get("markets", {"series_ticker": SERIES_TICKER, "status": "settled", "limit": limit})
    return data.get('markets', []) if data else []

def mins_until_close(close_time_str: str) -> Optional[float]:
    """Calculate minutes until market close"""
    if not close_time_str:
        return None
    try:
        close = datetime.fromisoformat(close_time_str.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        return (close - now).total_seconds() / 60
    except:
        return None

# =============================================================================
# GOOGLE SHEETS INTEGRATION
# =============================================================================

class SheetsReporter:
    """Report bot results to Google Sheets"""

    def __init__(self, spreadsheet_id: str = None):
        self.spreadsheet_id = spreadsheet_id
        self.enabled = spreadsheet_id is not None
        self.pending_updates = []
        self.last_flush = time.time()

        if self.enabled:
            try:
                import gspread
                from google.oauth2.service_account import Credentials

                scopes = ['https://spreadsheets.google.com/feeds',
                         'https://www.googleapis.com/auth/drive']

                creds = None

                # Try environment variable first (for Railway - JSON string)
                creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
                if creds_json:
                    import json as json_module
                    creds_dict = json_module.loads(creds_json)
                    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
                    print("Using credentials from GOOGLE_CREDENTIALS_JSON env var")

                # Fall back to file
                if not creds:
                    creds_file = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS',
                                                 'service_account.json')
                    if os.path.exists(creds_file):
                        creds = Credentials.from_service_account_file(creds_file, scopes=scopes)
                        print(f"Using credentials from file: {creds_file}")

                if creds:
                    self.gc = gspread.authorize(creds)
                    self.sheet = self.gc.open_by_key(spreadsheet_id)
                    print(f"Connected to Google Sheet: {self.sheet.title}")
                else:
                    print("No credentials found, sheets disabled")
                    self.enabled = False
            except Exception as e:
                print(f"Sheets setup failed: {e}")
                self.enabled = False

    def get_or_create_sheet(self, name: str):
        """Get worksheet by name, create if doesn't exist"""
        if not self.enabled:
            return None
        try:
            return self.sheet.worksheet(name)
        except:
            try:
                return self.sheet.add_worksheet(title=name, rows=1000, cols=20)
            except:
                return None

    def update_summary(self, bots: Dict[str, LiveBotState]):
        """Update the summary sheet with all bot stats"""
        if not self.enabled:
            return

        try:
            ws = self.get_or_create_sheet("Summary")
            if not ws:
                return

            # Headers
            headers = ['Bot ID', 'Series', 'Trades', 'Wins', 'Losses', 'Win%',
                      'Bankroll', 'Profit', 'ROI%', 'Streak', 'Pending']

            # Data rows
            rows = [headers]
            for bot_id, bot in sorted(bots.items()):
                stats = bot.get_stats()
                rows.append([
                    stats['bot_id'],
                    stats['series'],
                    stats['total_trades'],
                    stats['wins'],
                    stats['losses'],
                    f"{stats['win_rate']:.1f}",
                    f"{stats['bankroll']:.2f}",
                    f"{stats['total_profit']:.2f}",
                    f"{stats['roi']:.1f}",
                    stats['current_streak'],
                    'Yes' if stats['pending'] else 'No',
                ])

            ws.update('A1', rows)
        except Exception as e:
            print(f"Summary update failed: {e}")

    def log_trade(self, bot: LiveBotState, trade: dict):
        """Log a completed trade to the bot's sheet"""
        if not self.enabled:
            return

        try:
            # Create sheet name (max 100 chars)
            sheet_name = bot.bot_id[:50]
            ws = self.get_or_create_sheet(sheet_name)
            if not ws:
                return

            # Check if headers exist
            try:
                existing = ws.get_all_values()
                if not existing:
                    headers = ['Timestamp', 'Window', 'Strike', 'BTC Price', 'Direction',
                              'Entry Price', 'Edge%', 'Outcome', 'Profit', 'Bankroll']
                    ws.append_row(headers)
            except:
                pass

            # Append trade
            row = [
                trade['timestamp'],
                trade['window_id'],
                f"{trade['strike']:.2f}",
                f"{trade['btc_price']:.2f}",
                trade['direction'],
                trade['entry_price'],
                f"{trade.get('edge', 0) * 100:.1f}" if trade.get('edge') else 'N/A',
                trade['outcome'],
                f"{trade['profit']:.2f}",
                f"{trade['bankroll_after']:.2f}",
            ]
            ws.append_row(row)
        except Exception as e:
            print(f"Trade log failed: {e}")

# =============================================================================
# MAIN WORKER
# =============================================================================

class LiveWorker:
    """Main worker that runs all bots"""

    def __init__(self, sheets_id: str = None):
        self.bots: Dict[str, LiveBotState] = {}
        self.sheets = SheetsReporter(sheets_id)
        self.current_window = None
        self.settled_windows = set()
        self.last_status_log = 0
        self.start_time = datetime.now()

        # Initialize all bots
        for bot_id, config in ALL_BOTS.items():
            self.bots[bot_id] = LiveBotState(bot_id, config)

        print(f"Initialized {len(self.bots)} bots")

    def save_state(self):
        """Save current state to JSON for web dashboard"""
        state = {
            'last_update': datetime.now(timezone.utc).isoformat(),
            'windows_processed': len(self.settled_windows),
            'current_window': self.current_window,
            'runtime_seconds': (datetime.now() - self.start_time).total_seconds(),
            'bots': {}
        }

        for bot_id, bot in self.bots.items():
            stats = bot.get_stats()
            config = bot.config
            state['bots'][bot_id] = {
                'series': stats['series'],
                'name': config.get('name', bot_id),
                'description': config.get('description', ''),
                'trades': stats['total_trades'],
                'wins': stats['wins'],
                'losses': stats['losses'],
                'win_rate': stats['win_rate'],
                'bankroll': stats['bankroll'],
                'profit': stats['total_profit'],
                'roi': stats['roi'],
                'pending': stats['pending'],
                'total_wagered': stats['total_wagered'],
                'total_fees': stats['total_fees'],
                'current_streak': stats['current_streak'],
                'max_win_streak': stats['max_win_streak'],
                'max_loss_streak': stats['max_loss_streak'],
                'trade_history': bot.trades,  # Full trade history
                'pending_trade': bot.pending_trade,  # Current pending trade if any
                'last_skip_reason': bot.last_skip_reason,  # Why didn't it trade?
                # Config details for strategy summary
                'config': {
                    'target_minute': config.get('target_minute'),
                    'min_wait_minutes': config.get('min_wait_minutes'),
                    'min_edge': config.get('min_edge'),
                    'odds_threshold': config.get('odds_threshold'),
                    'true_probability': config.get('true_probability'),
                    'bet_size': config.get('bet_size', 10),
                    'scale_with_edge': config.get('scale_with_edge', False),
                },
            }

        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"Failed to save state: {e}")

    def log(self, msg: str):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

    def process_tick(self, tick: dict):
        """Process a tick for all bots"""
        for bot_id, bot in self.bots.items():
            trade_info = None

            if bot_id.startswith('s1_'):
                trade_info = check_fixed_minute_entry(bot, tick)
            elif bot_id.startswith('s2_'):
                trade_info = check_dynamic_edge_entry(bot, tick)
            elif bot_id.startswith('s3_'):
                trade_info = check_sentiment_entry(bot, tick)

            if trade_info:
                execute_trade(bot, tick, trade_info)
                self.log(f"TRADE: {bot_id} -> {trade_info['direction']} @ {trade_info['price']}c")

    def settle_window(self, window_id: str, result: str):
        """Settle all pending trades for a window"""
        if window_id in self.settled_windows:
            return

        trades_settled = 0
        trades_to_log = []

        for bot_id, bot in self.bots.items():
            if bot.pending_trade and bot.pending_trade['window_id'] == window_id:
                trade = settle_trade(bot, result)
                if trade:
                    trades_settled += 1
                    trades_to_log.append((bot, trade))

        if trades_settled > 0:
            self.log(f"SETTLED: Window {window_id} -> {result.upper()} ({trades_settled} trades)")

            # Log trades with rate limiting (1 per second to avoid API limits)
            for i, (bot, trade) in enumerate(trades_to_log):
                self.sheets.log_trade(bot, trade)
                if i % 10 == 9:  # Pause every 10 trades
                    time.sleep(2)

            self.sheets.update_summary(self.bots)
            self.save_state()  # Update dashboard

        self.settled_windows.add(window_id)

    def print_status(self):
        """Print status summary"""
        now = time.time()
        if now - self.last_status_log < STATUS_LOG_INTERVAL:
            return
        self.last_status_log = now

        # Count stats
        total_trades = sum(b.wins + b.losses for b in self.bots.values())
        total_wins = sum(b.wins for b in self.bots.values())
        pending = sum(1 for b in self.bots.values() if b.pending_trade)
        total_profit = sum(b.bankroll - b.initial_bankroll for b in self.bots.values())

        win_rate = total_wins / total_trades * 100 if total_trades > 0 else 0
        runtime = datetime.now() - self.start_time

        self.log(f"STATUS: {total_trades} trades, {win_rate:.1f}% win rate, ${total_profit:.2f} total P/L, {pending} pending | Runtime: {runtime}")

        # Save state for dashboard on every status update
        self.save_state()

        # Update sheets every 5 minutes to avoid rate limits
        if int(runtime.total_seconds()) % 300 < STATUS_LOG_INTERVAL:
            self.sheets.update_summary(self.bots)

    def run(self):
        """Main loop"""
        print("=" * 70)
        print("LIVE MULTI-BOT PAPER TRADING WORKER")
        print("=" * 70)
        print(f"Bots: {len(self.bots)}")
        print(f"Sheets: {'Enabled' if self.sheets.enabled else 'Disabled'}")
        print("=" * 70 + "\n")

        while True:
            try:
                # Check for settlements
                settled = get_settled_markets()
                for market in settled:
                    ticker = market.get('ticker')
                    result = market.get('result')
                    if ticker and result:
                        # Extract window_id from ticker
                        # Format: KXBTC15M-26FEB271300-00 -> 26FEB271300
                        parts = ticker.split('-')
                        if len(parts) >= 2:
                            window_id = parts[1]
                            self.settle_window(window_id, result)

                # Get current market
                market = get_active_market()
                if not market:
                    time.sleep(30)
                    continue

                details = get_market_details(market['ticker'])
                if not details:
                    time.sleep(10)
                    continue

                ticker = details['ticker']
                mins_left = mins_until_close(details.get('close_time'))

                if mins_left is None or mins_left < 0:
                    time.sleep(10)
                    continue

                # Get BTC price
                btc_price = get_btc_price()
                if not btc_price:
                    time.sleep(5)
                    continue

                # Extract window_id
                parts = ticker.split('-')
                window_id = parts[1] if len(parts) >= 2 else ticker

                # New window detection
                if window_id != self.current_window:
                    strike = details.get('floor_strike', 0)
                    self.log(f"\n{'='*50}")
                    self.log(f"NEW WINDOW: {window_id}")
                    self.log(f"Strike: ${strike:,.2f}")
                    self.log(f"{'='*50}")
                    self.current_window = window_id

                # Build tick
                tick = {
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'window_id': window_id,
                    'ticker': ticker,
                    'strike_price': details.get('floor_strike', 0),
                    'mins_left': mins_left,
                    'btc_price': btc_price,
                    'yes_ask': details.get('yes_ask', 0),
                    'yes_bid': details.get('yes_bid', 0),
                    'no_ask': details.get('no_ask', 0),
                    'no_bid': details.get('no_bid', 0),
                }

                # Skip if strike is 0
                if tick['strike_price'] == 0:
                    time.sleep(5)
                    continue

                # Process tick for all bots
                self.process_tick(tick)

                # Print status periodically
                self.print_status()

                # Adaptive sleep
                if mins_left > 10:
                    time.sleep(10)
                elif mins_left > 5:
                    time.sleep(5)
                elif mins_left > 1:
                    time.sleep(2)
                else:
                    time.sleep(1)

            except KeyboardInterrupt:
                self.shutdown()
                break
            except Exception as e:
                self.log(f"ERROR: {e}")
                time.sleep(30)

    def shutdown(self):
        """Clean shutdown"""
        print("\n" + "=" * 70)
        print("SHUTTING DOWN")
        print("=" * 70)

        # Final summary
        print("\nFINAL RESULTS BY SERIES:")
        for series_name, prefix in [("Series 1 (Fixed-Minute)", "s1_"),
                                     ("Series 2 (Dynamic Edge)", "s2_"),
                                     ("Series 3 (Sentiment)", "s3_")]:
            bots = [b for k, b in self.bots.items() if k.startswith(prefix)]
            total_trades = sum(b.wins + b.losses for b in bots)
            total_wins = sum(b.wins for b in bots)
            total_profit = sum(b.bankroll - b.initial_bankroll for b in bots)
            profitable = sum(1 for b in bots if b.bankroll > b.initial_bankroll)

            print(f"\n{series_name}:")
            print(f"  Bots: {len(bots)}, Profitable: {profitable}")
            print(f"  Trades: {total_trades}, Win Rate: {total_wins/total_trades*100:.1f}%" if total_trades > 0 else "  No trades")
            print(f"  Total P/L: ${total_profit:.2f}")

        # Save final state
        self.sheets.update_summary(self.bots)
        self.save_state()

        # Save to JSON
        results = {'bots': {}}
        for bot_id, bot in self.bots.items():
            results['bots'][bot_id] = {
                'stats': bot.get_stats(),
                'trades': bot.trades,
            }

        with open('live_results.json', 'w') as f:
            json.dump(results, f, indent=2)
        print("\nResults saved to live_results.json")

# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Live multi-bot paper trader")
    parser.add_argument('--sheets-id', help='Google Sheets spreadsheet ID')
    parser.add_argument('--no-sheets', action='store_true', help='Disable sheets integration')

    args = parser.parse_args()

    sheets_id = None if args.no_sheets else args.sheets_id

    worker = LiveWorker(sheets_id)
    worker.run()
