"""每日汇总推送 — 合并知识库回顾 + 网络发现，一条消息

回顾部分：长文档按标题自动切片 → 兴趣画像排序 → 精选 TOP5 片段
发现部分：基于用户画像的网络搜索推荐
"""
import json
import logging
import os
import random
import re
import time
import yaml
from pathlib import Path
from skills.delivery_skill import notify_wechat_kf, notify_email

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent

# digest 展示参数
MAX_CHUNKS = 5           # 最多展示的片段数
MAX_CHARS_PER_CHUNK = 400  # 每个片段最多展示字数
MAX_CHARS_PER_BITABLE = 800  # 表格记录最多展示字数
MIN_CHUNK_CHARS = 30      # 少于这个字数的片段忽略


# ── 图片引用处理 ──

_IMG_EXT = r'heic|png|jpg|jpeg|gif|webp|bmp|svg|tiff|raw|mov|mp4'
_RE_BARE_IMG = re.compile(
    r'^[\w\d_\-]+\.(?:' + _IMG_EXT + r')\s*$',
    re.IGNORECASE | re.MULTILINE,
)
_RE_UUID_IMG = re.compile(
    r'^[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{12}\s*$',
    re.MULTILINE,
)
_RE_WECHAT_IMG = re.compile(
    r'^[Ww]echat[_\s]?[A-Za-z]*\d*\.(?:' + _IMG_EXT + r')\s*$',
    re.IGNORECASE | re.MULTILINE,
)
_RE_MD_IMG = re.compile(r'!\[.*?\]\(.*?\)')
_RE_IMG_URL = re.compile(
    r'https?://\S+\.(?:png|jpg|jpeg|gif|webp|svg|bmp|heic)(?:\?\S*)?',
    re.IGNORECASE,
)
_RE_BASE64 = re.compile(r'data:image/\S+;base64,[A-Za-z0-9+/=]+')
_RE_HTML_IMG = re.compile(r'<img[^>]*/?>')


def _count_image_refs(text: str) -> int:
    """统计文本中图片引用的数量"""
    count = 0
    for pattern in [_RE_BARE_IMG, _RE_UUID_IMG, _RE_WECHAT_IMG,
                    _RE_MD_IMG, _RE_IMG_URL, _RE_BASE64, _RE_HTML_IMG]:
        count += len(pattern.findall(text))
    return count


def _replace_image_refs(text: str) -> str:
    """替换图片引用为占位符"""
    text = _RE_BARE_IMG.sub('', text)
    text = _RE_UUID_IMG.sub('', text)
    text = _RE_WECHAT_IMG.sub('', text)
    text = _RE_MD_IMG.sub('', text)
    text = _RE_IMG_URL.sub('', text)
    text = _RE_BASE64.sub('', text)
    text = _RE_HTML_IMG.sub('', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── 文档切片 ──

# 标题候选：短行（<40字），不含句末标点，至少含一个中文字符或英文字母
_RE_HEADING_CANDIDATE = re.compile(
    r'^(?=.*[一-鿿A-Za-z])[^。，！？、；：」』）\)]{1,40}$'
)
_RE_MARKDOWN_H = re.compile(r'^#{1,3}\s+')  # markdown 标题
_RE_NUMBERED = re.compile(r'^\d+[\.\、\s]')
_RE_LIST = re.compile(r'^[-*•]\s')
_RE_CODE_BLOCK = re.compile(r'^```|^\s{4,}\S|^{\s*"|^\s*"\w+":')


def _chunk_document(text: str, doc_title: str, source_path: str = "",
                    max_chunk_size: int = 2500) -> list[dict]:
    """按标题（markdown + 隐式标题）将长文档切分为独立片段。

    两轮处理：
    1. 按标题边界切分
    2. 超过 max_chunk_size 的片段用段落拆分再切
    """
    text = _replace_image_refs(text)
    if not text:
        return []

    raw_chunks = _split_by_headings(text, doc_title)
    if not raw_chunks:
        return []

    # 递归拆分超大片段（段落级）
    final_chunks = []
    for ch in raw_chunks:
        ch_text = '\n'.join(ch['_lines'])
        if ch['char_count'] > max_chunk_size and ch['char_count'] > 500:
            sub_chunks = _split_oversized(ch_text, ch['title'], max_chunk_size)
            for sub in sub_chunks:
                final_chunks.append(_make_chunk(
                    sub['title'], '\n'.join(sub['_lines']), source_path))
        else:
            final_chunks.append(_make_chunk(ch['title'], ch_text, source_path))

    # 过滤 TOC/目录型片段
    result = []
    for ch in final_chunks:
        if not _is_toc(ch):
            result.append(ch)

    return result


def _split_oversized(text: str, fallback_title: str, max_size: int) -> list[dict]:
    """对超大片段做拆分。先按双换行分段，如果只有一个大段落则行级切分。"""
    paragraphs = re.split(r'\n\n+', text.strip())
    if len(paragraphs) <= 1:
        # 没有段落分隔，回退到行级标题检测（放宽 prev_empty 约束）
        return _split_by_headings_relaxed(text, fallback_title)

    chunks = []
    current_title = fallback_title
    current_paras = []
    current_size = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        para_size = len(para)

        first_line = para.split('\n')[0].strip()
        is_new_section = (
            len(first_line) <= 40
            and _RE_HEADING_CANDIDATE.match(first_line)
            and current_size > 200
        )

        if is_new_section and current_paras:
            chunks.append({
                'title': current_title,
                '_lines': '\n\n'.join(current_paras).split('\n'),
                'char_count': current_size,
            })
            current_title = first_line
            current_paras = [para]
            current_size = para_size
        elif current_size + para_size > max_size and current_paras:
            # 对超大的单个段落递归行级切分
            sub_chunks = _split_by_headings_relaxed(
                '\n\n'.join(current_paras), current_title)
            chunks.extend(sub_chunks)
            current_paras = [para]
            current_size = para_size
        else:
            current_paras.append(para)
            current_size += para_size

    if current_paras:
        if current_size > max_size * 2:
            sub_chunks = _split_by_headings_relaxed(
                '\n\n'.join(current_paras), current_title)
            chunks.extend(sub_chunks)
        else:
            chunks.append({
                'title': current_title,
                '_lines': '\n\n'.join(current_paras).split('\n'),
                'char_count': current_size,
            })

    return chunks


def _split_by_headings_relaxed(text: str, fallback_title: str) -> list[dict]:
    """行级切分：任何符合条件的短行都视为标题边界（不要求前有空行）。

    用于处理无段落分隔的密集文本（如纯文本笔记连续换行）。
    """
    lines = text.split('\n')
    chunks = []
    current_title = fallback_title
    current_lines = []
    first_real_line = True

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if current_lines and current_lines[-1] != '':
                current_lines.append('')
            continue

        md_match = _RE_MARKDOWN_H.match(stripped)
        if md_match:
            if current_lines:
                chunks.append({
                    'title': current_title,
                    '_lines': current_lines[:],
                    'char_count': sum(len(l) for l in current_lines if l),
                })
            current_title = stripped[md_match.end():].strip()
            current_lines = []
            first_real_line = False
            continue

        if _RE_NUMBERED.match(stripped) or _RE_LIST.match(stripped):
            current_lines.append(line)
            first_real_line = False
            continue

        # 放宽条件：任何短行都可能成为标题（不要求 prev_empty）
        is_heading = (
            len(stripped) <= 40
            and _RE_HEADING_CANDIDATE.match(stripped)
            and not first_real_line  # 不全文档第一行当标题
            and len(current_lines) > 1  # 已有内容
        )

        if is_heading:
            chunk_text = '\n'.join(current_lines).strip()
            if len(chunk_text) >= MIN_CHUNK_CHARS:
                chunks.append({
                    'title': current_title,
                    '_lines': current_lines[:],
                    'char_count': sum(len(l) for l in current_lines if l),
                })
            current_title = stripped
            current_lines = []
        else:
            current_lines.append(line)

        first_real_line = False

    if current_lines:
        chunks.append({
            'title': current_title,
            '_lines': current_lines[:],
            'char_count': sum(len(l) for l in current_lines if l),
        })

    return chunks


def _split_by_headings(text: str, fallback_title: str) -> list[dict]:
    """按标题行切分文本，返回 {title, _lines, char_count} 列表"""
    lines = text.split('\n')
    chunks = []
    current_title = fallback_title
    current_lines = []
    prev_empty = True

    for line in lines:
        stripped = line.strip()

        # 空行
        if not stripped:
            prev_empty = True
            if current_lines and current_lines[-1] != '':
                current_lines.append('')
            continue

        # markdown 标题（## 或 ###）
        md_match = _RE_MARKDOWN_H.match(stripped)
        if md_match:
            heading_text = stripped[md_match.end():].strip()
            if current_lines:
                chunks.append({
                    'title': current_title,
                    '_lines': current_lines[:],
                    'char_count': sum(len(l) for l in current_lines if l),
                })
            current_title = heading_text or stripped
            current_lines = []
            prev_empty = False
            continue

        # 跳过纯序号/列表标记
        if _RE_NUMBERED.match(stripped) or _RE_LIST.match(stripped):
            current_lines.append(line)
            prev_empty = False
            continue

        # 隐式标题检测
        is_heading = (
            len(stripped) <= 40
            and prev_empty
            and _RE_HEADING_CANDIDATE.match(stripped)
            and len(current_lines) > 0  # 不是全文第一行
        )

        if is_heading:
            chunks.append({
                'title': current_title,
                '_lines': current_lines[:],
                'char_count': sum(len(l) for l in current_lines if l),
            })
            current_title = stripped
            current_lines = []
        else:
            current_lines.append(line)

        prev_empty = False

    # 最后一个
    if current_lines:
        chunks.append({
            'title': current_title,
            '_lines': current_lines[:],
            'char_count': sum(len(l) for l in current_lines if l),
        })

    return chunks


def _make_chunk(title: str, text: str, source_path: str) -> dict:
    """构建标准 chunk 结构"""
    img_count = _count_image_refs(text)
    # 统计代码行比例
    code_lines = sum(1 for l in text.split('\n') if _RE_CODE_BLOCK.match(l))
    total_lines = max(len(text.split('\n')), 1)
    return {
        'title': title,
        'content': text,
        'char_count': len(text),
        'image_count': img_count,
        'code_ratio': code_lines / total_lines,
        'source_path': source_path,
    }


def _is_toc(chunk: dict) -> bool:
    """检测是否为目录/元信息型片段（大量短标题行，无实质内容）"""
    lines = [l for l in chunk['content'].split('\n') if l.strip()]
    if not lines:
        return True
    short_lines = sum(1 for l in lines if len(l.strip()) <= 30)
    if len(lines) <= 5:
        return short_lines / len(lines) > 0.8 and chunk['char_count'] < 200
    return short_lines / len(lines) > 0.75 and chunk['char_count'] < 300


# ── 兴趣评分 ──

def _load_profile() -> dict:
    """加载兴趣画像"""
    profile_path = BASE_DIR / "data" / "interest_profile.json"
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _score_chunks(chunks: list[dict], profile: dict) -> list[dict]:
    """片段评分：统一基础分 + 只保留惩罚项，不偏向任何主题。"""
    keywords = profile.get("keywords", [])

    for ch in chunks:
        # 统一基础分，不偏好任何主题
        score = 1.0
        matched = []

        # 仅记录匹配关键词用于展示，不参与评分
        text = ch['title'] + ' ' + ch['content']
        for kw in keywords:
            term = kw.get("term", "")
            if ' ' in term or '与' in term or '和' in term:
                parts = re.split(r'[\s与和]', term)
                hits = sum(1 for p in parts if p and p in text)
                if hits >= len(parts) * 0.5:
                    matched.append(term)
            else:
                if term in text:
                    matched.append(term)

        # 惩罚项
        if ch.get('image_count', 0) > 3:
            score *= 0.3
        elif ch.get('image_count', 0) > 0:
            score *= 0.7
        if ch.get('code_ratio', 0) > 0.3:
            score *= 0.5

        ch['score'] = round(score, 2)
        ch['matched_keywords'] = matched

    chunks.sort(key=lambda c: c['score'], reverse=True)
    return chunks


def _truncate_chunk(text: str, max_chars: int = MAX_CHARS_PER_CHUNK) -> str:
    """截断片段到合适长度，在句末或换行处断"""
    if len(text) <= max_chars:
        return text
    cut = text.rfind('\n', 0, max_chars)
    if cut < max_chars // 2:
        cut = text.rfind('。', 0, max_chars)
    if cut < max_chars // 2:
        cut = text.rfind('；', 0, max_chars)
    if cut < max_chars // 2:
        cut = max_chars
    return text[:cut] + "\n…"


# ── 推送历史去重 ──

_DIGEST_HISTORY_FILE = BASE_DIR / "data" / "digest_history.json"
_HISTORY_WINDOW_DAYS = 5  # 5 天内推送过的片段大幅降权


def _load_delivered_keys() -> set:
    """加载最近 N 天已推送的片段标识 (source_title#title)"""
    try:
        with open(_DIGEST_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cutoff = int(time.time()) - _HISTORY_WINDOW_DAYS * 86400
        return {
            entry["key"]
            for entry in data.get("history", [])
            if entry.get("ts", 0) > cutoff
        }
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _record_delivered_chunks(chunks: list[dict]):
    """记录本次推送的片段，保留最近 14 天"""
    try:
        with open(_DIGEST_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"history": []}

    cutoff = int(time.time()) - 14 * 86400
    history = [h for h in data.get("history", []) if h.get("ts", 0) > cutoff]

    now = int(time.time())
    for ch in chunks:
        key = f"{ch.get('source_title', '')}#{ch.get('title', '')}"
        history.append({"key": key, "ts": now})

    try:
        with open(_DIGEST_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"history": history}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug(f"记录推送历史失败: {e}")


def _temperature_sample(chunks: list[dict], k: int, temperature: float = 0.6) -> list[dict]:
    """温度采样：高分优先，但低分片段也有机会入选。

    temperature → 0 时趋近于 greedy top-k；
    temperature → 1 时趋近于均匀随机；
    默认 0.6 兼顾相关性与多样性。
    """
    if len(chunks) <= k:
        return chunks

    scores = [max(c.get("score", 0), 0.01) for c in chunks]
    adjusted = [s ** (1 / temperature) for s in scores]
    total = sum(adjusted)
    probs = [a / total for a in adjusted]

    available = list(range(len(chunks)))
    selected = []
    for _ in range(min(k, len(chunks))):
        avail_probs = [probs[i] for i in available]
        s = sum(avail_probs)
        if s > 0:
            avail_probs = [p / s for p in avail_probs]
        idx = random.choices(available, weights=avail_probs, k=1)[0]
        selected.append(idx)
        available.remove(idx)

    return [chunks[i] for i in selected]


# ── 飞书配置 ──

def _load_feishu_sources() -> list[dict]:
    """读取飞书同步配置"""
    config_path = BASE_DIR / "config" / "feishu_sources.yaml"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        return config.get("sources", [])
    except FileNotFoundError:
        return []


def _get_source_records(conn) -> list[dict]:
    """从知识库中查找属于配置的飞书文档的记录"""
    sources = _load_feishu_sources()
    if not sources:
        return []

    from skills.feishu_skill import _extract_token_from_url

    records = []
    seen_tokens = set()

    for src in sources:
        url = src.get("url", "").strip()
        if not url:
            continue
        info = _extract_token_from_url(url)
        token = info.get("token", "")
        url_type = info.get("type", "")
        if not token or token in seen_tokens:
            continue
        seen_tokens.add(token)

        pattern = f"%{token}%"
        rows = conn.execute(
            """SELECT id, title, raw_content, full_content, summary, category,
                      source_type, source_path, created_at
               FROM knowledge_items
               WHERE source_path LIKE ? AND raw_content IS NOT NULL AND raw_content != ''
               ORDER BY created_at DESC""",
            (pattern,),
        ).fetchall()

        for row in rows:
            records.append({
                "id": row["id"],
                "title": row["title"] or "",
                "raw_content": row["raw_content"] or row["full_content"] or row["summary"] or "",
                "category": row["category"] or "",
                "source_type": row["source_type"] or "",
                "source_path": row["source_path"] or url,  # 保留原始 URL 用于生成链接
                "url_type": url_type,
            })

    return records


# ── 主入口 ──

def _push_digest_to_portal(items: list[dict]) -> bool:
    """将 digest 结构化数据推送到 Cloudflare Worker，供 Web 门户展示"""
    load_dotenv(BASE_DIR / "config" / ".env")
    worker_url = os.getenv("CF_WORKER_URL", "").rstrip("/")
    api_key = os.getenv("CF_SYNC_API_KEY", "")
    if not worker_url or not api_key:
        logger.debug("CF_WORKER_URL 或 CF_SYNC_API_KEY 未配置，跳过门户推送")
        return False

    try:
        resp = requests.post(
            f"{worker_url}/api/digest/push",
            json={"items": items},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        logger.info(f"门户 digest 推送成功: {len(items)} 条")
        return True
    except Exception as e:
        logger.warning(f"门户 digest 推送失败: {e}")
        return False


def send_daily_digest() -> bool:
    from knowledge.sqlite_store import (
        get_recommendations, _get_conn,
    )
    import time

    today_start = int(time.time()) - 86400
    conn = _get_conn()

    # ── 1. 知识库回顾：长文档切片 + 兴趣排序 ──
    source_records = _get_source_records(conn)
    profile = _load_profile()

    # ── 2. 网络发现：外部推荐 ──
    # 直接查数据库按时间取最近 48 小时，避免被老高分推荐挤掉
    cutoff_time = int(time.time()) - 2 * 86400
    rows = conn.execute(
        """SELECT id, url, title, snippet, score, reason, category_match,
                  interest_category, source_query, full_content, recommended_at
           FROM recommendations
           WHERE delivered=1 AND recommended_at > ?
           ORDER BY recommended_at DESC LIMIT 30""",
        (cutoff_time,),
    ).fetchall()
    ext_recent = [dict(r) for r in rows]

    if not source_records and not ext_recent:
        logger.info("今日无内容，跳过汇总推送")
        return False

    lines = ["📋 AIOS 每日精选\n"]

    # ── 回顾部分 ──
    if source_records:
        lines.append("━━━ 📖 知识库回顾 ━━━")

        wiki_records = [r for r in source_records if r["url_type"] in ("wiki", "docx", "doc")]
        bitable_records = [r for r in source_records if r["url_type"] == "bitable"]

        # Wiki 长文档：切片 + 评分排序 → 只展示 TOP 片段
        all_chunks = []
        top_chunks = []
        for rec in wiki_records:
            chunks = _chunk_document(
                rec["raw_content"], rec["title"],
                source_path=rec["source_path"],
            )
            for ch in chunks:
                ch["source_title"] = rec["title"]
                ch["source_path"] = rec["source_path"]
            all_chunks.extend(chunks)

        if all_chunks:
            scored = _score_chunks(all_chunks, profile)

            # ── 去重与随机化选择 ──
            # 1. 历史推送过的片段大幅降权（7 天内）
            delivered_keys = _load_delivered_keys()
            for ch in scored:
                key = f"{ch.get('source_title', '')}#{ch.get('title', '')}"
                if key in delivered_keys:
                    ch['score'] *= 0.05  # 已推送过 → 降权 95%

            # 2. 构建足够大的候选池（top 20），不再限制"同一文档最多一个"
            candidate_pool = scored[:20]

            # 3. 温度采样：temperature=0.8 让低分片段有更高概率入选
            top_chunks = _temperature_sample(candidate_pool, MAX_CHUNKS, temperature=0.8)

            # 4. 记录本次推送（用于下次去重）
            _record_delivered_chunks(top_chunks)

            shown_titles = set()
            for i, ch in enumerate(top_chunks):
                title = ch['title'][:80]
                score = ch['score']
                img_count = ch.get('image_count', 0)
                source_title = ch.get('source_title', '')

                # 相关性标记
                if score >= 0.8:
                    star = "🔥"
                elif score >= 0.5:
                    star = "⭐"
                elif score >= 0.2:
                    star = "📌"
                else:
                    star = "💡"

                # 标题去重（同一文档可能有相似标题的片段）
                content_preview = _truncate_chunk(ch['content'])

                if img_count > len(content_preview.split('\n')) * 0.4:
                    # 图片密集型：只显示摘要 + 链接
                    lines.append(f"\n{star} {title} ({source_title})")
                    lines.append(f"   🖼️ 含 {img_count} 张图，原文链接 →")
                else:
                    lines.append(f"\n{star} {title} ({source_title})")
                    for cline in content_preview.split('\n'):
                        lines.append(f"   {cline.rstrip()}")

                # 匹配关键词（可选展示）
                matched = ch.get('matched_keywords', [])
                if matched and score >= 0.3:
                    lines.append(f"   🏷️ {', '.join(matched[:3])}")

                shown_titles.add(ch['title'])

            # 如果有多篇文档的片段都没入选，提示可查看原文
            all_doc_titles = {r['title'] for r in wiki_records}
            covered = {ch.get('source_title', '') for ch in top_chunks}
            missing = all_doc_titles - covered
            if missing:
                lines.append(f"\n📎 另有「{'」「'.join(missing)}」可查看原文")
            lines.append("")

        # Bitable 记录：随机采样 5 条，避免每天重复
        if bitable_records:
            lines.append("\n📊 知识条目")
            random.shuffle(bitable_records)
            for rec in bitable_records[:5]:
                title = rec["title"][:80]
                raw = rec["raw_content"]
                cat = rec["category"]
                content = _replace_image_refs(raw)
                if len(content) > MAX_CHARS_PER_BITABLE:
                    content = content[:MAX_CHARS_PER_BITABLE] + "\n…"
                lines.append(f"\n   ▸ {title} [{cat}]")
                for cline in content.split('\n'):
                    lines.append(f"     {cline.rstrip()}")

    # ── 网络发现部分 ──
    if ext_recent:
        if source_records:
            lines.append("")
        lines.append("━━━ 🆕 网络发现 ━━━")
        for r in ext_recent[:3]:
            score = r.get("score", 0)
            star = "⭐" if score >= 80 else "🔵" if score >= 70 else "📎"
            title = r.get("title", "")[:60]
            url = r.get("url", "")
            reason = r.get("reason", "")[:120]
            lines.append(f"\n{star} [{score}分] {title}")
            if reason:
                lines.append(f"   💡 {reason}")
            if url:
                lines.append(f"   🔗 {url[:200]}")

    body = "\n".join(lines)

    # 收集结构化数据用于 Web 门户展示
    portal_items = []
    # 1) 外部发现：有 URL 和评分的推荐
    for r in ext_recent[:5]:
        score = r.get("score", 0)
        portal_items.append({
            "id": r.get("id", r.get("url", "")),
            "title": r.get("title", "")[:120],
            "url": r.get("url", ""),
            "score": score / 100.0 if score > 1 else score,
            "reason": r.get("reason", "")[:200],
            "category": r.get("interest_category", r.get("category_match", "")),
        })
    # 2) 知识库精选片段（复用上面已采样后的 top_chunks）
    if top_chunks:
        seen_titles = set()
        for ch in top_chunks:
            t = ch.get("title", "")[:120]
            if t in seen_titles:
                continue
            seen_titles.add(t)
            portal_items.append({
                "id": (ch.get("source_path", "") + "#" + t)[:200],
                "title": t,
                "url": ch.get("source_path", ""),
                "score": ch.get("score", 0),
                "reason": ", ".join(ch.get("matched_keywords", [])[:3]),
                "category": "知识库回顾",
            })
    if bitable_records:
        for rec in bitable_records[:5]:
            portal_items.append({
                "id": rec.get("id", ""),
                "title": rec.get("title", "")[:120],
                "url": rec.get("source_path", ""),
                "score": 0.5,
                "reason": rec.get("category", ""),
                "category": "知识条目",
            })

    # 优先企微，超过2000字或企微失败走邮件
    pushed = False
    if len(body) <= 2000:
        if notify_wechat_kf("📋 AIOS 每日精选", body):
            logger.info("每日汇总推送成功（微信客服）")
            pushed = True

    if not pushed:
        if notify_email("📋 AIOS 每日精选", body):
            logger.info(f"每日汇总推送成功（邮件，{len(body)}字）")
            pushed = True

    # 推送到 Web 门户
    if portal_items:
        _push_digest_to_portal(portal_items)

    if not pushed:
        logger.warning("每日汇总推送失败：微信和邮件均未成功")
    return pushed
