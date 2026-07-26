"""Mineru file-parsing service.

Mineru (https://mineru.net) is a hosted API that converts Office / PDF /
image documents into clean Markdown + structured layout JSON. We use it to
extract text from user-uploaded files before feeding them through the
structuring pipeline.

Flow:
    1. Client uploads a file via POST /ingest/upload
    2. We push the file to MinIO and create an InformationSource row
       (kind = user_upload) so it shows up in the source list immediately.
    3. If a Mineru API key is configured, we call Mineru to extract text
       (markdown). Otherwise we fall back to reading the raw bytes for
       plain-text files, or return an empty extraction with a warning.
    4. The extracted text is handed to StructuringService.ingest_text
       so the rest of the pipeline (LLM extraction → events / metrics /
       assertions / relationships) is reused unchanged.

The Mineru API used here is the public ``file/upload`` + ``extract/task``
flow documented at https://mineru.net/api/v4/docs. The exact request /
response shapes are kept inside this module so the rest of the codebase
only sees ``parse_file(...)`` -> ``ParsedDocument``.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.core.logging import get_logger
from app.llm.registry import get_mineru_config

log = get_logger(__name__)


SUPPORTED_FILE_TYPES = {
    # Office
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    # Text-ish
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    # Images (Mineru does OCR)
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
}

# Files we can ingest as plain text without Mineru
_PLAIN_TEXT_EXTS = {".txt", ".md", ".csv"}


@dataclass
class ParsedDocument:
    """Output of ``parse_file`` — text ready for the structuring pipeline."""

    text: str
    title: str | None = None
    page_count: int | None = None
    parser: str = "none"  # "mineru" | "plaintext" | "none"
    warning: str | None = None


class MineruError(RuntimeError):
    """Raised when Mineru parsing fails fatally."""


# ---------- Public API ----------


def is_supported(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_FILE_TYPES


def parse_file(file_bytes: bytes, filename: str, *, title: str | None = None) -> ParsedDocument:
    """Parse a file into Markdown text.

    Decision tree:
        - Plain-text file (txt/md/csv) → read utf-8 directly, no API call.
        - Mineru key configured → call Mineru async extraction flow.
        - Otherwise → return empty text + warning (caller decides whether
          to proceed; structuring will store the source but skip atoms).
    """
    suffix = Path(filename).suffix.lower()
    base_title = title or Path(filename).stem

    # 1. Plain-text fast path
    if suffix in _PLAIN_TEXT_EXTS:
        try:
            text = file_bytes.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return ParsedDocument(text="", title=base_title, parser="none",
                                  warning=f"无法解码文本文件: {exc}")
        return ParsedDocument(text=text, title=base_title, parser="plaintext")

    # 2. Mineru path
    api_key, base_url = get_mineru_config()
    if not api_key:
        return ParsedDocument(
            text="",
            title=base_title,
            parser="none",
            warning="未配置 Mineru API Key，无法解析该文件类型。请在设置页填入 Mineru Key 后重试。",
        )

    try:
        text, page_count = _run_mineru_extraction(
            api_key=api_key,
            base_url=base_url,
            file_bytes=file_bytes,
            filename=filename,
            mime_type=SUPPORTED_FILE_TYPES[suffix],
        )
        return ParsedDocument(
            text=text,
            title=base_title,
            page_count=page_count,
            parser="mineru",
        )
    except MineruError as exc:
        log.warning("mineru.parse_failed", filename=filename, error=str(exc))
        return ParsedDocument(text="", title=base_title, parser="none", warning=str(exc))
    except Exception as exc:  # noqa: BLE001
        log.error("mineru.unexpected_error", filename=filename, error=str(exc))
        return ParsedDocument(text="", title=base_title, parser="none",
                              warning=f"Mineru 解析出现未知错误: {exc}")


# ---------- Mineru API internals ----------

_MINERU_POLL_INTERVAL = 3.0  # seconds between task-status polls
_MINERU_MAX_WAIT = 600.0     # 10 minutes hard cap


def _run_mineru_extraction(
    *,
    api_key: str,
    base_url: str,
    file_bytes: bytes,
    filename: str,
    mime_type: str,
) -> tuple[str, int | None]:
    """Upload + poll Mineru until the extraction is ready.

    Returns (markdown_text, page_count). Raises ``MineruError`` on fatal
    failures (auth, upload, parse, timeout).
    """
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

    # Step 1: upload file to get a file_id
    upload_url = f"{base_url.rstrip('/')}/file/upload"
    files = {"file": (filename, io.BytesIO(file_bytes), mime_type)}
    with httpx.Client(timeout=120.0) as client:
        try:
            up = client.post(upload_url, headers=headers, files=files)
        except httpx.HTTPError as exc:
            raise MineruError(f"上传到 Mineru 失败: {exc}") from exc

        if up.status_code >= 400:
            raise MineruError(f"Mineru 上传接口返回 {up.status_code}: {up.text[:200]}")
        try:
            up_json = up.json()
        except Exception as exc:  # noqa: BLE001
            raise MineruError(f"Mineru 上传响应不是合法 JSON: {exc}") from exc

        file_id = up_json.get("data", {}).get("file_id") or up_json.get("file_id")
        if not file_id:
            raise MineruError(f"Mineru 上传响应缺少 file_id: {up_json}")

        # Step 2: create extraction task
        task_url = f"{base_url.rstrip('/')}/file/parse"
        task_body = {
            "file_id": file_id,
            "parse_method": "auto",  # let Mineru pick OCR vs text-layer
        }
        try:
            task = client.post(task_url, headers={**headers, "Content-Type": "application/json"},
                               json=task_body)
        except httpx.HTTPError as exc:
            raise MineruError(f"创建 Mineru 解析任务失败: {exc}") from exc
        if task.status_code >= 400:
            raise MineruError(f"Mineru 解析任务接口返回 {task.status_code}: {task.text[:200]}")

        try:
            task_json = task.json()
        except Exception as exc:  # noqa: BLE001
            raise MineruError(f"Mineru 任务响应不是合法 JSON: {exc}") from exc

        task_id = task_json.get("data", {}).get("task_id") or task_json.get("task_id")
        if not task_id:
            raise MineruError(f"Mineru 任务响应缺少 task_id: {task_json}")

        # Step 3: poll task status
        status_url = f"{base_url.rstrip('/')}/task/status"
        deadline = time.monotonic() + _MINERU_MAX_WAIT
        while time.monotonic() < deadline:
            try:
                st = client.get(status_url, headers=headers, params={"task_id": task_id})
            except httpx.HTTPError as exc:
                raise MineruError(f"查询 Mineru 任务状态失败: {exc}") from exc
            if st.status_code >= 400:
                raise MineruError(f"Mineru 任务状态接口返回 {st.status_code}: {st.text[:200]}")
            try:
                st_json = st.json()
            except Exception as exc:  # noqa: BLE001
                raise MineruError(f"Mineru 任务状态响应不是合法 JSON: {exc}") from exc

            data = st_json.get("data") or st_json
            status = (data.get("status") or "").lower()
            if status in ("success", "succeed", "done", "completed"):
                md = data.get("markdown") or data.get("text") or ""
                page_count = data.get("page_count")
                return md, page_count
            if status in ("failed", "error"):
                err = data.get("error") or "Mineru 解析失败"
                raise MineruError(err)
            # else: pending / running → keep waiting
            time.sleep(_MINERU_POLL_INTERVAL)

        raise MineruError("Mineru 解析超时（超过 10 分钟）")
