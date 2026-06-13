"""Managers That Suck — data models.

Design notes:
- Assessments are WRITE-ONCE. Rollup fields on Manager (score, trend, cats)
  are denormalized for read speed and updated transactionally on each filing,
  mirroring v1 blend semantics (0.7 old / 0.3 new, recency-forward trend).
  A nightly materialized recompute can replace the blend later without
  touching the API contract.
- Reviewer identity is NEVER stored. reviewer_hash is a salted one-way hash
  used only to rate-limit duplicate filings per manager per window.
"""
from datetime import datetime, timedelta

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.types import JSON

db = SQLAlchemy()

CATS = ['Administrative', 'Leadership', 'Communication', 'Adaptability',
        'Motivation', 'Technical', 'Cognitive', 'Results']

DECAY_MONTHS = 24          # reviews expire from scoring
DUPE_WINDOW_DAYS = 90      # one team filing per reviewer per manager per window


class Company(db.Model):
    __tablename__ = 'companies'
    id = db.Column(db.String(40), primary_key=True)          # slug
    name = db.Column(db.String(200), unique=True, nullable=False)
    industry = db.Column(db.String(120), default='Unverified')
    city = db.Column(db.String(120), default='—')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    managers = db.relationship('Manager', backref='company', lazy=True)

    def to_view(self):
        return {'id': self.id, 'name': self.name,
                'industry': self.industry, 'city': self.city}


class Manager(db.Model):
    __tablename__ = 'managers'
    id = db.Column(db.String(40), primary_key=True)          # slug
    company_id = db.Column(db.String(40), db.ForeignKey('companies.id'),
                           nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    title = db.Column(db.String(200), default='Manager')
    dept = db.Column(db.String(120), default='—')
    claimed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # denormalized rollups (see module docstring)
    score = db.Column(db.Float, default=0.0)
    delta = db.Column(db.Float, default=0.0)
    n = db.Column(db.Integer, default=0)
    trend = db.Column(JSON, default=list)                    # [float] trailing quarters
    plan = db.Column(db.Boolean, default=False)
    streak = db.Column(db.Integer, default=0)
    cats_team = db.Column(JSON, nullable=True)               # [8 floats]
    cats_self = db.Column(JSON, nullable=True)               # [8 floats]
    behaviors = db.Column(JSON, default=list)                # [[label, count]]
    reply = db.Column(db.Text, nullable=True)
    reviews = db.Column(JSON, default=list)                  # [{when, tags, helps, quote}]

    assessments = db.relationship('Assessment', backref='manager', lazy=True)

    def to_view(self):
        """Shape consumed by the SPA — must match the frontend's manager object."""
        return {
            'id': self.id, 'name': self.name, 'co': self.company_id,
            'coName': self.company.name, 'title': self.title,
            'dept': self.dept, 'city': self.company.city,
            'score': round(self.score or 0, 3), 'delta': round(self.delta or 0, 2),
            'n': self.n or 0, 'trend': self.trend or [],
            'plan': bool(self.plan), 'streak': self.streak or 0,
            'cats': {'team': self.cats_team, 'self': self.cats_self},
            'behaviors': self.behaviors or [], 'reply': self.reply,
            'reviews': self.reviews or [], 'claimed': self.claimed,
        }


class Assessment(db.Model):
    __tablename__ = 'assessments'
    id = db.Column(db.Integer, primary_key=True)
    manager_id = db.Column(db.String(40), db.ForeignKey('managers.id'),
                           nullable=False, index=True)
    perspective = db.Column(db.String(8), nullable=False)    # 'team' | 'self'
    mode = db.Column(db.String(8), nullable=False)           # 'quick' | 'full'
    reviewer_hash = db.Column(db.String(64), nullable=False, index=True)
    overall = db.Column(db.Float, nullable=False)
    cats = db.Column(JSON, nullable=False)                   # [8 floats]
    answers = db.Column(JSON, nullable=False)                # {"si_bi_qi": {"e":int,"i":int}}
    helps = db.Column(JSON, default=list)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    decays_at = db.Column(db.DateTime)

    def __init__(self, **kw):
        super().__init__(**kw)
        if not self.decays_at:
            self.decays_at = datetime.utcnow() + timedelta(days=30 * DECAY_MONTHS)
