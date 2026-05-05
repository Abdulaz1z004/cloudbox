import os
import boto3
import psycopg2
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
from botocore.exceptions import ClientError
import uuid

app = Flask(__name__)
app.secret_key = os.environ.get('APP_SECRET', 'change-this-in-production')

# ── Configuration (set as environment variables on EC2) ───────────────────────
DATABASE_HOST     = os.environ.get('DATABASE_HOST', 'localhost')
DATABASE_PORT     = os.environ.get('DATABASE_PORT', '5432')
DATABASE_NAME     = os.environ.get('DATABASE_NAME', 'cloudbox')
DATABASE_USER     = os.environ.get('DATABASE_USER', 'cloudbox_admin')
DATABASE_PASSWORD = os.environ.get('DATABASE_PASSWORD', 'changeme')

STORAGE_BUCKET    = os.environ.get('STORAGE_BUCKET', 'cloudbox-files')
CLOUD_REGION      = os.environ.get('CLOUD_REGION', 'us-east-1')

TEMP_UPLOAD_DIR = '/tmp/cloudbox_uploads'
MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500 MB
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

os.makedirs(TEMP_UPLOAD_DIR, exist_ok=True)

# ── DB helpers ─────────────────────────────────────────────────────────────────
def get_db():
    return psycopg2.connect(
        host=DATABASE_HOST, port=DATABASE_PORT,
        dbname=DATABASE_NAME, user=DATABASE_USER, password=DATABASE_PASSWORD
    )

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name VARCHAR(255),
            plan VARCHAR(50) DEFAULT 'Pro',
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS contacts (
            id SERIAL PRIMARY KEY,
            owner_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
            full_name VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL,
            company VARCHAR(255),
            storage_limit VARCHAR(50) DEFAULT '5 GB',
            plan VARCHAR(50) DEFAULT 'Pro',
            status VARCHAR(50) DEFAULT 'Active',
            storage_used VARCHAR(50) DEFAULT '0 MB',
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS uploads (
            id SERIAL PRIMARY KEY,
            owner_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
            filename VARCHAR(500) NOT NULL,
            bucket_key VARCHAR(500) NOT NULL,
            size_bytes BIGINT DEFAULT 0,
            status VARCHAR(50) DEFAULT 'Synced',
            version VARCHAR(20) DEFAULT 'v1',
            uploaded_at TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

# ── S3 helper ──────────────────────────────────────────────────────────────────
def get_storage_client():
    return boto3.client('s3', region_name=CLOUD_REGION)

def readable_size(n):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

def format_date(dt):
    today = datetime.utcnow().date()
    d = dt.date() if hasattr(dt, 'date') else dt
    delta = (today - d).days
    if delta == 0: return 'Today'
    if delta == 1: return 'Yesterday'
    return d.strftime('%b %d')

# ── Context processor – real sidebar storage ───────────────────────────────────
@app.context_processor
def inject_storage_info():
    if 'account_id' not in session:
        return {'sidebar_storage_used': '0 B', 'sidebar_storage_pct': 0}
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(size_bytes),0) FROM uploads WHERE owner_id=%s", (session['account_id'],))
        total = cur.fetchone()[0]
        cur.close()
        conn.close()
    except Exception:
        total = 0
    cap = 10 * 1024 * 1024 * 1024  # 10 GB
    pct = min(int(total / cap * 100), 100)
    return {'sidebar_storage_used': readable_size(total), 'sidebar_storage_pct': pct}

# ── Auth routes ────────────────────────────────────────────────────────────────
@app.route('/', methods=['GET', 'POST'])
def login():
    if 'account_id' in session:
        return redirect(url_for('dashboard'))
    error = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT id, password_hash, full_name, plan FROM accounts WHERE email=%s", (email,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row and check_password_hash(row[1], password):
                session['account_id'] = row[0]
                session['account_name'] = row[2] or email.split('@')[0]
                session['account_plan'] = row[3]
                return redirect(url_for('dashboard'))
            else:
                error = 'Invalid email or password.'
        except Exception as e:
            error = f'Database error: {e}'
    return render_template('login.html', error=error)

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if not email or not password:
            error = 'Email and password are required.'
        else:
            try:
                conn = get_db()
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO accounts (email, password_hash, full_name) VALUES (%s,%s,%s)",
                    (email, generate_password_hash(password), full_name)
                )
                conn.commit()
                cur.close()
                conn.close()
                flash('Account created! Please sign in.')
                return redirect(url_for('login'))
            except psycopg2.errors.UniqueViolation:
                error = 'Email already registered.'
            except Exception as e:
                error = f'Error: {e}'
    return render_template('register.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ── Dashboard ──────────────────────────────────────────────────────────────────
@app.route('/dashboard')
def dashboard():
    if 'account_id' not in session:
        return redirect(url_for('login'))
    uid = session['account_id']
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT filename, size_bytes, status, version, uploaded_at FROM uploads WHERE owner_id=%s ORDER BY uploaded_at DESC", (uid,))
        raw_files = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM uploads WHERE owner_id=%s", (uid,))
        file_count = cur.fetchone()[0]
        cur.execute("SELECT COALESCE(SUM(size_bytes),0) FROM uploads WHERE owner_id=%s", (uid,))
        total_bytes = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM contacts WHERE owner_id=%s", (uid,))
        contact_count = cur.fetchone()[0]
        cur.close()
        conn.close()
    except Exception as e:
        flash(f'DB error: {e}')
        raw_files, file_count, total_bytes, contact_count = [], 0, 0, 0

    file_list = [
        {'name': r[0], 'size': readable_size(r[1]), 'status': r[2], 'version': r[3], 'modified': format_date(r[4])}
        for r in raw_files
    ]
    return render_template('dashboard.html',
        files=file_list, file_count=file_count,
        storage_used=readable_size(total_bytes), shared_links=contact_count)

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'account_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        f = request.files.get('file')
        if not f or f.filename == '':
            flash('No file selected.')
            return redirect(url_for('upload'))
        filename = secure_filename(f.filename)
        uid = session['account_id']
        bucket_key = f"accounts/{uid}/{uuid.uuid4().hex}_{filename}"
        tmp_path = os.path.join(TEMP_UPLOAD_DIR, filename)
        f.save(tmp_path)
        file_size = os.path.getsize(tmp_path)
        try:
            client = get_storage_client()
            client.upload_file(tmp_path, STORAGE_BUCKET, bucket_key)
        except ClientError as e:
            flash(f'Storage upload failed: {e}')
            os.remove(tmp_path)
            return redirect(url_for('upload'))
        os.remove(tmp_path)
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO uploads (owner_id, filename, bucket_key, size_bytes) VALUES (%s,%s,%s,%s)",
                (uid, filename, bucket_key, file_size)
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            flash(f'DB error saving record: {e}')
        flash(f'"{filename}" uploaded successfully!')
        return redirect(url_for('dashboard'))
    return render_template('upload.html')

# ── Contacts (Clients) dashboard ───────────────────────────────────────────────
@app.route('/contacts')
def contacts():
    if 'account_id' not in session:
        return redirect(url_for('login'))
    uid = session['account_id']
    page = int(request.args.get('page', 1))
    per_page = 5
    offset = (page - 1) * per_page
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM contacts WHERE owner_id=%s", (uid,))
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT id,full_name,email,company,storage_used,status FROM contacts WHERE owner_id=%s ORDER BY id LIMIT %s OFFSET %s",
            (uid, per_page, offset)
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        flash(f'DB error: {e}')
        rows, total = [], 0

    contact_list = [
        {'id': r[0], 'full_name': r[1], 'email': r[2],
         'company': r[3] or '', 'storage_used': r[4] or '0 MB', 'status': r[5]}
        for r in rows
    ]
    total_pages = max(1, (total + per_page - 1) // per_page)
    return render_template('contacts.html',
        contacts=contact_list, page=page, total_pages=total_pages, total=total)

@app.route('/contacts/add', methods=['POST'])
def add_contact():
    if 'account_id' not in session:
        return redirect(url_for('login'))
    uid = session['account_id']
    full_name = request.form.get('full_name', '').strip()
    email = request.form.get('email', '').strip().lower()
    company = request.form.get('company', '').strip()
    storage_limit = request.form.get('storage_limit', '5 GB')
    plan = request.form.get('plan', 'Pro')
    status = request.form.get('status', 'Active')
    if not full_name or not email:
        flash('Name and email are required.')
        return redirect(url_for('contacts'))
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO contacts (owner_id,full_name,email,company,storage_limit,plan,status) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (uid, full_name, email, company, storage_limit, plan, status)
        )
        conn.commit()
        cur.close()
        conn.close()
        flash('Contact added successfully.')
    except Exception as e:
        flash(f'Error: {e}')
    return redirect(url_for('contacts'))

@app.route('/contacts/edit/<int:cid>', methods=['POST'])
def edit_contact(cid):
    if 'account_id' not in session:
        return redirect(url_for('login'))
    uid = session['account_id']
    full_name = request.form.get('full_name', '').strip()
    email = request.form.get('email', '').strip().lower()
    company = request.form.get('company', '').strip()
    storage_limit = request.form.get('storage_limit', '5 GB')
    plan = request.form.get('plan', 'Pro')
    status = request.form.get('status', 'Active')
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE contacts SET full_name=%s,email=%s,company=%s,storage_limit=%s,plan=%s,status=%s WHERE id=%s AND owner_id=%s",
            (full_name, email, company, storage_limit, plan, status, cid, uid)
        )
        conn.commit()
        cur.close()
        conn.close()
        flash('Contact updated.')
    except Exception as e:
        flash(f'Error: {e}')
    return redirect(url_for('contacts'))

@app.route('/contacts/delete/<int:cid>', methods=['POST'])
def delete_contact(cid):
    if 'account_id' not in session:
        return redirect(url_for('login'))
    uid = session['account_id']
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM contacts WHERE id=%s AND owner_id=%s", (cid, uid))
        conn.commit()
        cur.close()
        conn.close()
        flash('Contact deleted.')
    except Exception as e:
        flash(f'Error: {e}')
    return redirect(url_for('contacts'))

@app.route('/contacts/get/<int:cid>')
def get_contact(cid):
    if 'account_id' not in session:
        return jsonify({}), 401
    uid = session['account_id']
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id,full_name,email,company,storage_limit,plan,status FROM contacts WHERE id=%s AND owner_id=%s", (cid, uid))
    r = cur.fetchone()
    cur.close()
    conn.close()
    if not r:
        return jsonify({}), 404
    return jsonify({'id':r[0],'full_name':r[1],'email':r[2],'company':r[3],'storage_limit':r[4],'plan':r[5],'status':r[6]})

# ── Boot ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    try:
        init_db()
    except Exception as e:
        print(f"[WARN] DB init skipped: {e}")
    app.run(host='0.0.0.0', port=5000, debug=False)
