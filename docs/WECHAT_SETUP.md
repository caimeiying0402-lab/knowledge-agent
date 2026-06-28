# 企业微信接入指南 — P0 微信入口配置

## 概述

**目标**：在指定微信对话中发送文字 / 链接 / 图片，自动存入飞书多维表格知识库。
**方案**：企业微信自建应用 + Flask Webhook + Cloudflare Tunnel 内网穿透。
**耗时**：约 15 分钟完成全部配置。

---

## 第一步：注册企业微信（5 分钟）

> 如已有企业微信账号可跳过。

1. 打开 [https://work.weixin.qq.com](https://work.weixin.qq.com)，点击「企业注册」
2. 填写企业名称（可用个人名字）、行业随意选
3. 用手机微信扫码完成注册
4. 登录后台：[https://work.weixin.qq.com/wework_admin/frame](https://work.weixin.qq.com/wework_admin/frame)

---

## 第二步：创建自建应用

1. 后台左侧 → **应用管理** → **自建** → **创建应用**
2. 填写：
   - 应用名称：`知识收集助手`（随意）
   - 可见范围：选你自己
3. 创建完成后，记录：
   - `AgentID`（页面上显示）
   - `Secret`（点击「查看」后扫码获取）
4. 进入 **我的企业 → 企业信息**，记录 `企业ID`（CorpID）

---

## 第三步：配置接收消息回调

1. 进入刚创建的应用 → **接收消息** → 开启
2. 随机生成 Token 和 EncodingAESKey（点击「随机生成」即可）
3. **先不要填 URL**，把 Token / EncodingAESKey 记下来
4. 将以上信息填入 `config/.env`：

```bash
WECOM_CORP_ID=ww...
WECOM_CORP_SECRET=...
WECOM_AGENT_ID=1000003
WECOM_TOKEN=...         # 你生成的 Token
WECOM_AES_KEY=...       # 你生成的 43 位 AESKey
```

---

## 第四步：启动服务（一键）

```bash
cd /Users/caimeiying/AI-Agent-Lab/knowledge-agent
bash start_wechat.sh
```

脚本会自动完成：
1. 检查/安装依赖（flask、pycryptodome）
2. 首次运行自动下载 cloudflared（Cloudflare 内网穿透）
3. 预热 PaddleOCR 本地 OCR 引擎
4. 启动 Flask 服务（端口 5001）
5. 启动 Cloudflare 隧道并输出公网地址

成功后会看到类似：
```
=====================================================
  [隧道就绪] 公网地址:
  https://xxx-yyy-zzz.trycloudflare.com/wechat/callback

  把这个 URL 填到企业微信后台：
  应用管理 → 知识收集助手 → 接收消息 → 设置API接收
=====================================================
```

---

## 第五步：在企业微信后台填写回调 URL

1. 回到企业微信后台 → 应用 → 接收消息
2. URL 填写脚本输出的 `https://xxx.trycloudflare.com/wechat/callback`
3. 点击「保存」——企业微信会立即发 GET 请求验证
4. 显示「验证成功」即完成

---

## 第六步：在手机上使用

1. 手机打开企业微信
2. 工作台 → 找到「知识收集助手」
3. 直接发消息：
   - 发文字 → AI 提取摘要后存飞书
   - 发链接 → 抓取网页内容存飞书
   - 发图片 → PaddleOCR 本地识别后存飞书
4. 在个人微信中打开「企业微信」联系人也可以直接发消息

---

## 消息类型处理逻辑

| 消息类型 | 处理方式 | 飞书字段 source_type |
|---------|---------|---------------------|
| 纯文字  | 直接摘要 | `text` |
| 链接（含小程序分享） | 抓取 URL 网页内容 | `url` |
| 图片    | 下载 → PaddleOCR 本地识别 → 摘要 | `file` |
| 语音    | 暂不处理（日志记录） | — |

---

## 查看日志

```bash
tail -f /Users/caimeiying/AI-Agent-Lab/knowledge-agent/logs/wechat_webhook.log
```

---

## 常见问题

**Q：隧道 URL 重启会变吗？**
A：每次执行 `start_wechat.sh` 会生成新 URL，填入企业微信即可。Cloudflare 隧道基于 QUIC 协议，连接稳定不掉线，不像 SSH 隧道那样每 30 分钟断开。

**Q：验证 URL 一直失败怎么办？**
A：检查 (1) Flask 是否在跑 `curl localhost:5001/health` (2) `.env` 中 WECOM_TOKEN / WECOM_AES_KEY 是否填写正确。

**Q：图片 OCR 没有结果？**
A：检查 `config/.env` 中；PaddleOCR 本地引擎无需 API Key，模型保存在 `.paddleocr_cache/` 目录。
