#!/usr/bin/env python3
"""
Discovery Agent — 知识发现与推荐主编排器

流程: 兴趣画像 → 搜索词生成 → 全网搜索 → AI评分 → 去重 → 推送

用法:
  python src/agents/discovery_agent.py --run              # 执行一次发现
  python src/agents/discovery_agent.py --dry-run          # 只看不存
  python src/agents/discovery_agent.py --daemon           # 持续运行
  python src/agents/discovery_agent.py --stats            # 查看推荐统计
"""
import argparse
import json
import logging
import signal
import sys
import time
from pathlib import Path

# 确保 src 在 PYTHONPATH 中
_BASE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_BASE_DIR / "src"))

from models.deepseek_client import chat
from skills.interest_profile_skill import extract_profile
from skills.web_search_skill import search_web, enrich_results
from skills.recommendation_skill import score_results, deduplicate
from skills.delivery_skill import (
    notify,
    save_recommendations,
    print_recommendations,
    format_recommendation_message,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("discovery_agent")

# 全局开关，用于优雅退出
_running = True


def _signal_handler(signum, frame):
    global _running
    logger.info("收到退出信号，正在停止...")
    _running = False


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def _generate_search_queries(profile: dict) -> list[str]:
    """基于兴趣画像，用 DeepSeek 生成搜索词"""
    prompt_path = _BASE_DIR / "prompts" / "search_query_prompt.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    user_message = json.dumps(profile, ensure_ascii=False, indent=2)

    try:
        response = chat(system_prompt, user_message)
        cleaned = response.strip().strip("```json").strip("```").strip()
        result = json.loads(cleaned)
        queries = [q["query"] for q in result.get("queries", [])]
        logger.info(f"生成 {len(queries)} 个搜索词")
        for q in queries:
            logger.info(f"  → {q}")
        return queries
    except Exception as e:
        logger.warning(f"搜索词生成失败: {e}")
        # 降级：直接用兴趣分类名作为搜索词
        fallback = []
        for interest in profile.get("top_interests", [])[:3]:
            cat = interest.get("category", "")
            if cat:
                fallback.append(f"{cat} 最新资讯 2026")
        logger.info(f"降级搜索词: {fallback}")
        return fallback


def _run_discovery_cycle(dry_run: bool = False, fetch_content: bool = False,
                         push: bool = False,
                         use_gap_signals: bool = False) -> dict:
    """执行一次完整的发现周期"""
    start = time.time()
    logger.info("=" * 50)
    logger.info("开始知识发现周期")

    # 1. 提取兴趣画像
    logger.info("[1/6] 加载兴趣关键词画像...")
    try:
        from skills.keyword_profile_skill import load_profile, load_search_queries
        kw_profile = load_profile()
        logger.info(f"  摘要: {kw_profile.get('summary', '')[:80]}")
        logger.info(f"  关键词: {[k['term'] for k in kw_profile.get('keywords', [])[:8]]}")
    except Exception:
        kw_profile = None

    # 1.5 加载缺口信号
    gap_queries = []
    if use_gap_signals:
        gap_queries = _load_gap_signals()
        if gap_queries:
            logger.info(f"  已加载 {len(gap_queries)} 个缺口搜索词")

    # 2. 获取搜索词（优先用画像中的，降级用旧方法）
    logger.info("[2/6] 获取搜索词...")
    if kw_profile:
        queries = load_search_queries()
        profile = None  # 后续评分使用 kw_profile 信息
        if queries:
            logger.info(f"  从画像获取 {len(queries)} 个搜索词")
        else:
            profile = extract_profile()
            queries = _generate_search_queries(profile)
    else:
        profile = extract_profile()
        queries = _generate_search_queries(profile)
    queries.extend(gap_queries)
    if gap_queries:
        logger.info(f"  追加缺口搜索词: {gap_queries}")

    # 3. 全网搜索 + 固定内容源
    logger.info(f"[3/7] 全网搜索（{len(queries)} 个查询）...")
    search_results = search_web(queries, max_results_per_query=5)

    # 3.5 固定内容源
    logger.info("[3.5/7] 扫描固定内容源...")
    try:
        from skills.content_source_skill import scan_all_sources
        source_results = scan_all_sources()
        if source_results:
            search_results = list(search_results) + source_results
            logger.info(f"  固定源补充 {len(source_results)} 条")
    except Exception as e:
        logger.debug(f"固定源扫描失败: {e}")

    # 3.7 AI 内容生成（每天一篇原创文章）
    logger.info("[3.7/7] AI 原创内容生成...")
    try:
        from skills.claude_content_skill import generate_daily_article, get_recent_generated_titles
        recent_gen = get_recent_generated_titles(days=1)
        if recent_gen:
            logger.info(f"  今天已生成过，跳过（{recent_gen[0][:40]}）")
        else:
            ai_article = generate_daily_article(queries, recent_titles=recent_gen)
            if ai_article:
                # 保存到 SQLite + Chroma（复用 main.py 的存储逻辑）
                from skills.sqlite_skill import save_to_sqlite
                if save_to_sqlite(ai_article):
                    import threading
                    from skills.embedding_skill import embed_record
                    from knowledge.chroma_store import add_to_chroma
                    threading.Thread(
                        target=lambda: _save_ai_embedding(ai_article),
                        daemon=True,
                    ).start()
                # 加入搜索结果参与评分推送
                search_results.append({
                    "title": ai_article["title"],
                    "url": ai_article["source_path"],
                    "snippet": ai_article["summary"],
                    "source_query": "AI原创",
                })
                logger.info(f"  AI 生成: {ai_article['title'][:50]}")
    except Exception as e:
        logger.debug(f"AI 内容生成失败: {e}")

    if not search_results:
        logger.info("无搜索结果，周期结束")
        return {"discovered": 0, "queries": queries}

    logger.info(f"  获取 {len(search_results)} 条去重搜索结果")

    # 可选：抓取页面内容
    if fetch_content:
        logger.info("  抓取页面内容...")
        search_results = enrich_results(search_results, fetch_content=True)

    # 4. AI 评分
    logger.info(f"[4/6] AI 相关性评分...")
    if profile is None:
        profile = extract_profile()  # 确保有 profile 做评分
    scored = score_results(profile, search_results)
    logger.info(f"  评分≥60: {len(scored)} 条")

    if not scored:
        logger.info("无相关内容，周期结束")
        return {"discovered": 0, "queries": queries}

    # 5. 去重
    logger.info("[5/6] 去重检查...")
    new_items = deduplicate(scored)
    logger.info(f"  新内容: {len(new_items)} 条")

    # 6. 保存
    logger.info("[6/6] 保存结果...")
    if not dry_run and new_items:
        saved = save_recommendations(new_items, search_results, profile)
        if push:
            msg = format_recommendation_message(new_items)
            notify(f"🆕 发现 {len(new_items)} 条新内容", msg)
        else:
            logger.info(f"  已保存: {saved} 条（由 daily_digest 汇总推送）")
    elif dry_run:
        logger.info("  [DRY RUN] 跳过保存")

    # 终端输出
    print_recommendations(new_items)

    elapsed = time.time() - start
    logger.info(f"周期完成，耗时 {elapsed:.1f}s，发现 {len(new_items)} 条新推荐")

    return {
        "discovered": len(new_items),
        "queries": queries,
        "profile": profile,
        "elapsed": round(elapsed, 1),
    }


def _save_ai_embedding(record: dict):
    """后台保存 AI 生成内容的 embedding"""
    try:
        from skills.embedding_skill import embed_record
        from knowledge.chroma_store import add_to_chroma
        embedding = embed_record(record)
        add_to_chroma(record, embedding)
        from knowledge.sqlite_store import mark_embedded
        mark_embedded(record["id"])
    except Exception as e:
        logger.debug(f"AI 内容 embedding 失败: {e}")


def _load_gap_signals() -> list[str]:
    """从 Recommendation Agent 的最新输出中加载缺口搜索词"""
    try:
        from knowledge.sqlite_store import _get_conn
        conn = _get_conn()
        rows = conn.execute(
            """SELECT gap_signals FROM internal_recommendations
               WHERE gap_signals IS NOT NULL AND gap_signals != ''
               ORDER BY created_at DESC LIMIT 5"""
        ).fetchall()
        queries = []
        for row in rows:
            try:
                gaps = json.loads(row["gap_signals"])
                for g in gaps:
                    q = g.get("suggested_query", "")
                    if q and q not in queries:
                        queries.append(q)
            except (json.JSONDecodeError, TypeError):
                pass
        return queries
    except Exception as e:
        logger.warning(f"加载缺口信号失败: {e}")
        return []


def _show_stats():
    """显示推荐历史统计"""
    from knowledge.sqlite_store import get_recommendation_stats, get_recommendations

    stats = get_recommendation_stats()
    print(f"\n推荐系统统计:")
    print(f"  总推荐数: {stats['total']}")
    print(f"  已推送: {stats['delivered']}")
    print(f"  平均评分: {stats['avg_score']}")
    if stats.get("by_interest"):
        print(f"  按兴趣分布:")
        for cat, cnt in stats["by_interest"].items():
            print(f"    - {cat}: {cnt}")

    recent = get_recommendations(limit=10)
    if recent:
        print(f"\n最近10条推荐:")
        for r in recent:
            print(f"  [{r['score']}分] {r['title'][:70]}")
            print(f"    {r['url'][:100]}")


def _generate_plist_content() -> str:
    """生成 launchd plist 文件内容"""
    _d = str(_BASE_DIR)
    _py = str(_BASE_DIR / '.venv' / 'bin' / 'python3')
    _script = str(_BASE_DIR / 'src' / 'agents' / 'discovery_agent.py')
    _src = str(_BASE_DIR / 'src')
    _log = str(_BASE_DIR / 'logs' / 'discovery-agent.log')
    _err = str(_BASE_DIR / 'logs' / 'discovery-agent.err')
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
        '<plist version="1.0">',
        '<dict>',
        '    <key>Label</key>',
        '    <string>com.knowledge-agent.discovery</string>',
        '    <key>ProgramArguments</key>',
        '    <array>',
        f"        <string>{_py}</string>",
        f"        <string>{_script}</string>",
        '        <string>--run</string>',
        '    </array>',
        '    <key>WorkingDirectory</key>',
        f"    <string>{_d}</string>",
        '    <key>EnvironmentVariables</key>',
        '    <dict>',
        f"        <key>PYTHONPATH</key><string>{_src}</string>",
        '    </dict>',
        '    <key>StandardOutPath</key>',
        f"    <string>{_log}</string>",
        '    <key>StandardErrorPath</key>',
        f"    <string>{_err}</string>",
        '    <key>StartCalendarInterval</key>',
        '    <array>',
        '        <dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>0</integer></dict>',
        '        <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>0</integer></dict>',
        '    </array>',
        '    <key>RunAtLoad</key>',
        '    <false/>',
        '    <key>KeepAlive</key>',
        '    <false/>',
        '</dict>',
        '</plist>',
    ]
    return chr(10).join(lines)

def _print_plist():
    """输出 plist 配置"""
    print(_generate_plist_content())
    print("# 保存至: ~/Library/LaunchAgents/com.knowledge-agent.discovery.plist")
    print("# 加载: launchctl load ~/Library/LaunchAgents/com.knowledge-agent.discovery.plist")

def _install_launchd():
    """安装 launchd 定时任务"""
    import subprocess
    plist_name = "com.knowledge-agent.discovery.plist"
    dst = Path.home() / 'Library' / 'LaunchAgents' / plist_name
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(_generate_plist_content())
    subprocess.run(['launchctl', 'load', str(dst)], check=False)
    print(f"  launchd \u4efb\u52a1\u5df2\u5b89\u88c5: {dst}")
    print(f"  \u8fd0\u884c\u65f6\u95f4: \u6bcf\u5929 06:00, 18:00")
    print(f"  \u5378\u8f7d: launchctl unload {dst}")

def main():
    parser = argparse.ArgumentParser(
        description="Discovery Agent — 知识发现与推荐引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python src/agents/discovery_agent.py --run
  python src/agents/discovery_agent.py --dry-run
  python src/agents/discovery_agent.py --daemon --interval 3600
  python src/agents/discovery_agent.py --stats
        """,
    )
    parser.add_argument("--run", action="store_true", help="执行一次发现周期")
    parser.add_argument("--dry-run", action="store_true", help="试运行（不保存、不通知）")
    parser.add_argument("--daemon", action="store_true", help="持续运行模式")
    parser.add_argument("--interval", type=int, default=3600, help="守护模式间隔（秒），默认3600")
    parser.add_argument("--fetch-content", action="store_true", help="抓取搜索结果页面全文")
    parser.add_argument("--stats", action="store_true", help="查看推荐历史统计")
    parser.add_argument("--install-launchd", action="store_true", help="安装 macOS launchd 定时任务（每天 06:00/18:00）")
    parser.add_argument("--generate-plist", action="store_true", help="生成 launchd plist 文件到 stdout，不安装")
    parser.add_argument("--use-gap-signals", action="store_true", help="加载 Recommendation Agent 的缺口信号作为额外搜索词")
    parser.add_argument("--push", action="store_true", help="立即推送结果到微信（定时模式仅保存，由 daily_digest 汇总推送）")

    args = parser.parse_args()

    # 默认行为：无参数时等同 --run
    if not any([args.run, args.dry_run, args.daemon, args.stats]):
        args.run = True

    if args.stats:
        _show_stats()
        return

    if args.dry_run:
        logger.info("DRY RUN 模式 — 不会保存或推送")
        _run_discovery_cycle(dry_run=True, fetch_content=args.fetch_content,
                            use_gap_signals=args.use_gap_signals, push=args.push)
        return

    if args.run:
        _run_discovery_cycle(dry_run=False, fetch_content=args.fetch_content,
                            use_gap_signals=args.use_gap_signals, push=args.push)
        return

    if args.daemon:
        logger.info(f"守护模式启动，间隔 {args.interval}s")
        while _running:
            try:
                _run_discovery_cycle(dry_run=False, fetch_content=args.fetch_content,
                                    use_gap_signals=args.use_gap_signals, push=args.push)
            except Exception as e:
                logger.error(f"发现周期异常: {e}", exc_info=True)
            if _running:
                logger.info(f"等待 {args.interval}s 后下一轮...")
                for _ in range(args.interval):
                    if not _running:
                        break
                    time.sleep(1)
        logger.info("守护模式已退出")


if __name__ == "__main__":
    main()
