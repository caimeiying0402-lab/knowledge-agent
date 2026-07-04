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
            "headless": False,  # 非无头
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-automation",
                "--disable-dev-shm-usage",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-site-isolation-trials",
                "--disable-web-security",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-notifications",
                "--disable-popup-blocking",
                "--disable-sync",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-client-side-phishing-detection",
            ],
        }
        if chrome_path:
            path_lower = chrome_path.lower()
            if "google chrome" in path_lower:
                launch_args["channel"] = "chrome"
            elif "microsoft edge" in path_lower:
                launch_args["channel"] = "msedge"
            elif "brave" in path_lower:
                launch_args["channel"] = "chrome"  # Brave uses Chromium

        self._browser = self._playwright.chromium.launch(**launch_args)
        logger.info(f"Playwright 浏览器已启动 (headless=False)")

        # 注入反检测脚本
        stealth_js = """
        // 隐藏 webdriver 属性
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        // 覆盖 chrome.runtime
        window.chrome = { runtime: {} };
        // 伪造 plugins
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        // 伪造语言
        Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh'] });
        // 覆盖权限查询
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
        );
        """

        # 加载已保存的 session
        self._context = self._browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        self._context.add_init_script(stealth_js)
        if self._session_file.exists():
            try:
                self._context = self._browser.new_context(
                    storage_state=str(self._session_file),
                    viewport={"width": 1440, "height": 900},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )
                self._context.add_init_script(stealth_js)
                logger.info(f"已加载保存的 session: {self._session_file}")
            except Exception as e:
                logger.warning(f"Session 加载失败，将重新登录: {e}")
                self._context = self._browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )
                self._context.add_init_script(stealth_js)

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



# ── ScrapingApiEngine ──

class ScrapingApiEngine(BaseEngine):
    """第三方网页渲染 API 引擎 — 使用外部服务绕过反爬
    支持 ScrapingFish / ScrapingBee 等兼容服务
    API 设计: GET ?api_key=KEY&url=TARGET&render=true → 返回 HTML
    """
    name = "scraping"

    def __init__(self, api_key: str = "", base_url: str = "https://api.scrapingfish.com/api/v1/", platform: str = "boss"):
        import os
        from dotenv import load_dotenv
        env_path = BASE_DIR / "config" / ".env"
        load_dotenv(env_path)
        self._api_key = api_key or os.getenv("SCRAPING_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._platform = platform  # "boss" or "liepin"
        self._config = load_filters()
        ac = self._config.get("anti_crawl", {})
        self._min_delay = ac.get("min_delay", 3)
        self._max_delay = ac.get("max_delay", 8)

    def _build_search_url(self, kw: str) -> str:
        """根据平台构建搜索 URL"""
        if self._platform == "liepin":
            return f"https://www.liepin.com/zhaopin/?city=杭州&key={kw}"
        return f"https://www.zhipin.com/web/geek/job?city=杭州&query={kw}"

    def _fetch(self, url: str) -> str:
        """通过外部 API 获取渲染后的 HTML"""
        import urllib.parse, urllib.request

        params = urllib.parse.urlencode({
            "api_key": self._api_key,
            "url": url,
            "render_js": "true",
            "total_timeout_ms": "120000",
        })
        full_url = f"{self._base_url}?{params}"
        logger.info(f"  Fetching via ScrapingFish: {url[:80]}...")
        try:
            req = urllib.request.Request(full_url)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            logger.error(f"ScrapingFish API 请求失败: {e}")
            return ""

    def _parse_search_results(self, html: str) -> list[JobListing]:
        """解析 BOSS直聘搜索结果 HTML 为 JobListing 列表"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        listings = []

        # BOSS 搜索结果卡片选择器（多个版本兼容）
        cards = soup.select(".job-list-item, .job-card-wrapper, [class*='job-card'], .job-primary")
        for card in cards:
            try:
                title_el = card.select_one(".job-name, .job-title, [class*=\'title\']")
                company_el = card.select_one(".company-name, .company-text, [class*=\'company-name\'], .info-company")
                salary_el = card.select_one(".salary, .red, [class*=\'salary\']")
                location_el = card.select_one(".job-area, .city, [class*=\'location\']")
                link_el = card.select_one("a[href*=\'job_detail\']")

                title = title_el.get_text(strip=True) if title_el else ""
                company = company_el.get_text(strip=True) if company_el else ""
                salary = salary_el.get_text(strip=True) if salary_el else ""
                location = location_el.get_text(strip=True) if location_el else ""
                url = ""
                if link_el:
                    href = link_el.get("href", "")
                    if href.startswith("/"):
                        url = f"https://www.zhipin.com{href}"
                    elif href.startswith("http"):
                        url = href

                if title and company:
                    listings.append(JobListing(
                        title=title, company=company, salary=salary,
                        location=location, url=url,
                    ))
            except Exception as e:
                logger.debug(f"解析条目失败: {e}")
        return listings

    def _parse_jd_detail(self, html: str, url: str) -> Optional[JobDetail]:
        """解析 BOSS直聘 JD 详情页 HTML"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # JD 正文
        jd_selectors = [".job-sec-text", ".job-detail", ".detail-content",
                        ".text", "main", ".job-boss-desc", ".job-description"]
        jd_text = ""
        for sel in jd_selectors:
            el = soup.select_one(sel)
            if el:
                jd_text = el.get_text(strip=True)
                if len(jd_text) > 100:
                    break

        if not jd_text:
            jd_text = soup.get_text()[:3000]

        # 提取其他字段
        title = soup.title.string.strip() if soup.title else ""

        # 薪资/年限/学历 - 从各种可能的选择器中提取
        info_items = soup.select(".job-banner .info-item, .job-detail-header .info-item, [class*=\'tag\']")
        salary = ""
        experience = ""
        education = ""
        for item in info_items:
            text = item.get_text(strip=True)
            if "K" in text or "k" in text or "K" in text or "薪" in text:
                salary = text
            elif "年" in text or "经验" in text:
                experience = text
            elif "本科" in text or "硕士" in text or "博士" in text or "学历" in text:
                education = text

        if not jd_text:
            return None

        return JobDetail(
            title=title,
            company="",
            jd_text=jd_text,
            salary=salary,
            url=url,
            experience_years=experience,
            education=education,
        )

    def search(self, keywords: list[str], filters: dict) -> list[JobListing]:
        if not self._api_key:
            raise ValueError("未设置 API Key。请从 https://scrapingfish.com 注册获取，"
                             "然后设置环境变量 SCRAPING_API_KEY 或在 .env 中配置")

        all_listings = []
        for kw in keywords:
            search_url = self._build_search_url(kw)
            logger.info(f"搜索关键词: {kw} (平台: {self._platform})")
            html = self._fetch(search_url)
            if html:
                listings = self._parse_search_results(html)
                logger.info(f"  解析到 {len(listings)} 个岗位")
                all_listings.extend(listings)
            self._sleep_between()

            if len(all_listings) >= 60:
                break

        # 去重（按 URL）
        seen_urls = set()
        unique_listings = []
        for l in all_listings:
            key = l.url or l.title + l.company
            if key not in seen_urls:
                seen_urls.add(key)
                unique_listings.append(l)

        logger.info(f"去重后共 {len(unique_listings)} 个岗位")
        return unique_listings

    def get_detail(self, url: str) -> Optional[JobDetail]:
        if not url:
            return None
        html = self._fetch(url)
        if not html:
            return None
        detail = self._parse_jd_detail(html, url)
        return detail

    def _sleep_between(self):
        import time, random
        delay = random.uniform(self._min_delay, self._max_delay)
        time.sleep(delay)

# ── CDPEngine v2：API优先 + 隔离Profile（账户安全第一）──

# BOSS直聘内部搜索API（前端自己调的接口，返回明文薪资JSON）
BOSS_SEARCH_API = "/wapi/zpgeek/search/joblist.json"
BOSS_SEARCH_PARAMS = "scene=1&pageSize=30&city=101210100"  # 101210100=杭州


class CDPEngine(BaseEngine):
    """CDP v2 — API优先引擎，账户安全第一。

    核心变化（v1→v2）：
    - v1: 导航到搜索页 → DOM解析 → 字体反爬导致薪资乱码
    - v2: 注入JS调BOSS内部API → 拿明文JSON → 完全绕过字体反爬

    安全设计：
    1. 隔离Chrome Profile — 从真实Chrome复制Cookie到独立目录
    2. 独立Chrome进程 — 跟你日常用的Chrome完全分离
    3. API优先 — 不解析DOM，不模拟点击
    4. 极端保守频率 — 页间12-22s，详情间10-25s
    5. 单次上限 — 最多2个搜索词，每词最多5页
    """

    name = "cdp"

    # ── 安全限制常量 ──
    MAX_KEYWORDS = 2        # 单次最多搜索词数
    MAX_PAGES = 5           # 每词最多翻页数
    PAGE_SIZE = 30          # 每页结果数
    MIN_PAGE_DELAY = 12     # 翻页最小延迟(秒)
    MAX_PAGE_DELAY = 22     # 翻页最大延迟(秒)
    MIN_DETAIL_DELAY = 10   # 详情最小延迟(秒)
    MAX_DETAIL_DELAY = 25   # 详情最大延迟(秒)

    def __init__(self, cdp_url: str = "http://localhost:9222", city_code: str = "101210100"):
        self._playwright = None
        self._browser = None
        self._cdp_url = cdp_url
        self._city_code = city_code
        self._config = load_filters()
        self._block_count = 0
        self._request_count = 0

    # ═══ 浏览器连接 ═══

    def _ensure_browser(self):
        if self._browser is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("Playwright 未安装")

        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.connect_over_cdp(self._cdp_url)
            logger.info(f"CDP 已连接: {self._cdp_url}")
        except Exception as e:
            self._playwright.stop()
            raise RuntimeError(
                f"无法连接 Chrome CDP ({self._cdp_url})。\n"
                f"请先运行: bash start_chrome_cdp.sh\n"
                f"原始错误: {e}"
            )

    def _get_page(self):
        """获取一个可用的page（优先复用已有BOSS页面）"""
        self._ensure_browser()
        contexts = self._browser.contexts
        ctx = contexts[0] if contexts else self._browser.new_context()
        for page in ctx.pages:
            if "zhipin.com" in page.url:
                return page
        return ctx.new_page()

    # ═══ 登录探测 ═══

    def _probe_login(self, page) -> bool:
        """通过API返回的salaryDesc是否明文来判断登录态"""
        logger.info("探测登录态...")
        try:
            result = page.evaluate("""() => {
                const xhr = new XMLHttpRequest();
                xhr.open('GET', '/wapi/zpgeek/search/joblist.json?scene=1&query=产品经理&city=101210100&pageSize=5', false);
                xhr.send();
                if (xhr.status !== 200) return false;
                const data = JSON.parse(xhr.responseText);
                const jobs = data?.zpData?.jobList || [];
                return jobs.some(j => j.salaryDesc && j.salaryDesc.length > 0);
            }""")
            if result:
                logger.info("登录态正常（salaryDesc明文）")
            else:
                logger.warning("登录态异常：salaryDesc为空，可能未登录或被字体反爬")
            return bool(result)
        except Exception as e:
            logger.warning(f"登录探测失败: {e}")
            return False

    def _ensure_logged_in(self, page) -> bool:
        """确保已登录，未登录则引导用户"""
        if self._probe_login(page):
            return True

        print("\n" + "=" * 60)
        print("  ⚠️  BOSS直聘未登录或登录态失效")
        print("  请在隔离 Chrome 窗口中手动登录 zhipin.com")
        print("  登录成功后按回车继续...")
        print("=" * 60)
        input()

        # 登录后重新探测
        page.goto("https://www.zhipin.com/web/geek/job", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(3000)
        return self._probe_login(page)

    # ═══ API 搜索（核心） ═══

    def _call_search_api(self, page, kw: str, page_num: int = 1) -> list[dict]:
        """通过注入同步XHR调用BOSS搜索API，返回明文JSON中的岗位列表"""
        self._request_count += 1
        if self._request_count > 30:
            logger.warning("已达到单次请求上限(30)，停止搜索")
            return []

        js = f"""() => {{
            const url = '{BOSS_SEARCH_API}?{BOSS_SEARCH_PARAMS}&query={kw}&page={page_num}';
            const xhr = new XMLHttpRequest();
            xhr.open('GET', url, false);
            xhr.send();
            if (xhr.status !== 200) return [];
            const data = JSON.parse(xhr.responseText);
            const jobs = data?.zpData?.jobList || [];
            return jobs.map(j => ({{
                title: j.jobName || '',
                company: j.brandName || '',
                salary: j.salaryDesc || '',       // ← 明文薪资！
                location: j.cityName || '',
                url: 'https://www.zhipin.com/job_detail/' + (j.encryptJobId || '') + '.html',
                encryptId: j.encryptJobId || '',
                lid: j.lid || '',                 // 详情页需要的上下文
                securityId: j.securityId || '',
                tags: (j.jobLabels || []).map(l => typeof l === 'string' ? l : (l.name || '')),
                experience: j.experienceName || '',
                education: j.degreeName || '',
                publishTime: j.publishTime || '',
            }}));
        }}"""
        try:
            results = page.evaluate(js)
            logger.info(f"  API返回: {len(results)} 条 ({kw} 第{page_num}页)")
            return results
        except Exception as e:
            logger.warning(f"  API调用失败 ({kw} p{page_num}): {e}")
            return []

    def _human_delay(self, min_s: float, max_s: float):
        """人类级别随机延迟"""
        delay = random.uniform(min_s, max_s)
        # 15%概率插入额外长暂停（模拟看手机/倒水）
        if random.random() < 0.15:
            delay += random.uniform(5, 15)
            logger.info(f"  随机长暂停 {delay:.0f}s...")
        time.sleep(delay)

    def _human_scroll(self, page):
        """模拟人类浏览滚动（3-6次随机滚动，15%向上翻）"""
        try:
            for _ in range(random.randint(3, 6)):
                direction = -1 if random.random() < 0.15 else 1
                scroll = random.randint(150, 500) * direction
                page.evaluate(f"window.scrollBy(0, {scroll})")
                time.sleep(random.uniform(0.5, 2.0))
        except Exception:
            pass

    # ═══ 公开接口 ═══

    def search(self, keywords: list[str], filters: dict) -> list[JobListing]:
        """API优先搜索 — 调BOSS内部API拿明文JSON"""
        page = self._get_page()

        # 导航到BOSS首页并确保登录
        page.goto("https://www.zhipin.com/web/geek/job", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)
        if not self._ensure_logged_in(page):
            return []

        # 限制搜索词数量
        keywords = keywords[:self.MAX_KEYWORDS]
        logger.info(f"API搜索: {len(keywords)} 个关键词 (安全上限={self.MAX_KEYWORDS})")

        all_listings = []
        for kw in keywords:
            logger.info(f"搜索: {kw}")
            for page_num in range(1, self.MAX_PAGES + 1):
                results = self._call_search_api(page, kw, page_num)
                if not results:
                    break

                for r in results:
                    all_listings.append(JobListing(
                        title=r["title"], company=r["company"],
                        salary=r["salary"], location=r["location"],
                        url=r["url"],
                    ))

                if len(results) < self.PAGE_SIZE:
                    break  # 最后一页

                if page_num < self.MAX_PAGES:
                    logger.info(f"  翻页 {page_num}→{page_num+1}，等待...")
                    self._human_delay(self.MIN_PAGE_DELAY, self.MAX_PAGE_DELAY)

            # 关键词间休息
            self._human_delay(5, 10)

        logger.info(f"CDP v2 搜索完成: {len(all_listings)} 个岗位 (API明文薪资)")
        return all_listings

    def get_detail(self, url: str) -> Optional[JobDetail]:
        """获取详情 — 导航到详情页，用JS提取JD文本"""
        if not url:
            return None

        page = self._get_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(random.uniform(2000, 4000))
            self._human_scroll(page)

            jd_text = page.evaluate("""() => {
                const sels = ['.job-sec-text', '.job-detail', '.detail-content',
                              '.text', '.job-boss-desc', '.job-description',
                              '[class*="description"]', '[class*="detail"]'];
                for (const sel of sels) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.length > 100) return el.innerText.trim();
                }
                return document.body ? document.body.innerText.substring(0, 3000) : '';
            }""")

            return JobDetail(
                title=page.title(),
                company="",
                jd_text=jd_text,
                url=url,
            )
        finally:
            self._human_delay(self.MIN_DETAIL_DELAY, self.MAX_DETAIL_DELAY)

    def stop(self):
        """断开CDP（不关浏览器）"""
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._browser = None
        self._playwright = None
        logger.info("CDP 已断开")


# ── 工厂 ──

_ENGINES = {
    "manual": ManualEngine,
    "playwright": PlaywrightEngine,
    "scraping": ScrapingApiEngine,
    "cdp": CDPEngine,
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
        if isinstance(eng, (PlaywrightEngine, CDPEngine)):
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
        if isinstance(eng, (PlaywrightEngine, CDPEngine)):
            eng.stop()
