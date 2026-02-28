#!/usr/bin/env python3
"""
Combined Runner for Live Worker + Web Dashboard

Runs both the paper trading worker and the Flask dashboard together.
"""

import os
import sys
import subprocess
import signal
import time

def main():
    port = os.environ.get('PORT', '8080')

    print("=" * 70)
    print("STARTING BTC 15-MIN PAPER TRADING SYSTEM + DASHBOARD")
    print("=" * 70)
    print(f"Dashboard port: {port}")
    print("=" * 70)

    # Start processes
    processes = []

    # Start the live worker (no sheets - dashboard only)
    worker_cmd = [sys.executable, 'live_worker.py', '--no-sheets']
    worker_proc = subprocess.Popen(worker_cmd, stdout=sys.stdout, stderr=sys.stderr)
    processes.append(('worker', worker_proc))
    print(f"Started live_worker.py (PID: {worker_proc.pid})")

    # Give worker a moment to start and create initial state
    time.sleep(2)

    # Start the web dashboard using gunicorn for production
    dashboard_cmd = [
        sys.executable, '-m', 'gunicorn',
        '--bind', f'0.0.0.0:{port}',
        '--workers', '2',
        '--timeout', '120',
        'web_dashboard:app'
    ]
    dashboard_proc = subprocess.Popen(dashboard_cmd, stdout=sys.stdout, stderr=sys.stderr)
    processes.append(('dashboard', dashboard_proc))
    print(f"Started web_dashboard on port {port} (PID: {dashboard_proc.pid})")

    # Handle shutdown signals
    def shutdown(signum, frame):
        print("\nShutting down...")
        for name, proc in processes:
            print(f"Stopping {name}...")
            proc.terminate()
        for name, proc in processes:
            proc.wait(timeout=10)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Monitor processes
    try:
        while True:
            for name, proc in processes:
                if proc.poll() is not None:
                    print(f"WARNING: {name} exited with code {proc.returncode}")
                    # Restart if it crashed
                    if name == 'worker':
                        print("Restarting worker...")
                        new_proc = subprocess.Popen(worker_cmd, stdout=sys.stdout, stderr=sys.stderr)
                        processes[0] = ('worker', new_proc)
                    elif name == 'dashboard':
                        print("Restarting dashboard...")
                        new_proc = subprocess.Popen(dashboard_cmd, stdout=sys.stdout, stderr=sys.stderr)
                        processes[1] = ('dashboard', new_proc)
            time.sleep(10)
    except KeyboardInterrupt:
        shutdown(None, None)

if __name__ == "__main__":
    main()
