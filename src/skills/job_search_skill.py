"""岗位搜索引擎 — 多后端可插拔架构
    支持 ManualEngine（手动）和 PlaywrightEngine（半自动）
    安全第一：默认 manual，playwright 需手动 opt-in
"""
import json
import logging
import re
import time
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent


# ── 数据模型 ──

@dataclass
class JobListing:
    """搜索结果摘要（列表页）"""
    title: str
    company: str
    salary: Optional[str] = None
    location: Optional[str] = None
    url: Optional[str] = None
    platform: str = "boss"


@dataclass
class JobDetail:
    """岗位详情（含 JD 全文）"""
    title: str
    company: str
    jd_text: str
    salary: Optional[str] = None
    location: Optional[str] = None
    url: Optional[str] = None
    experience_years: Optional[str] = None
    education: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    publish_time: Optional[str] = None
    platform: str = "boss"


# ── 筛选条件加载 ──

def load_filters() -> dict:
    """从 job_filters.yaml 加载筛选条件"""
    import yaml
    path = BASE_DIR / "config" / "job_filters.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── 引擎基类 ──

class BaseEngine:
    """引擎基类"""
    name: str = "base"

    def search(self, keywords: list[str], filters: dict) -> list[JobListing]:
        """按关键词搜索，返回岗位列表"""
        raise NotImplementedError

    def get_detail(self, url: str) -> Optional[JobDetail]:
        """获取岗位详情（JD全文）"""
        raise NotImplementedError

    def search_with_details(self, keywords: list[str], filters: dict) -> list[JobDetail]:
        """搜索并获取详情"""
        listings = self.search(keywords, filters)
        logger.info(f"搜索到 {len(listings)} 个岗位，开始抓取详情...")
        details = []
        for i, listing in enumerate(listings):
            logger.info(f"  [{i+1}/{len(listings)}] {listing.title} @ {listing.company}")
            detail = self.get_detail(listing.url) if listing.url else None
            if detail:
                details.append(detail)
            else:
                # fallback: 用列表页信息
                details.append(JobDetail(
                    title=listing.title,
                    company=listing.company,
                    jd_text="",
                    salary=listing.salary,
                    location=listing.location,
                    url=listing.url,
                    platform=listing.platform,
                ))
            # Engine 之间的延迟
            if i < len(listings) - 1:
                self._sleep_between()
        return details

    def _sleep_between(self):
        """操作间休息，由子类实现"""
        pass


# ── ManualEngine ──

class ManualEngine(BaseEngine):
    """手动模式引擎 — 用户粘贴内容，零风险"""
    name = "manual"

    def search(self, keywords: list[str], filters: dict) -> list[JobListing]:
        print("\n" + "=" * 60)
        print("  手动模式：请打开 BOSS直聘 搜索以下关键词")
        print("=" * 60)
        for kw in keywords[:5]:
            url = f"https://www.zhipin.com/web/geek/job?city=杭州&query={kw}"
            print(f"  🔗 {kw}")
            print(f"     {url}")
        print("-" * 60)
        print("  请粘贴搜索结果页的内容（标题/公司/薪资），")
        print("  每行一条，用 | 分隔。输入完成后输入 EOF 结束：")
        print("-" * 60)
        lines = []
        while True:
            try:
                line = input()
                if line.strip() == "EOF":
                    break
                lines.append(line.strip())
            except EOFError:
                break

        listings = []
        for line in lines:
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                listings.append(JobListing(
                    title=parts[0],
                    company=parts[1],
                    salary=parts[2] if len(parts) > 2 else None,
                    location=parts[3] if len(parts) > 3 else None,
                    url=parts[4] if len(parts) > 4 else None,
                ))
        logger.info(f"手动模式：解析到 {len(listings)} 个岗位")
        return listings

    def get_detail(self, url: str) -> Optional[JobDetail]:
        if not url:
            return None
        print(f"\n📋 请打开以下链接，粘贴JD文本（输入 EOF 结束）：")
        print(f"   {url}")
        lines = []
        while True:
            try:
                line = input()
                if line.strip() == "EOF":
                    break
                lines.append(line)
            except EOFError:
                break
        jd_text = "\n".join(lines).strip()
        if not jd_text:
            return None
        return JobDetail(
            title="",
            company="",
            jd_text=jd_text,
            url=url,
        )


# ── PlaywrightEngine ──

class PlaywrightEngine(BaseEngine):
    """本地 Playwright 引擎 — 需手动登录，低风险"""
    name = "playwright"

    def __init__(self):
        self._browser = None
        self._playwright = None
        self._context = None
        self._config = load_filters()
        ac = self._config.get("anti_crawl", {})
        self._min_delay = ac.get("min_delay", 3)
        self._max_delay = ac.get("max_delay", 8)
        self._max_retries = ac.get("max_retries", 3)
        self._session_file = BASE_DIR / ac.get("session_file", "data/boss_session.json")
        self._block_count = 0

    def _ensure_browser(self):
        """初始化或复用浏览器实例"""
        if self._browser is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("Playwright 未安装，请执行: pip install playwright && playwright install chromium")

        self._playwright = sync_playwright().start()

        # 尝试从 Chromium 用户目录启动（复用本地登录态）
        chrome_path = None
        import shutil
        for p in [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]:
            if shutil.which(p) or Path(p).exists():
                chrome_path = p
                break

        launch_args = {
            "headless": False,  # 非无头，用户能看到浏览器
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        }
        if chrome_path:
            launch_args["channel"] = Path(chrome_path).stem.lower()

        self._browser = self._playwright.chromium.launch(**launch_args)
        logger.info(f"Playwright 浏览器已启动 (headless=False)")

        # 加载已保存的 session
        self._context = self._browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        if self._session_file.exists():
            try:
                self._context = self._browser.new_context(
                    storage_state=str(self._session_file),
                    viewport={"width": 1440, "height": 900},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                )
                logger.info(f"已加载保存的 session: {self._session_file}")
            except Exception as e:
                logger.warning(f"Session 加载失败，将重新登录: {e}")
                self._context = self._browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                )

    def _ensure_logged_in(self, page) -> bool:
        """检查登录态，如果未登录则引导用户手动扫码"""
        page.goto("https://www.zhipin.com/web/geek/job", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        # 检查是否被重定向到登录页
        if "login" in page.url.lower():
            print("\n" + "=" * 60)
            print("  🔑 需要登录 BOSS直聘")
            print("  ⚡ 请在打开的浏览器中扫码登录")
            print("  ⏳ 登录成功后请在此终端按回车继续...")
            print("=" * 60)
            input()
            page.wait_for_timeout(3000)
            # 重新检查
            if "login" in page.url.lower():
                logger.warning("登录检测失败，请手动导航到 BOSS 首页后重试")
                return False
            # 保存 session
            self._context.storage_state(path=str(self._session_file))
            logger.info(f"登录成功，Session 已保存至 {self._session_file}")
        return True

    def _detect_block(self, page) -> bool:
        """检查是否被反爬拦截"""
        body_text = page.inner_text("body").lower()
        block_signals = ["验证码", "captcha", "access denied", "请稍后再试",
                         "操作频繁", "人机验证", "verify"]
        for signal in block_signals:
            if signal.lower() in body_text:
                self._block_count += 1
                logger.warning(f"检测到反爬拦截 ({self._block_count}/{self._max_retries})")
                return True
        return False

    def _sleep(self):
        """随机延迟"""
        delay = random.uniform(self._min_delay, self._max_delay)
        logger.debug(f"等待 {delay:.1f}s...")
        time.sleep(delay)

    def search(self, keywords: list[str], filters: dict) -> list[JobListing]:
        self._ensure_browser()

        all_listings = []
        page = self._context.new_page()

        try:
            if not self._ensure_logged_in(page):
                return []

            for kw in keywords:
                if self._block_count >= self._max_retries:
                    logger.error(f"反爬拦截超过 {self._max_retries} 次，停止搜索")
                    print("\n⚠️ 连续被拦截，请切换到手动模式")
                    break

                # 搜索
                search_url = f"https://www.zhipin.com/web/geek/job?city=杭州&query={kw}"
                logger.info(f"搜索关键词: {kw}")
                page.goto(search_url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)

                if self._detect_block(page):
                    self._sleep()
                    continue

                # 提取岗位列表
                try:
                    # 等待列表加载
                    page.wait_for_selector(".job-list-item, .job-card-wrapper, [class*='job-card']",
                                           timeout=8000)
                except Exception:
                    logger.warning(f"搜索结果未加载: {kw}")
                    continue

                items = page.query_selector_all(".job-list-item, .job-card-wrapper, [class*='job-card'], .job-primary")
                logger.info(f"  找到 {len(items)} 个岗位（{kw}）")

                for item in items[:20]:  # 最多取前20
                    try:
                        title_el = item.query_selector(".job-name, .job-title, [class*='title']")
                        company_el = item.query_selector(".company-name, .company-text, [class*='company']")
                        salary_el = item.query_selector(".salary, .red, [class*='salary']")
                        location_el = item.query_selector(".job-area, .city, [class*='location']")
                        link_el = item.query_selector("a")

                        title = title_el.inner_text().strip() if title_el else ""
                        company = company_el.inner_text().strip() if company_el else ""
                        salary = salary_el.inner_text().strip() if salary_el else ""
                        location = location_el.inner_text().strip() if location_el else ""
                        url = ""
                        if link_el:
                            href = link_el.get_attribute("href") or ""
                            if href.startswith("/"):
                                url = f"https://www.zhipin.com{href}"
                            elif href.startswith("http"):
                                url = href

                        if title and company:
                            all_listings.append(JobListing(
                                title=title, company=company, salary=salary,
                                location=location, url=url,
                            ))
                    except Exception as e:
                        logger.debug(f"解析岗位条目失败: {e}")

                self._sleep()  # 关键词间延迟

                # 避免搜索太多关键词
                if len(all_listings) >= 60:
                    break

        finally:
            page.close()

        logger.info(f"Playwright搜索完成，共 {len(all_listings)} 个岗位")
        return all_listings

    def get_detail(self, url: str) -> Optional[JobDetail]:
        if not url:
            return None
        self._ensure_browser()

        page = self._context.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)

            if self._detect_block(page):
                self._block_count += 1
                return None

            # 提取 JD 文本
            try:
                page.wait_for_selector(".job-sec-text, .job-detail, .detail-content, .text, [class*='job-detail']",
                                       timeout=8000)
            except Exception:
                pass

            # 获取页面主要文本
            jd_selectors = [".job-sec-text", ".job-detail", ".detail-content",
                            ".text", "main", ".job-boss-desc"]
            jd_text = ""
            for sel in jd_selectors:
                try:
                    el = page.query_selector(sel)
                    if el:
                        jd_text = el.inner_text().strip()
                        break
                except Exception:
                    continue

            if not jd_text:
                jd_text = page.inner_text("body")[:3000]

            # 提取详情字段
            title = page.title()
            salary = ""
            experience = ""
            education = ""
            try:
                # 尝试提取薪资/年限/学历
                info_els = page.query_selector_all(".job-detail-header .info-item, .job-banner .info-item, [class*='tag']")
                for el in info_els:
                    text = el.inner_text().strip()
                    if "K" in text or "k" in text:
                        salary = text
                    elif "年" in text or "经验" in text:
                        experience = text
                    elif "本科" in text or "硕士" in text or "博士" in text or "学历" in text:
                        education = text
            except Exception:
                pass

            return JobDetail(
                title=title,
                company="",
                jd_text=jd_text,
                salary=salary,
                url=url,
                experience_years=experience,
                education=education,
            )
        finally:
            page.close()
            self._sleep()  # 详情间延迟

    def stop(self):
        """关闭浏览器"""
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._browser = None
        self._playwright = None
        self._context = None
        logger.info("Playwright 浏览器已关闭")


# ── 工厂 ──

_ENGINES = {
    "manual": ManualEngine,
    "playwright": PlaywrightEngine,
}


def search_jobs(keywords: Optional[list[str]] = None,
                engine: str = "manual",
                max_results: int = 20) -> list[JobDetail]:
    """
    统一入口：搜索岗位。

    Args:
        keywords: 搜索关键词列表，默认从 job_filters.yaml 加载
        engine: 引擎类型 ("manual" | "playwright")
        max_results: 最大返回结果数

    Returns:
        JobDetail 列表
    """
    config = load_filters()
    if keywords is None:
        keywords = config.get("search", {}).get("keywords", [])

    engine_cls = _ENGINES.get(engine)
    if not engine_cls:
        raise ValueError(f"不支持的引擎: {engine}，可选: {list(_ENGINES.keys())}")

    eng = engine_cls()
    try:
        details = eng.search_with_details(keywords, config)
        details = _apply_filters(details, config)
        details = details[:max_results]
        return details
    finally:
        if isinstance(eng, PlaywrightEngine):
            eng.stop()


def _apply_filters(details: list[JobDetail], config: dict) -> list[JobDetail]:
    """应用硬性筛选条件"""
    filters = config.get("filters", {})
    exclude_kw = config.get("search", {}).get("exclude_keywords", [])

    filtered = []
    for d in details:
        # exclude_keywords 过滤
        if exclude_kw:
            skip = False
            for ek in exclude_kw:
                if ek in d.title or ek in d.company or (d.jd_text and ek in d.jd_text):
                    skip = True
                    break
            if skip:
                continue
        filtered.append(d)
    return filtered


def get_job_detail(url: str, engine: str = "manual") -> Optional[JobDetail]:
    """获取单个岗位详情"""
    engine_cls = _ENGINES.get(engine)
    if not engine_cls:
        raise ValueError(f"不支持的引擎: {engine}")
    eng = engine_cls()
    try:
        return eng.get_detail(url)
    finally:
        if isinstance(eng, PlaywrightEngine):
            eng.stop()
