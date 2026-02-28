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
    <meta http-equiv="refresh" content="30">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'SF Mono', 'Fira Code', monospace;
            background: linear-gradient(135deg, #0a0a0a, #1a1a2e);
            min-height: 100vh;
            color: #e0e0e0;
            padding: 20px;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px;
            background: rgba(20, 20, 30, 0.9);
            border-radius: 15px;
            margin-bottom: 20px;
            border: 1px solid #333;
        }
        h1 { color: #00ff88; font-size: 1.8rem; }
        .stats-row {
            display: flex;
            gap: 15px;
        }
        .stat-box {
            background: rgba(0, 255, 136, 0.1);
            border: 1px solid rgba(0, 255, 136, 0.3);
            padding: 15px 25px;
            border-radius: 10px;
            text-align: center;
        }
        .stat-value {
            font-size: 1.8rem;
            font-weight: bold;
            color: #00ff88;
        }
        .stat-value.negative { color: #ff4444; }
        .stat-label { color: #888; font-size: 0.8rem; }
        .controls {
            display: flex;
            gap: 10px;
        }
        .btn {
            padding: 10px 20px;
            border-radius: 8px;
            border: 1px solid #00ff88;
            background: transparent;
            color: #00ff88;
            cursor: pointer;
            font-family: inherit;
            text-decoration: none;
        }
        .btn:hover { background: rgba(0, 255, 136, 0.2); }
        .btn.primary { background: #00ff88; color: #000; }
        .section {
            background: rgba(20, 20, 30, 0.9);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            border: 1px solid #333;
        }
        h2 {
            color: #00ff88;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #333;
        }
        h2.s1 { color: #00ff88; }
        h2.s2 { color: #00aaff; }
        h2.s3 { color: #ff88ff; }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            padding: 10px 12px;
            text-align: left;
            border-bottom: 1px solid #222;
        }
        th {
            background: rgba(0, 255, 136, 0.1);
            color: #00ff88;
            font-weight: 600;
            position: sticky;
            top: 0;
        }
        tr:hover { background: rgba(0, 255, 136, 0.05); }
        .positive { color: #00ff88; }
        .negative { color: #ff4444; }
        .pending { color: #ffcc00; }
        .winner { background: rgba(0, 255, 136, 0.1); }
        .loser { background: rgba(255, 68, 68, 0.05); }
        .last-update {
            color: #666;
            font-size: 0.8rem;
            text-align: right;
            margin-top: 10px;
        }
        .filter-row {
            display: flex;
            gap: 10px;
            margin-bottom: 15px;
        }
        .filter-btn {
            padding: 8px 16px;
            border-radius: 20px;
            border: 1px solid #444;
            background: transparent;
            color: #888;
            cursor: pointer;
            font-family: inherit;
        }
        .filter-btn.active {
            border-color: #00ff88;
            color: #00ff88;
            background: rgba(0, 255, 136, 0.1);
        }
        .scrollable {
            max-height: 400px;
            overflow-y: auto;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>BTC 15-Min Paper Trading</h1>
        <div class="stats-row">
            <div class="stat-box">
                <div class="stat-value">{{ total_trades }}</div>
                <div class="stat-label">Total Trades</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{{ "%.1f"|format(win_rate) }}%</div>
                <div class="stat-label">Win Rate</div>
            </div>
            <div class="stat-box">
                <div class="stat-value {{ 'negative' if total_profit < 0 else '' }}">${{ "%.2f"|format(total_profit) }}</div>
                <div class="stat-label">Total P/L</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{{ windows_processed }}</div>
                <div class="stat-label">Windows</div>
            </div>
        </div>
        <div class="controls">
            <a href="/download/json" class="btn">Download JSON</a>
            <a href="/download/csv" class="btn">Download CSV</a>
            <a href="/logout" class="btn">Logout</a>
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
                <td><strong>{{ bot.bot_id }}</strong></td>
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
                <th>Trades</th>
                <th>Wins</th>
                <th>Losses</th>
                <th>Win%</th>
                <th>Profit</th>
                <th>Pending</th>
            </tr>
            {% for bot in s1_bots %}
            <tr class="{{ 'winner' if bot.profit > 0 else 'loser' if bot.profit < 0 else '' }}">
                <td>{{ bot.bot_id }}</td>
                <td>Min {{ bot.bot_id.split('_')[-1] }}</td>
                <td>{{ bot.trades }}</td>
                <td>{{ bot.wins }}</td>
                <td>{{ bot.losses }}</td>
                <td class="{{ 'positive' if bot.win_rate >= 50 else 'negative' }}">{{ "%.1f"|format(bot.win_rate) }}%</td>
                <td class="{{ 'positive' if bot.profit > 0 else 'negative' }}">${{ "%.2f"|format(bot.profit) }}</td>
                <td class="{{ 'pending' if bot.pending else '' }}">{{ 'Yes' if bot.pending else 'No' }}</td>
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
                <th>Trades</th>
                <th>Wins</th>
                <th>Losses</th>
                <th>Win%</th>
                <th>Profit</th>
                <th>Pending</th>
            </tr>
            {% for bot in s2_bots %}
            <tr class="{{ 'winner' if bot.profit > 0 else 'loser' if bot.profit < 0 else '' }}">
                <td>{{ bot.bot_id }}</td>
                <td>{{ bot.trades }}</td>
                <td>{{ bot.wins }}</td>
                <td>{{ bot.losses }}</td>
                <td class="{{ 'positive' if bot.win_rate >= 50 else 'negative' }}">{{ "%.1f"|format(bot.win_rate) }}%</td>
                <td class="{{ 'positive' if bot.profit > 0 else 'negative' }}">${{ "%.2f"|format(bot.profit) }}</td>
                <td class="{{ 'pending' if bot.pending else '' }}">{{ 'Yes' if bot.pending else 'No' }}</td>
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
                <th>Trades</th>
                <th>Wins</th>
                <th>Losses</th>
                <th>Win%</th>
                <th>Profit</th>
                <th>Pending</th>
            </tr>
            {% for bot in s3_bots %}
            <tr class="{{ 'winner' if bot.profit > 0 else 'loser' if bot.profit < 0 else '' }}">
                <td>{{ bot.bot_id }}</td>
                <td>{{ bot.trades }}</td>
                <td>{{ bot.wins }}</td>
                <td>{{ bot.losses }}</td>
                <td class="{{ 'positive' if bot.win_rate >= 50 else 'negative' }}">{{ "%.1f"|format(bot.win_rate) }}%</td>
                <td class="{{ 'positive' if bot.profit > 0 else 'negative' }}">${{ "%.2f"|format(bot.profit) }}</td>
                <td class="{{ 'pending' if bot.pending else '' }}">{{ 'Yes' if bot.pending else 'No' }}</td>
            </tr>
            {% endfor %}
        </table>
        </div>
    </div>

    <p class="last-update">Last update: {{ last_update }} | Auto-refresh every 30 seconds</p>
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
