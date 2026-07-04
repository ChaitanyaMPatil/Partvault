# C:\UI\routes.py
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import Blueprint, current_app, jsonify, request
from models import db, User, VMRS, AttributeDefinition, Part, PartAttribute

api = Blueprint('api', __name__, url_prefix='/api')


# ── JWT ───────────────────────────────────────────────────────────────────────
def _mint_token(user):
    payload = {
        'sub':       str(user.id),   # ✅ FIXED: RFC 7519 requires sub to be a string
        'username':  user.username,
        'role':      user.role,
        'full_name': user.full_name,
        'initials':  user.initials,
        'exp': datetime.now(timezone.utc) + timedelta(hours=24),
        'iat': datetime.now(timezone.utc),
    }
    token = jwt.encode(
        payload,
        current_app.config['JWT_SECRET_KEY'],
        algorithm='HS256'
    )
    # PyJWT 1.x returns bytes; 2.x returns str — normalise to str
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    print(f'[Auth] Token minted for user {user.username} (id={user.id}), prefix={token[:20]}…')
    return token


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')

        if not auth.startswith('Bearer '):
            print(f'[Auth] Missing Bearer header — got: "{auth[:30]}"')
            return jsonify({'error': 'Authorization required'}), 401

        raw_token = auth.split(' ', 1)[1].strip()
        print(f'[Auth] Verifying token prefix: {raw_token[:20]}…')

        try:
            payload = jwt.decode(
                raw_token,
                current_app.config['JWT_SECRET_KEY'],
                algorithms=['HS256']
            )
        except jwt.ExpiredSignatureError:
            print('[Auth] Token EXPIRED')
            return jsonify({'error': 'Token expired — please log in again'}), 401
        except jwt.DecodeError as e:
            print(f'[Auth] Token DECODE ERROR: {e}  raw_token[:40]={raw_token[:40]}')
            return jsonify({'error': f'Token decode error: {e}'}), 401
        except jwt.InvalidSignatureError as e:
            print(f'[Auth] Token INVALID SIGNATURE: {e}')
            return jsonify({'error': 'Invalid token signature'}), 401
        except jwt.InvalidTokenError as e:
            print(f'[Auth] Token INVALID: {type(e).__name__}: {e}')
            return jsonify({'error': f'Invalid token ({type(e).__name__})'}), 401

        # ✅ FIXED: sub stored as string, convert back to int for DB queries
        try:
            request.uid = int(payload['sub'])
        except (KeyError, ValueError) as e:
            print(f'[Auth] Bad sub claim: {payload.get("sub")} — {e}')
            return jsonify({'error': 'Malformed token payload'}), 401

        print(f'[Auth] ✅ Token valid, uid={request.uid}')
        return f(*args, **kwargs)

    return decorated


# ── Auth ──────────────────────────────────────────────────────────────────────
@api.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'error': 'username and password required'}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        print(f'[Auth] Failed login attempt for username="{username}"')
        return jsonify({'error': 'Invalid credentials'}), 401

    token = _mint_token(user)
    print(f'[Auth] ✅ Login success: {username}')
    return jsonify({'token': token, 'user': user.to_dict()}), 200


@api.route('/auth/me', methods=['GET'])
@token_required
def me():
    user = db.session.get(User, request.uid)
    if not user:
        print(f'[Auth] /me: user id={request.uid} not found in DB')
        return jsonify({'error': 'User not found'}), 404
    return jsonify(user.to_dict()), 200


# ── Parts ─────────────────────────────────────────────────────────────────────
@api.route('/parts/assigned', methods=['GET'])
@token_required
def get_assigned_parts():
    print(f'[Parts] /assigned called by uid={request.uid}')
    parts = (Part.query
             .filter_by(assigned_to=request.uid)
             .order_by(Part.assigned_date.desc())
             .all())
    print(f'[Parts] Found {len(parts)} parts for uid={request.uid}')

    total       = len(parts)
    done        = sum(1 for p in parts if p.status == 'Done')
    in_progress = sum(1 for p in parts if p.status == 'InProgress')
    outlier     = sum(1 for p in parts if p.status == 'Outlier')
    pending     = sum(1 for p in parts if p.status == 'Pending')

    return jsonify({
        'stats': {
            'total': total, 'done': done, 'in_progress': in_progress,
            'outlier': outlier, 'pending': pending,
            'batch_name': 'Batch Q3-2026', 'last_synced': 'just now',
        },
        'parts': [p.to_dict() for p in parts]
    }), 200


@api.route('/parts/<string:part_number>', methods=['GET'])
@token_required
def get_part(part_number):
    print(f'[Parts] GET {part_number} by uid={request.uid}')
    part = Part.query.filter_by(part_number=part_number).first()
    if not part:
        return jsonify({'error': f'Part {part_number} not found'}), 404
    return jsonify(part.to_dict(include_attributes=True)), 200


@api.route('/parts/<string:part_number>/save', methods=['POST'])
@token_required
def save_part(part_number):
    part = Part.query.filter_by(part_number=part_number).first()
    if not part:
        return jsonify({'error': f'Part {part_number} not found'}), 404

    data        = request.get_json(silent=True) or {}
    save_type   = data.get('save_type', 'partial')
    description = data.get('description', part.description)
    attributes  = data.get('attributes', [])

    part.description = description

    for attr_data in attributes:
        attr_def_id = attr_data.get('attr_def_id')
        if not attr_def_id:
            continue
        ad = db.session.get(AttributeDefinition, attr_def_id)
        if not ad or ad.vmrs_id != part.vmrs_id:
            continue

        pa = PartAttribute.query.filter_by(
            part_id=part.id, attr_def_id=attr_def_id
        ).first()
        if pa is None:
            pa = PartAttribute(part_id=part.id, attr_def_id=attr_def_id)
            db.session.add(pa)

        pa.value = attr_data.get('value', '')
        pa.uom   = attr_data.get('uom', ad.default_uom)

    filled = sum(
        1 for pa in PartAttribute.query.filter_by(part_id=part.id)
        if pa.attr_def and pa.attr_def.classification == 'Mandatory'
        and (pa.value or '').strip()
    )
    part.mandatory_filled = filled

    if save_type == 'complete':
        part.status = 'Done'
    elif part.status == 'Pending':
        part.status = 'InProgress'

    oc = PartAttribute.query.filter_by(part_id=part.id, has_outlier=True).count()
    part.outlier_count = oc
    part.outlier_flag  = oc > 0
    if oc > 0 and part.status == 'Done':
        part.status = 'Outlier'

    part.updated_at = datetime.utcnow()
    db.session.commit()
    print(f'[Parts] Saved {part_number} as {save_type} → status={part.status}')
    return jsonify({'success': True, 'part': part.to_dict()}), 200


# ── VMRS ──────────────────────────────────────────────────────────────────────
@api.route('/vmrs', methods=['GET'])
@token_required
def get_vmrs():
    return jsonify([v.to_dict() for v in VMRS.query.order_by(VMRS.code).all()]), 200


# ── Health ────────────────────────────────────────────────────────────────────
@api.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'ts': datetime.utcnow().isoformat()}), 200