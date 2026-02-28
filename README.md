# Initial Tests - 15 Minute BTC Strategy

Multi-bot paper trading system to test various strategies against live Kalshi data.

## Overview

This system runs **100+ paper trading bots simultaneously**, each testing a different strategy. All bots report to Google Sheets for easy tracking.

## The Core Edge

From 5 years of BTC data (137,206 windows), we know:

| Minute | Time Left | Persistence | Edge vs 50/50 |
|--------|-----------|-------------|---------------|
| 1 | 13 min | 58.7% | +8.7% |
| 3 | 11 min | 65.7% | +15.7% |
| 5 | 9 min | 71.3% | +21.3% |
| 7 | 7 min | 76.7% | +26.7% |
| 9 | 5 min | 81.4% | +31.4% |
| 11 | 3 min | 87.0% | +37.0% |
| 13 | 1 min | 93.2% | +43.2% |

**The question:** Can we find prices on Kalshi that give us positive expected value after fees?

## Bot Series

### Series 1: Fixed-Minute Bots (13 bots)

Each bot focuses on ONE specific minute checkpoint.

| Bot | Target | True Prob | Max Price | Description |
|-----|--------|-----------|-----------|-------------|
| s1_fixed_min_1 | Min 1 | 58.7% | 55c | Only trades at 13 min left |
| s1_fixed_min_2 | Min 2 | 62.6% | 59c | Only trades at 12 min left |
| s1_fixed_min_3 | Min 3 | 65.7% | 62c | Only trades at 11 min left |
| ... | ... | ... | ... | ... |
| s1_fixed_min_13 | Min 13 | 93.2% | 88c | Only trades at 1 min left |

**Entry Criteria:**
- At the target minute (±30 sec)
- Price < breakeven (true_prob * 0.95)
- Edge > 3%

### Series 2: Dynamic Edge Bots (34 bots)

Wait X minutes, then enter when edge exceeds threshold.

**Configurations:**
- Wait times: 2, 3, 4, 5 minutes
- Edge thresholds: 5%, 10%, 12%, 15%, 20%, 25%, 30%, 40%

| Bot | Wait | Min Edge | Description |
|-----|------|----------|-------------|
| s2_dynamic_wait2_edge10 | 2 min | 10% | After 2 min, enter if edge ≥ 10% |
| s2_dynamic_wait3_edge15 | 3 min | 15% | After 3 min, enter if edge ≥ 15% |
| s2_dynamic_wait5_edge20 | 5 min | 20% | After 5 min, enter if edge ≥ 20% |
| ... | ... | ... | ... |

**Special Bots:**
- `s2_dynamic_scaled_wait3` - Scales bet size with edge
- `s2_dynamic_scaled_wait5` - Same, but waits longer

### Series 3: Sentiment Bots (77 bots)

Ignore our persistence curve. Bet WITH the crowd.

**Question:** Does following Kalshi sentiment work?

**Configurations:**
- Odds thresholds: 55c, 60c, 65c, 70c, 75c, 80c, 85c, 90c, 95c
- Wait times: 0, 1, 2, 3, 5, 7, 10 minutes

| Bot | Threshold | Wait | Description |
|-----|-----------|------|-------------|
| s3_sentiment_odds55_wait0 | 55c | 0 min | Bet favorite immediately when >55c |
| s3_sentiment_odds80_wait5 | 80c | 5 min | Bet favorite after 5 min if >80c |
| s3_sentiment_odds95_wait10 | 95c | 10 min | Bet late on strong favorites |
| ... | ... | ... | ... |

## Fee Comparison

| Platform | Fee Formula | At 50c | At 70c | At 90c |
|----------|-------------|--------|--------|--------|
| Kalshi | 7% * p(1-p) | 1.75c | 1.47c | 0.63c |
| Polymarket | 1.56% * p(1-p) | 0.39c | 0.33c | 0.14c |
| Polymarket US | 0.01% taker | ~0c | ~0c | ~0c |

**Polymarket US is 100x cheaper** - consider shifting there.

## Running Backtests

```bash
cd initial-tests

# Run backtest against collected data
python backtester.py \
  --tick-data ../data-2-27-26/Kalshi\ -\ 15\ Minute\ Scraper\ -\ Second\ By\ Second\ -\ tick_data.csv \
  --results ../data-2-27-26/Kalshi\ -\ 15\ Minute\ Scraper\ -\ Second\ By\ Second\ -\ window_results.csv \
  --output-dir results
```

Results saved to `results/backtest_summary.csv` and `results/backtest_results.json`.

## Running Live Paper Trading

```bash
# Without Google Sheets
python live_worker.py --no-sheets

# With Google Sheets
python live_worker.py --sheets-id YOUR_SPREADSHEET_ID
```

### Google Sheets Setup

1. Create a Google Cloud project
2. Enable the Google Sheets API
3. Create a service account and download JSON credentials
4. Share your spreadsheet with the service account email
5. Save credentials as `service_account.json` or set `GOOGLE_APPLICATION_CREDENTIALS`

### Railway Deployment

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and deploy
railway login
railway init
railway up
```

## Files

```
initial-tests/
├── config/
│   ├── persistence_odds.py   # The proven persistence rates
│   └── bot_configs.py        # All bot configurations
├── backtester.py             # Run backtests on historical data
├── live_worker.py            # Live paper trading worker
├── requirements.txt          # Python dependencies
├── Procfile                  # Railway process config
├── railway.json              # Railway deployment config
└── README.md                 # This file
```

## Interpreting Results

### What Makes a Bot Profitable?

1. **Win Rate > Breakeven**: After fees, you need ~52-55% to break even on 50/50 bets
2. **Consistent Edge**: Look for bots with positive ROI across multiple windows
3. **Max Loss Streak**: Can your bankroll survive the worst case?

### Key Metrics

- **ROI**: (Final - Initial) / Initial * 100
- **Edge**: True_Probability - Price_Paid
- **Win Rate**: Wins / Total_Trades

### Red Flags

- Very few trades (not enough data)
- High win rate but negative ROI (fees killing you)
- Max loss streak > bankroll can handle

## Next Steps

After finding profitable bots:

1. Increase sample size (run longer)
2. Test on Polymarket (lower fees)
3. Consider Martingale sizing for high-confidence entries
4. Add real-time BTC volatility filters

## The Honest Assessment

From the notes:
- Good prices (55-75c) disappear fast
- At 85c+ you need 91%+ win rate - very tight
- Kalshi's fees eat into thin edges
- Best case: $100-300/day with perfect execution
- Realistic: $20-50/day
- This is grind money, not get-rich money
