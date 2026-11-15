"""ScanSafe Factory: versioned capabilities on reusable Chert/browser infrastructure."""
from api import config  # Load local .env before initializing adapters.
from fastapi import FastAPI
from factory.api import router
from chert.factory import router as chert_router
app = FastAPI(title='ScanSafe Factory')
app.include_router(router)
app.include_router(chert_router)

@app.get('/health')
def health():
    return {'ok': True, 'product': 'skill-factory', 'build_method': 'tested_template'}
