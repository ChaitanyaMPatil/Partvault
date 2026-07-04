# C:\UI\bulk_imports.py
r"""
PartVault Bulk Importer — tuned for Part_list.csv column layout.

CSV columns detected:
  Material Number (external)                      -> part_number
  Material Description                            -> name + description
  Vehicle Maintenance Reporting Standards code    -> vmrs_code
  Attribute status                                -> status
  US Vendor Name                                  -> vendor (appended to description)
  Inactive/FS                                     -> skips Inactive rows
  trim part                                       -> ignored

Usage:
    python bulk_imports.py "C:\UI\Part_list.csv"
    python bulk_imports.py "C:\UI\Part_list.csv" demo 5000
"""

import csv
import sqlite3
import sys
import os
import time
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────
DB_PATH        = r'C:\UI\partvault.db'
DEFAULT_USER   = 'demo'
DEFAULT_BATCH  = 5000
VALID_STATUSES = {'Pending', 'InProgress', 'Done', 'Outlier'}

# ── YOUR EXACT CSV COLUMN NAMES ───────────────────────────────────────────────
COL_PART_NUMBER = 'Material Number (external)'
COL_NAME        = 'Material Description'
COL_DESCRIPTION = 'Material Description'
COL_VMRS        = 'Vehicle Maintenance Reporting Standards code'
COL_STATUS      = 'Attribute status'
COL_VENDOR      = 'US Vendor Name'
COL_INACTIVE    = 'Inactive/FS'

# ── STATUS VALUE MAPPING ──────────────────────────────────────────────────────
STATUS_MAP = {
    'complete':    'Done',
    'completed':   'Done',
    'done':        'Done',
    'in progress': 'InProgress',
    'inprogress':  'InProgress',
    'wip':         'InProgress',
    'pending':     'Pending',
    'new':         'Pending',
    'open':        'Pending',
    'outlier':     'Outlier',
    'flagged':     'Outlier',
    '':            'Pending',
}

SKIP_INACTIVE = True


# ─────────────────────────────────────────────────────────────────────────────
def run(csv_path, assign_to=DEFAULT_USER, batch_size=DEFAULT_BATCH):

    # ── Clean path ────────────────────────────────────────────────────────────
    csv_path = csv_path.strip().strip('"').strip("'").strip()
    csv_path = os.path.normpath(csv_path)

    print('\n' + '='*62)
    print('  PartVault Bulk Importer')
    print('='*62)
    print('  CSV    :', csv_path)
    print('  CSV?   :', 'Found' if os.path.exists(csv_path) else 'NOT FOUND')
    print('  DB     :', DB_PATH)
    print('  DB?    :', 'Found' if os.path.exists(DB_PATH) else 'NOT FOUND')
    print('-'*62)

    if not os.path.exists(csv_path):
        _suggest_csv(csv_path)
        sys.exit(1)

    if not os.path.exists(DB_PATH):
        print('\nDB not found. Run  python app.py  first.\n')
        sys.exit(1)

    # ── Connect ───────────────────────────────────────────────────────────────
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()

    # ── Lookup user ───────────────────────────────────────────────────────────
    cur.execute('SELECT id FROM users WHERE username = ?', (assign_to,))
    row = cur.fetchone()
    if not row:
        conn.close()
        print('\nUser "' + assign_to + '" not found. Run python app.py first.\n')
        sys.exit(1)
    user_id = row['id']
    print('\n  User   :', assign_to, ' id=' + str(user_id))

    # ── VMRS lookup ───────────────────────────────────────────────────────────
    cur.execute('SELECT id, code FROM vmrs')
    vmrs_map = {r['code']: r['id'] for r in cur.fetchall()}
    print('  VMRS   :', sorted(vmrs_map.keys()))

    # ── Attribute counts ──────────────────────────────────────────────────────
    cur.execute('''
        SELECT vmrs_id,
               COUNT(*) AS total,
               SUM(CASE WHEN classification="Mandatory" THEN 1 ELSE 0 END) AS mand
        FROM attribute_definitions
        GROUP BY vmrs_id
    ''')
    attr_counts = {r['vmrs_id']: (r['mand'], r['total']) for r in cur.fetchall()}

    # ── Existing part numbers ─────────────────────────────────────────────────
    print('  Loading existing part numbers...', end=' ', flush=True)
    cur.execute('SELECT part_number FROM parts')
    existing = {r[0] for r in cur.fetchall()}
    print(str(len(existing)) + ' found')

    # ── Encoding + row count ──────────────────────────────────────────────────
    encoding = _detect_encoding(csv_path)
    print('  Encoding :', encoding)

    print('  Counting rows...', end=' ', flush=True)
    with open(csv_path, 'r', encoding=encoding, errors='replace') as f:
        total_csv = max(0, sum(1 for _ in f) - 1)
    sz_mb = os.path.getsize(csv_path) / 1024 / 1024
    print(str(total_csv) + ' rows  (' + str(round(sz_mb, 2)) + ' MB)')

    # ── Validate columns ──────────────────────────────────────────────────────
    with open(csv_path, newline='', encoding=encoding, errors='replace') as f:
        sample_headers = next(csv.reader(f))

    print('\n  CSV columns found:')
    for h in sample_headers:
        print('    · "' + h + '"')

    for required in [COL_PART_NUMBER, COL_NAME]:
        if required not in sample_headers:
            print('\nRequired column not found: "' + required + '"')
            print('Available: ' + str(sample_headers))
            conn.close()
            sys.exit(1)

    print('\n  Column mapping:')
    print('    part_number  <- "' + COL_PART_NUMBER + '"')
    print('    name         <- "' + COL_NAME + '"')
    vmrs_status = 'OK' if COL_VMRS in sample_headers else 'NOT FOUND - parts unassigned'
    stat_status = 'OK' if COL_STATUS in sample_headers else 'NOT FOUND - default Pending'
    print('    vmrs_code    <- "' + COL_VMRS + '"  [' + vmrs_status + ']')
    print('    status       <- "' + COL_STATUS + '"  [' + stat_status + ']')
    print('    vendor       <- "' + COL_VENDOR + '"')

    # ── Show status values in CSV ─────────────────────────────────────────────
    _sample_status_values(csv_path, encoding,
                          COL_STATUS if COL_STATUS in sample_headers else None)

    # ── Performance PRAGMAs ───────────────────────────────────────────────────
    cur.executescript('''
        PRAGMA journal_mode  = WAL;
        PRAGMA synchronous   = NORMAL;
        PRAGMA cache_size    = -131072;
        PRAGMA temp_store    = MEMORY;
        PRAGMA mmap_size     = 1073741824;
        PRAGMA locking_mode  = EXCLUSIVE;
    ''')
    print('\n  SQLite performance mode ON (WAL + 128MB cache)')
    print('\n  Starting import...\n')

    # ── INSERT SQL ────────────────────────────────────────────────────────────
    INSERT_SQL = '''
        INSERT OR IGNORE INTO parts
            (part_number, name, description, vmrs_id, assigned_to,
             status, assigned_date,
             outlier_flag, outlier_count,
             mandatory_total, mandatory_filled, attr_count,
             updated_at)
        VALUES (?,?,?,?,?,?,?,0,0,?,0,?,?)
    '''

    now_str  = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    inserted = 0
    skipped  = 0
    inactive = 0
    errors   = 0
    batch    = []
    t_start  = time.time()

    with open(csv_path, newline='', encoding=encoding, errors='replace') as f:
        reader = csv.DictReader(f)

        for row_n, row in enumerate(reader, 1):
            try:
                # ── Part number ───────────────────────────────────────────────
                pn = (row.get(COL_PART_NUMBER) or '').strip()
                if not pn:
                    skipped += 1
                    continue

                # ── Skip inactive ─────────────────────────────────────────────
                if SKIP_INACTIVE:
                    inact_val = (row.get(COL_INACTIVE) or '').strip().lower()
                    if inact_val in ('inactive', 'yes', 'y', '1', 'true', 'x'):
                        inactive += 1
                        continue

                # ── Dedup ─────────────────────────────────────────────────────
                if pn in existing:
                    skipped += 1
                    continue

                # ── Name ──────────────────────────────────────────────────────
                name = (row.get(COL_NAME) or '').strip() or pn

                # ── Description + vendor ──────────────────────────────────────
                desc   = (row.get(COL_DESCRIPTION) or name).strip()
                vendor = (row.get(COL_VENDOR) or '').strip()
                if vendor:
                    desc = desc + ' | Vendor: ' + vendor if desc else 'Vendor: ' + vendor

                # ── VMRS ──────────────────────────────────────────────────────
                vmrs_raw  = (row.get(COL_VMRS) or '').strip()
                vmrs_code = vmrs_raw.zfill(3) if vmrs_raw.isdigit() else vmrs_raw
                vmrs_id   = vmrs_map.get(vmrs_code) or vmrs_map.get(vmrs_raw)

                # ── Status ────────────────────────────────────────────────────
                status_raw = (row.get(COL_STATUS) or '').strip()
                status     = STATUS_MAP.get(status_raw.lower(), 'Pending')

                # ── Attr counts ───────────────────────────────────────────────
                m_tot, a_tot = attr_counts.get(vmrs_id, (0, 0)) if vmrs_id else (0, 0)

                batch.append((
                    pn, name, desc, vmrs_id, user_id,
                    status, now_str,
                    m_tot, a_tot,
                    now_str
                ))
                existing.add(pn)

            except Exception as e:
                errors += 1
                if errors <= 5:
                    print('\n  Row ' + str(row_n) + ' error: ' + str(e))
                continue

            # ── Flush batch ───────────────────────────────────────────────────
            if len(batch) >= batch_size:
                cur.executemany(INSERT_SQL, batch)
                conn.commit()
                inserted += len(batch)
                batch = []
                _print_progress(row_n, total_csv, inserted, skipped, inactive, t_start)

        # ── Final batch ───────────────────────────────────────────────────────
        if batch:
            cur.executemany(INSERT_SQL, batch)
            conn.commit()
            inserted += len(batch)

    total_time = time.time() - t_start
    rate = inserted / total_time if total_time > 0 else 0

    print('\n\n' + '='*62)
    print('  Import finished in ' + _fmt(total_time))
    print('  Inserted  : ' + str(inserted))
    print('  Skipped   : ' + str(skipped) + '  (duplicates / empty)')
    print('  Inactive  : ' + str(inactive) + '  (Inactive/FS rows)')
    print('  Errors    : ' + str(errors))
    print('  Speed     : ' + str(round(rate)) + ' rows/second')
    print('='*62)

    print('\n  Releasing database lock...', end=' ', flush=True)

    # Commit any remaining data
    conn.commit()

    # Release exclusive lock BEFORE rebuilding FTS
    cur.execute('PRAGMA locking_mode = NORMAL')

    # Force a checkpoint to merge WAL back into main DB
    cur.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    conn.commit()
    print('released')

    # NOW rebuild FTS (runs in normal lock mode)
    _rebuild_fts(cur, conn, inserted)

    conn.close()
    print('\n  Done! ' + str(inserted) + ' new parts ready in PartVault.')
    print('  Restart backend:  python app.py\n')


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _detect_encoding(path):
    for enc in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
        try:
            with open(path, 'r', encoding=enc) as f:
                f.read(4096)
            return enc
        except UnicodeDecodeError:
            continue
    return 'latin-1'


def _sample_status_values(csv_path, encoding, status_col):
    if not status_col:
        return
    try:
        vals = set()
        with open(csv_path, newline='', encoding=encoding, errors='replace') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if i >= 2000:
                    break
                v = (row.get(status_col) or '').strip()
                if v:
                    vals.add(v)
        if vals:
            print('\n  Status values in CSV (sample of first 2000 rows):')
            for v in sorted(vals):
                mapped = STATUS_MAP.get(v.lower())
                if mapped:
                    print('    OK  "' + v + '"  ->  ' + mapped)
                else:
                    print('    ??  "' + v + '"  ->  Pending  (not in STATUS_MAP — add it to override)')
    except Exception:
        pass


def _rebuild_fts(cur, conn, n_new):
    if n_new == 0:
        return
    print('\n  Rebuilding FTS5 search index...', end=' ', flush=True)
    t0 = time.time()
    try:
        cur.execute("INSERT INTO parts_fts(parts_fts) VALUES('rebuild')")
        conn.commit()
        print('done (' + str(round(time.time()-t0, 1)) + 's)')
    except Exception:
        try:
            cur.executescript('''
                DELETE FROM parts_fts;
                INSERT INTO parts_fts(rowid, part_number, name, description)
                SELECT id,
                       COALESCE(part_number,''),
                       COALESCE(name,''),
                       COALESCE(description,'')
                FROM parts;
            ''')
            conn.commit()
            print('done - full rebuild (' + str(round(time.time()-t0, 1)) + 's)')
        except Exception as e2:
            print('skipped (' + str(e2) + ')')


def _print_progress(row_n, total, inserted, skipped, inactive, t_start):
    elapsed = time.time() - t_start
    rate    = inserted / elapsed if elapsed > 0 else 0
    eta     = (total - row_n) / rate if rate > 0 else 0
    pct     = row_n / total * 100 if total > 0 else 0
    bar_w   = 28
    filled  = int(bar_w * pct / 100)
    bar     = '#' * filled + '.' * (bar_w - filled)
    print(
        '\r  [' + bar + '] ' + str(round(pct, 1)) + '%  ' +
        str(inserted) + ' inserted  ' +
        str(skipped)  + ' skipped  ' +
        str(inactive) + ' inactive  ' +
        str(round(rate)) + ' rows/s  ' +
        'ETA ' + _fmt(eta) + '   ',
        end='', flush=True
    )


def _fmt(s):
    if s < 60:
        return str(int(s)) + 's'
    m, s2 = divmod(int(s), 60)
    return str(m) + 'm ' + str(s2).zfill(2) + 's'


def _suggest_csv(csv_path):
    folder = os.path.dirname(csv_path) or os.getcwd()
    print('\nCSV not found: ' + csv_path)
    if os.path.isdir(folder):
        csvs = [f for f in os.listdir(folder) if f.lower().endswith('.csv')]
        if csvs:
            print('\n  CSV files found in ' + folder + ':')
            for c in csvs:
                full = os.path.join(folder, c)
                sz   = os.path.getsize(full) / 1024
                print('    ' + c + '  (' + str(round(sz, 1)) + ' KB)')
                print('    Run: python bulk_imports.py "' + full + '"')
    print()


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    if len(sys.argv) < 2:
        # Auto-detect CSVs in C:\UI
        search_dir = r'C:\UI'
        if os.path.isdir(search_dir):
            csvs = [f for f in os.listdir(search_dir) if f.lower().endswith('.csv')]
            if csvs:
                print('\n  CSV files found in ' + search_dir + ':')
                for c in csvs:
                    print('    python bulk_imports.py "' + search_dir + '\\' + c + '"')
        sys.exit(0)

    _csv   = sys.argv[1]
    _user  = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_USER
    _batch = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_BATCH
    run(_csv, _user, _batch)