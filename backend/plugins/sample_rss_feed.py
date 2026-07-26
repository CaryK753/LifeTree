"""Sample plugin: pull an RSS feed and turn entries into LifeTree atoms.

This plugin demonstrates the ``transform(raw, llm)`` hook — instead of
letting StructuringService run its own extraction, we ask the LLM to
build a compact Markdown digest of the feed entries (top N by recency),
which is then handed to StructuringService.

Params:
    feed_url: RSS / Atom feed URL
    limit:    how many recent entries to keep (default 10)
"""

from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from app.services.plugins import Plugin, PluginManifest, PluginParam


def _parse_feed(xml: str, limit: int) -> list[dict[str, str]]:
    """Minimal RSS/Atom parser → list of {title, link, summary, published}."""
    root = ET.fromstring(xml)
    items: list[dict[str, str]] = []

    # RSS 2.0
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        items.append({"title": title, "link": link, "summary": desc, "published": pub})

    # Atom
    ns = {"a": "http://www.w3.org/2005/Atom"}
    if not items:
        for entry in root.findall("a:entry", ns):
            items.append({
                "title": (entry.findtext("a:title", default="", namespaces=ns) or "").strip(),
                "link": (entry.find("a:link", ns) or ET.Element("x")).get("href", ""),
                "summary": (entry.findtext("a:summary", default="", namespaces=ns) or "").strip(),
                "published": (entry.findtext("a:published", default="", namespaces=ns) or "").strip(),
            })

    return items[:limit]


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    return _TAG_RE.sub(" ", s).strip()


class Plugin:
    @staticmethod
    def manifest() -> PluginManifest:
        return PluginManifest(
            id="sample_rss_feed",
            name="RSS 订阅抓取",
            description="拉取一个 RSS/Atom 订阅源，把最近若干条用 LLM 整理成结构化信息",
            version="0.1.0",
            author="LifeTree",
            tags=["news", "rss"],
            params=[
                PluginParam(
                    name="feed_url",
                    label="订阅源地址",
                    type="string",
                    required=True,
                    help="RSS / Atom feed URL，例如 https://example.com/rss.xml",
                ),
                PluginParam(
                    name="limit",
                    label="抓取条数",
                    type="number",
                    required=False,
                    default=10,
                ),
            ],
        )

    @staticmethod
    def fetch(params: dict[str, Any]) -> str:
        url = params["feed_url"]
        limit = int(params.get("limit") or 10)
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={"User-Agent": "LifeTree-Plugin/0.1 (+https://lifetree.local)"},
            )
            resp.raise_for_status()
            items = _parse_feed(resp.text, limit)

        # Return a JSON-ish Markdown blob; transform() will refine it.
        lines = [f"# Feed: {url}", ""]
        for i, it in enumerate(items, 1):
            lines.append(f"## {i}. {it['title']}")
            if it["published"]:
                lines.append(f"- 发布时间: {it['published']}")
            if it["link"]:
                lines.append(f"- 链接: {it['link']}")
            if it["summary"]:
                lines.append("- 摘要: " + _strip_html(it["summary"])[:500])
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def transform(raw: str, llm) -> str:
        """Ask the LLM to condense the feed into a clean digest.

        If anything goes wrong (LLM not configured, request failed, …),
        the runner catches the exception and falls back to ``raw`` —
        so we don't need to defensive-code here.
        """
        client = llm.instructor
        model = llm.chat_model.model.name
        out = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一个新闻编辑助手。把用户提供的 RSS 摘要整理成简洁的中文 Markdown，"
                        "突出每条信息中可能影响决策的事实（数字、时间、政策变化）。"
                        "不要发明信息，只整理已有内容。"
                    ),
                },
                {"role": "user", "content": raw},
            ],
            temperature=0.2,
            max_tokens=1500,
        )
        return out.choices[0].message.content or raw
