# C:\UI\app.py
import os
from datetime import datetime
from flask import Flask
from flask_cors import CORS
from config import config_map
from models import db, User, VMRS, AttributeDefinition, Part, PartAttribute


def create_app(env=None):
    if env is None:
        env = os.environ.get('FLASK_ENV', 'development')
    app = Flask(__name__)
    app.config.from_object(config_map.get(env, config_map['default']))
    print(f'[PartVault] env={env}  DB={app.config["SQLALCHEMY_DATABASE_URI"]}')

    db.init_app(app)

    CORS(app, resources={r'/api/*': {
        'origins':       '*',
        'allow_headers': ['Content-Type', 'Authorization'],
        'methods':       ['GET','POST','PUT','PATCH','DELETE','OPTIONS'],
    }})

    from routes import api
    app.register_blueprint(api)

    with app.app_context():
        # Auto-reset dev DB if schema is out of date
        try:
            from sqlalchemy import text
            with db.engine.connect() as conn:
                conn.execute(text("SELECT full_name FROM users LIMIT 1"))
            # Schema is fine, just seed
            _seed()
        except Exception:
            print("[PartVault] ⚠️  Schema mismatch detected — dropping and recreating DB...")
            db.drop_all()
            db.create_all()
            _seed()

    return app


# ─────────────────────────────────────────────────────────────────────────────
def _seed():
    if User.query.filter_by(username='demo').first():
        return
    print('[PartVault] Seeding demo data...')

    # ── User ──────────────────────────────────────────────────────────────────
    user = User(username='demo', email='demo@partvault.local',
                full_name='A. Rajan', role='REVIEWER', initials='AR')
    user.set_password('demo123')
    db.session.add(user)
    db.session.flush()

    # ── VMRS codes ────────────────────────────────────────────────────────────
    VMRS_LIST = [
        ('012','Air Induction System'), ('013','Fuel System'),
        ('016','Clutch'),               ('022','Brakes'),
        ('031','Filters'),              ('033','Gaskets & Seals'),
        ('034','Transmission'),         ('040','Front Axle'),
        ('043','Engine Cooling'),       ('071','Front Suspension'),
    ]
    vmrs_map = {}
    for code, name in VMRS_LIST:
        v = VMRS(code=code, system_name=name)
        db.session.add(v)
        db.session.flush()
        vmrs_map[code] = v

    # ── Attribute definitions ─────────────────────────────────────────────────
    # (attr_code, attr_name, attr_type, default_uom, uom_type, classification, sort)
    FUEL_ATTRS = [
        ('ATR-D-001','Inlet Diameter',       'Dimensional',      'mm',  'Length',      'Mandatory',     1),
        ('ATR-D-002','Outer Diameter',        'Dimensional',      'mm',  'Length',      'Mandatory',     2),
        ('ATR-D-003','Overall Length',        'Dimensional',      'mm',  'Length',      'Mandatory',     3),
        ('ATR-M-001','Housing Material',      'Material',         '—',   'General',     'Mandatory',     4),
        ('ATR-M-002','Substrate Material',    'Material',         '—',   'General',     'Mandatory',     5),
        ('ATR-P-001','Max Operating Temp',    'Performance',      '°C',  'Temperature', 'Mandatory',     6),
        ('ATR-P-002','Operating Pressure',    'Performance',      'bar', 'Pressure',    'Mandatory',     7),
        ('ATR-P-003','Filter Efficiency',     'Performance',      '%',   'Ratio',       'Mandatory',     8),
        ('ATR-G-001','Compliance Standard',   'General Attribute','—',   'General',     'Mandatory',     9),
        ('ATR-G-002','Replacement Interval',  'General Attribute','—',   'General',     'Mandatory',    10),
        ('ATR-D-004','Wall Thickness',        'Dimensional',      'mm',  'Length',      'Mandatory',    11),
        ('ATR-D-005','Flange OD',             'Dimensional',      'mm',  'Length',      'Value Adding', 12),
        ('ATR-D-006','Port Thread Size',      'Dimensional',      'mm',  'Length',      'Value Adding', 13),
        ('ATR-G-003','OEM Reference',         'General Attribute','—',   'General',     'Value Adding', 14),
        ('ATR-G-004','Net Weight',            'Performance',      'kg',  'Weight',      'Value Adding', 15),
    ]
    GEN_ATTRS = [
        ('ATR-D-001','Overall Length',        'Dimensional',      'mm',  'Length',      'Mandatory',     1),
        ('ATR-D-002','Overall Width',         'Dimensional',      'mm',  'Length',      'Mandatory',     2),
        ('ATR-D-003','Overall Height',        'Dimensional',      'mm',  'Length',      'Mandatory',     3),
        ('ATR-M-001','Primary Material',      'Material',         '—',   'General',     'Mandatory',     4),
        ('ATR-M-002','Surface Treatment',     'Material',         '—',   'General',     'Mandatory',     5),
        ('ATR-P-001','Max Operating Temp',    'Performance',      '°C',  'Temperature', 'Mandatory',     6),
        ('ATR-P-002','Max Load Rating',       'Performance',      'kN',  'Force',       'Mandatory',     7),
        ('ATR-G-001','Compliance Standard',   'General Attribute','—',   'General',     'Mandatory',     8),
        ('ATR-G-002','Service Interval',      'General Attribute','—',   'General',     'Mandatory',     9),
        ('ATR-D-004','Bore Diameter',         'Dimensional',      'mm',  'Length',      'Mandatory',    10),
        ('ATR-D-005','Mounting Hole PCD',     'Dimensional',      'mm',  'Length',      'Value Adding', 11),
        ('ATR-G-003','OEM Reference',         'General Attribute','—',   'General',     'Value Adding', 12),
        ('ATR-G-004','Net Weight',            'Performance',      'kg',  'Weight',      'Value Adding', 13),
        ('ATR-P-003','Efficiency Rating',     'Performance',      '%',   'Ratio',       'Value Adding', 14),
    ]
    VMRS_ATTRS = {'013': FUEL_ATTRS}

    adef_map = {}   # (vmrs_code, attr_code) → AttributeDefinition
    for code, vobj in vmrs_map.items():
        defs = VMRS_ATTRS.get(code, GEN_ATTRS)
        for (ac, an, at, uom, ut, cls, srt) in defs:
            ad = AttributeDefinition(attr_code=ac, attr_name=an, attr_type=at,
                                     default_uom=uom, uom_type=ut,
                                     classification=cls, vmrs_id=vobj.id, sort_order=srt)
            db.session.add(ad)
            db.session.flush()
            adef_map[(code, ac)] = ad

    # ── Parts ─────────────────────────────────────────────────────────────────
    # (part_number, name, vmrs_code, status, date, outlier_count)
    PARTS = [
        ('ENG-8842-A','Fuel Injection Pump Assembly — Tier 4',     '013','InProgress','2026-06-10', 2),
        ('BRK-L138',  'Rear Brake Caliper — Heavy Duty',            '022','Outlier',   '2026-06-11', 1),
        ('FLT-8819-C','Hydraulic Oil Filter — 10 Micron Spin-On',  '031','Done',      '2026-06-11', 0),
        ('ESH-8877',  'Diesel Particulate Filter — Stage V',        '016','InProgress','2026-06-12', 0),
        ('CLT-8322-8','Clutch Pressure Plate — 430mm Single',       '016','InProgress','2026-06-12', 0),
        ('AIR-5561',  'Turbocharger Air Filter Assembly',            '012','Pending',   '2026-06-13', 0),
        ('RAD-2264-A','Engine Coolant Radiator — Aluminium Core',   '043','InProgress','2026-06-13', 0),
        ('SUS-8861',  'Front Suspension Control Arm — RH',          '071','Outlier',   '2026-06-14', 1),
        ('ENG-L884-C','Engine Oil Sump Gasket Set — Full',          '033','Outlier',   '2026-06-14', 1),
        ('GBX-8832-C','Manual Gearbox Input Shaft Bearing',         '034','Done',      '2026-06-14', 0),
        ('STR-8448',  'Power Steering Pump — Variable Displacement','016','Pending',   '2026-06-15', 0),
        ('CHL-8866-A','Intercooler Assembly — Air to Air',          '012','Outlier',   '2026-06-15', 1),
        ('BRK-8338',  'Front Disc Brake Rotor — Ventilated',        '022','Pending',   '2026-06-16', 0),
        ('ESH-8112-8','EGR Valve & Cooler Assembly',                '012','Pending',   '2026-06-16', 0),
        ('FLT-8855',  'Fuel Filter Separator — Primary Stage',      '031','Pending',   '2026-06-17', 0),
        ('AXL-2298-D','Front Drive Axle Differential Assembly',     '040','Pending',   '2026-06-17', 0),
        ('COL-8819',  'Cooling Fan Clutch — Viscous Drive',         '043','Done',      '2026-06-17', 0),
        ('ENG-8771-C','Crankshaft Position Sensor — Hall Effect',   '013','Done',      '2026-06-18', 0),
    ]

    # ── Pre-filled attribute values ───────────────────────────────────────────
    # {part_number: {attr_code: (value, uom, has_outlier)}}
    PRE = {
        'ENG-8842-A': {
            'ATR-P-001': ('620',           '°C',  True),
            'ATR-G-001': ('Stage V / EU6', '—',   False),
            'ATR-D-005': ('148',           'mm',  False),
        },
        'ESH-8877': {
            'ATR-D-001': ('145', 'mm', False), 'ATR-D-002': ('210', 'mm', False),
            'ATR-M-001': ('Cast Iron', '—', False), 'ATR-M-002': ('Cordierite', '—', False),
            'ATR-P-001': ('550', '°C', False),
        },
        'CLT-8322-8': {
            'ATR-D-001': ('430', 'mm', False),
            'ATR-M-001': ('Steel', '—', False), 'ATR-G-001': ('SAE J617', '—', False),
        },
        'RAD-2264-A': {
            'ATR-D-001': ('680', 'mm', False), 'ATR-D-002': ('420', 'mm', False),
            'ATR-M-001': ('Aluminium Alloy', '—', False), 'ATR-P-001': ('120', '°C', False),
        },
        'BRK-L138': {
            'ATR-D-001': ('310', 'mm', False), 'ATR-D-002': ('85', 'mm', False),
            'ATR-M-001': ('Cast Iron', '—', False), 'ATR-P-001': ('650', '°C', True),
        },
        'SUS-8861': {
            'ATR-D-001': ('520', 'mm', False), 'ATR-D-002': ('35', 'mm', False),
            'ATR-M-001': ('High-Strength Steel', '—', False), 'ATR-P-001': ('85', 'kN', True),
        },
        'ENG-L884-C': {
            'ATR-M-001': ('Graphite Composite', '—', False),
            'ATR-G-001': ('OEM Spec 44-B', '—', False), 'ATR-D-001': ('185', 'mm', True),
        },
        'CHL-8866-A': {
            'ATR-D-001': ('720', 'mm', False), 'ATR-D-002': ('380', 'mm', False),
            'ATR-M-001': ('Aluminium', '—', False), 'ATR-P-001': ('220', '°C', True),
        },
        # ── Done parts: all mandatory filled ─────────────────────────────────
        'FLT-8819-C': {
            'ATR-D-001':('120','mm',False),'ATR-D-002':('85','mm',False),
            'ATR-D-003':('195','mm',False),'ATR-D-004':('2.5','mm',False),
            'ATR-M-001':('Cellulose Fiber','—',False),'ATR-M-002':('Steel Casing','—',False),
            'ATR-P-001':('140','°C',False),'ATR-P-002':('10','kN',False),
            'ATR-G-001':('ISO 4548-12','—',False),'ATR-G-002':('500 hours','—',False),
            'ATR-D-005':('95','mm',False),'ATR-G-003':('HYD-119-C','—',False),
        },
        'GBX-8832-C': {
            'ATR-D-001':('180','mm',False),'ATR-D-002':('140','mm',False),
            'ATR-D-003':('38','mm',False), 'ATR-D-004':('25','mm',False),
            'ATR-M-001':('Chrome Steel','—',False),'ATR-M-002':('Hardened Steel','—',False),
            'ATR-P-001':('120','°C',False),'ATR-P-002':('45','kN',False),
            'ATR-G-001':('ISO 281','—',False),'ATR-G-002':('200,000 km','—',False),
            'ATR-D-005':('155','mm',False),'ATR-G-003':('GBX-32-C','—',False),
        },
        'COL-8819': {
            'ATR-D-001':('320','mm',False),'ATR-D-002':('210','mm',False),
            'ATR-D-003':('125','mm',False),'ATR-D-004':('28','mm',False),
            'ATR-M-001':('Aluminium Alloy','—',False),'ATR-M-002':('Steel Hub','—',False),
            'ATR-P-001':('130','°C',False),'ATR-P-002':('15','kN',False),
            'ATR-G-001':('SAE J639','—',False),'ATR-G-002':('100,000 km','—',False),
            'ATR-D-005':('190','mm',False),'ATR-G-003':('COL-819','—',False),
        },
        'ENG-8771-C': {
            'ATR-D-001':('45','mm',False), 'ATR-D-002':('18','mm',False),
            'ATR-D-003':('82','mm',False), 'ATR-D-004':('12','mm',False),
            'ATR-M-001':('ABS Polymer','—',False),'ATR-M-002':('Copper Winding','—',False),
            'ATR-P-001':('150','°C',False),'ATR-P-002':('5','bar',False),
            'ATR-P-003':('N/A','%',False),
            'ATR-G-001':('ISO 16750-2','—',False),'ATR-G-002':('Lifetime','—',False),
            'ATR-D-005':('N/A','mm',False),'ATR-G-003':('CPS-771-C','—',False),
        },
    }

    # ── vmrs_code lookup needed for PRE loop ──────────────────────────────────
    pn_to_vmrs = {pn: vc for (pn, _, vc, *__) in PARTS}

    part_map = {}
    for (pn, name, vc, status, dstr, oc) in PARTS:
        vobj  = vmrs_map[vc]
        defs  = VMRS_ATTRS.get(vc, GEN_ATTRS)
        m_tot = sum(1 for d in defs if d[5] == 'Mandatory')
        tot   = len(defs)

        p = Part(
            part_number=pn, name=name, description=name,
            vmrs_id=vobj.id, assigned_to=user.id, status=status,
            assigned_date=datetime.strptime(dstr, '%Y-%m-%d'),
            outlier_flag=oc > 0, outlier_count=oc,
            mandatory_total=m_tot, mandatory_filled=0, attr_count=tot,
        )
        db.session.add(p)
        db.session.flush()
        part_map[pn] = p

    # ── Insert pre-filled values & update mandatory_filled ────────────────────
    for pn, attr_vals in PRE.items():
        part = part_map.get(pn)
        if not part:
            continue
        vc     = pn_to_vmrs[pn]
        filled = 0
        for ac, (val, uom, outlier) in attr_vals.items():
            ad = adef_map.get((vc, ac))
            if not ad:
                continue
            pa = PartAttribute(part_id=part.id, attr_def_id=ad.id,
                               value=val, uom=uom, has_outlier=outlier)
            db.session.add(pa)
            if ad.classification == 'Mandatory' and val:
                filled += 1
        part.mandatory_filled = filled

    db.session.commit()
    print('[PartVault] ✅ Demo data seeded — username=demo  password=demo123')


if __name__ == '__main__':
    create_app().run(host='0.0.0.0', port=5000, debug=True)