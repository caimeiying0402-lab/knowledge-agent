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
    """全链路：搜索岗位 → 匹配评分 → TOP 3 → 简历定制 + 打招呼"""
    from skills.job_search_skill import search_jobs, load_filters
    from skills.match_skill import match
    from skills.resume_customize_skill import batch_customize

    resume = load_resume()
    config = load_filters()
    keywords = config.get("search", {}).get("keywords", [])

    print("=" * 60)
    print("  Job Agent — 搜索 → 匹配 → TOP3 → 定制")
    print("=" * 60)

    engine = args.engine or "cdp"
    print(f"  引擎: {engine}")
    print(f"  关键词: {', '.join(keywords[:5])}")
    print(f"  最大结果: {args.max_results}")
    print("=" * 60)

    # ═══ Step 1: 搜索岗位 ═══
    print(f"\n🔍 [1/4] 正在搜索岗位 (平台: {args.platform})...")
    details = []

    # BOSS搜索
    if args.platform in ("boss", "both"):
        try:
            boss_results = search_jobs(keywords=keywords, engine=engine, max_results=args.max_results)
            details.extend(boss_results)
            print(f"  BOSS: {len(boss_results)} 个岗位")
        except Exception as e:
            print(f"  ⚠️ BOSS搜索失败: {e}")

    # 猎聘搜索
    if args.platform in ("liepin", "both"):
        try:
            from skills.liepin_search_skill import search_liepin
            liepin_raw = search_liepin(keywords, max_results=args.max_results)
            from skills.job_search_skill import JobDetail
            for r in liepin_raw:
                details.append(JobDetail(
                    title=r["title"], company=r["company"],
                    jd_text=f"{r['title']} | {r.get('salary','')} | {r.get('location','')} | {r.get('experience','')} | {r.get('education','')}",
                    salary=r.get("salary", ""), location=r.get("location", ""),
                    url=r.get("url", ""),
                    experience_years=r.get("experience", ""),
                    education=r.get("education", ""),
                    platform="liepin",
                ))
            print(f"  猎聘: {len(liepin_raw)} 个岗位")
        except Exception as e:
            print(f"  ⚠️ 猎聘搜索失败: {e}")

    if not details:
        print("⚠️ 未找到岗位")
        return 0
    print(f"✅ 共搜索到 {len(details)} 个岗位")

    if not details:
        print("⚠️ 未找到岗位")
        return 0
    print(f"✅ 搜索到 {len(details)} 个岗位")

    # ═══ Step 2: 匹配评分 ═══
    print(f"\n🔍 [2/4] 正在匹配评分...")
    scored = []
    for i, d in enumerate(details):
        if d.jd_text:
            result = match(resume, d.jd_text)
            score = result.get("score", 0)
            scored.append((score, d, result))
        else:
            scored.append((0, d, None))
        if (i + 1) % 5 == 0:
            print(f"  已完成 {i+1}/{len(details)}...")

    scored.sort(key=lambda x: x[0], reverse=True)
    top3 = scored[:3]
    print(f"✅ 匹配完成，TOP 3 最高分: {top3[0][0] if top3 else 0}")

    # ═══ Step 3: TOP 3 展示 ═══
    print("\n" + "=" * 60)
    print("  📊 TOP 3 匹配岗位")
    print("=" * 60)
    for i, (score, d, result) in enumerate(top3):
        star = "⭐" if score >= 80 else "🔵" if score >= 65 else "📎"
        print(f"\n  #{i+1} {star} {d.title} @ {d.company} — {score}分")
        if d.salary:
            print(f"     💰 {d.salary}")
        if d.url:
            print(f"     🔗 {d.url[:100]}")
        if result:
            for mp in (result.get("match_points") or [])[:2]:
                print(f"     ✅ {mp}")
            for gp in (result.get("gap_points") or [])[:1]:
                print(f"     ⚠️ {gp}")

    # ═══ Step 4: 简历定制 + 打招呼 ═══
    if args.no_customize:
        print("\n⏭️  跳过简历定制 (--no-customize)")
        return 0

    print(f"\n🔍 [3/4] 正在为 TOP 3 生成个性化简历+打招呼语...")
    customized = batch_customize(resume, top3)

    print("\n" + "=" * 60)
    print("  ✨ TOP 3 — 个性化简历摘要 + 打招呼语")
    print("=" * 60)

    for i, c in enumerate(customized):
        print(f"\n{'─' * 50}")
        print(f"  📌 #{i+1} [{c['score']}分] {c['title']} @ {c['company']}")
        if c.get("jd_type"):
            print(f"     岗位类型: {c['jd_type']}")
        if c.get("customized_summary"):
            print(f"\n  📝 个性化简历摘要:")
            print(f"     {c['customized_summary'][:500]}")
        if c.get("greeting"):
            print(f"\n  💬 打招呼语:")
            print(f"     {c['greeting'][:400]}")
        if c.get("jd_keyword_gaps"):
            print(f"\n  ⚠️ 能力差距:")
            for gap in c["jd_keyword_gaps"][:3]:
                print(f"     - {gap}")

    # ═══ 汇总 ═══
    print(f"\n{'=' * 60}")
    print(f"  ✅ 全链路完成!")
    print(f"     搜索: {len(details)} 个岗位")
    print(f"     匹配: {len(scored)} 个评分")
    print(f"     定制: {len(customized)} 份简历+打招呼")

    # ═══ 保存到文件 ═══
    import time as _time
    output_dir = BASE_DIR / "data" / "job_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = _time.strftime("%Y%m%d_%H%M%S")

    # 保存 TOP 3 汇总 markdown
    summary_path = output_dir / f"top3_summary_{ts}.md"
    lines = [
        f"# TOP 3 岗位匹配结果",
        f"",
        f"生成时间: {_time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"搜索关键词: {', '.join(keywords[:5])}",
        f"搜索岗位数: {len(details)}",
        f"",
    ]
    for i, c in enumerate(customized):
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## #{i+1} [{c['score']}分] {c['title']} @ {c['company']}")
        lines.append(f"")
        if c.get('salary'):
            lines.append(f"**薪资:** {c['salary']}")
        if c.get('url'):
            lines.append(f"**链接:** {c['url']}")
        if c.get('jd_type'):
            lines.append(f"**岗位类型:** {c['jd_type']}")
        lines.append(f"")
        if c.get('match_points'):
            lines.append(f"### ✅ 匹配点")
            for mp in c['match_points'][:5]:
                lines.append(f"- {mp}")
        if c.get('gap_points'):
            lines.append(f"")
            lines.append(f"### ⚠️ 差距点")
            for gp in c['gap_points'][:5]:
                lines.append(f"- {gp}")
        if c.get('customized_summary'):
            lines.append(f"")
            lines.append(f"### 📝 个性化简历摘要")
            lines.append(f"")
            lines.append(c['customized_summary'])
        if c.get('greeting'):
            lines.append(f"")
            lines.append(f"### 💬 打招呼语")
            lines.append(f"")
            lines.append(c['greeting'])
        if c.get('jd_keyword_gaps'):
            lines.append(f"")
            lines.append(f"### 🔍 能力差距分析")
            for gap in c['jd_keyword_gaps']:
                lines.append(f"- {gap}")
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"     输出文件: {summary_path}")

    # 单独保存每份简历的定制摘要（方便复制粘贴投递）
    for i, c in enumerate(customized):
        job_path = output_dir / f"job_{i+1}_{c['company']}_{ts}.md"
        job_lines = [
            f"# {c['title']} @ {c['company']}",
            f"匹配分数: {c['score']}分 | {c.get('jd_type', '')}",
            f"薪资: {c.get('salary', '未知')}",
            f"",
            f"## 个性化简历摘要",
            f"",
            c.get('customized_summary', ''),
            f"",
            f"## 打招呼语",
            f"",
            c.get('greeting', ''),
        ]
        job_path.write_text("\n".join(job_lines), encoding="utf-8")

    print(f"{'=' * 60}")
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
    parser.add_argument("--search-only", action="store_true", help="搜索+匹配+TOP3+定制简历")
    parser.add_argument("--no-customize", action="store_true", help="跳过简历定制（仅搜索+匹配）")
    parser.add_argument("--engine", type=str, default=None,
                        choices=["manual", "playwright", "scraping", "cdp"],
                        help="搜索引擎 (默认 manual，推荐 cdp)")
    parser.add_argument("--max-results", type=int, default=20)
    parser.add_argument("--platform", type=str, default="boss",
                        choices=["boss", "liepin", "both"],
                        help="搜索平台 (默认 boss)")
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
