#!/usr/bin/env python3
"""
Recommendation Agent — 基于知识库的内部推荐系统（Layer 6）

流程: 兴趣画像 → 职业目标 → 候选召回 → 五维打分 → MMR精选 → 推送

用法:
  python src/agents/recommendation_agent.py --run              # 执行一次推荐
  python src/agents/recommendation_agent.py --dry-run           # 只看不存
  python src/agents/recommendation_agent.py --count 5           # 推荐5条（默认）
  python src/agents/recommendation_agent.py --stats             # 查看推荐统计
  python src/agents/recommendation_agent.py --install-launchd   # 安装定时任务
"""
import argparse
import json
import logging
import sys
import time
import uuid
from pathlib import Path

_BASE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_BASE_DIR / "src"))

from knowledge.sqlite_store import (
    get_recent_items,
    get_recently_recommended_item_ids,
    get_internal_recommendations,
    get_internal_recommendation_stats,
)
from models.deepseek_client import chat
from skills.interest_profile_skill import extract_profile
from skills.career_goal_skill import extract_career_goals
from skills.internal_recommendation_skill import score_candidates, select_top_k, generate_reasons
from skills.delivery_skill import (
    notify,
    notify_desktop,
    notify_internal_recommendations,
    save_internal_recommendations,
    format_internal_recommendation_message,
    print_internal_recommendations,
    notify_wecom_internal,
)
from skills.feedback_skill import record_batch_recommended, get_feedback_stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("recommendation_agent")


def _run_recommendation_cycle(dry_run: bool = False, count: int = 5) -> dict:
    """执行一次完整的推荐周期"""
    start = time.time()
    batch_id = str(uuid.uuid4())[:8]
    logger.info("=" * 50)
    logger.info(f"开始推荐周期 [batch={batch_id}]")

    # 1. 加载兴趣画像
    logger.info("[1/7] 分析知识库兴趣画像...")
    profile = extract_profile()
    logger.info(f"  主要兴趣: {[i['category'] for i in profile.get('top_interests', [])]}")
    logger.info(f"  偏好分类: {profile.get('preferred_categories', [])}")

    # 2. 加载职业目标
    logger.info("[2/7] 提取职业目标...")
    career_goals = extract_career_goals()
    logger.info(f"  岗位: {career_goals.get('role')}")
    logger.info(f"  领域: {career_goals.get('domains')}")
    logger.info(f"  目标技能: {career_goals.get('skills_to_build')}")

    # 3. 获取候选条目
    logger.info("[3/7] 召回候选条目...")
    all_items = get_recent_items(100)
    recently_rec_ids = get_recently_recommended_item_ids(days=7)

    candidates = [item for item in all_items if item["id"] not in recently_rec_ids]
    logger.info(f"  总条目: {len(all_items)}, 7天内已推荐: {len(recently_rec_ids)}, 候选: {len(candidates)}")

    if len(candidates) < count:
        logger.info(f"  候选不足，补充最近已推荐的条目")
        candidates = all_items

    # 4. 五维打分
    logger.info(f"[4/7] 五维打分（{len(candidates)} 条候选）...")
    feedback = get_feedback_stats(days=30)
    scored = score_candidates(candidates, profile, career_goals, feedback)
    scored = [s for s in scored if s["score"] >= 0.15]
    scored.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"  有效候选（score≥0.15）: {len(scored)} 条")

    if not scored:
        logger.info("无有效候选，周期结束")
        return {"recommended": 0, "batch_id": batch_id}

    # 5. MMR 精选
    logger.info(f"[5/7] MMR 精选 Top {count}...")
    selected = select_top_k(scored, k=count)

    # 生成推荐理由
    selected = generate_reasons(selected, career_goals)

    for i, item in enumerate(selected):
        logger.info(
            f"  #{i+1} [{item['score']:.2f}] {item.get('title', '')[:60]} "
            f"| content={item.get('_content_sim', 0):.2f} "
            f"career={item.get('_career_boost', 0):.2f} "
            f"recency={item.get('_recency', 0):.2f}"
        )

    # 6. 知识缺口分析
    logger.info("[6/7] 知识缺口分析...")
    gap_signals = _analyze_gaps(profile, career_goals)

    # 7. 推送
    logger.info("[7/7] 推送...")
    if not dry_run:
        saved = save_internal_recommendations(selected, batch_id, "scheduled", gap_signals)
        msg = format_internal_recommendation_message(selected)
        notify("📚 知识库今日精选", msg)
        logger.info(f"  已保存: {saved} 条")
        record_batch_recommended(selected, batch_id, context="scheduled")
    else:
        logger.info("  [DRY RUN] 跳过保存和通知")

    print_internal_recommendations(selected)

    elapsed = time.time() - start
    logger.info(f"周期完成，耗时 {elapsed:.1f}s，推荐 {len(selected)} 条")

    return {
        "recommended": len(selected),
        "batch_id": batch_id,
        "items": selected,
        "elapsed": round(elapsed, 1),
    }


def _analyze_gaps(profile: dict, career_goals: dict) -> list[dict] | None:
    """分析知识缺口，用于传递给 Discovery Agent"""
    try:
        prompt_path = _BASE_DIR / "prompts" / "gap_analysis_prompt.txt"
        with open(prompt_path, "r", encoding="utf-8") as f:
            system_prompt = f.read()
    except FileNotFoundError:
        logger.warning("gap_analysis_prompt.txt 未找到")
        return None

    from knowledge.sqlite_store import get_stats
    stats = get_stats()
    user_message = json.dumps({
        "profile": {
            "knowledge_gaps": profile.get("knowledge_gaps", []),
            "preferred_categories": profile.get("preferred_categories", []),
        },
        "career_goals": career_goals,
        "category_distribution": stats.get("categories", {}),
    }, ensure_ascii=False, indent=2)

    try:
        response = chat(system_prompt, user_message)
        cleaned = response.strip().strip("```json").strip("```").strip()
        result = json.loads(cleaned)
        gaps = result.get("gaps", [])
        if gaps:
            logger.info(f"  知识缺口: {len(gaps)} 个")
            for g in gaps[:3]:
                logger.info(f"    - {g.get('topic')}: {g.get('reason', '')[:60]}")
        return gaps
    except Exception as e:
        logger.warning(f"缺口分析失败: {e}")
        return None


def _show_stats():
    """显示内部推荐统计"""
    stats = get_internal_recommendation_stats()
    print(f"\n内部推荐系统统计:")
    print(f"  总推荐次数: {stats['total']}")
    print(f"  已推送: {stats['delivered']}")
    print(f"  平均评分: {stats['avg_score']}")

    feedback = get_feedback_stats(days=30)
    print(f"\n用户互动统计（近30天）:")
    print(f"  总互动: {feedback['total']}")
    for itype, cnt in feedback.get("by_type", {}).items():
        print(f"    {itype}: {cnt}")

    recent = get_internal_recommendations(limit=10)
    if recent:
        print(f"\n最近10条推荐:")
        for r in recent:
            print(f"  [{r['score']:.2f}] {r.get('item_id', '')[:8]} | {r.get('reason', '')[:80]}")


def _generate_plist_content() -> str:
    """生成 launchd plist 内容"""
    _d = str(_BASE_DIR)
    _py = str(_BASE_DIR / ".venv" / "bin" / "python3")
    _script = str(_BASE_DIR / "src" / "agents" / "recommendation_agent.py")
    _src = str(_BASE_DIR / "src")
    _log = str(_BASE_DIR / "logs" / "recommendation-agent.log")
    _err = str(_BASE_DIR / "logs" / "recommendation-agent.err")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
        '<plist version="1.0">',
        "<dict>",
        "    <key>Label</key>",
        "    <string>com.knowledge-agent.recommendation</string>",
        "    <key>ProgramArguments</key>",
        "    <array>",
        f"        <string>{_py}</string>",
        f"        <string>{_script}</string>",
        "        <string>--run</string>",
        "    </array>",
        "    <key>WorkingDirectory</key>",
        f"    <string>{_d}</string>",
        "    <key>EnvironmentVariables</key>",
        "    <dict>",
        f"        <key>PYTHONPATH</key><string>{_src}</string>",
        "    </dict>",
        "    <key>StandardOutPath</key>",
        f"    <string>{_log}</string>",
        "    <key>StandardErrorPath</key>",
        f"    <string>{_err}</string>",
        "    <key>StartCalendarInterval</key>",
        "    <array>",
        "        <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>",
        "    </array>",
        "    <key>RunAtLoad</key>",
        "    <false/>",
        "    <key>KeepAlive</key>",
        "    <false/>",
        "</dict>",
        "</plist>",
    ]
    return "\n".join(lines)


def _install_launchd():
    """安装 launchd 定时任务"""
    import subprocess
    plist_name = "com.knowledge-agent.recommendation.plist"
    dst = Path.home() / "Library" / "LaunchAgents" / plist_name
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(_generate_plist_content())
    subprocess.run(["launchctl", "load", str(dst)], check=False)
    print(f"  launchd 任务已安装: {dst}")
    print(f"  运行时间: 每天 08:00")
    print(f"  卸载: launchctl unload {dst}")


def main():
    parser = argparse.ArgumentParser(
        description="Recommendation Agent — 基于知识库的内部推荐系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python src/agents/recommendation_agent.py --run
  python src/agents/recommendation_agent.py --dry-run
  python src/agents/recommendation_agent.py --count 5
  python src/agents/recommendation_agent.py --stats
  python src/agents/recommendation_agent.py --install-launchd
        """,
    )
    parser.add_argument("--run", action="store_true", help="执行一次推荐周期")
    parser.add_argument("--dry-run", action="store_true", help="试运行（不保存、不通知）")
    parser.add_argument("--count", type=int, default=5, help="推荐条数，默认5")
    parser.add_argument("--stats", action="store_true", help="查看推荐统计")
    parser.add_argument("--install-launchd", action="store_true", help="安装每日8:00定时任务")
    parser.add_argument("--generate-plist", action="store_true", help="输出 plist 到 stdout")

    args = parser.parse_args()

    if args.stats:
        _show_stats()
        return

    if args.install_launchd:
        _install_launchd()
        return

    if args.generate_plist:
        print(_generate_plist_content())
        print("# 保存至: ~/Library/LaunchAgents/com.knowledge-agent.recommendation.plist")
        print("# 加载: launchctl load ~/Library/LaunchAgents/com.knowledge-agent.recommendation.plist")
        return

    if args.dry_run:
        logger.info("DRY RUN 模式 — 不会保存或推送")
        _run_recommendation_cycle(dry_run=True, count=args.count)
        return

    # 默认行为
    _run_recommendation_cycle(dry_run=False, count=args.count)


if __name__ == "__main__":
    main()
