"""全网搜索 — DuckDuckGo 搜索 + 页面内容抓取"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent


def search_web(queries: list[str], max_results_per_query: int = 5) -> list[dict]:
    """执行 DuckDuckGo 搜索，返回去重后的结果列表"""
    all_results = []
    seen_urls = set()

    try:
        from duckduckgo_search import DDGS
    except ImportError:
        logger.error("duckduckgo-search 未安装，请执行: pip install duckduckgo-search")
        return all_results

    with DDGS() as ddgs:
        for query in queries:
            try:
                results = list(ddgs.text(query, max_results=max_results_per_query))
                for r in results:
                    url = r.get("href", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append({
                            "title": r.get("title", ""),
                            "url": url,
                            "snippet": r.get("body", ""),
                            "source_query": query,
                        })
                logger.info(f"搜索 '{query}': 获取 {len(results)} 条结果")
            except Exception as e:
                logger.warning(f"DuckDuckGo 搜索失败 '{query}': {e}")

    logger.info(f"搜索完成: {len(queries)} 个查询 → {len(all_results)} 条去重结果")
    return all_results


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
        return {
            "url": url,
            "raw_content": "",
            "title": "",
            "success": False,
            "error": str(e)[:200],
        }


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
