"""Durable, versioned capability catalog. Only registered runners execute."""
from __future__ import annotations
import io
import json
import math
import os
import re
import sqlite3
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path
from fastapi import HTTPException

TEMPLATES = {
    'qr-checker': {
        'name': 'QR Scam Checker', 'runner': 'qr_check',
        'description': 'Investigate an HTTP(S) destination using the isolated ScanSafe browser.',
        'instructions': 'Ask for a QR destination link. Run the qr_check tool. Explain the verdict and evidence in simple words. A favorable scan is not a guarantee. Never enter credentials or make a payment.',
        'permissions': ['remote_browser', 'external_analysis'],
        'example': {'url': 'https://example.com'},
        'requirements': ['SANDBOX_URL', 'SANDBOX_TOKEN', 'JEV_API_KEY'],
    },
    'workout-summary': {
        'name': 'Workout Summary', 'runner': 'workout_summary',
        'description': 'Summarize user-entered exercise duration and training volume without external services.',
        'instructions': 'Ask for workout sessions, including exercise, minutes, sets, reps and weight_kg where known. Run workout_summary. Explain only the measured totals; do not diagnose, prescribe treatment or invent progress.',
        'permissions': [],
        'example': {'sessions': [{'exercise': 'Squat', 'minutes': 20, 'sets': 3, 'reps': 8, 'weight_kg': 40}]},
        'requirements': [],
    },
}

@contextmanager
def database():
    path = Path(os.getenv('FACTORY_DB', 'var/factory.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=10) as db:
        db.row_factory = sqlite3.Row
        db.executescript('''
        CREATE TABLE IF NOT EXISTS skills (id TEXT PRIMARY KEY, owner TEXT NOT NULL, latest INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS versions (skill TEXT, version INTEGER, manifest TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(skill,version));
        CREATE TABLE IF NOT EXISTS installs (owner TEXT, skill TEXT, version INTEGER, PRIMARY KEY(owner,skill));
        CREATE TABLE IF NOT EXISTS suggestions (id TEXT PRIMARY KEY, skill TEXT, version INTEGER, author TEXT, text TEXT, status TEXT NOT NULL DEFAULT 'open');
        CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, response TEXT NOT NULL);
        ''')
        yield db


def fail(status, detail):
    raise HTTPException(status, detail)


def owned(db, skill, owner):
    row = db.execute('SELECT * FROM skills WHERE id=? AND owner=?', (skill, owner)).fetchone()
    if not row:
        fail(404, 'Skill not found in your workspace')
    return row


def manifest(row):
    value = json.loads(row['manifest'])
    return {**value, 'published': bool(row['published'])}


def select_template(idea):
    text = idea.lower()
    qr = bool(re.search(r'\b(qr|scam|phishing|links?)\b', text))
    workout = bool(re.search(r'\b(workouts?|exercise|fitness|training)\b', text))
    if qr == workout:
        fail(422, 'Describe either a QR/link checker or a workout summary. This release builds from these two tested templates.')
    return 'qr-checker' if qr else 'workout-summary'


def build(owner, idea):
    template = select_template(idea)
    sid = uuid.uuid4().hex
    result = {'id': sid, 'version': 1, 'template': template, 'build_method': 'tested_template', **TEMPLATES[template]}
    validate(result)
    result['validation'] = {'manifest': 'passed', 'runtime': 'not_run', 'note': 'Try this skill with your own input before publishing.'}
    with database() as db:
        db.execute('INSERT INTO skills VALUES (?,?,1)', (sid, owner))
        db.execute('INSERT INTO versions(skill,version,manifest) VALUES (?,1,?)', (sid, json.dumps(result)))
    return {**result, 'published': False}


def validate(value):
    # Manifest content is data; never imports modules, executes code or selects arbitrary URLs.
    if value['runner'] not in ('qr_check', 'workout_summary'):
        fail(422, 'Unregistered runner')
    if not 10 <= len(value['instructions']) <= 6000:
        fail(422, 'Instructions must be 10–6000 characters')


def listing(owner=None):
    with database() as db:
        if owner:
            rows = db.execute('SELECT v.* FROM versions v JOIN skills s ON s.id=v.skill AND s.latest=v.version WHERE s.owner=?', (owner,)).fetchall()
        else:
            rows = db.execute('SELECT v.* FROM versions v WHERE v.published=1 AND v.version=(SELECT MAX(w.version) FROM versions w WHERE w.skill=v.skill AND w.published=1)').fetchall()
        return [manifest(row) for row in rows]


def get(skill, version, owner):
    with database() as db:
        row = db.execute('SELECT v.*,s.owner FROM versions v JOIN skills s ON s.id=v.skill WHERE v.skill=? AND v.version=?', (skill, version)).fetchone()
        if not row or (not row['published'] and row['owner'] != owner):
            fail(404, 'Skill version not found')
        return manifest(row)


def publish(skill, version, owner):
    with database() as db:
        owned(db, skill, owner)
        if not db.execute('UPDATE versions SET published=1 WHERE skill=? AND version=?', (skill, version)).rowcount:
            fail(404, 'Skill version not found')
    return get(skill, version, owner)


def install(skill, version, owner):
    value = get(skill, version, owner)
    if not value['published']:
        fail(409, 'Publish this version before installing it')
    with database() as db:
        db.execute('INSERT INTO installs VALUES (?,?,?) ON CONFLICT(owner,skill) DO UPDATE SET version=excluded.version', (owner, skill, version))
    return value


def installed(owner):
    with database() as db:
        rows = db.execute('SELECT v.* FROM installs i JOIN versions v ON v.skill=i.skill AND v.version=i.version WHERE i.owner=?', (owner,)).fetchall()
        return [manifest(row) for row in rows]


def suggest(skill, version, owner, text):
    value = get(skill, version, owner)
    if not value['published']:
        fail(409, 'Suggestions require a published release')
    sid = uuid.uuid4().hex
    with database() as db:
        db.execute('INSERT INTO suggestions(id,skill,version,author,text) VALUES (?,?,?,?,?)', (sid, skill, version, owner, text))
    return {'id': sid, 'status': 'open'}


def suggestions(skill, owner):
    with database() as db:
        owned(db, skill, owner)
        return [dict(r) for r in db.execute('SELECT id,version,text,status FROM suggestions WHERE skill=?', (skill,))]


def revise(skill, owner, instructions, expected_version, suggestion_id=None):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = owned(db, skill, owner)
        if row['latest'] != expected_version:
            fail(409, 'A newer version exists; refresh before revising')
        current = db.execute('SELECT * FROM versions WHERE skill=? AND version=?', (skill, expected_version)).fetchone()
        value = json.loads(current['manifest'])
        value.update(version=expected_version+1, instructions=instructions)
        value['validation'] = {'manifest': 'passed', 'runtime': 'not_run', 'note': 'Instructions revised; run the new version before publishing.'}
        validate(value)
        if suggestion_id:
            changed = db.execute("UPDATE suggestions SET status='accepted' WHERE id=? AND skill=? AND status='open'", (suggestion_id, skill)).rowcount
            if not changed:
                fail(409, 'Open suggestion not found for this skill')
        db.execute('INSERT INTO versions(skill,version,manifest) VALUES (?,?,?)', (skill, value['version'], json.dumps(value)))
        db.execute('UPDATE skills SET latest=? WHERE id=?', (value['version'], skill))
    return {**value, 'published': False}


def workout_summary(payload):
    sessions = payload.get('sessions')
    if not isinstance(sessions, list) or not 1 <= len(sessions) <= 100:
        fail(422, 'Provide 1–100 workout sessions')
    minutes = volume = 0.0
    for session in sessions:
        if not isinstance(session, dict) or not isinstance(session.get('exercise'), str) or not session['exercise'].strip():
            fail(422, 'Each session needs an exercise name')
        values = {}
        for key in ('minutes', 'sets', 'reps', 'weight_kg'):
            value = session.get(key, 0)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 10000:
                fail(422, f'{key} must be a finite number from 0 to 10000')
            values[key] = value
        if values['sets'] % 1 or values['reps'] % 1:
            fail(422, 'Sets and reps must be whole numbers')
        minutes += values['minutes']
        volume += values['sets'] * values['reps'] * values['weight_kg']
    return {'sessions': len(sessions), 'minutes': minutes, 'volume_kg': volume,
            'summary': f'{len(sessions)} sessions, {minutes:g} minutes, {volume:g} kg total recorded lifting volume.'}


def run(skill, version, owner, payload):
    value = get(skill, version, owner)
    with database() as db:
        creator = db.execute('SELECT owner FROM skills WHERE id=?', (skill,)).fetchone()['owner']
        pinned = db.execute('SELECT version FROM installs WHERE owner=? AND skill=?', (owner, skill)).fetchone()
    if creator != owner and (not pinned or pinned['version'] != version):
        fail(403, 'Install this exact version before running it')
    if value['runner'] == 'workout_summary':
        return {'skill_id': skill, 'version': version, 'result': workout_summary(payload)}
    from api import config
    if not (config.SANDBOX_URL and config.SANDBOX_TOKEN and config.JEV_API_KEY):
        fail(503, 'QR checks need configured sandbox and Jev credentials; no sample verdict is substituted')
    from api.scan import scan
    url = payload.get('url')
    if not isinstance(url, str) or not 1 <= len(url) <= 4096:
        fail(422, 'Provide an HTTP(S) URL of at most 4096 characters')
    return {'skill_id': skill, 'version': version, 'result': scan(url).model_dump(mode='json')}


def bundle(skill, version, owner):
    value = get(skill, version, owner)
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json', json.dumps(value, indent=2))
        z.writestr('SKILL.md', f"# {value['name']}\n\n{value['instructions']}\n\nRunner: {value['runner']}\nVersion: {version}\n\nRequires the ScanSafe Factory runtime and its registered Chert tools.\n")
    return out.getvalue()
