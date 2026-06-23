# Knowledge Agent — 架构与进度

## 架构概览

```
用户输入 (文字/图片/URL)
    │
    ▼
┌─────────────────────────────────────┐
│  ingest()  - ingestion_skill.py    │
│  自动识别: URL/文件/文本             │
│  URL: 平台检测 → 专用抓取器          │
│  文件: PNG/JPG → PaddleOCR          │
│  文本: 直接透传                     │
└──────────────┬──────────────────────┘
               │ raw_content + platform
               ▼
┌─────────────────────────────────────┐
│  summarize() - summary_skill.py    │
│  DeepSeek → title/summary/tags/     │
│             category/date          │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  write_to_bitable() - feishu       │
│  飞书多维表格 ← 结构化记录           │
└─────────────────────────────────────┘
```

## 当前进度

### ✅ 已完成

| 模块 | 状态 | 说明 |
|------|------|------|
| 文字采集 | ✅ | 任意文本输入 |
| 图片OCR | ✅ | PaddleOCR本地引擎，零成本 |
| AI摘要 | ✅ | DeepSeek，标题+摘要+标签+分类 |
| 飞书入库 | ✅ | 11字段自动写入 |
| 通用网页 | ✅ | Wikipedia/少数派等可达网站 |
| 企微自建应用 | ✅ | 企微成员发消息触发ETL |
| GitHub托管 | ✅ | 私有仓库已创建 |

### ⚠️ 部分可用

| 模块 | 状态 | 说明 |
|------|------|------|
| 小红书 | ⚠️ | 仅能获取og:metadata（JS渲染限制） |
| 豆瓣 | ⚠️ | 反爬严格，需手动复制内容 |
| 公众号 | ⚠️ | JS渲染，只能拿到页面标题 |
| 微信客服 | ⚠️ | 轮询模式受API限流影响 |

### ❌ 待实现

| 模块 | 优先级 |
|------|--------|
| Headless浏览器 | P1（可解决JS渲染网站抓取） |
| SQLite本地库 | P2 |
| RAG检索 | P2 |
| 微信SQLite真机 | P3 |

## 启动命令

```bash
cd /Users/caimeiying/AI-Agent-Lab/knowledge-agent
source .venv/bin/activate
PYTHONPATH=src python src/main.py
```

## 平台抓取能力矩阵

| 网站类型 | 直接抓取 | 限制说明 |
|---------|---------|---------|
| Wikipedia | ✅ 正常 | ~62K 字符 |
| 少数派 | ✅ 正常 | ~1.3K 字符 |
| 36氪 | ✅ 正常 | 内容OK |
| 小红书 | ⚠️ 仅元数据 | JS渲染，需浏览器 |
| 豆瓣 | ❌ 反爬 | 需登录态cookie |
| 公众号 | ⚠️ 仅标题 | 完全JS渲染 |
| 知乎 | ❌ 403 | 反爬 |
| 百度百科 | ❌ 403 | 反爬 |

## 技术栈

- Python 3.12 + .venv
- BeautifulSoup4（HTML解析）
- PaddleOCR（图片识别，本地引擎）
- DeepSeek（AI摘要）
- 飞书多维表格（数据存储）
- Flask + Cloudflare Tunnel（企微Webhook）
- GitHub（代码托管）
