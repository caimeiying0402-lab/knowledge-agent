# Personal AI OS — 架构设计（已实现状态）

> 最后更新：2026-07-01
> 反映代码实际运行状态，非计划状态。

---

## 一、系统定位

Personal AI OS = 多 Agent 协作系统。当前阶段：Knowledge Agent 主线。

**业务目的：** 将个人碎片化信息（微信消息、网页、图片、链接）自动采集、AI 提炼、结构化存储、可随时检索，构建个人知识库。

| Agent | 定位 | 状态 |
|-------|------|------|
| Knowledge Agent | 多端采集 → AI 处理 → 结构化知识库 → 可检索 | 🟢 主线已完工 |
| Job Agent | 简历 × JD 匹配 | ⬜ 下一阶段 |
| 自动记账 Agent | 账单 → 随手记 | ⬜ 未启动 |
| Rule Mining Agent | 规则挖掘 + 推荐 | ⬜ 未启动 |

---

## 二、云端 vs 本地：为什么 Mac 必须开机才能处理图片

### 云端负责（7×24，Mac 关机也可）

| 环节 | 运行位置 | 说明 |
|------|---------|------|
| 企微回调接收 | Cloudflare Worker | 接收企微推送的 POST 请求 |
| 签名验证 | Cloudflare Worker | SHA1 校验 msg_signature |
| AES-256-CBC 解密 | Cloudflare Worker | Web Crypto API + 纯 JS fallback |
| 消息入库 | Cloudflare D1 | 文字/链接/图片元数据存 D1，排队等待处理 |
| 图片下载 | Cloudflare Worker → R2 | 企微图片 media_id 3 天过期，Worker 收到后立即下载到 R2 永久保存 |

### 本地负责（Mac 开机时执行）

| 环节 | 运行位置 | **为什么必须在 Mac？** |
|------|---------|----------------------|
| 图片 OCR | Mac Python + PaddleOCR | Cloudflare Worker 只能跑 JS，**无法运行 PaddleOCR（Python 本地模型引擎，含数百 MB 模型文件）** |
| 网页内容抓取（JS 渲染） | Mac Python + Playwright | 需要 **Chromium 浏览器实例**，Worker 无浏览器环境 |
| AI 摘要（DeepSeek） | Mac Python | 技术上 Worker 可以调 DeepSeek API，但为保持管道一致性，统一在本地 ETL 中处理 |
| Embedding 向量化 | Mac Python + ONNX | **本地 ONNX 模型**（all-MiniLM-L6-v2），Worker 无 ONNX 运行时 |
| 飞书写入 | Mac Python | 飞书 API 调用，技术上 Worker 也可做，但统一在 ETL 管道处理 |
| SQLite 写入 | Mac Python | 本地数据库文件，Worker 无法访问 Mac 文件系统 |
| Chroma 向量写入 | Mac Python | 本地向量库文件，同上 |

### 架构决策：为什么不在 Worker 端做完所有事？

```
Worker 能做的：接收、解密、排队、图片转存 R2       → 已实现 ✅
Worker 做不了的：OCR、浏览器渲染、ONNX embedding    → 必须 Mac

文字消息虽然在 Worker 端完全可以直接调 DeepSeek + 飞书 API 完成端到端处理，但：
  - 保持管道统一（所有 ETL 逻辑在一个地方）
  - 避免 Worker 和 Mac 两处维护相同的 summarize/feishu 代码
  - 图片和链接消息无论如何需要在 Mac 处理，分两条路径徒增复杂度
```

---

## 三、Knowledge Agent — 完整架构

### 3.1 全链路数据流

```
┌──────────────────────────────────────────────────────────────────────┐
│                        云端（Cloudflare，7×24）                       │
│                                                                      │
│  企微消息 ──→ Worker 接收 ──→ 签名验证 ──→ AES解密 ──→ D1 排队      │
│                              （文字/链接/图片）         │             │
│                                   │                     │             │
│                              图片有media_id              │             │
│                                   │                     │             │
│                              Worker下载 → R2存储         │             │
│                              （绕过3天过期）              │             │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │
                                   │  Mac 开机时触发
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    Mac 本地（cloud_sync_skill.py）                     │
│                                                                      │
│  拉取 D1 pending 消息 ──→ 按类型分发                                  │
│    ├─ 文字 ──→ URL检测？──→ 是：ingestion抓取页面                     │
│    │                       否：透传                                  │
│    ├─ 图片 ──→ PaddleOCR 本地识别 ──→ 提取文字                       │
│    └─ 链接 ──→ ingestion_skill 页面抓取                               │
│                         │                                            │
│                         ▼                                            │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │              ETL 管道（main.py v5）                           │    │
│  │                                                              │    │
│  │  1. ingest()                                                 │    │
│  │     ├─ 平台检测（小红书/公众号/通用网页/纯文本/图片）           │    │
│  │     ├─ requests + BS4（静态网页）                              │    │
│  │     └─ Playwright Chromium（JS 渲染降级）                      │    │
│  │                         │                                    │    │
│  │  2. summarize() — DeepSeek Chat API                          │    │
│  │     输出: title / summary / highlights / category /          │    │
│  │           tags / source_quality / actionable                 │    │
│  │     19 分类体系 + 平台感知 Prompt                              │    │
│  │                         │                                    │    │
│  │  2.5. structured_format_skill.py                             │    │
│  │     编号层级笔记 ← DeepSeek 二次格式化                         │    │
│  │     每条 ≤80 字，零废话，原文不篡改                             │    │
│  │                         │                                    │    │
│  │  3. 三写存储                                                │    │
│  │     ├─ 飞书多维表格（主展示，结构化笔记）                        │    │
│  │     ├─ SQLite data/knowledge.db（本地真相源）                  │    │
│  │     └─ Chroma data/chroma_db/（向量检索，ONNX embedding）      │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 各环节：技术架构 + 业务目的

#### 环节 1：消息接收（Cloudflare Worker）

**文件：** `cloudflare-worker/src/index.ts` (v9)

| 维度 | 说明 |
|------|------|
| **业务目的** | 7×24 接收企微消息，Mac 关机时消息不丢失，排队等待处理 |
| **技术方案** | Cloudflare Worker（边缘计算，全球部署，免费额度足够） |
| **解密方案** | AES-256-CBC：Web Crypto API 优先，纯 JS 实现兜底（绕过企微非标准空格填充） |
| **签名验证** | SHA1(msg_token + timestamp + nonce + encrypt 排序拼接) |
| **图片处理** | 收到 media_id → 调企微 API 下载 → 存 R2（绕过 3 天过期限制） |
| **自定义域名** | `wechat.happymia.top`（workers.dev 国内不可达，绑定自定义域名解决） |
| **路由** | `/wechat/callback` GET(验证) POST(接收) / `/api/pending` / `/api/processed` / `/api/stats` / `/api/image/:key` / `/health` |
| **认证** | 企微回调：签名验证 / 同步 API：Bearer Token |

#### 环节 2：消息排队（Cloudflare D1）

| 维度 | 说明 |
|------|------|
| **业务目的** | 解耦 Worker 接收和 Mac 处理，消息不丢 |
| **技术方案** | Cloudflare D1（边缘 SQLite，免费 5GB 存储 / 5M 行查询/月） |
| **表结构** | messages(id, msg_type, from_user, content, url, title, description, media_id, image_r2_key, created_at, processed, processed_at) |
| **查询** | `SELECT * WHERE processed=0 ORDER BY id ASC`（FIFO） |

#### 环节 3：图片暂存（Cloudflare R2）

| 维度 | 说明 |
|------|------|
| **业务目的** | 企微临时 media_id 3 天过期，Worker 收到后立即下载到 R2 保证图片不丢 |
| **技术方案** | Cloudflare R2（S3 兼容对象存储，10GB 免费） |
| **Key 命名** | `wechat_{media_id}.jpg` |

#### 环节 4：本地同步（cloud_sync_skill.py）

**文件：** `src/skills/cloud_sync_skill.py`

| 维度 | 说明 |
|------|------|
| **业务目的** | Mac 开机后将 D1 排队消息拉取到本地，分类型处理（文字/图片/链接） |
| **技术方案** | HTTP 拉取 Worker API → 按消息类型分发 → 调 ETL 管道 |
| **图片处理** | 优先从 R2 下载（永久保存），失败则降级调企微 API（3 天内有效） |
| **URL 展开** | 文字中检测到 URL → 自动调 ingestion_skill 抓取页面正文 |
| **重试机制** | 指数退避，3 次重试，5xx 重试 4xx 不重试 |
| **轮询模式** | 单次（`sync_once`）或循环（`--loop`，智能：有消息 30s / 空闲 60s） |

#### 环节 5：内容采集（ingestion_skill.py + browser_skill.py）

**文件：** `src/skills/ingestion_skill.py`、`src/skills/browser_skill.py`

| 维度 | 说明 |
|------|------|
| **业务目的** | 从各种来源获取正文内容（网页/图片/文本） |
| **通用网页** | requests + BeautifulSoup4 → 提取正文 |
| **小红书** | 方式1: `__INITIAL_STATE__` JSON 解析 → 方式2: CSS 选择器 → 方式3: Playwright 渲染降级 |
| **公众号** | HTML 解析 → og:metadata 降级 → Playwright 渲染降级 |
| **图片 OCR** | PaddleOCR 本地引擎（中文识别，零 API 成本） |
| **浏览器渲染** | Playwright Chromium 单例复用，iPhone User-Agent，移动端视口 |
| **为什么必须本地？** | PaddleOCR = Python 本地模型（数百 MB）。Playwright = Chromium 浏览器进程。Cloudflare Worker 不支持。 |

#### 环节 6：AI 摘要（summary_skill.py + deepseek_client.py）

**文件：** `src/skills/summary_skill.py`、`src/models/deepseek_client.py`

| 维度 | 说明 |
|------|------|
| **业务目的** | 将非结构化长文提炼为结构化元数据，支撑后续检索和展示 |
| **技术方案** | DeepSeek Chat API（兼容 OpenAI SDK），低成本（约 ¥1/百万 token） |
| **输出字段** | title(标题) / summary(摘要) / highlights(亮点列表) / category(19分类) / tags(标签) / source_quality(可信度) / actionable(是否可行动) |
| **19 分类** | 个人成长 / 科技与AI / 效率方法 / 产品与工具 / 健康与心理 / 人际关系 / 美食与消费 / 职业发展 / 金融投资 / 设计审美 / 教育学习 / 娱乐休闲 / 社会观察 / 历史人文 / 自然科学 / 技术/编程 / 医学健康 / 法律 / 其他 |

#### 环节 7：结构化格式化（structured_format_skill.py）

**文件：** `src/skills/structured_format_skill.py` (v5 新增)

| 维度 | 说明 |
|------|------|
| **业务目的** | 将 AI 摘要从"亮点列表"转为编号层级笔记，方便飞书阅读 |
| **技术方案** | DeepSeek Chat API 二次格式化（temperature=0.1，减少创造） |
| **输出规则** | 层级编号（1. → 1.1 → 1.2）/ 每条 ≤80 字 / 禁止"这是""核心""值得"等元描述词 / 原文事实不篡改 |
| **输入** | 原文优先（≤3000 字）→ AI 摘要（参考）→ 候选亮点（参考） |
| **降级** | DeepSeek 调用失败时用原文摘要+亮点简单拼接 |

#### 环节 8：三写存储

| 存储 | 文件 | 业务目的 | 技术方案 |
|------|------|---------|---------|
| 飞书多维表格 | `src/skills/feishu_skill.py` | **主展示层**，人在飞书里看笔记 | tenant_access_token → bitable API → 11 字段记录 |
| SQLite | `src/knowledge/sqlite_store.py` + `src/skills/sqlite_skill.py` | **本地真相源**，离线可用，不受飞书 API 限制 | Python sqlite3，全文搜索（LIKE），按分类/标签/来源查询 |
| Chroma 向量库 | `src/knowledge/chroma_store.py` + `src/skills/embedding_skill.py` | **语义检索**，支持"相似内容"查询 | ChromaDB 持久化 + ONNX all-MiniLM-L6-v2 embedding（macOS x86_64 兼容，零 PyTorch 依赖） |

### 3.3 消息入口矩阵

| 入口 | 技术方案 | 消息类型 | 定位 | 状态 |
|------|---------|---------|------|------|
| 企微自建应用 | Cloudflare Worker + D1 + R2 + cloud_sync | 文字/链接/图片 | **主采集端** | ✅ 全链路 |
| 微信客服轮询 | sync_msg API 轮询 | 文字/链接/图片 | 备用入口（个人微信） | ⚠️ 45009 限流 |
| 手动 CLI | `python main.py` / 文件路径 / URL | 文本/URL/文件 | 调试/批量导入 | ✅ |

> iCloud + 快捷指令链路已移除（2026-06-28）。企微是唯一采集端。

### 3.4 平台抓取能力

| 平台 | 方案 | 状态 |
|------|------|------|
| 通用网页 | requests + BS4 | ✅ |
| 小红书 | INITIAL_STATE + CSS + Playwright 三级降级 | ✅ |
| 公众号 | HTML + `og:metadata` + Playwright 三级降级 | ✅ |
| 图片 | PaddleOCR 本地识别（中文优化） | ✅ |

---

## 四、Job Agent（下一阶段）

> 业务目的：简历 × 岗位 JD 自动匹配评分，辅助求职决策

```
简历(PDF/文本) → resume_skill(DeepSeek结构化提取) → match_skill(匹配评分)
                                                         ↑
                              岗位JD ← job_search_skill(BOSS/猎聘抓取)
```

待实现：简历解析、JD 采集、匹配评分。

---

## 五、共享基础设施

| 组件 | 选型 | 说明 |
|------|------|------|
| AI 引擎 | DeepSeek Chat API | 兼容 OpenAI SDK，低成本 |
| 本地 OCR | PaddleOCR | 中文识别，零 API 成本，必须 Mac |
| 浏览器渲染 | Playwright Chromium | 单例复用，必须 Mac |
| 消息网关 | Cloudflare Worker + D1 + R2 | 7×24 免费，Mac 离线不丢消息 |
| 主展示 | 飞书多维表格 | 11 字段，结构化笔记展示 |
| 本地真相源 | SQLite | 31 条，离线可用 |
| 向量检索 | Chroma + ONNX embedding | 24 条向量化，零 PyTorch 依赖 |
| 语言 | Python 3.12 | .venv 虚拟环境 |
