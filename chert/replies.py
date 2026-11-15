"""Opt-in replies to the verified sender of a signed inbound Chert event."""
import os
import httpx


def send_reply(sender, text, event_id):
    if os.getenv('FACTORY_SEND_REPLIES') != '1':
        return {'status': 'disabled'}
    if not all(os.getenv(k) for k in ('CHERT_API_KEY', 'CHERT_PROJECT_ID', 'CHERT_LINE_ID')):
        return {'status': 'not_configured'}
    try:
        r = httpx.post('https://app.trychert.com/api/v1/shared-messages',
            headers={'Authorization': 'Bearer '+os.environ['CHERT_API_KEY'],
                     'X-Chert-Project-Id': os.environ['CHERT_PROJECT_ID'],
                     'Idempotency-Key': 'factory-'+event_id[:150]},
            json={'line_id': os.environ['CHERT_LINE_ID'], 'recipient': sender, 'text': text[:4000]}, timeout=15)
        return {'status': 'sent' if r.is_success else 'provider_rejected', 'http_status': r.status_code}
    except httpx.HTTPError:
        return {'status': 'provider_unavailable'}
