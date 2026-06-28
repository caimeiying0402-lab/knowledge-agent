"""
浏览器渲染抓取技能 — Playwright 方案
用于抓取 JS 动态渲染的网站（小红书、公众号等）
零 API 成本，本地 Chromium 运行
"""
import logging

logger = logging.getLogger(__name__)

# 单例浏览器实例（复用，避免反复启动）
_browser_instance = None
_playwright_instance = None
_playwright_available = None


def _check_playwright():
    """检测 Playwright 是否可用"""
    global _playwright_available
    if _playwright_available is None:
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
            _playwright_available = True
        except ImportError:
            logger.warning(
                "Playwright 未安装，浏览器渲染降级不可用。"
                "安装: pip install playwright && playwright install chromium"
            )
            _playwright_available = False
    return _playwright_available


def _get_browser():
    """获取或创建浏览器实例（单例模式）"""
    global _browser_instance, _playwright_instance
    if not _check_playwright():
        raise RuntimeError("Playwright 不可用，请先安装 playwright")
    if _browser_instance is None:
        from playwright.sync_api import sync_playwright
        _playwright_instance = sync_playwright().start()
        _browser_instance = _playwright_instance.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        logger.info("Playwright Chromium 浏览器已启动（单例）")
    return _browser_instance


def render_and_extract(url: str, wait_selector: str = None,
                       timeout: int = 15000) -> str:
    """
    用浏览器渲染页面并提取可见文本。

    Args:
        url: 目标 URL
        wait_selector: 等待某个 CSS 选择器出现后再提取（如 '#detail-desc'）
        timeout: 超时毫秒数

    Returns:
        页面中的可见文本内容，失败返回空字符串
    """
    if not _check_playwright():
        logger.warning("Playwright 不可用，跳过浏览器渲染")
        return ""

    browser = _get_browser()
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/16.0 Mobile/15E148 Safari/604.1"
        ),
        viewport={"width": 390, "height": 844},
        locale="zh-CN",
    )
    page = context.new_page()

    try:
        page.goto(url, wait_until="networkidle", timeout=timeout)

        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=5000)
            except Exception:
                logger.debug(f"等待选择器超时: {wait_selector}")

        # 等待额外 2 秒让动态内容完全渲染
        page.wait_for_timeout(2000)

        text = page.inner_text("body")
        context.close()
        return text.strip()
    except Exception as e:
        context.close()
        raise e


def stop_browser():
    """关闭浏览器实例（服务停止时调用）"""
    global _browser_instance, _playwright_instance
    if _browser_instance:
        _browser_instance.close()
        _browser_instance = None
    if _playwright_instance:
        _playwright_instance.stop()
        _playwright_instance = None
        logger.info("Playwright 浏览器已关闭")
