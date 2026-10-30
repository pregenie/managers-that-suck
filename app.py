"""Managers That Suck — Flask backend.

Endpoints (response format: {'success': bool, 'data'|'error': ...}):
  GET  /api/health
  GET  /api/bootstrap                          → all companies + manager rollups
  POST /api/managers                           → register a manager (anonymous)
  POST /api/managers/<id>/assessments          → file team rating or self+plan

Anonymity: reviewer identity is reduced to sha256(SALT + ip + user-agent) and
discarded. The hash exists solely to enforce one team filing per reviewer per
manager per 90 days. It cannot be reversed and is never joined to anything.
"""
import hashlib
import os
import re
import unicodedata
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, send_from_directory

from models import db, Company, Manager, Assessment, DUPE_WINDOW_DAYS
from scoring import validate_and_score, blend_rollup, ScoringError
from seed import seed_if_empty

SALT = os.environ.get('SECRET_SALT', 'dev-salt-change-me')


def create_app():
    app = Flask(__name__, static_folder='static')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL', 'sqlite:///mts.db').replace('postgres://', 'postgresql://')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAX_CONTENT_LENGTH'] = 256 * 1024  # answers payloads are small

    db.init_app(app)
    with app.app_context():
        try:
            db.create_all()
            seed_if_empty(db)
        except Exception:
            # another worker/instance won the init race — schema already exists
            db.session.rollback()

    # ---------- helpers ----------
    def reviewer_hash():
        ip = (request.headers.get('X-Forwarded-For', request.remote_addr or '')
              .split(',')[0].strip())
        ua = request.headers.get('User-Agent', '')
        return hashlib.sha256(f'{SALT}|{ip}|{ua}'.encode()).hexdigest()

    def slugify(text, prefix=''):
        s = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
        s = re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')[:30] or 'x'
        base, slug, k = s, prefix + s, 2
        Model = Manager if prefix == 'm-' else Company
        while db.session.get(Model, slug):
            slug, k = f'{prefix}{base}-{k}', k + 1
        return slug

    def ok(data, code=200):
        return jsonify({'success': True, 'data': data}), code

    def err(message, code=400):
        return jsonify({'success': False, 'error': message}), code

    # ---------- API ----------
    @app.get('/api/health')
    def health():
        return ok({'status': 'up', 'time': datetime.utcnow().isoformat()})

    @app.get('/api/bootstrap')
    def bootstrap():
        return ok({
            'companies': [c.to_view() for c in Company.query.all()],
            'managers': [m.to_view() for m in Manager.query.all()],
        })

    @app.post('/api/managers')
    def register_manager():
        body = request.get_json(silent=True) or {}
        name = (body.get('name') or '').strip()[:200]
        co_name = (body.get('company') or '').strip()[:200]
        if not name or not co_name:
            return err('name and company are required')

        co = Company.query.filter(
            db.func.lower(Company.name) == co_name.lower()).first()
        if not co:
            co = Company(id=slugify(co_name), name=co_name,
                         industry='Unverified',
                         city=(body.get('city') or '—').strip()[:120])
            db.session.add(co)

        m = Manager(id=slugify(name, 'm-'), company=co, name=name,
                    title=(body.get('title') or 'Manager').strip()[:200],
                    dept=(body.get('dept') or '—').strip()[:120])
        db.session.add(m)
        db.session.commit()
        return ok({'manager': m.to_view(), 'company': co.to_view()}, 201)

    @app.post('/api/managers/<mid>/assessments')
    def file_assessment(mid):
        m = db.session.get(Manager, mid)
        if not m:
            return err('manager not found', 404)
        body = request.get_json(silent=True) or {}
        persp = body.get('perspective')
        if persp not in ('team', 'self'):
            return err('perspective must be team or self')

        try:
            overall, cats = validate_and_score(
                body.get('answers'), body.get('mode'))
        except ScoringError as e:
            return err(str(e))

        rh = reviewer_hash()
        if persp == 'team':
            window = datetime.utcnow() - timedelta(days=DUPE_WINDOW_DAYS)
            dupe = Assessment.query.filter(
                Assessment.manager_id == m.id,
                Assessment.reviewer_hash == rh,
                Assessment.perspective == 'team',
                Assessment.created_at >= window).first()
            if dupe:
                return err('You already filed on this manager this quarter — '
                           'one rating per reviewer per 90 days keeps the '
                           'scores honest.', 409)

        helps = [str(h)[:120] for h in (body.get('helps') or [])][:8]
        a = Assessment(manager_id=m.id, perspective=persp,
                       mode=body['mode'], reviewer_hash=rh,
                       overall=overall, cats=cats,
                       answers=body['answers'], helps=helps)
        db.session.add(a)

        when = datetime.utcnow().strftime('%b %Y').upper()
        if persp == 'team':
            blend_rollup(m, overall, cats)
            reviews = list(m.reviews or [])
            reviews.insert(0, {
                'when': when, 'tags': [], 'helps': helps,
                'quote': f"Filed via MTS-360 "
                         f"({'full, 110 items' if body['mode'] == 'full' else 'quick read'}).",
            })
            m.reviews = reviews[:20]
        else:  # self: publishes the improvement plan
            m.cats_self = cats
            m.plan = True
            focus = [str(f)[:80] for f in (body.get('focus') or [])][:3]
            if body.get('reply'):
                m.reply = str(body['reply'])[:600]
            elif focus and not m.reply:
                m.reply = (f"Self-assessed {when}. Plan published: "
                           f"{', '.join(focus)}. Re-assess me in 90 days.")

        db.session.commit()
        return ok({'manager': m.to_view(),
                   'anon_id': 'ANON-' + rh[:6].upper(),
                   'decays': a.decays_at.strftime('%b %Y').upper()}, 201)

    # Public crawler files use real root URLs, separate from hash navigation.
    @app.get('/robots.txt')
    def robots():
        return send_from_directory(app.static_folder, 'robots.txt', mimetype='text/plain')

    @app.get('/sitemap.xml')
    def sitemap():
        return send_from_directory(app.static_folder, 'sitemap.xml', mimetype='application/xml')

    # ---------- SPA ----------
    @app.get('/')
    def index():
        return send_from_directory(app.static_folder, 'index.html')

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
