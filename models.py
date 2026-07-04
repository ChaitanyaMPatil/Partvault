# C:\UI\models.py
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80),  unique=True, nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name     = db.Column(db.String(120), default='')
    role          = db.Column(db.String(30),  default='REVIEWER')
    initials      = db.Column(db.String(5),   default='')
    created_at    = db.Column(db.DateTime,    default=datetime.utcnow)

    def set_password(self, pw):      self.password_hash = generate_password_hash(pw)
    def check_password(self, pw):    return check_password_hash(self.password_hash, pw)

    def to_dict(self):
        return { 'id': self.id, 'username': self.username, 'email': self.email,
                 'full_name': self.full_name, 'role': self.role, 'initials': self.initials }


class VMRS(db.Model):
    __tablename__ = 'vmrs'
    id          = db.Column(db.Integer, primary_key=True)
    code        = db.Column(db.String(10),  unique=True, nullable=False)
    system_name = db.Column(db.String(120), nullable=False)

    def to_dict(self):
        return { 'id': self.id, 'code': self.code, 'system_name': self.system_name,
                 'display': f'VMRS {self.code} \u2014 {self.system_name}' }


class AttributeDefinition(db.Model):
    __tablename__ = 'attribute_definitions'
    id             = db.Column(db.Integer, primary_key=True)
    attr_code      = db.Column(db.String(20),  nullable=False)
    attr_name      = db.Column(db.String(120), nullable=False)
    attr_type      = db.Column(db.String(50))            # Dimensional | Material | Performance | General Attribute
    default_uom    = db.Column(db.String(20),  default='—')
    uom_type       = db.Column(db.String(50))            # Length | Temperature | Pressure …
    classification = db.Column(db.String(30))            # Mandatory | Value Adding
    vmrs_id        = db.Column(db.Integer, db.ForeignKey('vmrs.id'), nullable=False)
    sort_order     = db.Column(db.Integer, default=0)

    vmrs = db.relationship('VMRS', backref='attr_defs')

    def to_dict(self):
        return { 'id': self.id, 'attr_code': self.attr_code, 'attr_name': self.attr_name,
                 'attr_type': self.attr_type, 'default_uom': self.default_uom,
                 'uom_type': self.uom_type, 'classification': self.classification,
                 'vmrs_id': self.vmrs_id, 'sort_order': self.sort_order }


class Part(db.Model):
    __tablename__ = 'parts'
    id               = db.Column(db.Integer, primary_key=True)
    part_number      = db.Column(db.String(50),  unique=True, nullable=False)
    name             = db.Column(db.String(200), nullable=False)
    description      = db.Column(db.Text,        default='')
    vmrs_id          = db.Column(db.Integer, db.ForeignKey('vmrs.id'), nullable=True)
    assigned_to      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    status           = db.Column(db.String(20),  default='Pending')
    assigned_date    = db.Column(db.DateTime,    default=datetime.utcnow)
    outlier_flag     = db.Column(db.Boolean,     default=False)
    outlier_count    = db.Column(db.Integer,     default=0)
    mandatory_total  = db.Column(db.Integer,     default=0)
    mandatory_filled = db.Column(db.Integer,     default=0)
    attr_count       = db.Column(db.Integer,     default=0)
    updated_at       = db.Column(db.DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)

    vmrs_ref   = db.relationship('VMRS',          backref='parts')
    assignee   = db.relationship('User',          backref='parts')
    attributes = db.relationship('PartAttribute', backref='part',
                                 lazy='subquery', cascade='all, delete-orphan')

    @property
    def progress_pct(self):
        if not self.mandatory_total:
            return 0
        return round(self.mandatory_filled / self.mandatory_total * 100)

    def to_dict(self, include_attributes=False):
        v = self.vmrs_ref
        d = {
            'id': self.id, 'part_number': self.part_number,
            'name': self.name, 'description': self.description or '',
            'vmrs_code':    v.code        if v else None,
            'vmrs_system':  v.system_name if v else None,
            'vmrs_display': f'VMRS {v.code} \u2014 {v.system_name}' if v else None,
            'status': self.status,
            'assigned_date':  self.assigned_date.strftime('%b %d') if self.assigned_date else None,
            'outlier_flag':   self.outlier_flag,
            'outlier_count':  self.outlier_count,
            'mandatory_total':  self.mandatory_total,
            'mandatory_filled': self.mandatory_filled,
            'progress_pct':     self.progress_pct,
            'attr_count':       self.attr_count,
        }
        if include_attributes:
            defs = (AttributeDefinition.query
                    .filter_by(vmrs_id=self.vmrs_id)
                    .order_by(AttributeDefinition.sort_order)
                    .all())
            d['attr_definitions'] = {
                'mandatory':    [a.to_dict() for a in defs if a.classification == 'Mandatory'],
                'value_adding': [a.to_dict() for a in defs if a.classification == 'Value Adding'],
            }
            d['part_attributes'] = {
                str(pa.attr_def_id): {
                    'value': pa.value or '', 'uom': pa.uom or '', 'has_outlier': pa.has_outlier
                }
                for pa in self.attributes
            }
        return d


class PartAttribute(db.Model):
    __tablename__ = 'part_attributes'
    id           = db.Column(db.Integer, primary_key=True)
    part_id      = db.Column(db.Integer, db.ForeignKey('parts.id'), nullable=False)
    attr_def_id  = db.Column(db.Integer, db.ForeignKey('attribute_definitions.id'), nullable=False)
    value        = db.Column(db.String(500), default='')
    uom          = db.Column(db.String(20),  default='')
    has_outlier  = db.Column(db.Boolean,     default=False)
    updated_at   = db.Column(db.DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)

    attr_def = db.relationship('AttributeDefinition', backref='part_attributes')

    __table_args__ = (
        db.UniqueConstraint('part_id', 'attr_def_id', name='uq_part_attr'),
    )