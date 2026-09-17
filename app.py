import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify

app = Flask(__name__)
DB_FILE = 'attendance.db'

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Master Workers Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS workers (
            emp_code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT
        )
    ''')
    
    # 2. Daily Attendance Logs Table (Tracks 3 distinct shift slots per day)
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
    
    # Seed sample workers if table is empty
    cursor.execute("SELECT COUNT(*) FROM workers")
    if cursor.fetchone()[0] == 0:
        sample_workers = [
            ('EMP001', 'Rajesh Kumar', 'Production'),
            ('EMP002', 'Amit Sharma', 'Logistics'),
            ('EMP003', 'Sunita Rao', 'Quality Control'),
            ('EMP004', 'Vijay Yadav', 'Maintenance')
        ]
        cursor.executemany("INSERT INTO workers VALUES (?, ?, ?)", sample_workers)
        
    conn.commit()
    conn.close()

@app.route('/')
def index():
    conn = get_db_connection()
    workers = conn.execute("SELECT * FROM workers ORDER BY name ASC").fetchall()
    
    today_str = datetime.today().strftime('%Y-%m-%d')
    logs = conn.execute(
        "SELECT * FROM attendance_logs WHERE log_date = ?", (today_str,)
    ).fetchall()
    conn.close()
    
    log_map = {log['emp_code']: log for log in logs}
    return render_template('dashboard.html', workers=workers, log_map=log_map, today_str=today_str)

@app.route('/submit-attendance', methods=['POST'])
def submit_attendance():
    conn = get_db_connection()
    today_str = datetime.today().strftime('%Y-%m-%d')
    workers = conn.execute("SELECT emp_code FROM workers").fetchall()
    
    for worker in workers:
        code = worker['emp_code']
        m_shift = request.form.get(f'morning_{code}', 'None')
        a_shift = request.form.get(f'afternoon_{code}', 'None')
        n_shift = request.form.get(f'night_{code}', 'None')
        
        conn.execute('''
            INSERT INTO attendance_logs (log_date, emp_code, shift_morning, shift_afternoon, shift_night)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(log_date, emp_code) DO UPDATE SET
                shift_morning=excluded.shift_morning,
                shift_afternoon=excluded.shift_afternoon,
                shift_night=excluded.shift_night
        ''', (today_str, code, m_shift, a_shift, n_shift))
        
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/payroll-report')
def payroll_report():
    conn = get_db_connection()
    # Aggregates records for the current month execution
    current_month = datetime.today().strftime('%Y-%m')
    
    report_query = '''
        SELECT 
            w.emp_code, 
            w.name, 
            w.department,
            COUNT(CASE WHEN al.shift_morning = 'Present' THEN 1 END) +
            COUNT(CASE WHEN al.shift_afternoon = 'Present' THEN 1 END) +
            COUNT(CASE WHEN al.shift_night = 'Present' THEN 1 END) as regular_shifts,
            
            COUNT(CASE WHEN al.shift_morning = 'WOW' THEN 1 END) +
            COUNT(CASE WHEN al.shift_afternoon = 'WOW' THEN 1 END) +
            COUNT(CASE WHEN al.shift_night = 'WOW' THEN 1 END) as weekly_off_worked,
            
            COUNT(CASE WHEN al.shift_morning = 'SL' OR al.shift_afternoon = 'SL' OR al.shift_night = 'SL' THEN 1 END) as sick_leaves,
            COUNT(CASE WHEN al.shift_morning = 'CL' OR al.shift_afternoon = 'CL' OR al.shift_night = 'CL' THEN 1 END) as casual_leaves,
            COUNT(CASE WHEN al.shift_morning = 'PL' OR al.shift_afternoon = 'PL' OR al.shift_night = 'PL' THEN 1 END) as paid_leaves
        FROM workers w
        LEFT JOIN attendance_logs al ON w.emp_code = al.emp_code AND al.log_date LIKE ?
        GROUP BY w.emp_code
    '''
    rows = conn.execute(report_query, (f'{current_month}%',)).fetchall()
    conn.close()
    return render_template('report.html', rows=rows, current_month=current_month)

if __name__ == '__main__':
    init_db()
    # Render binds to port 10000 by default or environment variables
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
