# Job Agent — 完整开发规格书

> 写给 AI Agent（Codex/Trae/Claude Code）的开发文档。
> 目标读者：能独立完成代码实现的 AI。
> 最后更新：2026-07-01

---

## 一、产品概述

Job Agent = 简历 × 岗位 JD 自动匹配系统。

**核心链路：**
```
定时/手动触发 → 搜索BOSS/猎聘岗位 → 简历匹配评分 → 筛选Top3 →
生成个性化简历+打招呼语 → 企微推送给用户 → 用户决定投递 →
岗位记录留痕(SQLite) → 去重避免重复推送
```

---

## 二、功能需求清单

| ID | 功能 | 优先级 | 说明 |
|----|------|--------|------|
| F1 | 简历结构化解析 | P0 | PDF/文本 → 结构化JSON |
| F2 | 岗位搜索（BOSS直聘） | P0 | Playwright模拟搜索+反爬 |
| F3 | 岗位搜索（猎聘） | P1 | 同上 |
| F4 | 简历×JD匹配评分 | P0 | DeepSeek评分0-100 |
| F5 | 个性化简历生成 | P0 | 针对每个岗位定制简历 |
| F6 | 打招呼语生成 | P0 | 针对每个岗位生成话术 |
| F7 | 企微推送 | P0 | 通过企微自建应用发消息 |
| F8 | 岗位去重 | P0 | 同岗位不重复推送 |
| F9 | 定时调度 | P0 | 支持cron和手动触发 |
| F10 | 硬性筛选 | P0 | 地域/年限/薪资/关键词过滤 |
| F11 | 投递记录留痕 | P1 | SQLite记录+分析基础 |
| F12 | 反爬虫降级 | P0 | 自动→手动降级机制 |

---

## 三、技术架构

### 3.1 整体架构

```
src/agents/career_agent.py          ← 主控调度
src/agents/resume_profile.json      ← 简历数据（AI生成，人工review）
src/skills/resume_skill.py          ← F1: 简历解析
src/skills/job_search_skill.py      ← F2/F3: 岗位搜索
src/skills/match_skill.py           ← F4: 匹配评分
src/skills/resume_generator_skill.py ← F5: 个性化简历
src/skills/greeting_skill.py        ← F6: 打招呼语
src/skills/delivery_skill.py        ← F7: 企微推送
src/knowledge/job_store.py          ← F8/F11: 岗位记录(SQLite)
config/job_filters.yaml             ← F10: 筛选条件配置
```

### 3.2 数据流

```
                      ┌──────────────────────────┐
                      │    career_agent.py (主控) │
                      │    编排调度所有skill      │
                      └──────────┬───────────────┘
                                 │
        ┌────────────────────────┼──────────────────────────┐
        │                        │                          │
        ▼                        ▼                          ▼
┌──────────────┐       ┌──────────────┐          ┌──────────────┐
│ F1 简历解析  │       │ F2/3 岗位搜索│          │ F4 匹配评分  │
│ resume_skill │       │job_search    │          │ match_skill  │
│              │       │   _skill     │          │              │
│ PDF/文本输入 │       │ BOSS/猎聘    │          │ 简历×JD      │
│ →结构化JSON  │       │ →JD列表      │          │ →0-100分+理由│
└──────────────┘       └──────┬───────┘          └──────┬───────┘
                              │                          │
                              ▼                          ▼
                     ┌────────────────┐        ┌──────────────┐
                     │ 硬性筛选+去重  │◄───────│ 匹配评分结果  │
                     │ (地域/年限等)  │        └──────────────┘
                     │ Top3           │
                     └───────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
      ┌────────────┐ ┌────────────┐ ┌────────────┐
      │F5 个性化   │ │F6 打招呼语 │ │F7 企微推送 │
      │简历生成    │ │生成        │ │            │
      │resume_gene │ │greeting    │ │delivery    │
      │rator_skill │ │_skill      │ │_skill      │
      └────────────┘ └────────────┘ └─────┬──────┘
                                          │
                          ┌───────────────┘
                          ▼
                  ┌──────────────┐
                  │  用户看到    │
                  │  决定是否    │
                  │  投递        │
                  └──────┬───────┘
                         │
                         ▼
                  ┌──────────────┐
                  │F8 去重记录   │
                  │F11 投递记录  │
                  │job_store.py  │
                  │→ SQLite      │
                  └──────────────┘
```

---

## 四、各模块详细规格

### F1: resume_skill.py — 简历结构化解析

**输入:** PDF文件路径 或 纯文本
**输出:** 结构化JSON（与 resume_profile.json 同schema）

**实现方案:**
1. PDF → 文本提取：`pdfplumber` 库（pip install pdfplumber）
2. 文本 → 结构化JSON：DeepSeek Chat API，专用System Prompt
3. 输出字段：personal / core_competencies / work_experience / education / languages

**Prompt设计要点:**
- 提取: 姓名、目标岗位、工作年限、技能列表（领域知识+AI专长+产品技能）
- 工作经历: 公司、职位、时间段、3-5条核心亮点
- 教育: 学位、专业、学校
- 语言能力

**参考文件:** `src/agents/resume_profile.json`（已基于简历PDF生成，人工review后可用）

---

### F2/F3: job_search_skill.py — 岗位搜索

**职责:** 在BOSS直聘/猎聘上搜索匹配岗位

#### BOSS直聘方案

**技术方案:** Playwright（复用已有 browser_skill.py 的 Chromium 实例）

**搜索流程:**
1. 打开 `https://www.zhipin.com/web/geek/job?city=杭州&query=财务产品经理`
2. 等待岗位列表加载 → 提取前N条岗位
3. 遍历每个岗位详情页 → 提取JD全文
4. 应用硬性筛选条件（见F10）

**反爬虫策略（关键！）:**

BOSS直聘反爬非常严格，需要多层防护：

```
Level 1: stealth.js 注入
  - 隐藏 webdriver 属性
  - 伪造 navigator 指纹
  - 覆盖 chrome.runtime

Level 2: 行为模拟
  - 随机延迟（3-8秒）在每次操作间
  - 模拟人类鼠标轨迹（不是直线）
  - 搜索结果页随机滚动
  - 不要一次性打开所有详情页（间隔打开）

Level 3: Cookie/Session 管理
  - 首次运行需要人类扫码登录
  - 保存登录后的 storage_state（Playwright）
  - 后续运行复用 storage_state
  - 检测到登录过期 → 提示人类重新登录

Level 4: 降级策略
  - 连续3次被拦截 → 切换到"手动触发模式"
  - 在企微通知用户："BOSS反爬升级，请手动打开BOSS并触发一次搜索"
  - 提供手动模式：用户在BOSS搜索后复制URL → Agent解析URL → 抓取
```

**存储状态文件:** `data/boss_session.json`（Playwright storage_state，gitignored）

**提取字段:**
- 岗位标题、公司、薪资、地点、年限要求、学历要求
- JD全文、岗位标签、发布时间
- 原始URL（用于去重+用户点击跳转）

#### 猎聘方案

与BOSS类似，适配猎聘的DOM结构。猎聘反爬相对宽松，但需注意：
- 可能需要对搜索结果页做分页滚动
- 猎聘有"投递"按钮状态，可判断是否已投递

---

### F4: match_skill.py — 匹配评分

**输入:** 简历JSON + JD文本
**输出:** {score: 0-100, match_points: [], gap_points: [], suggestion: ""}

**实现方案:** DeepSeek Chat API

**Prompt 设计关键:**
```
你是岗位匹配评估引擎。

【评分维度】（总分100）
1. 领域匹配度(30分): 财务/ERP/企业服务领域的经验匹配
2. 技能匹配度(25分): AI能力、产品技能、工具链
3. 经验年限匹配(20分): 工作年限与岗位要求对比
4. 行业匹配度(15分): 互联网/企业服务行业经验
5. 项目亮点匹配(10分): 过往项目与岗位需求的契合

【输出格式】
{
  "score": 85,
  "breakdown": {"domain": 28, "skill": 22, "experience": 18, "industry": 12, "highlights": 5},
  "match_points": ["...具体匹配点..."],
  "gap_points": ["...差距点..."],
  "overall_assessment": "一句话总结",
  "suggestion": "投递建议（强推/可投/观望）"
}

【约束】
- 严格基于简历和JD事实评分
- 不夸大简历能力
- 差距点要诚实指出
```

**硬性一票否决（在匹配前执行）:**
- 工作年限不匹配 → 不进入AI评分
- 薪资范围不匹配 → 标记但不过滤
- 地域不匹配 → 过滤

---

### F5: resume_generator_skill.py — 个性化简历生成

**输入:** 简历JSON + 目标岗位JD
**输出:** 针对该岗位定制的简历文本

**定制逻辑:**
1. 根据JD中的关键词，调整技能highlight的顺序（最匹配的放前面）
2. 工作经历中的项目描述，用JD中的术语重新表述
3. 补充JD中要求但简历中未体现的能力（从过往项目推断）
4. AI专长部分根据岗位是否需要AI能力做强调或弱化

**注意:** 不编造经历。只在表述层面做优化。

---

### F6: greeting_skill.py — 打招呼语生成

**输入:** 简历JSON + 目标岗位JD + 匹配结果
**输出:** 50-150字的打招呼文本

**风格要求:**
- 不卑不亢，专业自信
- 体现对岗位的理解（用JD中的关键词）
- 突出1-2个最匹配的个人亮点
- 避免"您好我是XXX"这种模板化开头
- 例："在字节和网易做了5年财务产品，从0-1做过智能审核和费控系统。看到贵司在招财务产品经理，正好我的经验是..."

---

### F7: delivery_skill.py — 企微推送

**方案:** 复用现有企微自建应用，通过"应用消息"接口反向推送。

**实现:**
- 用 WECOM_CORP_ID + WECOM_CORP_SECRET 获取 access_token
- 调用企微"发送应用消息"API：`POST /cgi-bin/message/send`
- msgtype: `textcard`（卡片消息，支持标题+描述+点击跳转URL）

**消息模板:**
```
标题：【Job Agent】{岗位} @ {公司} | 匹配度{score}分
描述：
💰 {薪资} | 📍 {地点} | 📅 {年限要求}
📋 JD摘要：{前200字}
✅ 匹配点：{match_points前3条}
⚠️ 差距：{gap_points}

【已生成】个性化简历 | 打招呼语
【原始链接】BOSS直聘查看详情
```

**降级方案（企微推送失败时）:**
- 优先：企微应用消息
- 备选1：本地文件 `data/job_output/{date}/{公司}_{岗位}.md`
- 备选2：终端输出（最后兜底）

---

### F8/F11: job_store.py — 岗位记录与去重

**SQLite 表结构 (data/job_tracker.db):**

```sql
CREATE TABLE IF NOT EXISTS job_pushes (
    id TEXT PRIMARY KEY,             -- UUID
    job_url TEXT NOT NULL,           -- 岗位原始URL（去重键）
    job_title TEXT NOT NULL,         -- 岗位名称
    company TEXT NOT NULL,           -- 公司
    salary TEXT,                     -- 薪资
    location TEXT,                   -- 地点
    platform TEXT,                   -- boss/猎聘
    match_score INTEGER,             -- 匹配分 0-100
    jd_summary TEXT,                 -- JD摘要
    personalized_resume TEXT,        -- 个性化简历全文
    greeting_text TEXT,              -- 打招呼语
    pushed_at INTEGER,               -- 推送时间(unix timestamp)
    delivered_via TEXT,              -- 推送渠道
    human_action TEXT,               -- 用户操作: pending/rejected/applied/interview/offer
    human_action_at INTEGER,         -- 操作时间
    notes TEXT                       -- 人类备注
);

CREATE INDEX IF NOT EXISTS idx_job_url ON job_pushes(job_url);
CREATE INDEX IF NOT EXISTS idx_pushed_at ON job_pushes(pushed_at);
CREATE INDEX IF NOT EXISTS idx_human_action ON job_pushes(human_action);
```

**去重逻辑:**
- 每次搜索到新岗位 → 查询 `job_url` 是否已存在
- 存在 → 跳过
- 不存在 → 进入匹配评分流程

---

### F9: career_agent.py — 定时调度与主控

**CLI 入口:**
```bash
# 手动单次运行
PYTHONPATH=src python src/agents/career_agent.py

# 定时模式（配合launchd或cron）
PYTHONPATH=src python src/agents/career_agent.py --schedule

# 仅搜索+匹配（不生成简历不推送）
PYTHONPATH=src python src/agents/career_agent.py --search-only --max-results 10

# 查看历史投递记录
PYTHONPATH=src python src/agents/career_agent.py --stats
```

**执行流程:**
```
1. 加载简历 (resume_profile.json)
2. 加载筛选条件 (job_filters.yaml)
3. 遍历搜索平台 [BOSS, 猎聘]:
   a. 按关键词搜索
   b. 提取岗位列表
   c. 硬性筛选
   d. 去重检查
   e. 逐个JD抓取详情
4. 对每个新岗位:
   a. 匹配评分
   b. 按分数排序 → Top3
5. 对Top3 每个岗位:
   a. 生成个性化简历
   b. 生成打招呼语
   c. 推送用户
   d. 记录到 job_tracker.db
```

**定时调度:**
```bash
# macOS launchd (~/Library/LaunchAgents/com.knowledge-agent.job.plist)
# 每天早上6点触发
# 如果6点Mac未开机，开机后自动补跑一次

# 或使用 crontab
# 0 6 * * * cd /path && source .venv/bin/activate && PYTHONPATH=src python src/agents/career_agent.py
```

**反爬降级逻辑:**
- 首次尝试 → 自动模式（Playwright + stealth）
- 连续失败3次 → 通知用户"反爬升级"
- 切换定时到晚上9点（用户在线时可手动配合）
- 或切换到纯手动模式

---

### F10: job_filters.yaml — 硬性筛选条件

```yaml
# config/job_filters.yaml
filters:
  location: "杭州"
  work_years: [5, 10]           # 5-10年
  salary_monthly: [40000, 60000] # 月薪范围
  salary_annual_min: 700000      # 年薪最低

search:
  platforms: ["boss", "liepin"]  # BOSS优先，猎聘备选
  max_results_per_platform: 20   # 每个平台最多搜索结果数
  daily_push_limit: 3            # 每天最多推送3个新岗位

  keywords:                      # 按优先级排序
    - "财务产品经理"
    - "财税产品经理"
    - "ERP产品经理"
    - "财务共享产品经理"
    - "业财产品经理"
    - "费控产品经理"
    - "企业服务产品经理"

  exclude_keywords:              # 排除关键字
    - "实习"
    - "应届"
    - "外包"
    - "兼职"

anti_crawl:
  min_delay: 3                   # 操作间最小延迟(秒)
  max_delay: 8                   # 操作间最大延迟(秒)
  max_retries: 3                 # 最大重试次数
  session_file: "data/boss_session.json"
  fallback_mode: "manual"        # manual | evening | disabled
  fallback_hour: 21              # 降级时间(晚上9点)

delivery:
  primary: "wecom"               # 企微应用消息
  fallback: "local_file"         # 本地文件
  output_dir: "data/job_output"  # 本地文件输出目录
```

---

## 五、实现顺序（推荐）

### Phase 1: 最小可用（1-2天）

```
1. resume_skill.py     — 简历解析（读PDF→结构化JSON，有现成prompt可参考summary_skill）
2. match_skill.py      — 匹配评分（纯DeepSeek API，不需要浏览器）
3. career_agent.py     — 主控（手动输入JD文本，匹配评分，终端输出结果）
```

验证标准：手动粘贴JD文本 → 得到匹配分 + 匹配理由

### Phase 2: 岗位搜索（2-3天，反爬是核心难点）

```
4. job_search_skill.py — BOSS直聘 Playwright搜索+详情抓取
5. job_filters.yaml    — 筛选条件配置
6. 反爬虫策略          — stealth.js + 行为模拟 + session管理
```

验证标准：自动搜索"财务产品经理" → 返回 ≥5 个岗位JD

### Phase 3: 简历+推送（1-2天）

```
7. resume_generator_skill.py — 个性化简历
8. greeting_skill.py          — 打招呼语
9. delivery_skill.py          — 企微推送
10. job_store.py               — SQLite去重+记录
```

验证标准：完整链路跑通，企微收到消息

### Phase 4: 定时调度（半天）

```
11. launchd plist 或 crontab
12. 反爬降级逻辑
13. --stats 历史查看
```

---

## 六、依赖与配置

### 新增 pip 依赖
```
pdfplumber          # PDF文本提取
playwright          # 已安装，浏览器的stealth模式需要 playwright-stealth
pyyaml              # job_filters.yaml 解析
```

### 新增 .env 配置（已有，无需新增）
```
DEEPSEEK_API_KEY     # 已有
WECOM_CORP_ID        # 已有，用于企微推送
WECOM_CORP_SECRET    # 已有
WECOM_AGENT_ID       # 已有，用于指定推送应用
```

---

## 七、测试用例

| 测试 | 输入 | 预期输出 |
|------|------|---------|
| T1 | `resume_skill("简历.pdf")` | 结构化JSON，含姓名/技能/经历 |
| T2 | `match_skill(resume, jd_text)` | 0-100分 + 维度分解 + 理由 |
| T3 | `job_search_skill.search("财务产品经理", "杭州")` | ≥5条JD |
| T4 | `resume_generator(resume, jd)` | 定制后简历，技能顺序调整 |
| T5 | `greeting_skill(resume, jd, match)` | 50-150字话术 |
| T6 | `delivery_skill.push(job_record)` | 企微收到卡片消息 |
| T7 | 同一岗位推送2次 | 第二次被去重过滤 |
| T8 | `career_agent.py` 完整运行 | 搜索→匹配→Top3→推送→记录 |
| T9 | BOSS触发验证码 | 提示用户手动干预 |
| T10 | `career_agent.py --stats` | 显示投递统计 |

---

## 八、给人类用户的准备清单

在 AI Agent 开始开发前，需要人类确认/提供：

- [x] 简历PDF → 已生成 `resume_profile.json`，**请人类review确认内容准确**
- [ ] `resume_profile.json` review通过后，job_search_skill 才能开始
- [ ] 首次运行 job_search_skill 时，需要人类在Playwright打开的浏览器中扫码登录BOSS
- [ ] 企微推送需要确认 WECOM_AGENT_ID=1000002 的应用有"发送消息"权限
