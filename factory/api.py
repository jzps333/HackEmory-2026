"""Same-origin browser API; anonymous workspace credentials are HttpOnly cookies."""
import hashlib
import os
import secrets
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from factory import catalog

router = APIRouter(prefix='/factory', tags=['factory'])


def owner(request: Request, response: Response):
    # Browser mutations require same-origin, or an explicit configured frontend origin.
    origin = request.headers.get('origin')
    allowed = {str(request.base_url).rstrip('/'), *os.getenv('FACTORY_ORIGINS', '').split(',')}
    if request.method != 'GET' and origin and origin not in allowed:
        raise HTTPException(403, 'Untrusted origin')
    key = request.cookies.get('factory_workspace')
    if not key or len(key) != 64:
        key = secrets.token_hex(32)
        response.set_cookie('factory_workspace', key, httponly=True, secure=request.url.scheme == 'https', samesite='lax', max_age=60*60*24*30)
    return hashlib.sha256(key.encode()).hexdigest()


class Build(BaseModel):
    idea: str = Field(min_length=5, max_length=2000)

class Version(BaseModel):
    version: int = Field(ge=1)

class Run(Version):
    input: dict = Field(default_factory=dict)

class Suggest(Version):
    text: str = Field(min_length=10, max_length=4000)

class Revision(BaseModel):
    expected_version: int = Field(ge=1)
    instructions: str = Field(min_length=10, max_length=6000)
    suggestion_id: str | None = None

@router.get('/templates')
def templates():
    return catalog.TEMPLATES

@router.post('/build', status_code=201)
def build(body: Build, who=Depends(owner)):
    return catalog.build(who, body.idea)

@router.get('/workspace')
def workspace(who=Depends(owner)):
    return {'skills': catalog.listing(who), 'installed': catalog.installed(who)}

@router.get('/library')
def library():
    return catalog.listing()

@router.post('/skills/{skill}/publish')
def publish(skill: str, body: Version, who=Depends(owner)):
    return catalog.publish(skill, body.version, who)

@router.post('/skills/{skill}/install')
def install(skill: str, body: Version, who=Depends(owner)):
    return catalog.install(skill, body.version, who)

@router.post('/skills/{skill}/run')
def run(skill: str, body: Run, who=Depends(owner)):
    return catalog.run(skill, body.version, who, body.input)

@router.post('/skills/{skill}/suggestions', status_code=201)
def suggest(skill: str, body: Suggest, who=Depends(owner)):
    return catalog.suggest(skill, body.version, who, body.text)

@router.get('/skills/{skill}/suggestions')
def suggestions(skill: str, who=Depends(owner)):
    return catalog.suggestions(skill, who)

@router.post('/skills/{skill}/revisions', status_code=201)
def revise(skill: str, body: Revision, who=Depends(owner)):
    return catalog.revise(skill, who, body.instructions, body.expected_version, body.suggestion_id)

@router.get('/skills/{skill}/versions/{version}/bundle')
def bundle(skill: str, version: int, who=Depends(owner)):
    return Response(catalog.bundle(skill, version, who), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="skill.zip"'})
