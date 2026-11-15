"""Chert adapters share the catalog, ownership and installed runner rules with the web UI."""
import hashlib
import json
import os
from fastapi import APIRouter, HTTPException, Request
from factory import catalog
from chert.signatures import verify_signature

router = APIRouter()


def identity(sender):
    # Provider identity is accepted only after signature verification, never from a web body.
    if not isinstance(sender, str) or not sender.startswith('+') or not sender[1:].isdigit() or not 8 <= len(sender) <= 16:
        raise HTTPException(422, 'A verified E.164 sender is required')
    return hashlib.sha256(('chert:'+sender).encode()).hexdigest()


def handle_message(sender, text):
    """BUILD <request>, LIBRARY, INSTALL <id> <version>, RUN <id> <version> <JSON>."""
    who = identity(sender)
    command, _, rest = text.strip().partition(' ')
    command = command.upper()
    if command == 'BUILD':
        if not 5 <= len(rest) <= 2000:
            raise HTTPException(422, 'BUILD needs a request of 5–2000 characters')
        value = catalog.build(who, rest)
        return {'skill': value, 'reply': walkthrough(value)}
    if command == 'LIBRARY':
        return {'skills': catalog.listing()}
    if command in ('INSTALL', 'PUBLISH', 'RUN'):
        parts = rest.split(' ', 2)
        if len(parts) < 2:
            raise HTTPException(422, 'Provide a skill ID and version')
        try:
            version = int(parts[1])
            if version < 1:
                raise ValueError()
            payload = json.loads(parts[2]) if command == 'RUN' and len(parts) == 3 else {}
            if not isinstance(payload, dict):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(422, 'Use a positive version and a JSON object input')
        if command == 'INSTALL':
            return catalog.install(parts[0], version, who)
        if command == 'PUBLISH':
            return catalog.publish(parts[0], version, who)
        return catalog.run(parts[0], version, who, payload)
    raise HTTPException(422, 'Use BUILD, LIBRARY, INSTALL, PUBLISH or RUN')


def walkthrough(value):
    # Only trusted template descriptions; do not speak arbitrary contributor instructions.
    template = catalog.TEMPLATES[value['template']]
    return f"I built {template['name']}, version {value['version']}, from a tested template. {template['description']} It is private until you choose to publish it."

@router.post('/chert/webhook')
async def webhook(request: Request):
    secret = os.getenv('CHERT_WEBHOOK_SECRET')
    if not secret:
        raise HTTPException(503, 'Configure CHERT_WEBHOOK_SECRET before accepting events')
    raw = await request.body()
    if len(raw) > 32000:
        raise HTTPException(413, 'Event too large')
    if not verify_signature(secret, raw, request.headers):
        raise HTTPException(401, 'Invalid signature')
    try:
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError()
        if (event.get('event_type') or event.get('type')) != 'message.received':
            return {'ok': True, 'ignored': True}
        msg = event['data']['message']
        sender = msg['sender']
        if isinstance(sender, dict):
            sender = sender.get('handle')
        identity(sender)
        text = ' '.join(p.get('value', p.get('text', '')) for p in msg.get('parts', []) if p.get('type') == 'text')
        event_id = str(event.get('event_id') or event.get('id') or hashlib.sha256(raw).hexdigest())
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(422, 'Unsupported Chert message event shape')
    # Claim before processing: duplicate delivery never rebuilds or reruns a skill.
    with catalog.database() as db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT response FROM events WHERE id=?', (event_id,)).fetchone()
        if old:
            return {'ok': True, 'duplicate': True, 'result': json.loads(old['response'])}
        db.execute('INSERT INTO events VALUES (?,?)', (event_id, json.dumps({'status': 'processing'})))
    try:
        result = handle_message(sender, text)
    except HTTPException as error:
        result = {'error': error.detail, 'status': error.status_code}
    except Exception:
        result = {'error': 'Capability execution failed; no result available', 'status': 500}
    from chert.replies import send_reply
    import asyncio
    reply = result.get('reply') or json.dumps(result, ensure_ascii=False)
    delivery = await asyncio.to_thread(send_reply, sender, reply, event_id)
    result['delivery'] = delivery
    with catalog.database() as db:
        db.execute('UPDATE events SET response=? WHERE id=?', (json.dumps(result), event_id))
    return {'ok': True, 'result': result}
