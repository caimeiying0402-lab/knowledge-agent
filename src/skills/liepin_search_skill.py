"""猎聘搜索引擎 — CDP拦截API方案（稳定，不依赖第三方API）
与 job_search_skill.py 的 CDPEngine 共享同一个隔离 Chrome
"""
import json
import logging
import random
import time
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent


def search_liepin(keywords: list[str], max_results: int = 40,
                  cdp_url: str = "http://localhost:9222") -> list[dict]:
    """CDP拦截猎聘搜索API → 返回结构化岗位列表

    共享 BOSS CDPEngine 的隔离 Chrome（同一个 :9222 端口）

    Returns:
        [{"title": "", "company": "", "salary": "", "location": "", "url": "",
          "experience": "", "education": "", "platform": "liepin"}, ...]
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("Playwright 未安装")
        return []

    results = []
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.connect_over_cdp(cdp_url)
        except Exception as e:
            logger.error(f"CDP连接失败: {e}")
            return []

        ctx = browser.contexts[0]
        page = ctx.new_page()

        # 拦截搜索API响应
        captured = {"jobs": [], "total": 0}

        def on_response(response):
            if "searchfront4c.pc-search-job" in response.url and response.status == 200:
                try:
                    d = json.loads(response.text())
                    if d.get("flag") == 1:
                        inner = d.get("data", {}).get("data", {})
                        captured["jobs"] = inner.get("jobCardList", [])
                        captured["total"] = inner.get("totalCount", 0)
                except Exception:
                    pass

        page.on("response", on_response)

        for kw in keywords[:3]:  # 最多3个搜索词
            logger.info(f"猎聘搜索: {kw}")
            url = f"https://www.liepin.com/zhaopin/?city=杭州&key={kw}"
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
                time.sleep(random.uniform(3, 5))
            except Exception as e:
                logger.warning(f"页面加载失败 ({kw}): {e}")
                continue

            for job_data in captured["jobs"]:
                job = job_data.get("job", {})
                comp = job_data.get("comp", {})

                results.append({
                    "title": job.get("title", ""),
                    "company": comp.get("compName", ""),
                    "salary": job.get("salary", ""),        # ← 明文！
                    "location": job.get("dq", ""),
                    "url": job.get("link", ""),
                    "experience": job.get("requireWorkYears", ""),
                    "education": job.get("requireEduLevel", ""),
                    "platform": "liepin",
                })

            if len(results) >= max_results:
                break

            time.sleep(random.uniform(5, 10))  # 关键词间休息

        try:
            page.close()
        except Exception:
            pass

    # 去重
    seen = set()
    unique = []
    for r in results:
        if r["url"] and r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)
    logger.info(f"猎聘搜索完成: {len(unique)} 个岗位 (去重后)")
    return unique[:max_results]


def get_detail(url: str, cdp_url: str = "http://localhost:9222") -> dict:
    """获取猎聘岗位详情页JD文本"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"jd_text": "", "url": url}

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.connect_over_cdp(cdp_url)
        except Exception:
            return {"jd_text": "", "url": url}

        ctx = browser.contexts[0]
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(3)

            jd_text = page.evaluate("""() => {
                const sels = ['.job-detail-box', '.job-description', '.content-word',
                              '[class*=\"description\"]', '[class*=\"detail\"]',
                              '.job-intro', '.require', 'main'];
                for (const sel of sels) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.length > 100) return el.innerText.trim();
                }
                return document.body ? document.body.innerText.substring(0, 3000) : '';
            }""")
            return {"jd_text": jd_text or "", "url": url}
        except Exception as e:
            logger.warning(f"猎聘详情获取失败: {e}")
            return {"jd_text": "", "url": url}
        finally:
            try:
                page.close()
            except Exception:
                pass
