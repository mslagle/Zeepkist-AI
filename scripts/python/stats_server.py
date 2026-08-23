import os
import re
import sys
import json
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8080
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILEPATH = os.path.join(SCRIPT_DIR, "zeepkist_training.log")

def get_log_file():
    candidates = [
        os.path.join(SCRIPT_DIR, "zeepkist_training.log"),
        os.path.join(SCRIPT_DIR, "..", "zeepkist_training.log"),
        os.path.join(SCRIPT_DIR, "..", "..", "zeepkist_training.log"),
        "zeepkist_training.log"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return os.path.join(SCRIPT_DIR, "zeepkist_training.log")

def get_time_file():
    candidates = [
        os.path.join(SCRIPT_DIR, "zeepkist_total_time.txt"),
        os.path.join(SCRIPT_DIR, "..", "zeepkist_total_time.txt"),
        os.path.join(SCRIPT_DIR, "..", "..", "zeepkist_total_time.txt"),
        "zeepkist_total_time.txt"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return os.path.join(SCRIPT_DIR, "zeepkist_total_time.txt")

def parse_logs(log_filepath=None):
    if log_filepath is None or not os.path.exists(log_filepath):
        log_filepath = get_log_file()
        
    history = []
    current_entry = {}
    recent_resets = []
    reset_counts = {"crashed": 0, "stuck": 0, "finished": 0, "total": 0}
    total_training_time = 0.0
    
    # Try reading the last saved time as starting point
    time_filepath = get_time_file()
    if os.path.exists(time_filepath):
        try:
            with open(time_filepath, "r") as tf:
                total_training_time = float(tf.read().strip())
        except:
            pass

    if not os.path.exists(log_filepath):
        return {
            "history": [],
            "reset_stats": reset_counts,
            "recent_resets": [],
            "total_training_time": total_training_time
        }
        
    reset_pattern = re.compile(r"\[RESET\] Reason: (.+?) \| Ep Reward: ([-+]?\d*\.?\d+(?:e[-+]?\d+)?)")
    status_pattern = re.compile(r"\[STATUS\] Time: (\d+)s")
    
    try:
        with open(log_filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                # Check for status lines (periodic updates)
                status_match = status_pattern.search(line)
                if status_match:
                    try:
                        total_training_time = float(status_match.group(1))
                    except ValueError:
                        pass
                    continue
                
                # Check for resets
                reset_match = reset_pattern.search(line)
                if reset_match:
                    reason = reset_match.group(1)
                    try:
                        reward = float(reset_match.group(2))
                    except ValueError:
                        reward = 0.0
                    
                    reason_lower = reason.lower()
                    category = "other"
                    if "crash" in reason_lower or "wheel" in reason_lower:
                        category = "crashed"
                        reset_counts["crashed"] += 1
                    elif "stuck" in reason_lower:
                        category = "stuck"
                        reset_counts["stuck"] += 1
                    elif "finish" in reason_lower:
                        category = "finished"
                        reset_counts["finished"] += 1
                    
                    reset_counts["total"] += 1
                    recent_resets.append({
                        "reason": reason,
                        "reward": reward,
                        "category": category
                    })
                    continue
                
                # Check for table boundaries or start of a block
                is_boundary = (all(c == '-' for c in line) and len(line) > 5) or (all(c == '=' for c in line) and len(line) > 5)
                
                if is_boundary:
                    if current_entry and "total_timesteps" in current_entry:
                        history.append(current_entry)
                        current_entry = {}
                    continue
                    
                if line.startswith("|") and line.endswith("|"):
                    parts = [p.strip() for p in line.split("|") if p.strip()]
                    if len(parts) == 2:
                        key = parts[0]
                        val = parts[1]
                        if key.endswith("/") or not val:
                            continue
                        current_entry[key] = val
                else:
                    if current_entry and "total_timesteps" in current_entry:
                        history.append(current_entry)
                        current_entry = {}
                        
            if current_entry and "total_timesteps" in current_entry:
                history.append(current_entry)
    except Exception as e:
        print(f"Error reading log file: {e}")
            
    processed_history = []
    for entry in history:
        try:
            it = int(entry.get("iterations", entry.get("episodes", 0)))
            rew = float(entry.get("ep_rew_mean", 0.0))
            length = float(entry.get("ep_len_mean", 0.0))
            fps = float(entry.get("fps", 0.0))
            timesteps = int(entry.get("total_timesteps", 0))
            elapsed = int(entry.get("time_elapsed", 0))
            
            # Additional diagnostic metrics (PPO or SAC)
            try: approx_kl = float(entry.get("approx_kl", 0.0))
            except: approx_kl = 0.0
            
            # entropy_loss (PPO) or ent_coef (SAC)
            try: 
                entropy_loss = float(entry.get("entropy_loss", entry.get("ent_coef", 0.0)))
            except: 
                entropy_loss = 0.0
                
            try: explained_variance = float(entry.get("explained_variance", 0.0))
            except: explained_variance = 0.0
            
            try: lr = float(entry.get("learning_rate", 0.0))
            except: lr = 0.0
            
            # loss (PPO) or actor_loss (SAC)
            try: 
                loss = float(entry.get("loss", entry.get("actor_loss", 0.0)))
            except: 
                loss = 0.0
                
            # value_loss (PPO) or critic_loss (SAC)
            try: 
                val_loss = float(entry.get("value_loss", entry.get("critic_loss", 0.0)))
            except: 
                val_loss = 0.0
            
            processed_history.append({
                "iteration": it,
                "ep_rew_mean": rew,
                "ep_len_mean": length,
                "fps": fps,
                "total_timesteps": timesteps,
                "time_elapsed": elapsed,
                "approx_kl": approx_kl,
                "entropy_loss": entropy_loss,
                "explained_variance": explained_variance,
                "learning_rate": lr,
                "loss": loss,
                "value_loss": val_loss
            })
        except (ValueError, TypeError):
            pass
            
    # De-duplicate entries by total_timesteps, taking the latest one
    unique_history = {}
    for entry in processed_history:
        unique_history[entry["total_timesteps"]] = entry
        
    sorted_history = sorted(unique_history.values(), key=lambda x: x["total_timesteps"])
    formatted_recent_resets = list(reversed(recent_resets[-10:]))
    
    return {
        "history": sorted_history,
        "reset_stats": reset_counts,
        "recent_resets": formatted_recent_resets,
        "total_training_time": total_training_time
    }

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zeepkist AI - Telemetry Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg-color: #060608;
            --card-bg: rgba(16, 16, 22, 0.65);
            --card-border: rgba(255, 255, 255, 0.06);
            --text-primary: #ffffff;
            --text-secondary: rgba(255, 255, 255, 0.45);
            --accent-purple: #a855f7;
            --accent-purple-glow: rgba(168, 85, 247, 0.35);
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --accent-amber: #f59e0b;
            --accent-blue: #0ea5e9;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-primary);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            overflow-x: hidden;
            transition: background 0.3s ease;
        }

        /* Glassmorphism card */
        .glass-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            backdrop-filter: blur(16px);
            border-radius: 16px;
            padding: 24px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
            position: relative;
            overflow: hidden;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .glass-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.02) 0%, transparent 100%);
            pointer-events: none;
        }

        header {
            width: 100%;
            max-width: 1500px;
            margin: 0 auto;
            padding: 32px 24px 16px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .logo-section h1 {
            font-weight: 800;
            font-size: 26px;
            letter-spacing: -0.5px;
            background: linear-gradient(to right, #ffffff, var(--accent-purple));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .logo-section p {
            font-size: 13px;
            color: var(--text-secondary);
            margin-top: 4px;
        }

        .status-badge {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            border-radius: 9999px;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.5px;
            text-transform: uppercase;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--card-border);
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: var(--text-secondary);
            display: inline-block;
        }

        .status-badge.live .status-dot {
            background-color: var(--accent-green);
            box-shadow: 0 0 12px var(--accent-green);
            animation: pulse 1.5s infinite;
        }

        .status-badge.idle .status-dot {
            background-color: var(--accent-amber);
            box-shadow: 0 0 12px var(--accent-amber);
        }

        main {
            width: 100%;
            max-width: 1500px;
            margin: 0 auto;
            padding: 16px 24px 40px 24px;
            flex-grow: 1;
        }

        /* Dual column layout */
        .dashboard-container {
            display: grid;
            grid-template-columns: 3fr 1fr;
            gap: 24px;
            width: 100%;
        }

        @media (max-width: 1100px) {
            .dashboard-container {
                grid-template-columns: 1fr;
            }
        }

        .main-column {
            display: flex;
            flex-direction: column;
            gap: 24px;
        }

        .side-column {
            display: flex;
            flex-direction: column;
            gap: 24px;
        }

        /* Metrics grid */
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
        }

        .metric-card.primary {
            grid-column: span 2;
            border: 1px solid rgba(168, 85, 247, 0.35);
            box-shadow: 0 10px 40px rgba(168, 85, 247, 0.12);
        }

        @media (max-width: 768px) {
            .metric-card.primary {
                grid-column: span 1;
            }
        }

        .metric-label {
            font-size: 11px;
            font-weight: 700;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.8px;
            margin-bottom: 6px;
        }

        .metric-value {
            font-size: 34px;
            font-weight: 800;
            line-height: 1.1;
            letter-spacing: -0.8px;
            font-family: 'Outfit', sans-serif;
            transition: color 0.3s ease;
        }

        .metric-card.primary .metric-value {
            font-size: 46px;
            background: linear-gradient(135deg, #ffffff, var(--accent-purple));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .metric-trend {
            display: flex;
            align-items: center;
            gap: 4px;
            font-size: 12px;
            margin-top: 10px;
            font-weight: 600;
        }

        .trend-up { color: var(--accent-green); }
        .trend-down { color: var(--accent-red); }
        .trend-neutral { color: var(--text-secondary); }

        /* Chart card */
        .chart-container {
            height: 380px;
            position: relative;
            margin-top: 16px;
        }

        /* Sidebar components */
        .panel-title {
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 1px;
            text-transform: uppercase;
            color: var(--text-primary);
            border-left: 3px solid var(--accent-purple);
            padding-left: 8px;
            margin-bottom: 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .diag-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.03);
            font-size: 13px;
        }

        .diag-row:last-child {
            border-bottom: none;
        }

        .diag-name {
            color: var(--text-secondary);
            font-weight: 500;
        }

        .diag-val {
            font-family: 'JetBrains Mono', monospace;
            font-weight: 700;
            color: var(--text-primary);
        }

        /* Progress bars */
        .progress-section {
            margin-top: 12px;
        }

        .progress-row {
            margin-bottom: 12px;
        }

        .progress-header {
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            font-weight: 600;
            margin-bottom: 4px;
        }

        .progress-bar-bg {
            width: 100%;
            height: 6px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 3px;
            overflow: hidden;
        }

        .progress-bar-fill {
            height: 100%;
            border-radius: 3px;
            transition: width 0.5s ease-out;
        }

        .progress-bar-fill.crash { background-color: var(--accent-red); }
        .progress-bar-fill.stuck { background-color: var(--accent-amber); }
        .progress-bar-fill.finish { background-color: var(--accent-green); }

        /* Incident Feed */
        .runs-feed {
            display: flex;
            flex-direction: column;
            gap: 8px;
            max-height: 250px;
            overflow-y: auto;
            padding-right: 4px;
        }

        .run-feed-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(255, 255, 255, 0.02);
            border-radius: 8px;
            padding: 8px 12px;
            font-size: 12px;
            border-left: 3px solid var(--text-secondary);
        }

        .run-feed-item.crashed { border-left-color: var(--accent-red); }
        .run-feed-item.stuck { border-left-color: var(--accent-amber); }
        .run-feed-item.finished { border-left-color: var(--accent-green); }

        .run-info {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }

        .run-reason {
            font-weight: 600;
            color: var(--text-primary);
            max-width: 150px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .run-cat {
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 0.5px;
            text-transform: uppercase;
        }

        .run-feed-item.crashed .run-cat { color: var(--accent-red); }
        .run-feed-item.stuck .run-cat { color: var(--accent-amber); }
        .run-feed-item.finished .run-cat { color: var(--accent-green); }
        .run-feed-item.other .run-cat { color: var(--accent-purple); }

        .run-reward {
            font-family: 'JetBrains Mono', monospace;
            font-weight: 700;
        }

        /* Stream modes */
        body.stream-mode {
            background: transparent !important;
            min-height: auto;
            overflow: hidden;
        }

        body.stream-mode header,
        body.stream-mode footer,
        body.stream-mode .stream-hide {
            display: none !important;
        }

        body.stream-mode main {
            padding: 0;
            max-width: none;
            margin: 0;
        }

        body.stream-mode .glass-card {
            background: rgba(8, 8, 12, 0.9);
            border: 1px solid rgba(255, 255, 255, 0.08);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.65);
        }

        /* Layout visibility */
        .stream-layout-bar,
        .stream-layout-incidents,
        .stream-layout-diagnostics {
            display: none;
        }

        /* Apply configurations based on layout class */
        body.stream-mode.layout-bar .stream-layout-bar {
            display: flex;
            gap: 12px;
            width: 100%;
        }

        body.stream-mode.layout-bar .dashboard-container {
            display: none !important;
        }

        body.stream-mode.layout-incidents .stream-layout-incidents {
            display: flex;
            flex-direction: column;
            gap: 16px;
            width: 320px;
        }

        body.stream-mode.layout-incidents .dashboard-container {
            display: none !important;
        }

        body.stream-mode.layout-diagnostics .stream-layout-diagnostics {
            display: flex;
            flex-direction: column;
            gap: 16px;
            width: 300px;
        }

        body.stream-mode.layout-diagnostics .dashboard-container {
            display: none !important;
        }

        body.stream-mode.layout-chart .side-column {
            display: none !important;
        }

        body.stream-mode.layout-chart .dashboard-container {
            grid-template-columns: 1fr;
        }

        body.stream-mode.layout-chart .metrics-grid {
            display: none !important;
        }

        body.stream-mode.layout-chart .chart-card {
            height: 100vh;
            border-radius: 0;
            border: none;
        }

        body.stream-mode.layout-chart .chart-container {
            height: calc(100vh - 40px);
        }

        footer {
            max-width: 1500px;
            width: 100%;
            margin: 0 auto;
            padding: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 13px;
            color: var(--text-secondary);
            border-top: 1px solid rgba(255, 255, 255, 0.03);
            margin-top: auto;
        }

        footer a {
            color: var(--accent-purple);
            text-decoration: none;
            font-weight: 600;
        }

        footer a:hover {
            text-decoration: underline;
        }

        .control-btn {
            background: rgba(168, 85, 247, 0.12);
            border: 1px solid rgba(168, 85, 247, 0.25);
            color: #ffffff;
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: all 0.2s;
        }

        .control-btn:hover {
            background: var(--accent-purple);
            box-shadow: 0 0 15px var(--accent-purple-glow);
        }

        kbd {
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.1);
            padding: 2px 5px;
            border-radius: 4px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 10px;
        }

        @keyframes pulse {
            0% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.25); opacity: 0.4; }
            100% { transform: scale(1); opacity: 1; }
        }

        .counter-changed {
            animation: highlight 0.8s ease;
        }

        @keyframes highlight {
            0% { text-shadow: 0 0 12px rgba(255, 255, 255, 0.8); color: #ffffff; }
            100% { text-shadow: none; }
        }
    </style>
</head>
<body>

    <!-- Standard Header -->
    <header class="stream-hide">
        <div class="logo-section">
            <h1><span>⚡</span> ZEEPKIST AI TELEMETRY</h1>
            <p>Real-time neural network training metrics</p>
        </div>
        <div style="display: flex; align-items: center; gap: 12px;">
            <button class="control-btn" onclick="toggleStreamMode()">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
                OBS Stream Mode
            </button>
            <div id="statusBadge" class="status-badge">
                <span class="status-dot"></span>
                <span id="statusText">Checking Log...</span>
            </div>
        </div>
    </header>

    <!-- Main Workspace -->
    <main>
        
        <!-- STREAM OVERLAY 1: COMPACT TELEMETRY BAR -->
        <div class="stream-layout-bar">
            <div class="glass-card" style="padding: 10px 16px; flex-grow: 1; display: flex; align-items: center; justify-content: space-between;">
                <div>
                    <div class="metric-label" style="margin: 0; font-size: 10px;">REWARD MEAN</div>
                    <div id="bar_reward" class="metric-value" style="font-size: 22px; font-weight: 800;">-</div>
                </div>
                <div id="bar_reward_trend" class="metric-trend" style="margin: 0; margin-left: 8px;"></div>
            </div>
            
            <div class="glass-card" style="padding: 10px 16px; display: flex; align-items: center; justify-content: space-between; min-width: 150px;">
                <div>
                    <div class="metric-label" style="margin: 0; font-size: 10px;">TIMESTEPS</div>
                    <div id="bar_timesteps" class="metric-value" style="font-size: 22px; font-weight: 800;">-</div>
                </div>
            </div>

            <div class="glass-card" style="padding: 10px 16px; display: flex; align-items: center; justify-content: space-between; min-width: 150px;">
                <div>
                    <div class="metric-label" style="margin: 0; font-size: 10px;">TRAINING TIME</div>
                    <div id="bar_training_time" class="metric-value" style="font-size: 22px; font-weight: 800; color: var(--accent-purple);">-</div>
                </div>
            </div>

            <div class="glass-card" style="padding: 10px 16px; display: flex; align-items: center; justify-content: space-between; min-width: 160px;">
                <div>
                    <div class="metric-label" style="margin: 0; font-size: 10px;">FINISH RATE</div>
                    <div id="bar_fin_rate" class="metric-value" style="font-size: 22px; font-weight: 800; color: var(--accent-green);">-</div>
                </div>
            </div>

            <div class="glass-card" style="padding: 10px 16px; display: flex; align-items: center; justify-content: space-between; min-width: 160px;">
                <div>
                    <div class="metric-label" style="margin: 0; font-size: 10px;">INCIDENTS (CR/ST)</div>
                    <div id="bar_incidents" class="metric-value" style="font-size: 22px; font-weight: 800; color: var(--accent-red);">-</div>
                </div>
            </div>

            <div class="glass-card" style="padding: 10px 16px; display: flex; align-items: center; justify-content: space-between; position: relative; min-width: 180px;">
                <div>
                    <div class="metric-label" style="margin: 0; font-size: 10px;">TRAINING STATUS</div>
                    <div id="bar_status" class="metric-value" style="font-size: 18px; font-weight: 700;">UNKNOWN</div>
                </div>
                <div id="bar_status_dot" class="status-dot" style="position: absolute; right: 16px; top: calc(50% - 4px); width: 8px; height: 8px;"></div>
            </div>
        </div>

        <!-- STREAM OVERLAY 2: INCIDENT FEED -->
        <div class="stream-layout-incidents">
            <div class="glass-card">
                <div class="panel-title">INCIDENT LOGS</div>
                <div id="stream_feed" class="runs-feed" style="max-height: 300px;"></div>
            </div>
            
            <div class="glass-card" style="padding: 18px;">
                <div class="panel-title">INCIDENT RATE</div>
                <div class="progress-section" id="stream_incidents_section">
                    <!-- filled dynamically -->
                </div>
            </div>
        </div>

        <!-- STREAM OVERLAY 3: NEURAL DIAGNOSTICS -->
        <div class="stream-layout-diagnostics">
            <div class="glass-card">
                <div class="panel-title">NEURAL OPTIMIZER</div>
                <div id="stream_diag_list">
                    <!-- filled dynamically -->
                </div>
            </div>
        </div>

        <!-- NORMAL DASHBOARD CONTAINER -->
        <div class="dashboard-container">
            
            <!-- Left Main Column -->
            <div class="main-column">
                
                <!-- Core Metrics Grid -->
                <div class="metrics-grid">
                    <div class="glass-card metric-card primary">
                        <div class="metric-label">EPISODE REWARD MEAN (ep_rew_mean)</div>
                        <div id="rewardMean" class="metric-value">-</div>
                        <div id="rewardTrend" class="metric-trend">
                            <span class="trend-neutral">⏳ Awaiting neural update...</span>
                        </div>
                    </div>

                    <div class="glass-card metric-card">
                        <div class="metric-label">EPISODE LENGTH MEAN</div>
                        <div id="epLength" class="metric-value">-</div>
                        <div class="metric-label" style="margin-top: 8px; font-size: 10px;">AVERAGE STEPS</div>
                    </div>

                    <div class="glass-card metric-card">
                        <div class="metric-label">TOTAL TIMESTEPS</div>
                        <div id="totalTimesteps" class="metric-value">-</div>
                        <div id="totalTimestepsRate" class="metric-trend" style="font-weight: 400; color: var(--text-secondary);">-</div>
                    </div>

                    <div class="glass-card metric-card">
                        <div class="metric-label">UPDATES</div>
                        <div id="iterations" class="metric-value">-</div>
                        <div class="metric-label" style="margin-top: 8px; font-size: 10px;">OPTIMIZER UPDATES</div>
                    </div>

                    <div class="glass-card metric-card">
                        <div class="metric-label">SIMULATION FPS</div>
                        <div id="fpsRate" class="metric-value">-</div>
                        <div class="metric-label" style="margin-top: 8px; font-size: 10px;">SAMPLES / HZ</div>
                    </div>

                    <div class="glass-card metric-card">
                        <div class="metric-label">TOTAL TRAINING TIME</div>
                        <div id="totalTrainingTime" class="metric-value">-</div>
                        <div class="metric-label" style="margin-top: 8px; font-size: 10px;">ACCUMULATED SIM TIME</div>
                    </div>
                </div>

                <!-- History Chart -->
                <div class="glass-card chart-card">
                    <div class="metric-label" style="margin-bottom: 0;">REWARD GRADIENT HISTORY</div>
                    <div class="chart-container">
                        <canvas id="rewardChart"></canvas>
                    </div>
                </div>
            </div>

            <!-- Right Sidebar Column -->
            <div class="side-column">
                
                <!-- Neural Diagnostics Panel -->
                <div class="glass-card">
                    <div class="panel-title">NEURAL DIAGNOSTICS</div>
                    <div id="diag_list">
                        <div class="diag-row">
                            <span class="diag-name">Learning Rate</span>
                            <span id="diag_lr" class="diag-val">-</span>
                        </div>
                        <div class="diag-row">
                            <span class="diag-name">Value Loss</span>
                            <span id="diag_val_loss" class="diag-val">-</span>
                        </div>
                        <div class="diag-row">
                            <span class="diag-name">Entropy Loss</span>
                            <span id="diag_ent_loss" class="diag-val">-</span>
                        </div>
                        <div class="diag-row">
                            <span class="diag-name">Explained Variance</span>
                            <span id="diag_exp_var" class="diag-val">-</span>
                        </div>
                        <div class="diag-row">
                            <span class="diag-name">Approx KL</span>
                            <span id="diag_kl" class="diag-val">-</span>
                        </div>
                        <div class="diag-row">
                            <span class="diag-name">Policy Loss</span>
                            <span id="diag_policy_loss" class="diag-val">-</span>
                        </div>
                    </div>
                </div>

                <!-- Reset Statistics (Incidents) -->
                <div class="glass-card">
                    <div class="panel-title">
                        <span>INCIDENT REPORT</span>
                        <span id="totalResetsBadge" style="font-family: 'JetBrains Mono', monospace; font-size: 11px; background: rgba(255,255,255,0.06); padding: 2px 6px; border-radius: 4px;">RUNS: -</span>
                    </div>
                    <div class="progress-section">
                        <!-- Finishes -->
                        <div class="progress-row">
                            <div class="progress-header">
                                <span style="color: var(--accent-green);">Finishes</span>
                                <div><span id="stat_fin_cnt">-</span> (<span id="stat_fin_pct">-</span>%)</div>
                            </div>
                            <div class="progress-bar-bg">
                                <div id="stat_fin_bar" class="progress-bar-fill finish" style="width: 0%"></div>
                            </div>
                        </div>
                        
                        <!-- Crashes -->
                        <div class="progress-row">
                            <div class="progress-header">
                                <span style="color: var(--accent-red);">Crashes</span>
                                <div><span id="stat_crash_cnt">-</span> (<span id="stat_crash_pct">-</span>%)</div>
                            </div>
                            <div class="progress-bar-bg">
                                <div id="stat_crash_bar" class="progress-bar-fill crash" style="width: 0%"></div>
                            </div>
                        </div>

                        <!-- Stuck -->
                        <div class="progress-row">
                            <div class="progress-header">
                                <span style="color: var(--accent-amber);">Stuck</span>
                                <div><span id="stat_stuck_cnt">-</span> (<span id="stat_stuck_pct">-</span>%)</div>
                            </div>
                            <div class="progress-bar-bg">
                                <div id="stat_stuck_bar" class="progress-bar-fill stuck" style="width: 0%"></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Recent Runs Feed -->
                <div class="glass-card">
                    <div class="panel-title">RECENT RUNS</div>
                    <div id="recentResetsFeed" class="runs-feed">
                        <div class="trend-neutral" style="font-size: 12px; text-align: center; padding: 20px 0;">Awaiting reset logs...</div>
                    </div>
                </div>

            </div>
        </div>

    </main>

    <!-- Footer -->
    <footer class="stream-hide">
        <div>Zeepkist AI Telemetry &bull; <span style="font-family: 'JetBrains Mono', monospace; font-size: 11px;">v1.2.0</span></div>
        <div>Stream URLs: <a href="?stream=true&layout=bar" target="_blank">?layout=bar</a> | <a href="?stream=true&layout=chart" target="_blank">?layout=chart</a> | <a href="?stream=true&layout=incidents" target="_blank">?layout=incidents</a> | <a href="?stream=true&layout=diagnostics" target="_blank">?layout=diagnostics</a></div>
    </footer>

    <script>
        let chart = null;
        let lastIteration = -1;
        let lastRewardValue = null;
        let isStreamMode = false;
        let activeLayout = 'default';

        function init() {
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.get('stream') === 'true') {
                isStreamMode = true;
                document.body.classList.add('stream-mode');
                
                activeLayout = urlParams.get('layout') || 'bar';
                document.body.classList.add('layout-' + activeLayout);
            }

            setupChart();
            pollData();
            setInterval(pollData, 2000);
        }

        function toggleStreamMode() {
            const url = new URL(window.location.href);
            if (isStreamMode) {
                url.searchParams.delete('stream');
                url.searchParams.delete('layout');
            } else {
                url.searchParams.set('stream', 'true');
                
                // Show options
                const choice = prompt("Select stream overlay layout:\\n1: Horizontal Bar\\n2: Chart Only\\n3: Incident Feed\\n4: Neural Optimizer", "1");
                if (choice === "1") url.searchParams.set('layout', 'bar');
                else if (choice === "2") url.searchParams.set('layout', 'chart');
                else if (choice === "3") url.searchParams.set('layout', 'incidents');
                else if (choice === "4") url.searchParams.set('layout', 'diagnostics');
                else url.searchParams.set('layout', 'bar');
            }
            window.location.href = url.toString();
        }

        function setupChart() {
            const ctx = document.getElementById('rewardChart').getContext('2d');
            
            let gradient = ctx.createLinearGradient(0, 0, 0, 400);
            gradient.addColorStop(0, 'rgba(168, 85, 247, 0.25)');
            gradient.addColorStop(1, 'rgba(168, 85, 247, 0.0)');

            chart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'ep_rew_mean',
                        data: [],
                        borderColor: '#a855f7',
                        borderWidth: 3,
                        backgroundColor: gradient,
                        fill: true,
                        tension: 0.35,
                        pointBackgroundColor: '#c084fc',
                        pointBorderColor: '#060608',
                        pointBorderWidth: 2,
                        pointRadius: 3,
                        pointHoverRadius: 6
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(15, 15, 20, 0.95)',
                            titleFont: { family: 'Outfit', size: 13, weight: 'bold' },
                            bodyFont: { family: 'JetBrains Mono', size: 12 },
                            borderColor: 'rgba(255, 255, 255, 0.08)',
                            borderWidth: 1,
                            padding: 12,
                            displayColors: false,
                            callbacks: {
                                label: function(context) {
                                    return `Reward Mean: ${context.raw.toFixed(2)}`;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: 'rgba(255, 255, 255, 0.03)', drawBorder: false },
                            ticks: { color: 'rgba(255, 255, 255, 0.4)', font: { family: 'JetBrains Mono', size: 11 } }
                        },
                        y: {
                            grid: { color: 'rgba(255, 255, 255, 0.03)', drawBorder: false },
                            ticks: { color: 'rgba(255, 255, 255, 0.4)', font: { family: 'JetBrains Mono', size: 11 } }
                        }
                    }
                }
            });
        }

        function formatTime(seconds) {
            const h = Math.floor(seconds / 3600);
            const m = Math.floor((seconds % 3600) / 60);
            const s = seconds % 60;
            return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
        }

        function formatNumber(num) {
            return num.toString().replace(/\\B(?=(\\d{3})+(?!\\d))/g, ",");
        }

        function formatScientfic(num) {
            if (Math.abs(num) < 0.0001 && num !== 0) {
                return num.toExponential(4);
            }
            return num.toFixed(5);
        }

        function animateValue(id, formattedValue) {
            const el = document.getElementById(id);
            if (!el) return;
            
            const prevText = el.innerText;
            if (prevText !== formattedValue) {
                el.innerText = formattedValue;
                el.classList.remove('counter-changed');
                void el.offsetWidth;
                el.classList.add('counter-changed');
            }
        }

        function pollData() {
            fetch('/data')
                .then(res => res.json())
                .then(data => {
                    updateStatus(data.active);
                    
                    // Handle reset stats
                    updateResetStats(data.reset_stats);
                    
                    // Handle recent run feed
                    updateRunFeed(data.recent_resets);

                    // Update total training time
                    const totalTrainingSeconds = data.total_training_time || 0;
                    animateValue('totalTrainingTime', formatTime(totalTrainingSeconds));
                    animateValue('bar_training_time', formatTime(totalTrainingSeconds));

                    if (!data.history || data.history.length === 0) return;
                    
                    const latest = data.latest || data.history[data.history.length - 1];
                    
                    // Update core metrics
                    animateValue('rewardMean', latest.ep_rew_mean.toFixed(2));
                    animateValue('epLength', latest.ep_len_mean.toFixed(0));
                    animateValue('totalTimesteps', formatNumber(latest.total_timesteps));
                    animateValue('totalTimestepsRate', `${latest.total_timesteps > 0 ? (latest.total_timesteps / latest.time_elapsed).toFixed(1) : 0} steps/sec`);
                    animateValue('iterations', latest.iteration.toString());
                    animateValue('fpsRate', `${latest.fps.toFixed(0)} Hz`);
                    
                    // Update stream layout bar
                    animateValue('bar_reward', latest.ep_rew_mean.toFixed(1));
                    animateValue('bar_timesteps', formatNumber(latest.total_timesteps));
                    
                    // Update neural diagnostics sidebar
                    animateValue('diag_lr', formatScientfic(latest.learning_rate));
                    animateValue('diag_val_loss', latest.value_loss.toFixed(5));
                    animateValue('diag_ent_loss', latest.entropy_loss.toFixed(3));
                    animateValue('diag_exp_var', latest.explained_variance.toFixed(3));
                    animateValue('diag_kl', latest.approx_kl.toFixed(5));
                    animateValue('diag_policy_loss', latest.loss.toFixed(5));

                    // Highlight colors
                    const rewColor = latest.ep_rew_mean >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
                    const rewEl = document.getElementById('rewardMean');
                    if (rewEl) rewEl.style.color = rewColor;
                    const barRewEl = document.getElementById('bar_reward');
                    if (barRewEl) barRewEl.style.color = rewColor;

                    updateTrend(latest.ep_rew_mean);

                    // Sync Neural diagnostics overlay
                    syncDiagnosticsOverlay(latest);

                    // Update Chart
                    const iterations = data.history.map(item => item.iteration);
                    const rewards = data.history.map(item => item.ep_rew_mean);
                    
                    if (iterations.length > 0 && iterations[iterations.length - 1] !== lastIteration) {
                        chart.data.labels = iterations;
                        chart.data.datasets[0].data = rewards;
                        
                        if (rewards.length >= 2) {
                            const lastVal = rewards[rewards.length - 1];
                            const prevVal = rewards[rewards.length - 2];
                            if (lastVal > prevVal) {
                                chart.data.datasets[0].borderColor = '#10b981';
                                chart.data.datasets[0].pointBackgroundColor = '#34d399';
                            } else {
                                chart.data.datasets[0].borderColor = '#a855f7';
                                chart.data.datasets[0].pointBackgroundColor = '#c084fc';
                            }
                        }
                        
                        chart.update('none');
                        lastIteration = iterations[iterations.length - 1];
                    }
                })
                .catch(err => {
                    console.error('Error fetching data:', err);
                    updateStatus(false, true);
                });
        }

        function updateStatus(active, error = false) {
            const badge = document.getElementById('statusBadge');
            const text = document.getElementById('statusText');
            
            const barStatus = document.getElementById('bar_status');
            const barDot = document.getElementById('bar_status_dot');

            badge.className = 'status-badge';
            
            if (error) {
                text.innerText = 'OFFLINE';
                badge.classList.add('idle');
                badge.style.borderColor = 'rgba(239, 68, 68, 0.4)';
                
                if (barStatus) {
                    barStatus.innerText = 'OFFLINE';
                    barStatus.style.color = 'var(--accent-red)';
                }
                if (barDot) {
                    barDot.style.backgroundColor = 'var(--accent-red)';
                    barDot.style.boxShadow = '0 0 12px var(--accent-red)';
                }
            } else if (active) {
                text.innerText = 'TRAINING LIVE';
                badge.classList.add('live');
                badge.style.borderColor = 'rgba(16, 185, 129, 0.4)';
                
                if (barStatus) {
                    barStatus.innerText = 'TRAINING';
                    barStatus.style.color = 'var(--accent-green)';
                }
                if (barDot) {
                    barDot.style.backgroundColor = 'var(--accent-green)';
                    barDot.style.boxShadow = '0 0 12px var(--accent-green)';
                    barDot.style.animation = 'pulse 1.5s infinite';
                }
            } else {
                text.innerText = 'IDLE / SAVED';
                badge.classList.add('idle');
                badge.style.borderColor = 'rgba(245, 158, 11, 0.4)';
                
                if (barStatus) {
                    barStatus.innerText = 'IDLE';
                    barStatus.style.color = 'var(--accent-amber)';
                }
                if (barDot) {
                    barDot.style.backgroundColor = 'var(--accent-amber)';
                    barDot.style.boxShadow = '0 0 12px var(--accent-amber)';
                    barDot.style.animation = 'none';
                }
            }
        }

        function updateTrend(currentVal) {
            const trendContainer = document.getElementById('rewardTrend');
            const barTrend = document.getElementById('bar_reward_trend');
            if (!trendContainer) return;

            if (lastRewardValue === null) {
                lastRewardValue = currentVal;
                return;
            }

            const diff = currentVal - lastRewardValue;
            if (diff !== 0) {
                const isUp = diff > 0;
                const sign = isUp ? '+' : '';
                const arrow = isUp ? '▲' : '▼';
                const trendClass = isUp ? 'trend-up' : 'trend-down';
                
                trendContainer.innerHTML = `<span class="${trendClass}">${arrow} ${sign}${diff.toFixed(2)} since update</span>`;
                if (barTrend) {
                    barTrend.innerHTML = `<span class="${trendClass}" style="font-size: 11px;">${arrow} ${sign}${diff.toFixed(1)}</span>`;
                }
                lastRewardValue = currentVal;
            }
        }

        function updateResetStats(stats) {
            if (!stats) return;
            
            const total = stats.total;
            const crashed = stats.crashed;
            const stuck = stats.stuck;
            const finished = stats.finished;
            
            const crashPct = total > 0 ? (crashed / total * 100).toFixed(1) : '0.0';
            const stuckPct = total > 0 ? (stuck / total * 100).toFixed(1) : '0.0';
            const finPct = total > 0 ? (finished / total * 100).toFixed(1) : '0.0';

            // Sidebar stats
            animateValue('totalResetsBadge', `RUNS: ${total}`);
            
            animateValue('stat_fin_cnt', finished);
            animateValue('stat_fin_pct', finPct);
            document.getElementById('stat_fin_bar').style.width = finPct + '%';

            animateValue('stat_crash_cnt', crashed);
            animateValue('stat_crash_pct', crashPct);
            document.getElementById('stat_crash_bar').style.width = crashPct + '%';

            animateValue('stat_stuck_cnt', stuck);
            animateValue('stat_stuck_pct', stuckPct);
            document.getElementById('stat_stuck_bar').style.width = stuckPct + '%';

            // Stream layouts update
            animateValue('bar_fin_rate', `${finPct}%`);
            animateValue('bar_incidents', `${crashed}/${stuck}`);

            // Incident Overlay Layout
            const strIncidentsContainer = document.getElementById('stream_incidents_section');
            if (strIncidentsContainer && activeLayout === 'incidents') {
                strIncidentsContainer.innerHTML = `
                    <div class="progress-row">
                        <div class="progress-header">
                            <span style="color: var(--accent-green);">Finishes</span>
                            <div>${finished} (${finPct}%)</div>
                        </div>
                        <div class="progress-bar-bg"><div class="progress-bar-fill finish" style="width: ${finPct}%"></div></div>
                    </div>
                    <div class="progress-row">
                        <div class="progress-header">
                            <span style="color: var(--accent-red);">Crashes</span>
                            <div>${crashed} (${crashPct}%)</div>
                        </div>
                        <div class="progress-bar-bg"><div class="progress-bar-fill crash" style="width: ${crashPct}%"></div></div>
                    </div>
                    <div class="progress-row">
                        <div class="progress-header">
                            <span style="color: var(--accent-amber);">Stuck</span>
                            <div>${stuck} (${stuckPct}%)</div>
                        </div>
                        <div class="progress-bar-bg"><div class="progress-bar-fill stuck" style="width: ${stuckPct}%"></div></div>
                    </div>
                `;
            }
        }

        function updateRunFeed(resets) {
            const feed = document.getElementById('recentResetsFeed');
            const streamFeed = document.getElementById('stream_feed');
            if (!feed) return;
            
            if (!resets || resets.length === 0) {
                feed.innerHTML = `<div class="trend-neutral" style="font-size: 12px; text-align: center; padding: 20px 0;">Awaiting reset logs...</div>`;
                if (streamFeed) streamFeed.innerHTML = feed.innerHTML;
                return;
            }

            let html = '';
            resets.forEach(run => {
                const formattedReward = run.reward.toLocaleString(undefined, {minimumFractionDigits: 1, maximumFractionDigits: 1});
                const colorLabel = run.reward >= 0 ? 'var(--accent-green)' : '';
                
                html += `
                    <div class="run-feed-item ${run.category}">
                        <div class="run-info">
                            <span class="run-cat">${run.category.toUpperCase()}</span>
                            <span class="run-reason" title="${run.reason}">${run.reason}</span>
                        </div>
                        <div class="run-reward" style="color: ${colorLabel}">${formattedReward}</div>
                    </div>
                `;
            });

            feed.innerHTML = html;
            if (streamFeed && activeLayout === 'incidents') {
                streamFeed.innerHTML = html;
            }
        }

        function syncDiagnosticsOverlay(latest) {
            const strDiagList = document.getElementById('stream_diag_list');
            if (strDiagList && activeLayout === 'diagnostics') {
                strDiagList.innerHTML = `
                    <div class="diag-row">
                        <span class="diag-name">Learning Rate</span>
                        <span class="diag-val">${formatScientfic(latest.learning_rate)}</span>
                    </div>
                    <div class="diag-row">
                        <span class="diag-name">Value Loss</span>
                        <span class="diag-val">${latest.value_loss.toFixed(5)}</span>
                    </div>
                    <div class="diag-row">
                        <span class="diag-name">Entropy Loss</span>
                        <span class="diag-val">${latest.entropy_loss.toFixed(3)}</span>
                    </div>
                    <div class="diag-row">
                        <span class="diag-name">Explained Var</span>
                        <span class="diag-val">${latest.explained_variance.toFixed(3)}</span>
                    </div>
                    <div class="diag-row">
                        <span class="diag-name">Approx KL</span>
                        <span class="diag-val">${latest.approx_kl.toFixed(5)}</span>
                    </div>
                    <div class="diag-row">
                        <span class="diag-name">Policy Loss</span>
                        <span class="diag-val">${latest.loss.toFixed(5)}</span>
                    </div>
                `;
            }
        }

        window.onload = init;
    </script>
</body>
</html>
"""

class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        
        if path == "/" or path == "":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
            
        elif path == "/data":
            # Check training activity
            is_active = False
            if os.path.exists(LOG_FILEPATH):
                last_mod = os.path.getmtime(LOG_FILEPATH)
                is_active = (time.time() - last_mod) < 20.0
                
            data = parse_logs(LOG_FILEPATH)
            
            response_data = {
                "active": is_active,
                "latest": data["history"][-1] if data["history"] else None,
                "history": data["history"],
                "reset_stats": data["reset_stats"],
                "recent_resets": data["recent_resets"],
                "total_training_time": data["total_training_time"]
            }
            
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode("utf-8"))
            
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found")

def run_server():
    server_address = ("", PORT)
    httpd = HTTPServer(server_address, DashboardHandler)
    print("="*60)
    print(f" ZEEPKIST AI TELEMETRY SERVER STARTED")
    print(f" Dashboard URL:  http://localhost:{PORT}")
    print(f" OBS Overlay:    http://localhost:{PORT}/?stream=true")
    print(f" Close with Ctrl+C")
    print("="*60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()
        print("Server stopped.")

if __name__ == "__main__":
    run_server()
