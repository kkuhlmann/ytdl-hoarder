import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import DEFAULT_INSECURE_SECRET_KEY, settings
from database import db
from logger import logger
from middleware.auth import OptionalAuthMiddleware
from orchestrator import orch
from orchestrator.recovery import retry_scheduler_loop, run_startup_recovery
from orchestrator.scheduler import cron_loop
from progress_publisher import broadcaster
from repositories import settings as settings_repo
from repositories.errors import InvalidStateError, NotFoundError
from routers.auth import router as auth_router
from routers.clips import router as clips_router
from routers.media import router as media_router
from routers.media_details import router as media_details_router
from routers.playlists import router as playlists_router
from routers.settings import router as settings_router
from routers.sse import router as sse_router
from routers.stats import router as stats_router
from routers.subscriptions import router as subscriptions_router
from routers.task_records import router as tasks_router
from routers.ytdl_router import router as ytdl_router
from tasks import register_all_jobs
from tasks.registry import build_cron_jobs
from utils import load_embedding_model

STATIC_DIR = Path(os.getenv('STATIC_FILES_DIR', '/app/static'))
SERVE_FRONTEND = STATIC_DIR.exists() and (STATIC_DIR / 'index.html').exists()

API_PREFIX = '/api' if SERVE_FRONTEND else ''


def docs_kwargs(serve_frontend: bool) -> dict[str, str | None]:
    """OpenAPI schema and its two UIs are dev-only; the production image never registers them.

    Returns FastAPI constructor kwargs. In prod the routes simply don't exist, so `/docs`
    falls through to the SPA catch-all like any other unknown path.
    """
    if serve_frontend:
        return {'openapi_url': None, 'docs_url': None, 'redoc_url': None}
    return {}


BANNER = r"""
     _______________/\/\____________/\/\__/\/\______________/\/\__________________________________________________/\/\_________________________
    _/\/\__/\/\__/\/\/\/\/\________/\/\__/\/\______________/\/\__________/\/\/\____/\/\/\______/\/\__/\/\________/\/\____/\/\/\____/\/\__/\/\_
   _/\/\__/\/\____/\/\________/\/\/\/\__/\/\____/\/\/\/\__/\/\/\/\____/\/\__/\/\______/\/\____/\/\/\/\______/\/\/\/\__/\/\/\/\/\__/\/\/\/\___
  ___/\/\/\/\____/\/\______/\/\__/\/\__/\/\______________/\/\__/\/\__/\/\__/\/\__/\/\/\/\____/\/\________/\/\__/\/\__/\/\________/\/\_______
 _______/\/\____/\/\/\______/\/\/\/\__/\/\/\____________/\/\__/\/\____/\/\/\____/\/\/\/\/\__/\/\__________/\/\/\/\____/\/\/\/\__/\/\_______
_/\/\/\/\_________________________________________________________________________________________________________________________________
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(BANNER)  # noqa: T201 — startup banner, deliberately raw stdout, not a log record

    if settings.auth.secret_key == DEFAULT_INSECURE_SECRET_KEY:
        msg = (
            'auth.secret_key is still the sample value, which is published in this '
            'repo — anyone could forge an admin token. Set a real one as '
            'auth.secret_key in config.yml (or, outside Docker, via the '
            'AUTH__SECRET_KEY environment variable). '
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
        raise RuntimeError(msg)

    db.initialize_database()

    app.state.embedding_model = load_embedding_model()

    register_all_jobs()
    broadcaster.set_loop(asyncio.get_running_loop())
    app_settings = await settings_repo.get_settings()
    await orch.start(settings_repo.lane_concurrency(app_settings))

    await asyncio.to_thread(run_startup_recovery, orch, settings.tasks.purge_on_startup)

    orch.add_service(retry_scheduler_loop(orch), 'retry-scheduler')
    orch.add_service(
        cron_loop(build_cron_jobs(app_settings.subscription_check_minutes), lambda: orch.running),
        'cron-scheduler',
    )

    if SERVE_FRONTEND:
        logger.info(f'Production mode: serving frontend from {STATIC_DIR}')
        logger.info(f'API routes prefixed with {API_PREFIX}')
    else:
        logger.info('Development mode: API-only, no frontend serving')

    yield

    logger.info('Shutting down application.')
    await orch.stop()
    await db.close()


app = FastAPI(lifespan=lifespan, **docs_kwargs(SERVE_FRONTEND))


# Repositories raise transport-agnostic errors; the HTTP status lives here, at the edge.
@app.exception_handler(NotFoundError)
async def _not_found_error_handler(_request, exc):
    return JSONResponse(status_code=404, content={'detail': str(exc)})


@app.exception_handler(InvalidStateError)
async def _invalid_state_error_handler(_request, exc):
    return JSONResponse(status_code=400, content={'detail': str(exc)})


# Auth middleware — reads JWT cookie, never rejects (enforcement is per-route via dependencies)
app.add_middleware(OptionalAuthMiddleware)

app.include_router(auth_router, tags=['auth'], prefix=f'{API_PREFIX}/auth')
app.include_router(
    subscriptions_router, tags=['subscriptions'], prefix=f'{API_PREFIX}/subscriptions'
)
app.include_router(
    media_details_router, tags=['media details'], prefix=f'{API_PREFIX}/media-details'
)
app.include_router(tasks_router, tags=['tasks'], prefix=f'{API_PREFIX}/tasks')
app.include_router(ytdl_router, tags=['YouTube download'], prefix=f'{API_PREFIX}/ytdl')
app.include_router(media_router, tags=['media'], prefix=f'{API_PREFIX}/media')
app.include_router(clips_router, tags=['clips'], prefix=f'{API_PREFIX}/clips')
app.include_router(playlists_router, tags=['playlists'], prefix=f'{API_PREFIX}/playlists')
app.include_router(sse_router, tags=['sse'], prefix=f'{API_PREFIX}/sse')
app.include_router(settings_router, tags=['settings'], prefix=f'{API_PREFIX}/settings')
app.include_router(stats_router, tags=['stats'], prefix=f'{API_PREFIX}/stats')


@app.get('/health')
def healthcheck():
    return {'status': 'ok'}


def resolve_spa_file(path: str) -> Path:
    """Map a request path to a file to serve, defaulting to the SPA entrypoint.

    Containment must be re-checked *after* resolving: uvicorn percent-decodes the
    request path before routing and Starlette's `:path` convertor matches `..`, so
    the raw join escapes STATIC_DIR (`/%2e%2e/%2e%2e/etc/app/config.yml`). Resolving
    also collapses symlinks that point outside the static root.
    """
    static_root = STATIC_DIR.resolve()
    index = static_root / 'index.html'

    try:
        candidate = (static_root / path).resolve()
    except (OSError, ValueError):
        # ValueError, not OSError, is what an embedded NUL raises out of realpath().
        return index

    if not candidate.is_relative_to(static_root):
        return index

    if candidate.is_file():
        return candidate

    # Next.js trailingSlash: true emits directories containing index.html
    if (candidate / 'index.html').is_file():
        return candidate / 'index.html'

    return index


if SERVE_FRONTEND:
    if (STATIC_DIR / '_next').exists():
        app.mount('/_next', StaticFiles(directory=str(STATIC_DIR / '_next')), name='next-static')

    # Catch-all route for SPA - must be after API routes
    @app.get('/{path:path}')
    async def serve_spa(path: str):
        return FileResponse(resolve_spa_file(path))
else:
    # allow_origins=['*'] with allow_credentials=True makes Starlette echo the
    # request Origin back and set Access-Control-Allow-Credentials, so any site
    # could read API responses cross-origin. Only added in dev mode — the
    # production image serves the frontend same-origin and needs no CORS at all.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.auth.allowed_origins,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )
