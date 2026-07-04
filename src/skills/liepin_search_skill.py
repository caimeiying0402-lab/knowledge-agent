"""猎聘搜索引擎 — 独立文件，不依赖 job_search_skill.py
使用 ScrapingFish API 搜索猎聘岗位
"""
import json
import logging
import re
import requests
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent


@dataclass
class JobItem:
    title: str
    company: str
    salary: str = ""
    location: str = ""
    url: str = ""
    platform: str = "liepin"


SCRAPINGFISH_API = "https://api.scrapingfish.com/api/v1/"


def search_liepin(keyword: str, api_key: str = "", max_results: int = 40, 
                  location_code: str = "070020", timeout: int = 60) -> list[JobItem]:
    """搜索猎聘岗位"""
    if not api_key:
        from dotenv import load_dotenv
        import os as _os
        env_path = BASE_DIR / "config" / ".env"
        load_dotenv(env_path)
        api_key = _os.getenv("SCRAPING_API_KEY", "")
        if not api_key:
            logger.error("未设置 SCRAPING_API_KEY")
            return []

    url = f"https://www.liepin.com/zhaopin/?key={keyword}&dqs={location_code}"
    params = {"api_key": api_key, "url": url}
    
    logger.info(f"猎聘搜索: {keyword}")
    try:
        resp = requests.get(SCRAPINGFISH_API, params=params, timeout=timeout)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"API 请求失败: {e}")
        return []

    return _parse_listings(resp.text)


def _parse_listings(html: str) -> list[JobItem]:
    """解析猎聘搜索结果 HTML"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    items = []

    links = soup.select("a[data-nick*='job-detail']")
    logger.info(f"  找到 {len(links)} 个岗位链接")
    
    for link in links:
        try:
            text = link.get_text(strip=True)
            href = link.get("href", "")
            if href and not href.startswith("http"):
                href = f"https:{href}" if href.startswith("//") else href

            salary = ""
            title = text
            location = "杭州"

            sal_match = re.search(r'[\d.]+[Kk]-[\d.]+[Kk][^\s]*', text)
            if sal_match:
                salary = sal_match.group()
                title = text[:sal_match.start()].strip()

            loc_match = re.search(r'【([^】]+)】', text)
            if loc_match:
                location = loc_match.group(1)

            card = link.find_parent("[data-tlg-elem-id*='job_listcard']") or link.parent
            card_text = card.get_text(strip=True) if card else text
            company = ""
            parts = card_text.split(text, 1)
            if len(parts) > 1:
                comp = re.match(r'([^\d\u5df2\u4e0a\u674e\u5f20\u738b\u5218\u9648\u8d75\u94b1\u5b59\u5468]+)', parts[1])
                if comp:
                    company = comp.group(1).strip()[:40]

            items.append(JobItem(
                title=title.strip("- ").strip(),
                company=company or "",
                salary=salary,
                location=location,
                url=href,
            ))
        except Exception as e:
            logger.debug(f"解析失败: {e}")

    seen = set()
    unique = []
    for item in items:
        if item.url not in seen:
            seen.add(item.url)
            unique.append(item)
    
    logger.info(f"  解析到 {len(unique)} 个岗位")
    return unique


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    items = search_liepin("财务产品经理")
    for i, item in enumerate(items[:10], 1):
        print(f"[{i}] {item.title} @ {item.company} | {item.salary or '-'}")
