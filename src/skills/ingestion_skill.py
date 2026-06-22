import re
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from skills.multimodal_skill import image_to_text


# ──────────────────────────────────────────────────────────
# 平台识别
# ──────────────────────────────────────────────────────────

_PLATFORM_PATTERNS = {
    "xiaohongshu":  r"xiaohongshu\.com",
    "douban":       r"douban\.com",
    "wechat_mp":    r"mp\.weixin\.qq\.com",
}

def _detect_platform(url: str) -> str:
    """根据 URL 域名识别平台，返回平台标识或 'generic'"""
    for name, pattern in _PLATFORM_PATTERNS.items():
        if re.search(pattern, url):
            return name
    return "generic"


# ──────────────────────────────────────────────────────────
# 通用 HTTP 工具
# ──────────────────────────────────────────────────────────

_BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _fetch_html(url: str, extra_headers: dict = None, timeout: int = 15) -> str:
    """统一的网页抓取，返回 HTML 文本"""
    headers = dict(_BASE_HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    resp = requests.get(url, headers=headers, timeout=timeout,
                        allow_redirects=True,
                        proxies={"http": None, "https": None})
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def _extract_clean_text(html: str, remove_tags: list = None) -> str:
    """从 HTML 中提取清洗后的纯文本"""
    soup = BeautifulSoup(html, "html.parser")

    # 移除干扰标签
    kill_tags = remove_tags or ["script", "style", "nav", "footer", "header",
                                "iframe", "noscript", "svg"]
    for tag in soup(kill_tags):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    # 去除多余空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ──────────────────────────────────────────────────────────
# 各平台专用抓取器
# ──────────────────────────────────────────────────────────

def _ingest_xiaohongshu(url: str) -> dict:
    """小红书笔记抓取"""
    try:
        html = _fetch_html(url, extra_headers={
            "Referer": "https://www.xiaohongshu.com/",
            "Cookie": "",  # 如需登录态可在此处填入
        })

        # 小红书在 <meta name="og:title"> 和 <meta name="description"> 中有信息
        soup = BeautifulSoup(html, "html.parser")

        title = ""
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"]

        desc = ""
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            desc = og_desc["content"]
        if not desc:
            desc_meta = soup.find("meta", attrs={"name": "description"})
            if desc_meta and desc_meta.get("content"):
                desc = desc_meta["content"]

        # 正文内容从 #detail-desc 或 note-scroller 容器提取
        content_parts = []
        for selector in ["#detail-desc", ".note-scroller", ".note-text",
                         "[class*='note-text']", "[class*='content']"]:
            try:
                el = soup.select_one(selector)
                if el:
                    content_parts.append(el.get_text(separator="\n", strip=True))
            except Exception:
                pass

        body = "\n".join(content_parts) if content_parts else _extract_clean_text(html)
        full_text = f"{title}\n{desc}\n{body}".strip()

        return {"type": "url", "raw_content": full_text, "source_path": url,
                "platform": "xiaohongshu"}
    except Exception as e:
        return _fallback_generic(url, f"小红书抓取失败: {e}")


def _ingest_douban(url: str) -> dict:
    """豆瓣（影评/书评/日记/小组帖）抓取"""
    try:
        html = _fetch_html(url, extra_headers={
            "Referer": "https://www.douban.com/",
        })
        soup = BeautifulSoup(html, "html.parser")

        # 提取标题
        title = ""
        for sel in ["h1", "[property='og:title']", ".article h1", ".subject h1"]:
            el = soup.select_one(sel)
            if el:
                t = el.get("content", "") if el.name == "meta" else el.get_text(strip=True)
                if t:
                    title = t
                    break

        # 提取正文
        body_parts = []
        for sel in [
            "#link-report",          # 书评/影评正文
            ".review-content",       # 评论
            ".topic-content",        # 小组主帖
            ".note-content",         # 日记
            ".article .intro",       # 简介
        ]:
            el = soup.select_one(sel)
            if el:
                body_parts.append(el.get_text(separator="\n", strip=True))

        # 如果有评分等结构化信息，也保留
        rating_el = soup.select_one(".rating_num, [class*='rating']")
        rating = f"评分: {rating_el.get_text(strip=True)}" if rating_el else ""

        body = "\n".join(p for p in body_parts if p)
        if rating:
            body = f"{rating}\n{body}"

        full_text = f"{title}\n{body}".strip()
        if not full_text.strip():
            full_text = _extract_clean_text(html)

        return {"type": "url", "raw_content": full_text, "source_path": url,
                "platform": "douban"}
    except Exception as e:
        return _fallback_generic(url, f"豆瓣抓取失败: {e}")


def _ingest_wechat_mp(url: str) -> dict:
    """微信公众号文章抓取"""
    try:
        # 微信公众号有较强反爬，需要模拟浏览器行为
        html = _fetch_html(url, extra_headers={
            "Referer": "https://mp.weixin.qq.com/",
            "Accept-Encoding": "gzip, deflate, br",
        }, timeout=20)

        soup = BeautifulSoup(html, "html.parser")

        # 公众号文章标题在 #activity-name 或 <h1>
        title = ""
        for sel in ["#activity-name", "h1.rich_media_title", ".rich_media_title"]:
            el = soup.select_one(sel)
            if el:
                title = el.get_text(strip=True)
                break

        # 正文在 #js_content 或 .rich_media_content
        body = ""
        for sel in ["#js_content", ".rich_media_content", "#js_article"]:
            el = soup.select_one(sel)
            if el:
                body = el.get_text(separator="\n", strip=True)
                break

        # 如果都提取不到，尝试从 meta 标签获取
        if not title and not body:
            og_title = soup.find("meta", property="og:title")
            if og_title:
                title = og_title.get("content", "")
            og_desc = soup.find("meta", property="og:description")
            if og_desc:
                body = og_desc.get("content", "")

        full_text = f"{title}\n\n{body}".strip()
        return {"type": "url", "raw_content": full_text, "source_path": url,
                "platform": "wechat_mp"}
    except Exception as e:
        return _fallback_generic(url, f"公众号抓取失败: {e}")


def _ingest_generic(url: str) -> dict:
    """通用网页抓取"""
    try:
        html = _fetch_html(url)
        soup = BeautifulSoup(html, "html.parser")

        # 优先提取 meta 信息
        title = ""
        og_title = soup.find("meta", property="og:title")
        if og_title:
            title = og_title.get("content", "")
        if not title:
            t = soup.find("title")
            if t:
                title = t.get_text(strip=True)

        desc = ""
        og_desc = soup.find("meta", property="og:description")
        if og_desc:
            desc = og_desc.get("content", "")
        if not desc:
            dm = soup.find("meta", attrs={"name": "description"})
            if dm:
                desc = dm.get("content", "")

        # 正文：优先找 <article>/<main>，再降级到 <body>
        body = ""
        for sel in ["article", "main", "[role='main']", ".post-content", ".article-content"]:
            el = soup.select_one(sel)
            if el:
                body = el.get_text(separator="\n", strip=True)
                break
        if not body:
            body = _extract_clean_text(html)

        full_text = f"{title}\n{desc}\n{body}".strip()
        return {"type": "url", "raw_content": full_text, "source_path": url,
                "platform": "generic"}
    except Exception as e:
        return {"type": "url", "raw_content": f"[抓取失败] {e}", "source_path": url,
                "platform": "generic"}


def _fallback_generic(url: str, reason: str) -> dict:
    """平台专用抓取失败时，降级到通用抓取"""
    try:
        result = _ingest_generic(url)
        return result
    except Exception:
        return {"type": "url", "raw_content": f"[{reason}]", "source_path": url,
                "platform": "generic"}


# ──────────────────────────────────────────────────────────
# 统一入口
# ──────────────────────────────────────────────────────────

def ingest(source: str) -> dict:
    """
    统一入口: 自动识别输入类型
    返回: {"type": "url|file|text", "raw_content": str, "source_path": str, "platform": str}
    """
    # 1. 判断是否是 URL
    if source.startswith(("http://", "https://")):
        platform = _detect_platform(source)

        if platform == "xiaohongshu":
            return _ingest_xiaohongshu(source)
        elif platform == "douban":
            return _ingest_douban(source)
        elif platform == "wechat_mp":
            return _ingest_wechat_mp(source)
        else:
            return _ingest_generic(source)

    # 2. 判断是否是本地文件路径（超过500字符或含换行直接当文本）
    if len(source) > 500 or "\n" in source:
        return {"type": "text", "raw_content": source, "source_path": "", "platform": "text"}

    source_path = Path(source)
    if source_path.exists() and source_path.is_file():
        return _ingest_file(str(source_path.resolve()))

    # 3. 默认作为纯文本
    return {"type": "text", "raw_content": source, "source_path": "", "platform": "text"}


def _ingest_file(filepath: str) -> dict:
    ext = Path(filepath).suffix.lower()

    if ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff"]:
        try:
            text = image_to_text(filepath)
            return {"type": "file", "raw_content": text, "source_path": filepath, "platform": "file"}
        except Exception as e:
            return {"type": "file", "raw_content": f"[识别失败] {e}", "source_path": filepath, "platform": "file"}

    elif ext == ".txt":
        with open(filepath, "r", encoding="utf-8") as f:
            return {"type": "file", "raw_content": f.read(), "source_path": filepath, "platform": "file"}

    else:
        return {"type": "file", "raw_content": f"[不支持: {ext}]", "source_path": filepath, "platform": "file"}
