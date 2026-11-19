import logging
import re
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routers import (assistant, auth, consultations, dashboard, doctors, documents, fhir, hip, hiu, hospital, lab, network, patients, portal, prescriptions, staff)

app = FastAPI(title="ABDM Hospital Platform API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"],)

for module in (auth, hospital, network, staff, doctors, patients, dashboard, consultations, prescriptions, lab, fhir, documents, assistant, hip, hiu, portal):
    app.include_router(module.router, prefix="/api")

class RedactAccessLog(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            record.args = (*record.args[:2], re.sub(r"\?.*$", "", str(record.args[2])), *record.args[3:])
        return True

logging.getLogger("uvicorn.access").addFilter(RedactAccessLog())

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.scheme == "https": 
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store") 
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; sandbox")
    return response

@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok"}
