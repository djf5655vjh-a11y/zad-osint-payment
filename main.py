import hmac
import html
import json
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app import routes_admin, routes_auth, routes_pay, routes_user
from app.config import FORCE_HTTPS
from app.db import get_setting, init_db
from app.deps import base_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("zadpay")
ROOT = Path(__file__).parent
STATIC = ROOT / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    log.info("ZAD PAY started")
    yield


app = FastAPI(title="ZAD PAY API", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
for r in (routes_auth.router, routes_user.router, routes_pay.router, routes_admin.admin, routes_admin.owner):
    app.include_router(r)

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'")


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    host = (request.headers.get("host") or "").split(":")[0]
    if FORCE_HTTPS and proto == "http" and host not in ("localhost", "127.0.0.1", "") and path != "/healthz":
        return RedirectResponse(str(request.url.replace(scheme="https")), status_code=301)
    if (path.startswith("/api") and request.method in ("POST", "PUT", "PATCH", "DELETE") and not path.startswith("/api/payment/webhook")
            and not request.headers.get("authorization", "").lower().startswith("bearer ")):
        ck, hd = request.cookies.get("zp_csrf"), request.headers.get("x-csrf-token")
        if not ck or not hd or not hmac.compare_digest(ck, hd):
            return JSONResponse({"detail": "Security check failed. Refresh the page and try again."}, status_code=403)
    resp = await call_next(request)
    if not request.cookies.get("zp_csrf"):
        resp.set_cookie("zp_csrf", secrets.token_urlsafe(24), httponly=False, secure=proto == "https", samesite="lax", path="/", max_age=86400 * 14)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if proto == "https":
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if not path.startswith("/api/docs") and not path.startswith("/api/openapi"):
        resp.headers["Content-Security-Policy"] = CSP
    if path.startswith("/api"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Something went wrong on our side. Please try again."}, status_code=500)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots(request: Request):
    return f"User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /admin\nDisallow: /owner\nSitemap: {base_url(request)}/sitemap.xml\n"


@app.get("/sitemap.xml")
def sitemap(request: Request):
    b = base_url(request)
    urls = "".join(f"<url><loc>{b}{p}</loc></url>" for p in ("/", "/login", "/register"))
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>', media_type="application/xml")


@app.get("/manifest.json")
def manifest():
    name = get_setting("brand_name", "ZAD PAY")
    return JSONResponse({"name": f"{name} - ZAD OSINT Gateway", "short_name": name, "start_url": "/dashboard", "scope": "/", "display": "standalone",
                         "background_color": "#ffffff", "theme_color": get_setting("primary_color", "#1456f0"), "description": "ZAD OSINT Gateway payment platform",
                         "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                                   {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]},
                        media_type="application/manifest+json")


@app.get("/sw.js")
def sw():
    return Response((STATIC / "sw.js").read_text(), media_type="application/javascript", headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
_INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/{full_path:path}")
def spa(full_path: str, request: Request):
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not found."}, status_code=404)
    brand = html.escape(get_setting("brand_name", "ZAD PAY"))
    page = _INDEX.replace("%%BASE_URL%%", html.escape(base_url(request))).replace("%%BRAND%%", brand)
    return HTMLResponse(page, headers={"Cache-Control": "no-cache"})
