"""MTS-360 scoring — the server is the source of truth.

The client sends raw answers keyed "si_bi_qi" where si is the category index
(0..7 over CATS). The server recomputes everything; client-side numbers are
display sugar and are never trusted.

Effectiveness = Σ(extent × importance) ÷ Σ(5 × importance)
Bands: < .70 needs improvement · .70–.80 within requirements · > .80 exceeding
"""
import re
from models import CATS

QID = re.compile(r'^([0-7])_(\d{1,2})_(\d{1,2})$')
VALID_COUNTS = {'quick': 19, 'full': 110}


class ScoringError(ValueError):
    pass


def validate_and_score(answers: dict, mode: str):
    """Return (overall, cats[8]) or raise ScoringError."""
    if mode not in VALID_COUNTS:
        raise ScoringError('mode must be quick or full')
    if not isinstance(answers, dict):
        raise ScoringError('answers must be an object')
    if len(answers) != VALID_COUNTS[mode]:
        raise ScoringError(
            f'{mode} mode requires exactly {VALID_COUNTS[mode]} answers, '
            f'got {len(answers)}')

    num = [0.0] * len(CATS)
    den = [0.0] * len(CATS)
    for key, a in answers.items():
        m = QID.match(str(key))
        if not m:
            raise ScoringError(f'bad answer key: {key}')
        si = int(m.group(1))
        try:
            e, i = int(a['e']), int(a['i'])
        except (KeyError, TypeError, ValueError):
            raise ScoringError(f'answer {key} must contain integer e and i')
        if not (1 <= e <= 5 and 1 <= i <= 5):
            raise ScoringError(f'answer {key}: e and i must be 1..5')
        num[si] += e * i
        den[si] += 5 * i

    if any(d == 0 for d in den):
        raise ScoringError('every category must contain at least one answer')

    cats = [round(n / d, 3) for n, d in zip(num, den)]
    overall = round(sum(num) / sum(den), 3)
    return overall, cats


def blend_rollup(manager, overall, cats, max_trend=8):
    """v1 recency blend, identical to the demo semantics:
    new_score = 0.7*old + 0.3*new (or new if first filing)."""
    old = manager.score or 0.0
    first = (manager.n or 0) == 0
    new_score = overall if first else round(old * 0.7 + overall * 0.3, 3)

    trend = list(manager.trend or [])
    trend.append(new_score)
    if len(trend) < 2:
        trend.insert(0, round(overall * 0.92, 2))
    manager.trend = trend[-max_trend:]

    manager.delta = round((new_score - old) + (manager.delta or 0) * 0.5, 2)
    manager.score = new_score
    manager.n = (manager.n or 0) + 1

    team = manager.cats_team
    manager.cats_team = (cats if not team
                         else [round(t * 0.7 + c * 0.3, 3)
                               for t, c in zip(team, cats)])
