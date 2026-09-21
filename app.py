import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, abort

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "factory-ultra-secure-key-2026!")
DB_FILE = 'attendance.db'

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Master Workers
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS workers (
            emp_code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT
        )
    ''')
    
    # 2. Shift Tracking Logs
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date TEXT NOT NULL,
            emp_code TEXT NOT NULL,
            shift_morning TEXT DEFAULT 'None',
            shift_afternoon TEXT DEFAULT 'None',
            shift_night TEXT DEFAULT 'None',
            FOREIGN KEY (emp_code) REFERENCES workers (emp_code),
            UNIQUE(log_date, emp_code)
        )
    ''')
    
    # 3. Secure Role Authentication
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT DEFAULT 'active'
        )
    ''')
    
    # Seed default Master Account if empty
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO users VALUES (?, ?, ?, ?)", ('admin', 'adminpassword', 'admin', 'active'))
        
    conn.commit()
    conn.close()

def require_login():
    if 'username' not in session: return False
    conn = get_db_connection()
    user = conn.execute("SELECT status FROM users WHERE username = ?", (session['username'],)).fetchone()
    conn.close()
    if not user or user['status'] != 'active':
        session.clear()
        return False
    return True

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password').strip()
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()
        conn.close()
        if user and user['status'] == 'active':
            session['username'] = user['username']
            session['role'] = user['role']
            return redirect(url_for('index'))
        return render_template('login.html', error="Access Denied. Invalid parameters.")
    return render_template('login.html', error=None)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def index():
    if not require_login(): return redirect(url_for('login'))
    today_str = datetime.today().strftime('%Y-%m-%d')
    selected_date = request.args.get('date', today_str)
    
    if session['role'] == 'supervisor' and selected_date != today_str:
        return redirect(url_for('index', date=today_str))
        
    conn = get_db_connection()
    workers = conn.execute("SELECT * FROM workers ORDER BY emp_code ASC").fetchall()
    logs = conn.execute("SELECT * FROM attendance_logs WHERE log_date = ?", (selected_date,)).fetchall()
    supervisors = conn.execute("SELECT * FROM users WHERE role = 'supervisor'").fetchall()
    conn.close()
    
    log_map = {log['emp_code']: log for log in logs}
    return render_template('dashboard.html', workers=workers, log_map=log_map, today_str=selected_date, supervisors=supervisors)

@app.route('/submit-attendance', methods=['POST'])
def submit_attendance():
    if not require_login(): return redirect(url_for('login'))
    today_str = datetime.today().strftime('%Y-%m-%d')
    target_date = request.form.get('target_date', today_str)
    if session['role'] == 'supervisor': target_date = today_str
    
    conn = get_db_connection()
    workers = conn.execute("SELECT emp_code FROM workers").fetchall()
    for worker in workers:
        code = worker['emp_code']
        m = request.form.get(f'morning_{code}', 'None')
        a = request.form.get(f'afternoon_{code}', 'None')
        n = request.form.get(f'night_{code}', 'None')
        conn.execute('''
            INSERT INTO attendance_logs (log_date, emp_code, shift_morning, shift_afternoon, shift_night)
            VALUES (?, ?, ?, ?, ?) ON CONFLICT(log_date, emp_code) DO UPDATE SET
            shift_morning=excluded.shift_morning, shift_afternoon=excluded.shift_afternoon, shift_night=excluded.shift_night
        ''', (target_date, code, m, a, n))
    conn.commit()
    conn.close()
    return redirect(url_for('index', date=target_date))

@app.route('/add-worker', methods=['POST'])
def add_worker():
    if not require_login() or session['role'] != 'admin': abort(403)
    code = request.form.get('emp_code').strip().upper()
    name = request.form.get('name').strip()
    dept = request.form.get('department').strip()
    if code and name:
        conn = get_db_connection()
        try: conn.execute("INSERT INTO workers VALUES (?, ?, ?)", (code, name, dept)); conn.commit()
        except sqlite3.IntegrityError: pass
        conn.close()
    return redirect(url_for('index'))

@app.route('/manage-supervisor', methods=['POST'])
def manage_supervisor():
    if not require_login() or session['role'] != 'admin': abort(403)
    action = request.form.get('action')
    username = request.form.get('username').strip()
    password = request.form.get('password').strip()
    conn = get_db_connection()
    if action == 'create' and username and password:
        try: conn.execute("INSERT INTO users VALUES (?, ?, 'supervisor', 'active')", (username, password))
        except sqlite3.IntegrityError: pass
    elif action == 'toggle':
        current = conn.execute("SELECT status FROM users WHERE username = ?", (username,)).fetchone()
        if current:
            nxt = 'inactive' if current['status'] == 'active' else 'active'
            conn.execute("UPDATE users SET status = ? WHERE username = ?", (nxt, username))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/change-password', methods=['POST'])
def change_password():
    if not require_login(): return redirect(url_for('login'))
    new_p = request.form.get('new_password').strip()
    if new_p:
        conn = get_db_connection()
        conn.execute("UPDATE users SET password = ? WHERE username = ?", (new_p, session['username']))
        conn.commit()
        conn.close()
    return redirect(url_for('index'))

@app.route('/payroll-report')
def payroll_report():
    if not require_login() or session['role'] != 'admin': abort(403)
    current_month = request.args.get('month', datetime.today().strftime('%Y-%m'))
    conn = get_db_connection()
    report_query = '''
        SELECT w.emp_code, w.name, w.department,
            COUNT(CASE WHEN al.shift_morning = 'Present' THEN 1 END) + COUNT(CASE WHEN al.shift_afternoon = 'Present' THEN 1 END) + COUNT(CASE WHEN al.shift_night = 'Present' THEN 1 END) as regular_shifts,
            COUNT(CASE WHEN al.shift_morning = 'WOW' THEN 1 END) + COUNT(CASE WHEN al.shift_afternoon = 'WOW' THEN 1 END) + COUNT(CASE WHEN al.shift_night = 'WOW' THEN 1 END) as weekly_off_worked,
            COUNT(CASE WHEN al.shift_morning = 'SL' OR al.shift_afternoon = 'SL' OR al.shift_night = 'SL' THEN 1 END) as sick_leaves,
            COUNT(CASE WHEN al.shift_morning = 'CL' OR al.shift_afternoon = 'CL' OR al.shift_night = 'CL' THEN 1 END) as casual_leaves,
            COUNT(CASE WHEN al.shift_morning = 'PL' OR al.shift_afternoon = 'PL' OR al.shift_night = 'PL' THEN 1 END) as paid_leaves
        FROM workers w LEFT JOIN attendance_logs al ON w.emp_code = al.emp_code AND al.log_date LIKE ?
        GROUP BY w.emp_code ORDER BY w.emp_code ASC
    '''
    rows = conn.execute(report_query, (f'{current_month}%',)).fetchall()
    conn.close()
    return render_template('report.html', rows=rows, current_month=current_month)

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
