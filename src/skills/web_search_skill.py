"""全网搜索 — DuckDuckGo + Bing HTML 降级"""
import logging
import re
import requests
from urllib.parse import quote

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
}


def search_web(queries: list[str], max_results_per_query: int = 5) -> list[dict]:
    """执行网络搜索，DuckDuckGo 优先，Bing HTML 降级"""
    all_results = []
    seen_urls = set()

    for query in queries:
        results = _search_ddg(query, max_results_per_query)
        if not results:
            logger.info(f"DDG 无结果，降级到 Bing: '{query}'")
            results = _search_bing_html(query, max_results_per_query)

        for r in results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                r["source_query"] = query
                all_results.append(r)
        logger.info(f"搜索 '{query[:30]}': {len(results)} 条 → {len(all_results)} 条累计")

    logger.info(f"搜索完成: {len(queries)} 查询 → {len(all_results)} 去重结果")
    return all_results


def _search_ddg(query: str, max_results: int) -> list[dict]:
    """DuckDuckGo (ddgs 包)"""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            logger.debug("ddgs/duckduckgo_search 未安装")
            return []

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            return [
                {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
                for r in results if r.get("href")
            ]
    except Exception as e:
        logger.debug(f"DDG 搜索异常: {e}")
        return []


def _search_bing_html(query: str, max_results: int) -> list[dict]:
    """Bing HTML 抓取降级方案"""
    try:
        url = f"https://www.bing.com/search?q={quote(query)}&setlang=zh-cn"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return []

        # 从 HTML 中提取搜索结果
        results = []
        # Bing 的搜索结果在 <li class="b_algo"> 中
        # 用简单正则提取标题链接和摘要
        pattern = re.compile(
            r'<a[^>]*href="(https?://[^"]+)"[^>]*>\s*(?:<[^>]+>)*([^<]+)',
            re.IGNORECASE
        )
        matches = pattern.findall(resp.text)

        for href, title in matches:
            href = href.strip()
            title = re.sub(r'<[^>]+>', '', title).strip()
            if (href.startswith("http") and "bing.com" not in href
                    and "microsoft.com/bing" not in href
                    and len(title) > 2):
                results.append({"title": title, "url": href, "snippet": ""})

        # 去重（按URL）
        seen = set()
        unique = []
        for r in results:
            if r["url"] not in seen:
                seen.add(r["url"])
                unique.append(r)

        return unique[:max_results]
    except Exception as e:
        logger.debug(f"Bing HTML 搜索异常: {e}")
        return []


def fetch_page_content(url: str, timeout: int = 15) -> dict:
    """抓取单个页面的正文内容（复用 ingestion_skill）"""
    try:
        from skills.ingestion_skill import ingest
        result = ingest(url)
        return {
            "url": url,
            "raw_content": result.get("content", "")[:3000],
            "title": result.get("title", ""),
            "success": bool(result.get("content")),
            "error": "",
        }
    except Exception as e:
        logger.warning(f"页面抓取失败 {url[:80]}: {e}")
        return {"url": url, "raw_content": "", "title": "", "success": False, "error": str(e)[:200]}


def enrich_results(results: list[dict], fetch_content: bool = False) -> list[dict]:
    """可选：为搜索结果补充页面正文内容"""
    if not fetch_content:
        return results
    enriched = []
    for r in results:
        page = fetch_page_content(r["url"])
        r["full_content"] = page["raw_content"]
        r["fetched_title"] = page["title"]
        enriched.append(r)
    return enriched
