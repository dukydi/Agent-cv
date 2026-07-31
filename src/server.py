"""Agent CV — API FastAPI.

Expose deux modes :

- **Sync** (legacy) : ``POST /generate`` et ``POST /generate/pptx`` — retournent
  le PPTX dans la réponse HTTP. Conservés pour la CLI et les usages directs.
- **Async** (Polaris) : ``POST /jobs`` → 202 + ``job_id``, traitement dans un
  ``ThreadPoolExecutor`` (max 3 jobs simultanés), puis callback HTTP POST vers
  l'URL fournie par l'appelant. ``GET /jobs/{id}`` permet de récupérer l'état
  en fallback si le callback échoue.

Tous les endpoints (sauf ``/health``) sont protégés par ``X-Shared-Secret``
si ``CV_AGENT_SHARED_SECRET`` est défini dans l'environnement. Si vide
(défaut), l'auth est désactivée (mode dev / tests).
"""
from __future__ import annotations

import base64
import binascii
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from src import config
from src.analysis.llm_client import LLMClient, LLMError
from src.analysis.parsing import ParsingError, parse_pdf_bytes, parse_text
from src.analysis.pipeline.orchestrate import generate
from src.rendering.constraints import default_constraints
from src.rendering.pptx_renderer import render
from src.schemas import ApiError, GenerateResponse, RawDocument


PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

CALLBACK_RETRY_DELAYS = [1, 2, 4, 8, 16, 32, 64, 128]  # secondes, total ~5 min
COMPLETED_JOB_TTL = timedelta(hours=1)
ORPHANED_JOB_TTL = timedelta(hours=24)
EVICTION_INTERVAL = timedelta(minutes=5)

logger = logging.getLogger("agent_cv.server")


JobStatus = Literal["pending", "processing", "completed", "failed"]


@dataclass
class Job:
    job_id: str
    status: JobStatus = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    callback_url: str | None = None
    callback_secret: str | None = None
    callback_delivered: bool = False
    pptx_base64: str | None = None
    warnings: list[str] = field(default_factory=list)
    error: ApiError | None = None
    # Consommation LLM du job, remontée à Polaris par le callback (gouvernance).
    usage: dict[str, int] | None = None
    cost_usd: float | None = None


class FilePayload(BaseModel):
    """Fichier transporté en base64 — aligné sur le ``FilePayload`` Polaris."""

    name: str
    mime_type: str | None = None
    content_base64: str


class JobCreateRequest(BaseModel):
    cvs: list[FilePayload] = Field(..., min_length=1)
    ao_file: FilePayload | None = None
    ao_text: str | None = None
    callback_url: str
    callback_secret: str


class JobAcceptedResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobStateResponse(BaseModel):
    job_id: str
    status: JobStatus
    pptx_base64: str | None = None
    warnings: list[str] = Field(default_factory=list)
    error: ApiError | None = None


_JOBS: dict[str, Job] = {}
_JOBS_LOCK = threading.Lock()
_executor: ThreadPoolExecutor | None = None
_eviction_stop = threading.Event()
_eviction_thread: threading.Thread | None = None


# ───────────────────────────────────────────────────────────────────── helpers


def _max_workers() -> int:
    raw = getattr(config, "MAX_CONCURRENT_JOBS", None)
    if raw is None:
        return 3
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 3
    return max(1, n)


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=_max_workers(), thread_name_prefix="agent-cv-job"
        )
    return _executor


def _shutdown_executor() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=False)
        _executor = None


def _check_shared_secret(
    x_shared_secret: Annotated[str | None, Header(alias="X-Shared-Secret")] = None,
) -> None:
    expected = getattr(config, "CV_AGENT_SHARED_SECRET", "") or ""
    if not expected:
        return
    if x_shared_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing shared secret")


def _decode_base64(payload: FilePayload) -> bytes:
    try:
        return base64.b64decode(payload.content_base64, validate=True)
    except (ValueError, binascii.Error) as e:
        raise HTTPException(
            status_code=400, detail=f"Base64 invalide pour '{payload.name}': {e}"
        )


def _parse_payload(req: JobCreateRequest) -> tuple[list[RawDocument], RawDocument]:
    if (req.ao_file is None) == (not req.ao_text):
        raise HTTPException(
            status_code=400,
            detail="Fournir exactement un de : ao_file (PDF) ou ao_text (texte)",
        )

    cv_docs: list[RawDocument] = []
    for cv in req.cvs:
        content = _decode_base64(cv)
        try:
            cv_docs.append(parse_pdf_bytes(content, cv.name))
        except ParsingError as e:
            raise HTTPException(
                status_code=400, detail=f"Erreur sur CV '{cv.name}': {e}"
            )

    if req.ao_file is not None:
        content = _decode_base64(req.ao_file)
        try:
            ao = parse_pdf_bytes(content, req.ao_file.name)
        except ParsingError as e:
            raise HTTPException(status_code=400, detail=f"Erreur sur AO: {e}")
    else:
        try:
            ao = parse_text(req.ao_text or "", "ao-input.txt")
        except ParsingError as e:
            raise HTTPException(status_code=400, detail=f"Erreur sur AO texte: {e}")

    return cv_docs, ao


def _update_job(job_id: str, **changes) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        for k, v in changes.items():
            setattr(job, k, v)


def _snapshot_job(job_id: str) -> Job | None:
    with _JOBS_LOCK:
        return _JOBS.get(job_id)


# ───────────────────────────────────────────────────────────────────── worker


def _process_job(
    job_id: str,
    cv_docs: list[RawDocument],
    ao: RawDocument,
    callback_url: str,
    callback_secret: str,
) -> None:
    """Exécute le pipeline puis poste le callback. Tourne dans le ThreadPool."""
    start = time.monotonic()
    _update_job(job_id, status="processing")
    constraints = default_constraints()

    # Instancié ici (et non dans `generate`) pour pouvoir relire la consommation
    # même quand le pipeline échoue : les tokens ont été brûlés quand même.
    llm = LLMClient()

    try:
        adapted = generate(cv_docs, ao, constraints, client=llm)
        llm_seconds = time.monotonic() - start
        out = render(adapted, constraints)
        render_seconds = time.monotonic() - start - llm_seconds
    except LLMError as e:
        logger.exception("job %s — LLM error", job_id)
        _update_job(
            job_id,
            status="failed",
            completed_at=datetime.now(timezone.utc),
            error=ApiError(code="llm_error", message=str(e)),
            usage=llm.usage_totals(),
            cost_usd=llm.total_cost_usd(),
        )
    except Exception as e:
        logger.exception("job %s — internal error", job_id)
        _update_job(
            job_id,
            status="failed",
            completed_at=datetime.now(timezone.utc),
            error=ApiError(code="internal", message=str(e)),
            usage=llm.usage_totals(),
            cost_usd=llm.total_cost_usd(),
        )
    else:
        _update_job(
            job_id,
            status="completed",
            completed_at=datetime.now(timezone.utc),
            pptx_base64=base64.b64encode(out.pptx_bytes).decode("ascii"),
            warnings=list(out.truncations),
            usage=llm.usage_totals(),
            cost_usd=llm.total_cost_usd(),
        )
        logger.info(
            "job %s — completed in %.1fs (llm=%.1fs render=%.1fs) "
            "%d call(s), %d tokens, $%.4f",
            job_id,
            time.monotonic() - start,
            llm_seconds,
            render_seconds,
            llm.call_count,
            llm.usage_totals()["total_tokens"],
            llm.total_cost_usd(),
        )

    _send_callback_with_retry(job_id, callback_url, callback_secret)


def _post_callback(url: str, payload: dict, headers: dict) -> None:
    """Point d'extension testable : un seul POST HTTP, isolé pour mock facile."""
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, json=payload, headers=headers)
    resp.raise_for_status()


def _send_callback_with_retry(
    job_id: str, callback_url: str, callback_secret: str
) -> None:
    job = _snapshot_job(job_id)
    if job is None:
        return

    payload = {
        "job_id": job_id,
        "status": job.status,
        "pptx_base64": job.pptx_base64,
        "warnings": list(job.warnings),
        "error": job.error.model_dump() if job.error else None,
        # Gouvernance Polaris : clés input_tokens / output_tokens / total_tokens.
        # Champs optionnels côté Polaris — un ancien Polaris les ignorera.
        "usage": job.usage,
        "cost_usd": job.cost_usd,
    }
    headers = {"X-Callback-Secret": callback_secret}

    delays = [0, *CALLBACK_RETRY_DELAYS]
    for attempt, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        try:
            _post_callback(callback_url, payload, headers)
            _update_job(job_id, callback_delivered=True)
            logger.info("job %s — callback delivered (attempt %d)", job_id, attempt + 1)
            return
        except httpx.HTTPError as e:
            logger.warning(
                "job %s — callback attempt %d failed: %s", job_id, attempt + 1, e
            )

    logger.error("job %s — callback orphaned after %d attempts", job_id, len(delays))


# ──────────────────────────────────────────────────────────────────── eviction


def _evict_old_jobs() -> None:
    now = datetime.now(timezone.utc)
    to_delete: list[str] = []
    with _JOBS_LOCK:
        for jid, job in _JOBS.items():
            if job.completed_at and now - job.completed_at > COMPLETED_JOB_TTL:
                to_delete.append(jid)
            elif (
                job.completed_at is None
                and now - job.created_at > ORPHANED_JOB_TTL
            ):
                to_delete.append(jid)
        for jid in to_delete:
            _JOBS.pop(jid, None)
    if to_delete:
        logger.info("eviction — removed %d job(s)", len(to_delete))


def _eviction_loop() -> None:
    while not _eviction_stop.wait(EVICTION_INTERVAL.total_seconds()):
        try:
            _evict_old_jobs()
        except Exception:
            logger.exception("eviction loop error")


def _start_eviction_thread() -> None:
    global _eviction_thread
    if _eviction_thread is not None and _eviction_thread.is_alive():
        return
    _eviction_stop.clear()
    _eviction_thread = threading.Thread(
        target=_eviction_loop, name="agent-cv-eviction", daemon=True
    )
    _eviction_thread.start()


def _stop_eviction_thread() -> None:
    global _eviction_thread
    _eviction_stop.set()
    _eviction_thread = None


# ─────────────────────────────────────────────────────────────────── lifespan


def _warn_if_model_not_priceable() -> None:
    """Un modèle absent de la table de prix litellm remonte un coût de 0 $ sans
    lever d'erreur : la gouvernance Polaris afficherait alors une dépense nulle.
    On le signale au démarrage plutôt que de le découvrir sur les factures."""
    try:
        import litellm

        litellm.get_model_info(config.LLM_MODEL)
    except Exception:  # noqa: BLE001
        logger.warning(
            "modele %s inconnu de la table de prix litellm — cost_usd remontera 0 $",
            config.LLM_MODEL,
        )


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _warn_if_model_not_priceable()
    _get_executor()
    _start_eviction_thread()
    try:
        yield
    finally:
        _stop_eviction_thread()
        _shutdown_executor()


app = FastAPI(title="Agent CV API", version="2.0.0", lifespan=_lifespan)


# ────────────────────────────────────────────────────────────────── endpoints


@app.get("/health")
def health():
    return {"status": "ok", "service": "agent-cv-v2"}


def _read_inputs(
    cvs: list[UploadFile],
    ao_file: UploadFile | None,
    ao_text: str | None,
) -> tuple[list[RawDocument], RawDocument]:
    if not cvs:
        raise HTTPException(status_code=400, detail="Au moins un CV requis")
    if (ao_file is None) == (not ao_text):
        raise HTTPException(
            status_code=400,
            detail="Fournir exactement un de : ao_file (PDF) ou ao_text (texte)",
        )

    cv_docs: list[RawDocument] = []
    for f in cvs:
        try:
            content = f.file.read()
            cv_docs.append(parse_pdf_bytes(content, f.filename or "cv.pdf"))
        except ParsingError as e:
            raise HTTPException(
                status_code=400, detail=f"Erreur sur CV '{f.filename}': {e}"
            )

    if ao_file is not None:
        try:
            content = ao_file.file.read()
            ao = parse_pdf_bytes(content, ao_file.filename or "ao.pdf")
        except ParsingError as e:
            raise HTTPException(status_code=400, detail=f"Erreur sur AO: {e}")
    else:
        try:
            ao = parse_text(ao_text or "", "ao-input.txt")
        except ParsingError as e:
            raise HTTPException(status_code=400, detail=f"Erreur sur AO texte: {e}")

    return cv_docs, ao


@app.post(
    "/generate",
    response_model=GenerateResponse,
    dependencies=[Depends(_check_shared_secret)],
)
def generate_endpoint(
    cvs: Annotated[list[UploadFile], File(description="1 à N PDFs du CV consultant")],
    ao_file: Annotated[
        UploadFile | None,
        File(description="PDF de l'AO (alternatif à ao_text)"),
    ] = None,
    ao_text: Annotated[
        str | None,
        Form(description="Texte de l'AO (alternatif à ao_file)"),
    ] = None,
):
    cv_docs, ao = _read_inputs(cvs, ao_file, ao_text)
    constraints = default_constraints()

    try:
        adapted = generate(cv_docs, ao, constraints)
    except LLMError as e:
        return GenerateResponse(
            success=False,
            error=ApiError(code="llm_error", message=str(e)),
        )
    except Exception as e:
        return GenerateResponse(
            success=False,
            error=ApiError(code="internal", message=str(e)),
        )

    try:
        out = render(adapted, constraints)
    except Exception as e:
        return GenerateResponse(
            success=False,
            error=ApiError(code="render_error", message=str(e)),
            adapted_cv=adapted,
        )

    return GenerateResponse(
        success=True,
        adapted_cv=adapted,
        pptx_base64=base64.b64encode(out.pptx_bytes).decode("ascii"),
        warnings=out.truncations,
    )


@app.post("/generate/pptx", dependencies=[Depends(_check_shared_secret)])
def generate_pptx_endpoint(
    cvs: Annotated[list[UploadFile], File()],
    ao_file: Annotated[UploadFile | None, File()] = None,
    ao_text: Annotated[str | None, Form()] = None,
):
    cv_docs, ao = _read_inputs(cvs, ao_file, ao_text)
    constraints = default_constraints()

    try:
        adapted = generate(cv_docs, ao, constraints)
        out = render(adapted, constraints)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal: {e}")

    nom_raw = adapted.consultant.nom or "cv"
    slug = nom_raw.replace("[[", "").replace("]]", "").replace(" ", "_").strip() or "cv"
    return Response(
        content=out.pptx_bytes,
        media_type=PPTX_MIME,
        headers={"Content-Disposition": f'attachment; filename="cv-{slug}.pptx"'},
    )


@app.post(
    "/jobs",
    response_model=JobAcceptedResponse,
    status_code=202,
    dependencies=[Depends(_check_shared_secret)],
)
def create_job(req: JobCreateRequest):
    cv_docs, ao = _parse_payload(req)

    job_id = str(uuid.uuid4())
    with _JOBS_LOCK:
        _JOBS[job_id] = Job(
            job_id=job_id,
            callback_url=req.callback_url,
            callback_secret=req.callback_secret,
        )

    _get_executor().submit(
        _process_job, job_id, cv_docs, ao, req.callback_url, req.callback_secret
    )
    logger.info("job %s — submitted", job_id)

    return JobAcceptedResponse(job_id=job_id, status="pending")


@app.get(
    "/jobs/{job_id}",
    response_model=JobStateResponse,
    dependencies=[Depends(_check_shared_secret)],
)
def get_job(job_id: str):
    job = _snapshot_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStateResponse(
        job_id=job.job_id,
        status=job.status,
        pptx_base64=job.pptx_base64,
        warnings=list(job.warnings),
        error=job.error,
    )
