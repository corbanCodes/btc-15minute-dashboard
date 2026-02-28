#!/usr/bin/env python3
"""
Web Dashboard for 111-Bot Paper Trading

Nice UI to monitor all bots in real-time.
Password protected via DASHBOARD_PASSWORD env var.
"""

import os
import json
import csv
import io
from datetime import datetime
from functools import wraps
from flask import Flask, render_template_string, jsonify, request, Response, redirect, url_for, session

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET', 'dev-secret-key-change-me')

# Password from environment
DASHBOARD_PASSWORD = os.environ.get('DASHBOARD_PASSWORD', 'btc15min')

# Path to bot state file (written by live_worker.py)
STATE_FILE = 'bot_state.json'

def load_state():
    """Load current bot state from JSON file"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {'bots': {}, 'last_update': None, 'windows_processed': 0}

def require_auth(f):
    """Simple password protection decorator"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# HTML Templates
LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Login - BTC 15-Min Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'SF Mono', monospace;
            background: linear-gradient(135deg, #0a0a0a, #1a1a2e);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #e0e0e0;
        }
        .login-box {
            background: rgba(20, 20, 30, 0.95);
            padding: 40px;
            border-radius: 15px;
            border: 1px solid #333;
            text-align: center;
        }
        h1 { color: #00ff88; margin-bottom: 20px; }
        input {
            padding: 12px 20px;
            font-size: 1rem;
            border: 1px solid #333;
            border-radius: 8px;
            background: #111;
            color: #fff;
            margin: 10px 0;
            width: 250px;
        }
        button {
            padding: 12px 30px;
            font-size: 1rem;
            background: #00ff88;
            color: #000;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: bold;
        }
        button:hover { background: #00cc66; }
        .error { color: #ff4444; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>BTC 15-Min Dashboard</h1>
        <form method="POST">
            <input type="password" name="password" placeholder="Password" autofocus><br>
            <button type="submit">Enter</button>
        </form>
        {% if error %}<p class="error">{{ error }}</p>{% endif %}
    </div>
</body>
</html>
'''

DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>BTC 15-Min Bot Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="30">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0d1117;
            min-height: 100vh;
            color: #c9d1d9;
            padding: 12px;
        }
        .header {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 16px;
        }
        .header-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
            margin-bottom: 16px;
        }
        h1 { color: #58a6ff; font-size: 1.4rem; font-weight: 600; }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
            gap: 12px;
        }
        .stat-box {
            background: #21262d;
            border: 1px solid #30363d;
            padding: 12px;
            border-radius: 8px;
            text-align: center;
        }
        .stat-value {
            font-size: 1.4rem;
            font-weight: 700;
            color: #3fb950;
        }
        .stat-value.negative { color: #f85149; }
        .stat-label { color: #8b949e; font-size: 0.75rem; margin-top: 4px; }
        .controls {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
        .btn {
            padding: 8px 14px;
            border-radius: 6px;
            border: 1px solid #30363d;
            background: #21262d;
            color: #c9d1d9;
            cursor: pointer;
            font-size: 0.85rem;
            text-decoration: none;
            white-space: nowrap;
        }
        .btn:hover { background: #30363d; border-color: #8b949e; }
        .section {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 16px;
            overflow-x: auto;
        }
        h2 {
            color: #58a6ff;
            font-size: 1rem;
            font-weight: 600;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid #30363d;
        }
        h2.s1 { color: #3fb950; }
        h2.s2 { color: #58a6ff; }
        h2.s3 { color: #bc8cff; }
        table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
        th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid #21262d; white-space: nowrap; }
        th { background: #21262d; color: #8b949e; font-weight: 600; font-size: 0.75rem; text-transform: uppercase; }
        tr:hover { background: rgba(56, 139, 253, 0.1); }
        .positive { color: #3fb950; }
        .negative { color: #f85149; }
        .pending { color: #d29922; }
        .winner { background: rgba(63, 185, 80, 0.1); }
        .loser { background: rgba(248, 81, 73, 0.05); }
        .skip-reason { color: #8b949e; font-size: 0.75rem; max-width: 200px; overflow: hidden; text-overflow: ellipsis; }
        .last-update { color: #484f58; font-size: 0.75rem; text-align: center; padding: 12px; }
        a.bot-link { color: #58a6ff; text-decoration: none; }
        a.bot-link:hover { text-decoration: underline; }
        .scrollable { max-height: 350px; overflow-y: auto; }
        @media (max-width: 768px) {
            body { padding: 8px; }
            .header { padding: 12px; }
            h1 { font-size: 1.1rem; }
            .stat-value { font-size: 1.1rem; }
            .btn { padding: 6px 10px; font-size: 0.75rem; }
            table { font-size: 0.75rem; }
            th, td { padding: 6px 8px; }
            .controls { justify-content: center; }
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-top">
            <h1>BTC 15-Min Paper Trading</h1>
            <div class="controls">
                <a href="/download/json" class="btn">JSON</a>
                <a href="/download/csv" class="btn">Summary</a>
                <a href="/download/all-trades" class="btn">All Trades</a>
                <a href="/logout" class="btn">Logout</a>
            </div>
        </div>
        <div class="stats-grid">
            <div class="stat-box">
                <div class="stat-value">{{ total_trades }}</div>
                <div class="stat-label">Trades</div>
            </div>
            <div class="stat-box">
                <div class="stat-value {{ 'negative' if win_rate < 50 else '' }}">{{ "%.1f"|format(win_rate) }}%</div>
                <div class="stat-label">Win Rate</div>
            </div>
            <div class="stat-box">
                <div class="stat-value {{ 'negative' if total_profit < 0 else '' }}">${{ "%.2f"|format(total_profit) }}</div>
                <div class="stat-label">P/L</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{{ windows_processed }}</div>
                <div class="stat-label">Windows</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{{ current_window or 'N/A' }}</div>
                <div class="stat-label">Current</div>
            </div>
        </div>
    </div>

    <!-- Top Performers -->
    <div class="section">
        <h2>Top 10 Performers</h2>
        <table>
            <tr>
                <th>Rank</th>
                <th>Bot ID</th>
                <th>Series</th>
                <th>Trades</th>
                <th>Win Rate</th>
                <th>Profit</th>
                <th>ROI</th>
                <th>Status</th>
            </tr>
            {% for bot in top_bots %}
            <tr class="{{ 'winner' if bot.profit > 0 else 'loser' if bot.profit < 0 else '' }}">
                <td>{{ loop.index }}</td>
                <td><a href="/bot/{{ bot.bot_id }}" class="bot-link">{{ bot.bot_id }}</a></td>
                <td>{{ bot.series }}</td>
                <td>{{ bot.trades }}</td>
                <td class="{{ 'positive' if bot.win_rate >= 50 else 'negative' }}">{{ "%.1f"|format(bot.win_rate) }}%</td>
                <td class="{{ 'positive' if bot.profit > 0 else 'negative' }}">${{ "%.2f"|format(bot.profit) }}</td>
                <td class="{{ 'positive' if bot.roi > 0 else 'negative' }}">{{ "%.1f"|format(bot.roi) }}%</td>
                <td class="{{ 'pending' if bot.pending else '' }}">{{ 'PENDING' if bot.pending else 'Ready' }}</td>
            </tr>
            {% endfor %}
        </table>
    </div>

    <!-- Series 1: Fixed Minute -->
    <div class="section">
        <h2 class="s1">Series 1: Fixed-Minute Bots ({{ s1_bots|length }})</h2>
        <div class="scrollable">
        <table>
            <tr>
                <th>Bot</th>
                <th>Target</th>
                <th>W/L</th>
                <th>Win%</th>
                <th>Profit</th>
                <th>Status</th>
            </tr>
            {% for bot in s1_bots %}
            <tr class="{{ 'winner' if bot.profit > 0 else 'loser' if bot.profit < 0 else '' }}">
                <td><a href="/bot/{{ bot.bot_id }}" class="bot-link">{{ bot.bot_id }}</a></td>
                <td>Min {{ bot.bot_id.split('_')[-1] }}</td>
                <td>{{ bot.wins }}/{{ bot.losses }}</td>
                <td class="{{ 'positive' if bot.win_rate >= 50 else 'negative' if bot.trades > 0 else '' }}">{{ "%.0f"|format(bot.win_rate) }}%</td>
                <td class="{{ 'positive' if bot.profit > 0 else 'negative' if bot.profit < 0 else '' }}">${{ "%.2f"|format(bot.profit) }}</td>
                <td class="skip-reason">{{ 'PENDING' if bot.pending else (bot.skip_reason or 'Ready') }}</td>
            </tr>
            {% endfor %}
        </table>
        </div>
    </div>

    <!-- Series 2: Dynamic Edge -->
    <div class="section">
        <h2 class="s2">Series 2: Dynamic Edge Bots ({{ s2_bots|length }})</h2>
        <div class="scrollable">
        <table>
            <tr>
                <th>Bot</th>
                <th>W/L</th>
                <th>Win%</th>
                <th>Profit</th>
                <th>Status</th>
            </tr>
            {% for bot in s2_bots %}
            <tr class="{{ 'winner' if bot.profit > 0 else 'loser' if bot.profit < 0 else '' }}">
                <td><a href="/bot/{{ bot.bot_id }}" class="bot-link">{{ bot.bot_id }}</a></td>
                <td>{{ bot.wins }}/{{ bot.losses }}</td>
                <td class="{{ 'positive' if bot.win_rate >= 50 else 'negative' if bot.trades > 0 else '' }}">{{ "%.0f"|format(bot.win_rate) }}%</td>
                <td class="{{ 'positive' if bot.profit > 0 else 'negative' if bot.profit < 0 else '' }}">${{ "%.2f"|format(bot.profit) }}</td>
                <td class="skip-reason">{{ 'PENDING' if bot.pending else (bot.skip_reason or 'Ready') }}</td>
            </tr>
            {% endfor %}
        </table>
        </div>
    </div>

    <!-- Series 3: Sentiment -->
    <div class="section">
        <h2 class="s3">Series 3: Sentiment Bots ({{ s3_bots|length }})</h2>
        <div class="scrollable">
        <table>
            <tr>
                <th>Bot</th>
                <th>W/L</th>
                <th>Win%</th>
                <th>Profit</th>
                <th>Status</th>
            </tr>
            {% for bot in s3_bots %}
            <tr class="{{ 'winner' if bot.profit > 0 else 'loser' if bot.profit < 0 else '' }}">
                <td><a href="/bot/{{ bot.bot_id }}" class="bot-link">{{ bot.bot_id }}</a></td>
                <td>{{ bot.wins }}/{{ bot.losses }}</td>
                <td class="{{ 'positive' if bot.win_rate >= 50 else 'negative' if bot.trades > 0 else '' }}">{{ "%.0f"|format(bot.win_rate) }}%</td>
                <td class="{{ 'positive' if bot.profit > 0 else 'negative' if bot.profit < 0 else '' }}">${{ "%.2f"|format(bot.profit) }}</td>
                <td class="skip-reason">{{ 'PENDING' if bot.pending else (bot.skip_reason or 'Ready') }}</td>
            </tr>
            {% endfor %}
        </table>
        </div>
    </div>

    <p class="last-update">Last update: {{ last_update }} | Auto-refresh every 30 seconds</p>
</body>
</html>
'''

BOT_DETAIL_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>{{ bot_id }} - Bot Details</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="30">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0d1117;
            min-height: 100vh;
            color: #c9d1d9;
            padding: 12px;
        }
        .header {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 16px;
        }
        .header-top {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            flex-wrap: wrap;
            gap: 12px;
            margin-bottom: 16px;
        }
        h1 { color: #58a6ff; font-size: 1.3rem; font-weight: 600; margin-top: 8px; }
        .back-link { color: #8b949e; text-decoration: none; font-size: 0.85rem; }
        .back-link:hover { color: #58a6ff; }
        .series-label { color: #8b949e; font-size: 0.85rem; margin-top: 4px; }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(80px, 1fr));
            gap: 10px;
        }
        .stat-box {
            background: #21262d;
            border: 1px solid #30363d;
            padding: 10px;
            border-radius: 8px;
            text-align: center;
        }
        .stat-value { font-size: 1.2rem; font-weight: 700; color: #3fb950; }
        .stat-value.negative { color: #f85149; }
        .stat-label { color: #8b949e; font-size: 0.7rem; margin-top: 2px; }
        .section {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 16px;
            overflow-x: auto;
        }
        h2 { color: #58a6ff; font-size: 1rem; font-weight: 600; margin-bottom: 12px; }
        table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
        th, td { padding: 8px; text-align: left; border-bottom: 1px solid #21262d; white-space: nowrap; }
        th { background: #21262d; color: #8b949e; font-weight: 600; font-size: 0.7rem; text-transform: uppercase; }
        .positive { color: #3fb950; }
        .negative { color: #f85149; }
        .win { background: rgba(63, 185, 80, 0.1); }
        .loss { background: rgba(248, 81, 73, 0.08); }
        .status-box {
            background: #21262d;
            border: 1px solid #30363d;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 16px;
        }
        .status-box.pending { border-color: #d29922; background: rgba(210, 153, 34, 0.1); }
        .status-box h3 { color: #d29922; font-size: 0.85rem; margin-bottom: 8px; }
        .status-box p { font-size: 0.8rem; color: #8b949e; }
        .status-box.skip { border-color: #8b949e; }
        .status-box.skip h3 { color: #8b949e; }
        .btn {
            padding: 8px 14px;
            border-radius: 6px;
            border: 1px solid #30363d;
            background: #21262d;
            color: #c9d1d9;
            font-size: 0.8rem;
            text-decoration: none;
        }
        .btn:hover { background: #30363d; }
        @media (max-width: 768px) {
            body { padding: 8px; }
            .stat-value { font-size: 1rem; }
            table { font-size: 0.7rem; }
            th, td { padding: 6px 4px; }
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-top">
            <div>
                <a href="/" class="back-link">&larr; Back to Dashboard</a>
                <h1>{{ bot_id }}</h1>
                <p class="series-label">{{ bot_data.series | replace('_', ' ') | title }}</p>
            </div>
            <a href="/bot/{{ bot_id }}/csv" class="btn">Download CSV</a>
        </div>
        <div class="stats-grid">
            <div class="stat-box">
                <div class="stat-value">{{ bot_data.trades }}</div>
                <div class="stat-label">Trades</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{{ bot_data.wins }}/{{ bot_data.losses }}</div>
                <div class="stat-label">W/L</div>
            </div>
            <div class="stat-box">
                <div class="stat-value {{ 'negative' if bot_data.win_rate < 50 and bot_data.trades > 0 else '' }}">{{ "%.0f"|format(bot_data.win_rate) }}%</div>
                <div class="stat-label">Win Rate</div>
            </div>
            <div class="stat-box">
                <div class="stat-value {{ 'negative' if bot_data.profit < 0 else '' }}">${{ "%.2f"|format(bot_data.profit) }}</div>
                <div class="stat-label">P/L</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">${{ "%.2f"|format(bot_data.bankroll) }}</div>
                <div class="stat-label">Bankroll</div>
            </div>
            <div class="stat-box">
                <div class="stat-value {{ 'negative' if bot_data.roi < 0 else '' }}">{{ "%.1f"|format(bot_data.roi) }}%</div>
                <div class="stat-label">ROI</div>
            </div>
        </div>
    </div>

    {% if pending_trade %}
    <div class="status-box pending">
        <h3>PENDING TRADE</h3>
        <p><strong>Window:</strong> {{ pending_trade.window_id }} |
           <strong>{{ pending_trade.direction }}</strong> @ {{ pending_trade.entry_price }}c |
           BTC: ${{ "%.2f"|format(pending_trade.btc_price) }} |
           Strike: ${{ "%.0f"|format(pending_trade.strike) }} |
           Bet: ${{ "%.2f"|format(pending_trade.bet_size) }}</p>
    </div>
    {% elif skip_reason %}
    <div class="status-box skip">
        <h3>CURRENT STATUS</h3>
        <p>{{ skip_reason }}</p>
    </div>
    {% endif %}

    <div class="section">
        <h2>Trade History ({{ trades|length }} trades)</h2>
        {% if trades %}
        <table>
            <tr>
                <th>#</th>
                <th>Time</th>
                <th>Window</th>
                <th>Dir</th>
                <th>Entry</th>
                <th>Edge</th>
                <th>Result</th>
                <th>P/L</th>
            </tr>
            {% for trade in trades | reverse %}
            <tr class="{{ 'win' if trade.outcome == 'win' else 'loss' }}">
                <td>{{ trades|length - loop.index0 }}</td>
                <td>{{ trade.timestamp[11:16] if trade.timestamp else '' }}</td>
                <td>{{ trade.window_id[-4:] if trade.window_id else '' }}</td>
                <td>{{ trade.direction }}</td>
                <td>{{ trade.entry_price }}c</td>
                <td>{{ "%.0f"|format(trade.edge * 100) if trade.edge else '-' }}%</td>
                <td class="{{ 'positive' if trade.outcome == 'win' else 'negative' }}">{{ trade.outcome | upper }}</td>
                <td class="{{ 'positive' if trade.profit > 0 else 'negative' }}">${{ "%.2f"|format(trade.profit) }}</td>
            </tr>
            {% endfor %}
        </table>
        {% else %}
        <p style="color: #8b949e; padding: 20px; text-align: center;">No trades yet</p>
        {% endif %}
    </div>

    <div class="section">
        <h2>Statistics</h2>
        <table>
            <tr><td>Total Wagered</td><td>${{ "%.2f"|format(bot_data.total_wagered) }}</td></tr>
            <tr><td>Total Fees Paid</td><td>${{ "%.2f"|format(bot_data.total_fees) }}</td></tr>
            <tr><td>Current Streak</td><td class="{{ 'positive' if bot_data.current_streak > 0 else 'negative' if bot_data.current_streak < 0 else '' }}">{{ bot_data.current_streak }}</td></tr>
            <tr><td>Best Win Streak</td><td class="positive">{{ bot_data.max_win_streak }}</td></tr>
            <tr><td>Worst Loss Streak</td><td class="negative">{{ bot_data.max_loss_streak }}</td></tr>
        </table>
    </div>
</body>
</html>
'''

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == DASHBOARD_PASSWORD:
            session['authenticated'] = True
            return redirect(url_for('dashboard'))
        error = 'Invalid password'
    return render_template_string(LOGIN_TEMPLATE, error=error)

@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    return redirect(url_for('login'))

@app.route('/')
@require_auth
def dashboard():
    state = load_state()
    bots = state.get('bots', {})

    # Calculate totals
    total_trades = sum(b.get('trades', 0) for b in bots.values())
    total_wins = sum(b.get('wins', 0) for b in bots.values())
    total_profit = sum(b.get('profit', 0) for b in bots.values())
    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0

    # Convert to list and sort
    bot_list = []
    for bot_id, data in bots.items():
        bot_list.append({
            'bot_id': bot_id,
            'series': data.get('series', 'unknown'),
            'trades': data.get('trades', 0),
            'wins': data.get('wins', 0),
            'losses': data.get('losses', 0),
            'win_rate': data.get('win_rate', 0),
            'profit': data.get('profit', 0),
            'roi': data.get('roi', 0),
            'pending': data.get('pending', False),
            'bankroll': data.get('bankroll', 1000),
            'skip_reason': data.get('last_skip_reason'),
        })

    # Sort by profit
    bot_list.sort(key=lambda x: x['profit'], reverse=True)

    # Split by series
    s1_bots = [b for b in bot_list if b['bot_id'].startswith('s1_')]
    s2_bots = [b for b in bot_list if b['bot_id'].startswith('s2_')]
    s3_bots = [b for b in bot_list if b['bot_id'].startswith('s3_')]

    return render_template_string(
        DASHBOARD_TEMPLATE,
        total_trades=total_trades,
        win_rate=win_rate,
        total_profit=total_profit,
        windows_processed=state.get('windows_processed', 0),
        current_window=state.get('current_window'),
        top_bots=bot_list[:10],
        s1_bots=sorted(s1_bots, key=lambda x: x['profit'], reverse=True),
        s2_bots=sorted(s2_bots, key=lambda x: x['profit'], reverse=True),
        s3_bots=sorted(s3_bots, key=lambda x: x['profit'], reverse=True),
        last_update=state.get('last_update', 'Never'),
    )

@app.route('/api/state')
@require_auth
def api_state():
    """Return current state as JSON"""
    return jsonify(load_state())

@app.route('/download/json')
@require_auth
def download_json():
    """Download full state as JSON"""
    state = load_state()
    return Response(
        json.dumps(state, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment;filename=bot_state.json'}
    )

@app.route('/download/csv')
@require_auth
def download_csv():
    """Download bot summary as CSV"""
    state = load_state()
    bots = state.get('bots', {})

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Bot ID', 'Series', 'Trades', 'Wins', 'Losses', 'Win Rate', 'Bankroll', 'Profit', 'ROI', 'Pending'])

    for bot_id, data in sorted(bots.items()):
        writer.writerow([
            bot_id,
            data.get('series', ''),
            data.get('trades', 0),
            data.get('wins', 0),
            data.get('losses', 0),
            f"{data.get('win_rate', 0):.1f}%",
            f"${data.get('bankroll', 1000):.2f}",
            f"${data.get('profit', 0):.2f}",
            f"{data.get('roi', 0):.1f}%",
            'Yes' if data.get('pending') else 'No',
        ])

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment;filename=bot_summary.csv'}
    )

@app.route('/download/all-trades')
@require_auth
def download_all_trades():
    """Download ALL trades from ALL bots as one CSV"""
    state = load_state()
    bots = state.get('bots', {})

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Bot ID', 'Series', 'Timestamp', 'Window', 'Direction', 'Entry Price',
                     'Strike', 'BTC Price', 'Edge %', 'Bet Size', 'Fee', 'Outcome', 'Profit', 'Bankroll After'])

    for bot_id, data in sorted(bots.items()):
        trades = data.get('trade_history', [])
        for trade in trades:
            writer.writerow([
                bot_id,
                data.get('series', ''),
                trade.get('timestamp', ''),
                trade.get('window_id', ''),
                trade.get('direction', ''),
                trade.get('entry_price', ''),
                trade.get('strike', ''),
                trade.get('btc_price', ''),
                f"{trade.get('edge', 0) * 100:.1f}" if trade.get('edge') else 'N/A',
                trade.get('bet_size', ''),
                trade.get('fee', ''),
                trade.get('outcome', ''),
                trade.get('profit', ''),
                trade.get('bankroll_after', ''),
            ])

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment;filename=all_trades.csv'}
    )

@app.route('/bot/<bot_id>')
@require_auth
def bot_detail(bot_id):
    """Show detailed view for a single bot"""
    state = load_state()
    bots = state.get('bots', {})

    if bot_id not in bots:
        return f"Bot {bot_id} not found", 404

    bot_data = bots[bot_id]
    trades = bot_data.get('trade_history', [])
    pending_trade = bot_data.get('pending_trade')
    skip_reason = bot_data.get('last_skip_reason')

    return render_template_string(
        BOT_DETAIL_TEMPLATE,
        bot_id=bot_id,
        bot_data=bot_data,
        trades=trades,
        pending_trade=pending_trade,
        skip_reason=skip_reason,
    )

@app.route('/bot/<bot_id>/csv')
@require_auth
def bot_trades_csv(bot_id):
    """Download trade history for a single bot as CSV"""
    state = load_state()
    bots = state.get('bots', {})

    if bot_id not in bots:
        return f"Bot {bot_id} not found", 404

    bot_data = bots[bot_id]
    trades = bot_data.get('trade_history', [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Timestamp', 'Window', 'Direction', 'Entry Price', 'Strike', 'BTC Price',
                     'Edge %', 'Bet Size', 'Fee', 'Outcome', 'Profit', 'Bankroll After'])

    for trade in trades:
        writer.writerow([
            trade.get('timestamp', ''),
            trade.get('window_id', ''),
            trade.get('direction', ''),
            trade.get('entry_price', ''),
            trade.get('strike', ''),
            trade.get('btc_price', ''),
            f"{trade.get('edge', 0) * 100:.1f}" if trade.get('edge') else 'N/A',
            trade.get('bet_size', ''),
            trade.get('fee', ''),
            trade.get('outcome', ''),
            trade.get('profit', ''),
            trade.get('bankroll_after', ''),
        ])

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment;filename={bot_id}_trades.csv'}
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
