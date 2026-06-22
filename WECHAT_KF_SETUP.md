# 微信客服接入指南（方案B · 主动拉取）

## 概述

个人微信用户通过「富婆OS客服」发消息 → 你的电脑自动拉取 → AI摘要 → 飞书入库。

**方案B 优势（相比回调推送）：**
- ✅ 不需要 Cloudflare 隧道 / 内网穿透
- ✅ 不需要配置企业微信后台的回调 URL
- ✅ 不需要公网 IP
- ✅ 电脑重启后自动恢复，URL 永不变

## 快速开始

### 1. 确认配置 `config/.env`

必须配置的变量：
```bash
WECOM_CORP_ID=ww039ee325a51bc124        # 企业ID
WECOM_CORP_SECRET=rAHqa_asYhmglRKtG...   # 自建应用 Secret
WECOM_KF_OPEN_ID=wkRDNiaQAAROMxoll1...  # 客服账号 OpenKfId（⚠️ 不是 kf_id！）
```

> **如何获取 OpenKfId？**
> 方法 A：运行 `python -c "from skills.wechat_kf_poller import *; ..."` 调用 API 自动获取（见代码注释）
> 方法 B：管理后台 → 微信客服 → 客服账号详情页 → OpenKfId 字段
>
> ⚠️ 注意：OpenKfId 格式为 `wk` 开头（如 `wkRDNiaQAAROMxoll1UnMyW28byKS8Eg`），不是 `kfc` 开头的 kf_id！

### 2. 启动服务

```bash
cd knowledge-agent
bash start_wechat.sh poller    # 仅启动微信客服轮询
# 或
bash start_wechat.sh all      # 同时启动自建应用 + 客服轮询（推荐）
```

启动后终端显示：
```
=====================================================
  Knowledge Agent - 微信接入服务
  模式: poller
=====================================================

[启动] 微信客服消息轮询服务（方案B·主动拉取）...
  ✅ 不需要内网穿透
  ✅ 不需要配置回调 URL
[就绪] 微信客服轮询服务已启动 (PID=xxxxx)
```

### 3. 发送测试消息

1. 打开 **微信 APP**
2. 搜索 **「富婆OS客服」** 或扫客服二维码进入会话
3. 发送一条消息（文字/图片/链接）
4. 观察终端日志输出：
   ```
   [KF-ETL 开始] text from xxxxxxxxxx @ 2026-06-21 22:35:00
   [KF-ETL 完成] title=用户消息的AI摘要标题
   ```
5. 打开飞书多维表格查看结果

## 后台运行（推荐长期使用）

```bash
nohup bash start_wechat.sh poller > /dev/null 2>&1 &
echo $! > data/.kf_poller.pid
```

停止：
```bash
kill $(cat data/.kf_poller.pid) 2>/dev/null
```

## 支持的消息类型

| 类型 | 处理方式 |
|------|---------|
| 文字 | 直接进入 ETL（ingest → summarize → feishu）|
| 图片 | 下载临时素材 → PaddleOCR 识别 → ETL |
| 链接 | 提取 URL → ingestion_skill 抓取内容 → ETL |
| 文件 | 下载 → 按 URL/文本处理 |

## 常见问题

### Q: sync_msg 返回 48002 api forbidden？
**A:** 确认你的自建应用已在「微信客服 → 可调用API的自建应用」列表中。位置：管理后台 → 微信客服 → 企业内部开发。

### Q: sync_msg 返回 95000 invalid open_kfid？
**A:** 你填的是 kf_id（`kfc53007d57d4293a31`），不是 open_kfid（`wkRDNiaQAAROMxoll1UnMyW28byKS8Eg`）。通过 API 获取正确的值：
```bash
python3 -c "
import requests, os
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path('config/.env'))
r = requests.get(f'https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={os.getenv(\"WECOM_CORP_ID\")}&corpsecret={os.getenv(\"WECOM_CORP_SECRET\")}', timeout=10, proxies={'http':None,'https':None})
token = r.json()['access_token']
r2 = requests.post(f'https://qyapi.weixin.qq.com/cgi-bin/kf/account/list?access_token={token}', json={'offset':0,'limit':10}, timeout=10, proxies={'http':None,'https':None})
for acc in r2.json().get('account_list', []):
    print(f'{acc[\"name\"]}: {acc[\"open_kfidf\"]}')
"
```
