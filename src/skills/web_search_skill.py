"""全网搜索 — ddgs 多引擎聚合搜索"""
import logging
import time

logger = logging.getLogger(__name__)


def search_web(queries: list[str], max_results_per_query: int = 5) -> list[dict]:
    """执行网络搜索（ddgs 多引擎聚合），查询间自动延迟避免限流"""
    all_results = []
    seen_urls = set()

    for i, query in enumerate(queries):
        if i > 0:
            time.sleep(2)  # 查询间隔，避免触发限流

        results = _search_ddg(query, max_results_per_query)
        if not results:
            # 重试一次（间隔 3s）
            time.sleep(3)
            results = _search_ddg(query, max_results_per_query)
            if results:
                logger.info(f"DDG 重试成功: '{query[:40]}'")

        for r in results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                r["source_query"] = query
                all_results.append(r)
        logger.info(f"搜索 '{query[:30]}': {len(results)} 条 -> {len(all_results)} 条累计")

    logger.info(f"搜索完成: {len(queries)} 查询 -> {len(all_results)} 去重结果")
    return all_results


def _search_ddg(query: str, max_results: int) -> list[dict]:
    """DuckDuckGo 多引擎聚合搜索（ddgs 包）"""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            logger.debug("ddgs/duckduckgo_search 未安装")
            return []

    # 降低 ddgs 内部日志噪音（搜索引擎连接失败在墙内是常态）
    logging.getLogger("ddgs.ddgs").setLevel(logging.WARNING)
    logging.getLogger("primp").setLevel(logging.WARNING)

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
