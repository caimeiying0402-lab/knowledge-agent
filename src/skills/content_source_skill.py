"""固定内容源扫描 — RSS + 网页抓取，作为 Discovery 补充数据源"""
import logging
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
import yaml

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
CONFIG_PATH = BASE_DIR / "config" / "content_sources.yaml"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
}


def load_config() -> dict:
    """加载内容源配置"""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {"sources": {"rss": [], "douban_groups": [], "web_pages": []}}


def scan_rss_feeds() -> list[dict]:
    """扫描所有启用的 RSS 源，返回文章列表"""
    config = load_config()
    rss_sources = config.get("sources", {}).get("rss", [])
    max_items = config.get("schedule", {}).get("max_items_per_source", 5)

    results = []
    for src in rss_sources:
        if not src.get("enabled", True):
            continue
        items = _fetch_rss(src["url"], max_items, src.get("category", ""))
        for item in items:
            item["source_type"] = "rss"
            item["source_name"] = src.get("name", "")
        results.extend(items)
        logger.info(f"RSS [{src['name']}]: {len(items)} 篇")

    return results


def scan_web_pages() -> list[dict]:
    """扫描配置的固定网页（简单HTML抓取标题和链接）"""
    config = load_config()
    pages = config.get("sources", {}).get("web_pages", [])
    results = []

    for page in pages:
        if not page.get("enabled", False):
            continue
        try:
            resp = requests.get(page["url"], headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            # 提取页面中的文章链接
            items = _extract_links_from_html(resp.text, page["url"], page.get("category", ""))
            for item in items:
                item["source_type"] = "web_page"
                item["source_name"] = page.get("name", "")
            results.extend(items[:5])
        except Exception as e:
            logger.debug(f"网页源 [{page['name']}] 抓取失败: {e}")

    return results


def scan_all_sources() -> list[dict]:
    """扫描所有固定内容源，返回合并结果"""
    all_results = []
    all_results.extend(scan_rss_feeds())
    all_results.extend(scan_web_pages())

    # 去重
    seen = set()
    unique = []
    for r in all_results:
        url = r.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(r)

    logger.info(f"固定源扫描完成: {len(all_results)} → {len(unique)} 去重")
    return unique


# ── 内部 ──

def _fetch_rss(feed_url: str, max_items: int, category: str) -> list[dict]:
    """抓取 RSS feed"""
    try:
        resp = requests.get(feed_url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return []

        root = ET.fromstring(resp.text)

        # RSS 2.0
        items = []
        for entry in root.iter("item"):
            title = _el_text(entry, "title")
            link = _el_text(entry, "link")
            desc = _el_text(entry, "description") or ""

            if title and link:
                # 清理 HTML 标签
                desc = re.sub(r"<[^>]+>", "", desc)[:200]
                items.append({
                    "title": title.strip(),
                    "url": link.strip(),
                    "snippet": desc.strip(),
                    "category": category,
                })

            if len(items) >= max_items:
                break

        # Atom
        if not items:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                title = _el_text(entry, "atom:title", ns)
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""
                summary = _el_text(entry, "atom:summary", ns) or ""

                if title and link:
                    summary = re.sub(r"<[^>]+>", "", summary)[:200]
                    items.append({
                        "title": title.strip(),
                        "url": link.strip(),
                        "snippet": summary.strip(),
                        "category": category,
                    })

                if len(items) >= max_items:
                    break

        return items
    except ET.ParseError:
        logger.debug(f"RSS 解析失败: {feed_url}")
        return []
    except Exception as e:
        logger.debug(f"RSS 抓取失败 [{feed_url}]: {e}")
        return []


def _el_text(element, tag, ns=None):
    el = element.find(tag, ns) if ns else element.find(tag)
    return el.text.strip() if el is not None and el.text else ""


def _extract_links_from_html(html: str, base_url: str, category: str) -> list[dict]:
    """从 HTML 中提取文章链接"""
    results = []
    seen = set()
    # 简单提取 h2/h3 标签中的链接
    pattern = re.compile(
        r'<h[23][^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    for href, title in pattern.findall(html):
        title = re.sub(r"<[^>]+>", "", title).strip()
        if not title or not href:
            continue
        if href.startswith("/"):
            from urllib.parse import urljoin
            href = urljoin(base_url, href)
        if href not in seen and len(title) > 3:
            seen.add(href)
            results.append({"title": title, "url": href, "snippet": "", "category": category})
    return results[:10]
