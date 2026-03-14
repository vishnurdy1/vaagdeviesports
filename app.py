from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import sqlite3
import os

app = Flask(__name__, template_folder='.')
app.secret_key = 'esports_secret_key_123'
ADMIN_PASSWORD = 'admin'

DB_PATH = os.path.join(os.path.dirname(__file__), 'database.db')

# ─────────────────────────────────────────
#  BGMI-style placement points table
# ─────────────────────────────────────────
PLACEMENT_POINTS = {
    1: 15,
    2: 12,
    3: 10,
    4: 8,
    5: 6,
}

def get_placement_points(placement: int) -> int:
    if placement in PLACEMENT_POINTS:
        return PLACEMENT_POINTS[placement]
    elif 6 <= placement <= 10:
        return 4
    elif 11 <= placement <= 15:
        return 2
    else:
        return 0


# ─────────────────────────────────────────
#  Database helpers
# ─────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist and seed demo data."""
    conn = get_db()
    cur = conn.cursor()
    
    # Leaderboard table (Live standing)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leaderboard (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            team_name TEXT    UNIQUE NOT NULL,
            kills     INTEGER DEFAULT 0,
            placement INTEGER DEFAULT 0,
            points    INTEGER DEFAULT 0
        )
    """)
    
    # Registered Teams table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            team_name    TEXT    UNIQUE NOT NULL,
            captain_name TEXT,
            game         TEXT    CHECK(game IN ('BGMI', 'Free Fire')),
            members      TEXT,   -- Comma separated names
            uid_branch   TEXT,   -- Branch/UID
            year         TEXT    -- Year of college
        )
    """)

    # Match Logs table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS match_logs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            team_name    TEXT    NOT NULL,
            kills        INTEGER NOT NULL,
            placement    INTEGER NOT NULL,
            points       INTEGER NOT NULL,
            match_number INTEGER NOT NULL,
            timestamp    DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Match Schedule table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schedule (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            match_number INTEGER NOT NULL,
            game         TEXT    NOT NULL,
            map_name     TEXT    NOT NULL,
            start_time   TEXT    NOT NULL,
            status       TEXT    DEFAULT 'Upcoming'
        )
    """)

    # Seed default schedule if empty
    cur.execute("SELECT COUNT(*) FROM schedule")
    if cur.fetchone()[0] == 0:
        cur.executemany("""
            INSERT INTO schedule (match_number, game, map_name, start_time, status)
            VALUES (?, ?, ?, ?, ?)
        """, [
            (1, "BGMI", "Erangel", "10:00 AM", "Finished"),
            (2, "BGMI", "Miramar", "11:00 AM", "Live"),
            (3, "Free Fire", "Bermuda", "12:00 PM", "Upcoming")
        ])

    # Global Settings table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Seed default settings
    default_settings = {
        "tournament_name": "VAAGDEVI ESPORTS",
        "game_mode":       "BGMI",
        "map_name":       "Erangel",
        "match_number":   "1",
        "num_teams":      "18",
        "next_match":     "Free Fire",
        "match_status":   "Upcoming",
        "youtube_url":     "",
        "stream_mode":     "upcoming",
        "break_message":   "Stay tuned! Next match loading...",
        "registration_url": "https://docs.google.com/forms/d/e/1FAIpQLSfI9d59zR6A4m84xC7Mr5-YYVhHyUd33aNUgapUxJ6IWSmTEA/viewform"
    }
    for k, v in default_settings.items():
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    # Seed some demo teams if table is empty
    cur.execute("SELECT COUNT(*) FROM leaderboard")
    if cur.fetchone()[0] == 0:
        seed_teams = [
            ("Team Alpha",   12, 1),
            ("Shadow Strike", 9, 2),
            ("BloodRush",     7, 3),
            ("NightHawks",    5, 4),
            ("Phoenix Squad", 4, 5),
        ]
        for name, kills, placement in seed_teams:
            pts = kills + get_placement_points(placement)
            cur.execute(
                "INSERT INTO leaderboard (team_name, kills, placement, points) VALUES (?, ?, ?, ?)",
                (name, kills, placement, pts)
            )
            cur.execute(
                "INSERT OR IGNORE INTO teams (team_name, captain_name, game) VALUES (?, ?, ?)",
                (name, "Captain " + name.split()[0], "BGMI")
            )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────
#  Page Routes
# ─────────────────────────────────────────
@app.route('/')
def home():
    return render_template('home.html')


@app.route('/tournament')
def tournament():
    return render_template('tournament.html')


@app.route('/admin')
def admin():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('admin_panel.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin'))
        else:
            return render_template('login.html', error="Invalid password!")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('home'))


# ─────────────────────────────────────────
#  API: GET /api/leaderboard
# ─────────────────────────────────────────
@app.route('/api/leaderboard', methods=['GET'])
def api_leaderboard():
    conn = get_db()
    rows = conn.execute(
        "SELECT team_name, kills, placement, points FROM leaderboard ORDER BY points DESC"
    ).fetchall()
    conn.close()
    data = [
        {
            "rank":       idx + 1,
            "team_name":  row["team_name"],
            "kills":      row["kills"],
            "placement":  row["placement"],
            "points":     row["points"],
        }
        for idx, row in enumerate(rows)
    ]
    return jsonify(data)


# ─────────────────────────────────────────
#  API: POST /api/update_score
# ─────────────────────────────────────────
@app.route('/api/update_score', methods=['POST'])
def api_update_score():
    if not session.get('logged_in'):
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.get_json(silent=True) or request.form
    team_name = (data.get('team_name') or '').strip()
    kills     = data.get('kills', 0)
    placement = data.get('placement', 0)

    if not team_name:
        return jsonify({"success": False, "message": "Team name is required."}), 400

    try:
        kills     = int(kills)
        placement = int(placement)
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Kills and placement must be numbers."}), 400

    if kills < 0 or placement < 1:
        return jsonify({"success": False, "message": "Kills must be ≥ 0 and placement must be ≥ 1."}), 400

    placement_pts = get_placement_points(placement)
    total_points  = kills + placement_pts

    conn = get_db()
    try:
        # Update Leaderboard
        conn.execute("""
            INSERT INTO leaderboard (team_name, kills, placement, points)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(team_name) DO UPDATE SET
                kills     = leaderboard.kills + excluded.kills,
                placement = excluded.placement,
                points    = leaderboard.points + excluded.points
        """, (team_name, kills, placement, total_points))
        
        # Add to Match Logs
        match_number = conn.execute("SELECT value FROM settings WHERE key='match_number'").fetchone()["value"]
        conn.execute("""
            INSERT INTO match_logs (team_name, kills, placement, points, match_number)
            VALUES (?, ?, ?, ?, ?)
        """, (team_name, kills, placement, total_points, match_number))
        
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "message": str(e)}), 500
    conn.close()

    return jsonify({
        "success":          True,
        "message":          f"Score updated for {team_name}!",
        "team_name":        team_name,
        "kills":            kills,
        "placement":        placement,
        "placement_points": placement_pts,
        "total_points":     total_points,
    })


# ─────────────────────────────────────────
#  API: POST /api/reset_scores
# ─────────────────────────────────────────
@app.route('/api/reset_scores', methods=['POST'])
def api_reset_scores():
    if not session.get('logged_in'):
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    conn = get_db()
    try:
        conn.execute("DELETE FROM leaderboard")
        conn.execute("DELETE FROM match_logs")
        conn.commit()
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        conn.close()
        
    return jsonify({"success": True, "message": "All scores and logs have been cleared."})


# ─────────────────────────────────────────
#  API: POST /api/sync_leaderboard
# ─────────────────────────────────────────
@app.route('/api/sync_leaderboard', methods=['POST'])
def api_sync_leaderboard():
    if not session.get('logged_in'):
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    conn = get_db()
    try:
        # Wipe leaderboard and rebuild from logs
        conn.execute("DELETE FROM leaderboard")
        
        # Get summed kills and points per team
        rows = conn.execute("""
            SELECT team_name, SUM(kills) as tk, SUM(points) as tp, MAX(placement) as lp
            FROM match_logs 
            GROUP BY team_name
        """).fetchall()
        
        for r in rows:
            conn.execute("""
                INSERT INTO leaderboard (team_name, kills, placement, points)
                VALUES (?, ?, ?, ?)
            """, (r["team_name"], r["tk"], r["lp"], r["tp"]))
        
        conn.commit()
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        conn.close()
        
    return jsonify({"success": True, "message": "Leaderboard recalulated and synced!"})


# ─────────────────────────────────────────
#  Teams API
# ─────────────────────────────────────────
@app.route('/api/teams', methods=['GET', 'POST'])
def api_teams():
    conn = get_db()
    if request.method == 'GET':
        rows = conn.execute("SELECT * FROM teams ORDER BY team_name ASC").fetchall()
        conn.close()
        return jsonify([dict(row) for row in rows])
    
    if not session.get('logged_in'):
        return jsonify({"success": False, "message": "Unauthorized"}), 401
        
    data = request.get_json()
    try:
        conn.execute("INSERT INTO teams (team_name, captain_name, game, members, uid_branch, year) VALUES (?, ?, ?, ?, ?, ?)",
                    (data['team_name'], data['captain_name'], data['game'], data.get('members', ''), data.get('uid_branch', ''), data.get('year', '')))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400
    finally:
        conn.close()

@app.route('/api/teams/<int:team_id>', methods=['DELETE', 'PUT'])
def api_team_detail(team_id):
    if not session.get('logged_in'):
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    conn = get_db()
    if request.method == 'DELETE':
        conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))
    elif request.method == 'PUT':
        data = request.get_json()
        conn.execute("UPDATE teams SET team_name=?, captain_name=?, game=?, members=?, uid_branch=?, year=? WHERE id=?",
                    (data['team_name'], data['captain_name'], data['game'], data.get('members', ''), data.get('uid_branch', ''), data.get('year', ''), team_id))
    
    conn.commit()
    conn.close()
    return jsonify({"success": True})


# ─────────────────────────────────────────
#  Schedule API
# ─────────────────────────────────────────
@app.route('/api/schedule', methods=['GET', 'POST'])
def api_schedule():
    conn = get_db()
    if request.method == 'GET':
        rows = conn.execute("SELECT * FROM schedule ORDER BY match_number ASC").fetchall()
        conn.close()
        return jsonify([dict(row) for row in rows])
    
    if not session.get('logged_in'):
        return jsonify({"success": False, "message": "Unauthorized"}), 401
        
    data = request.get_json()
    conn.execute("INSERT INTO schedule (match_number, game, map_name, start_time, status) VALUES (?, ?, ?, ?, ?)",
                (data['match_number'], data['game'], data['map_name'], data['start_time'], data.get('status', 'Upcoming')))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/api/schedule/<int:sid>', methods=['DELETE', 'PUT'])
def api_schedule_detail(sid):
    if not session.get('logged_in'):
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    conn = get_db()
    if request.method == 'DELETE':
        conn.execute("DELETE FROM schedule WHERE id = ?", (sid,))
    elif request.method == 'PUT':
        data = request.get_json()
        conn.execute("UPDATE schedule SET match_number=?, game=?, map_name=?, start_time=?, status=? WHERE id=?",
                    (data['match_number'], data['game'], data['map_name'], data['start_time'], data['status'], sid))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


# ─────────────────────────────────────────
#  Team Stats API (For Dashboard)
# ─────────────────────────────────────────
@app.route('/api/team_stats', methods=['GET'])
def api_team_stats():
    conn = get_db()
    # Join teams with leaderboard to get kills and points
    rows = conn.execute("""
        SELECT t.id, t.team_name, t.game, t.captain_name, t.members, t.uid_branch, t.year,
               COALESCE(SUM(l.kills), 0) as kills,
               COALESCE(SUM(l.points), 0) as points
        FROM teams t
        LEFT JOIN match_logs l ON t.team_name = l.team_name
        GROUP BY t.id, t.team_name, t.game, t.captain_name, t.members, t.uid_branch, t.year
        ORDER BY points DESC, kills DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


# ─────────────────────────────────────────
#  Logs API
# ─────────────────────────────────────────
@app.route('/api/logs', methods=['GET'])
def api_logs():
    conn = get_db()
    rows = conn.execute("SELECT * FROM match_logs ORDER BY timestamp DESC").fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])

@app.route('/api/logs/<int:log_id>', methods=['DELETE'])
def api_delete_log(log_id):
    if not session.get('logged_in'):
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    conn = get_db()
    try:
        conn.execute("DELETE FROM match_logs WHERE id = ?", (log_id,))
        conn.commit()
        # Note: Leaderboard will be out of sync until a manual Sync is triggered
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"success": True})


# ─────────────────────────────────────────
#  Settings API
# ─────────────────────────────────────────
@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    conn = get_db()
    if request.method == 'GET':
        rows = conn.execute("SELECT * FROM settings").fetchall()
        conn.close()
        return jsonify({row["key"]: row["value"] for row in rows})
    
    if not session.get('logged_in'):
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.get_json()
    print(f"[LOG] Received settings update: {data}")
    for k, v in data.items():
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, str(v)))
    
    conn.commit()
    conn.close()
    return jsonify({"success": True})


# ─────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────
# Run initialization here so it works on deployment servers (Gunicorn)
init_db()

if __name__ == '__main__':
    print("\n[+] TECHNOCRAFT x VAAGTARANG Esports Server running!")
    print("   Home      -> http://localhost:5000/")
    print("   Tournament-> http://localhost:5000/tournament")
    print("   Admin     -> http://localhost:5000/admin\n")
    app.run(debug=True, host='0.0.0.0', port=5000)
