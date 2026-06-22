#!/usr/bin/env python3
"""
Knowledge Agent — 全链路自动化测试 Harness
============================================
测试覆盖：
  1. 采集层 — 文字/URL/文件/图片统一入口
  2. OCR 层 — PaddleOCR 图片文字识别
  3. 摘要层 — DeepSeek 摘要质量
  4. 飞书层 — 写多维表格
  5. E2E  — 全链路端到端

用法:
  cd /path/to/knowledge-agent
  export PYTHONPATH=src PADDLE_PDX_CACHE_HOME=.paddleocr_cache
  python src/tests/test_harness.py

输出:
  ✓ = 通过   ✗ = 失败   — = 跳过
"""

import os
import sys
import time
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / "config" / ".env")


def red(s):   return f"\033[91m{s}\033[0m"
def green(s): return f"\033[92m{s}\033[0m"
def yellow(s):return f"\033[93m{s}\033[0m"
def bold(s):  return f"\033[1m{s}\033[0m"


def _find_chinese_font():
    """找到系统可用的中文字体路径"""
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def make_test_image(text: str) -> str:
    """生成含中文的测试图片"""
    from PIL import Image, ImageDraw, ImageFont

    font_path = _find_chinese_font()
    # 创建足够宽的画布，确保文字完全可见
    img = Image.new("RGB", (1200, 200), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    if font_path:
        font = ImageFont.truetype(font_path, 40)
    else:
        font = ImageFont.load_default()

    draw.text((40, 60), text, fill=(0, 0, 0), font=font)

    path = str(BASE_DIR / "data" / "inbox" / "test_harness_img.png")
    os.makedirs(BASE_DIR / "data" / "inbox", exist_ok=True)
    img.save(path)
    return path


# ──────────────────────────────────────────────────────────
# 测试用例
# ──────────────────────────────────────────────────────────

class TestIngestion(unittest.TestCase):
    """采集层 — 文字/URL/文件输入"""

    def test_text_input(self):
        """纯文本输入 → 返回结构化 dict"""
        from skills.ingestion_skill import ingest
        result = ingest("这是一段测试文本，用于验证纯文本采集功能是否正常。")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["type"], "text")
        self.assertIn("测试文本", result["raw_content"])
        self.assertTrue(len(result["raw_content"]) > 20)

    def test_long_text_no_file_path_mistake(self):
        """长文本（含换行）不被误判为文件路径"""
        from skills.ingestion_skill import ingest
        long_text = "每天都要记得做三件事\n" * 100
        result = ingest(long_text)
        self.assertEqual(result["type"], "text")
        self.assertIn("每天都要记得做三件事", result["raw_content"])

    def test_url_input(self):
        """URL 输入 → 返回网页内容"""
        from skills.ingestion_skill import ingest
        # 用 Hacker News（稳定、反爬弱）
        result = ingest("https://news.ycombinator.com")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["type"], "url")
        self.assertTrue(len(result.get("raw_content", "")) > 50,
                        f"URL 内容太短: {repr(result.get('raw_content', '')[:100])}")

    def test_url_platform_detection_douban(self):
        """豆瓣 URL → 正确识别平台"""
        from skills.ingestion_skill import ingest
        result = ingest("https://www.douban.com/")
        self.assertEqual(result.get("platform"), "douban")

    def test_url_platform_detection_xiaohongshu(self):
        """小红书 URL → 正确识别平台"""
        from skills.ingestion_skill import ingest
        result = ingest("https://www.xiaohongshu.com/discovery/item/test")
        self.assertEqual(result.get("platform"), "xiaohongshu")

    def test_url_platform_detection_wechat(self):
        """公众号 URL → 正确识别平台"""
        from skills.ingestion_skill import ingest
        result = ingest("https://mp.weixin.qq.com/s/test_article")
        self.assertEqual(result.get("platform"), "wechat_mp")

    def test_file_input(self):
        """本地文件输入 → 读取文件内容"""
        from skills.ingestion_skill import ingest
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("这是通过本地文件采集的测试内容。")
            tmp = f.name
        try:
            result = ingest(tmp)
            self.assertIsInstance(result, dict)
            self.assertEqual(result["type"], "file")
            self.assertIn("本地文件采集", result["raw_content"])
        finally:
            os.unlink(tmp)


class TestOCR(unittest.TestCase):
    """OCR 层 — PaddleOCR 图片识别"""

    @classmethod
    def setUpClass(cls):
        cls.img_path = make_test_image("知识就是力量")

    def test_ocr_returns_text(self):
        """图片 OCR → 返回非空文字"""
        from skills.multimodal_skill import image_to_text
        result = image_to_text(self.img_path)
        self.assertIsNotNone(result)
        self.assertTrue(len(result) > 2,
                        f"OCR 结果太短: {repr(result)}")

    def test_ocr_contains_keywords(self):
        """OCR 结果包含原图中的关键词（至少命中一个字）"""
        from skills.multimodal_skill import image_to_text
        result = image_to_text(self.img_path)
        keywords = ["知识", "就是", "力量", "知", "识", "力", "量"]
        hit = any(kw in result for kw in keywords)
        self.assertTrue(hit, f"未命中任何关键词: {repr(result[:100])}")

    def test_ocr_warmup(self):
        """OCR 模块预热函数正常执行"""
        from skills.multimodal_skill import warmup
        warmup()


class TestSummary(unittest.TestCase):
    """摘要层 — DeepSeek AI 摘要质量"""

    def _summarize(self, content):
        from skills.summary_skill import summarize
        return summarize(content)

    def test_summary_returns_structure(self):
        """摘要返回包含 title/summary/tags/category"""
        result = self._summarize(
            "Python 是一门优雅的编程语言，以其简洁的语法和强大的生态而闻名。"
            "它在数据科学、Web 开发和 AI 领域都有广泛应用。"
        )
        self.assertIsInstance(result, dict)
        for key in ("title", "summary", "tags", "category"):
            self.assertIn(key, result, f"缺少字段: {key}")

    def test_title_not_empty(self):
        """摘要标题非空且有意义"""
        result = self._summarize(
            "量子计算利用量子比特的叠加态和纠缠态来进行并行计算。"
        )
        self.assertTrue(len(result.get("title", "")) > 1)
        self.assertNotEqual(result.get("title", ""), "无标题")

    def test_tags_is_list(self):
        """tags 字段是列表类型"""
        result = self._summarize("机器学习是人工智能的一个分支。")
        tags = result.get("tags", [])
        self.assertIsInstance(tags, list)
        self.assertTrue(len(tags) >= 1, f"标签列表为空: {tags}")


class TestFeishu(unittest.TestCase):
    """飞书层 — 多维表格写入"""

    def test_write_and_verify(self):
        """写入一条记录 → 验证返回"""
        from skills.feishu_skill import write_to_bitable

        if not os.getenv("FEISHU_APP_ID"):
            self.skipTest("FEISHU_APP_ID 未配置")

        record = {
            "id": f"harness_test_{int(time.time())}",
            "source_type": "test",
            "source_path": "harness",
            "title": "自动化测试标题",
            "summary": "这是一条由自动化测试写入的记录。",
            "full_content": "自动化测试内容。",
            "tags": ["测试", "自动化"],
            "category": "测试",
            "embedding_status": False,
            "created_at": int(time.time() * 1000),
        }
        resp = write_to_bitable(record)
        self.assertIn("code", resp)
        self.assertEqual(
            resp.get("code"), 0,
            f"飞书写入失败: {resp.get('msg', resp)}"
        )


class TestE2E(unittest.TestCase):
    """E2E — 全链路端到端"""

    def test_text_e2e(self):
        """文字全链路：ingest → summarize → feishu"""
        from main import process

        result = process(
            "《原子习惯》是 James Clear 写的一本畅销书，"
            "核心观点是：微小的改变通过复利效应可以带来巨大的成果。"
            "作者提出了习惯四步法：提示、渴求、回应、奖赏。"
        )
        for key in ("title", "summary", "tags", "category"):
            self.assertIn(key, result, f"缺少字段: {key}")
        self.assertTrue(len(result["title"]) > 0)
        self.assertIn("record_id", result)

    def test_image_e2e(self):
        """图片全链路：OCR → summarize → feishu"""
        from main import process

        img = make_test_image("《原子习惯》教你如何养成好习惯")
        result = process(img)

        for key in ("title", "summary", "tags", "category"):
            self.assertIn(key, result, f"缺少字段: {key}")

        self.assertNotEqual(
            result.get("title"), "无标题",
            "图片摘要不应为「无标题」"
        )
        self.assertIn("record_id", result)


# ──────────────────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print(bold("=" * 60))
    print(bold("  Knowledge Agent — 全链路自动化测试"))
    print(bold("=" * 60))
    print()

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestIngestion))
    suite.addTests(loader.loadTestsFromTestCase(TestOCR))
    suite.addTests(loader.loadTestsFromTestCase(TestSummary))
    suite.addTests(loader.loadTestsFromTestCase(TestFeishu))
    suite.addTests(loader.loadTestsFromTestCase(TestE2E))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # 总结
    print()
    print(bold("─" * 60))
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors) - len(result.skipped)
    skipped = len(result.skipped)
    failed = len(result.failures) + len(result.errors)

    if failed == 0 and skipped == 0:
        print(green(f"  ALL PASSED  {passed}/{total}"))
    elif failed == 0:
        print(yellow(f"  PASSED {passed}/{total}  (skipped {skipped})"))
    else:
        print(red(f"  FAILED {failed}/{total}"))
        for test, tb in result.failures + result.errors:
            print(red(f"    ✗ {test}"))

    print(bold("─" * 60))
    print()

    sys.exit(0 if failed == 0 else 1)
