"""FastAPI REST server for pdf2docx-plus.

Exposes:
    POST /convert        multipart upload -> streams DOCX back
    POST /extract-tables multipart upload -> JSON tables
    GET  /healthz        liveness probe
    GET  /version        version string

Run:

    pip install 'pdf2docx-plus[rest]'
    pdf2docx-plus serve --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import io
from pathlib import Path

try:
    from fastapi import FastAPI, File, Form, HTTPException, UploadFile
    from fastapi.responses import JSONResponse, StreamingResponse
except ImportError as e:  # pragma: no cover
    raise RuntimeError(
        "REST server requires the 'rest' extra: pip install 'pdf2docx-plus[rest]'"
    ) from e

from .api import Converter
from .errors import ConversionError, PasswordRequired
from .version import __version__

app = FastAPI(title="pdf2docx-plus", version=__version__)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
def version() -> dict[str, str]:
    return {"version": __version__}


@app.post("/convert")
async def convert_endpoint(
    file: UploadFile = File(...),
    password: str | None = Form(default=None),
    profile: str = Form(default="fidelity"),
    timeout_s: float = Form(default=120),
) -> StreamingResponse:
    data = await file.read()
    sink = io.BytesIO()
    try:
        with Converter(stream=data, password=password) as cv:
            result = cv.convert(sink, profile=profile, timeout_s=timeout_s, continue_on_error=True)
    except PasswordRequired as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    except ConversionError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    sink.seek(0)
    headers = {
        "X-Pages-Total": str(result.pages_total),
        "X-Pages-Ok": str(result.pages_ok),
        "X-Pages-Failed": str(result.pages_failed),
        "X-Elapsed-Seconds": f"{result.elapsed_s:.3f}",
        "Content-Disposition": f'attachment; filename="{Path(file.filename or "out").stem}.docx"',
    }
    return StreamingResponse(
        sink,
        media_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        headers=headers,
    )


@app.post("/extract-tables")
async def extract_tables_endpoint(
    file: UploadFile = File(...),
    password: str | None = Form(default=None),
) -> JSONResponse:
    data = await file.read()
    try:
        with Converter(stream=data, password=password) as cv:
            tables = cv.extract_tables()
    except PasswordRequired as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    except ConversionError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return JSONResponse({"tables": tables})
