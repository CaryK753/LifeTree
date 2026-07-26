"""Sample plugin: pull a web page and feed it to the structuring pipeline.

Usage in UI:
    参数 url：要抓取的网页地址，例如 https://www.example.com/news/...
    参数 title：信源标题（可选）

The plugin demonstrates the three-step contract:
    1. fetch(params) downloads the page HTML and strips tags.
    2. transform(raw, llm) is OPTIONAL here — we let StructuringService
       run its own LLM extraction.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.services.plugins import Plugin, PluginManifest, PluginParam


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _html_to_text(html: str) -> str:
    # Very small HTML→text stripper. Plugins are free to use BeautifulSoup
    # / trafilatura for richer extraction; this keeps the example dependency-free.
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html)
    text = _TAG_RE.sub(" ", html)
    return _WS_RE.sub(" ", text).strip()


class Plugin:
    @staticmethod
    def manifest() -> PluginManifest:
        return PluginManifest(
            id="sample_web_scraper",  # overwritten by runner to match filename
            name="网页抓取",
            description="下载一个网页，提取正文，让 AI 把里面的信息提炼入库",
            version="0.1.0",
            author="LifeTree",
            tags=["news", "web"],
            params=[
                PluginParam(
                    name="url",
                    label="网址",
                    type="string",
                    required=True,
                    help="要抓取的页面 URL，例如 https://example.com/article",
                ),
                PluginParam(
                    name="title",
                    label="信源标题（可选）",
                    type="string",
                    required=False,
                ),
            ],
        )

    @staticmethod
    def fetch(params: dict[str, Any]) -> str:
        url = params["url"]
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            )
        }
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            return _html_to_text(resp.text)
