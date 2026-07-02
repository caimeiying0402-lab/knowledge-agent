"""Job Agent 主控 — Phase 2: 岗位搜索 + 匹配评分 → 终端输出"""
import json
import argparse
import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

BASE_DIR = Path(__file__).parent.parent.parent
RESUME_PATH = BASE_DIR / "src" / "agents" / "resume_profile.json"


def load_resume() -> dict:
    with open(RESUME_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_match(args):
    """手动输入JD → 匹配评分 → 终端输出"""
    from skills.match_skill import match

    resume = load_resume()

    if args.jd_file:
        with open(args.jd_file, "r", encoding="utf-8") as f:
            jd_text = f.read()
    else:
        print("=" * 60)
        print("  Job Agent — 岗位匹配引擎")
        print("=" * 60)
        name = resume.get("personal", {}).get("name", "未知")
        yrs = resume.get("personal", {}).get("years_of_experience", "未知")
        loc = resume.get("personal", {}).get("target_location", "未知")
        print(f"  简历: {name} ({yrs})")
        print(f"  目标: {loc} / 财务产品经理")
        print("-" * 60)
        print("  请粘贴JD文本，输入完成后输入 EOF 结束：")
        print("-" * 60)
        lines = []
        while True:
            try:
                line = input()
                if line.strip() == "EOF":
                    break
                lines.append(line)
            except EOFError:
                break
        jd_text = "\n".join(lines)

    if not jd_text.strip():
        print("❌ JD文本为空，退出")
        return 1

    print("\n🔍 正在匹配评分...")
    result = match(resume, jd_text)

    score = result.get("score", 0)
    suggestion = result.get("suggestion", "")
    overall = result.get("overall_assessment", "")

    if score >= 80:
        color_start, color_end = "\033[92m", "\033[0m"
    elif score >= 60:
        color_start, color_end = "\033[93m", "\033[0m"
    else:
        color_start, color_end = "\033[91m", "\033[0m"

    print(f"\n{'=' * 60}")
    print(f"  匹配结果: {color_start}{score}分 — {suggestion}{color_end}")
    print(f"  {overall}")
    print(f"{'=' * 60}")

    breakdown = result.get("breakdown", {})
    labels = [
        ("领域匹配度", "domain", 30),
        ("技能匹配度", "skill", 25),
        ("经验年限匹配", "experience", 20),
        ("行业匹配度", "industry", 15),
        ("项目亮点匹配", "highlights", 10),
    ]
    for label, key, total in labels:
        print(f"  {label}:     {breakdown.get(key, 0)}/{total}")
    print(f"{'=' * 60}")

    match_points = result.get("match_points", [])
    if match_points:
        print(f"\n✅ 匹配点 ({len(match_points)}条):")
        for p in match_points:
            print(f"   • {p}")

    gap_points = result.get("gap_points", [])
    if gap_points:
        print(f"\n⚠️ 差距点 ({len(gap_points)}条):")
        for p in gap_points:
            print(f"   • {p}")

    print(f"\n{'=' * 60}")
    return 0


def cmd_search_only(args):
    """搜索岗位列表 + 匹配评分"""
    from skills.job_search_skill import search_jobs, get_job_detail, load_filters
    from skills.match_skill import match

    resume = load_resume()
    config = load_filters()
    keywords = config.get("search", {}).get("keywords", [])

    print("=" * 60)
    print("  Job Agent — 岗位搜索 + 匹配")
    print("=" * 60)

    engine = args.engine or "manual"
    print(f"  引擎: {engine}")
    print(f"  关键词: {', '.join(keywords[:3])}...")
    print(f"  最大结果: {args.max_results}")
    print("=" * 60)

    print("\n🔍 正在搜索岗位...")
    try:
        details = search_jobs(keywords=keywords, engine=engine, max_results=args.max_results)
    except Exception as e:
        print(f"❌ 搜索失败: {e}")
        return 1

    if not details:
        print("⚠️ 未找到岗位")
        return 0

    print(f"\n✅ 搜索到 {len(details)} 个岗位")
    print("=" * 60)

    # 逐一匹配评分
    scored = []
    for i, d in enumerate(details):
        print(f"\n[{i+1}/{len(details)}] {d.title} @ {d.company}")
        if d.salary:
            print(f"    💰 {d.salary}")

        if d.jd_text:
            print("    🔍 正在匹配评分...")
            result = match(resume, d.jd_text)
            score = result.get("score", 0)
            suggestion = result.get("suggestion", "")
            print(f"    匹配结果: {score}分 — {suggestion}")
            scored.append((score, d, result))
        else:
            print("    ⚠️ 无JD详情，跳过匹配")
            scored.append((0, d, None))

    # 按分数排序
    scored.sort(key=lambda x: x[0], reverse=True)

    print("\n" + "=" * 60)
    print("  📊 Top 匹配结果")
    print("=" * 60)
    for i, (score, d, result) in enumerate(scored[:5]):
        print(f"\n  #{i+1} {d.title} @ {d.company} — {score}分")
        if d.salary:
            print(f"     💰 {d.salary}")
        if d.url:
            print(f"     🔗 {d.url}")
        if result:
            mp = result.get("match_points", [])
            gp = result.get("gap_points", [])
            if mp:
                print(f"     ✅ {mp[0]}")
            if gp:
                print(f"     ⚠️ {gp[0]}")

    return 0


def cmd_stats(args):
    db_path = BASE_DIR / "data" / "job_tracker.db"
    print("📊 投递统计功能将在 Phase 3 实现")
    print(f"   数据文件: {db_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Job Agent — 简历×岗位JD自动匹配系统"
    )
    parser.add_argument("--schedule", action="store_true", help="定时模式 (Phase 4)")
    parser.add_argument("--search-only", action="store_true", help="仅搜索+匹配")
    parser.add_argument("--engine", type=str, default=None,
                        choices=["manual", "playwright", "scraping"],
                        help="搜索引擎 (默认 manual)")
    parser.add_argument("--max-results", type=int, default=20)
    parser.add_argument("--stats", action="store_true", help="查看历史投递记录")
    parser.add_argument("--jd-file", type=str, help="从文件读取JD文本")

    args, remaining = parser.parse_known_args()

    if args.stats:
        return cmd_stats(args)
    elif args.schedule:
        print("⏰ 定时调度功能将在 Phase 4 实现")
        return 0
    elif args.search_only:
        return cmd_search_only(args)
    else:
        return cmd_match(args)


if __name__ == "__main__":
    sys.exit(main())
