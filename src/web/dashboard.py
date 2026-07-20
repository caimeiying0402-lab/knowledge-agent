"""Knowledge Agent Dashboard — 作品集展示网站 + Agent 手动触发"""
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

# 确保 src 在路径中
_BASE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_BASE_DIR / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [dashboard] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))


# ── 页面路由 ──

@app.route("/")
def index():
    return render_template("dashboard.html")


# ── API 路由 ──

@app.route("/api/stats")
def api_stats():
    try:
        from knowledge.sqlite_store import get_stats
        from knowledge.chroma_store import get_chroma_stats

        sqlite_stats = get_stats()
        chroma_stats = get_chroma_stats()
        rec_stats = {}
        try:
            from knowledge.sqlite_store import get_recommendation_stats
            rec_stats = get_recommendation_stats()
        except Exception:
            pass

        return jsonify({
            "knowledge": sqlite_stats,
            "chroma": chroma_stats,
            "recommendations": rec_stats,
            "timestamp": int(time.time()),
        })
    except Exception as e:
        logger.warning(f"/api/stats 失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/knowledge")
def api_knowledge():
    try:
        from knowledge.sqlite_store import get_recent_items
        limit = request.args.get("limit", 20, type=int)
        offset = request.args.get("offset", 0, type=int)
        items = get_recent_items(limit + offset)
        return jsonify({
            "items": items[offset:offset + limit],
            "total": len(items),
            "limit": limit,
            "offset": offset,
        })
    except Exception as e:
        logger.warning(f"/api/knowledge 失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/knowledge/search")
def api_knowledge_search():
    try:
        q = request.args.get("q", "")
        if not q:
            return jsonify({"items": []})
        from knowledge.rag_retriever import hybrid_search
        results = hybrid_search(q, top_k=10)
        return jsonify({"items": results, "query": q})
    except Exception as e:
        logger.warning(f"/api/knowledge/search 失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/categories")
def api_categories():
    try:
        from knowledge.sqlite_store import get_stats
        stats = get_stats()
        categories = stats.get("categories", {})
        return jsonify({
            "categories": [
                {"name": k, "count": v}
                for k, v in sorted(categories.items(), key=lambda x: -x[1])
            ]
        })
    except Exception as e:
        logger.warning(f"/api/categories 失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/timeline")
def api_timeline():
    try:
        from knowledge.sqlite_store import _get_conn
        conn = _get_conn()
        rows = conn.execute(
            """SELECT DATE(created_at, 'unixepoch') as date, COUNT(*) as cnt
               FROM knowledge_items
               GROUP BY date
               ORDER BY date ASC"""
        ).fetchall()
        timeline = [{"date": r["date"], "count": r["cnt"]} for r in rows]
        return jsonify({"timeline": timeline})
    except Exception as e:
        logger.warning(f"/api/timeline 失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/recommendations")
def api_recommendations():
    try:
        from knowledge.sqlite_store import get_recommendations
        limit = request.args.get("limit", 20, type=int)
        items = get_recommendations(limit=limit)
        return jsonify({"items": items, "total": len(items)})
    except Exception as e:
        logger.warning(f"/api/recommendations 失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/internal-recommendations")
def api_internal_recommendations():
    try:
        from knowledge.sqlite_store import get_internal_recommendations
        limit = request.args.get("limit", 20, type=int)
        items = get_internal_recommendations(limit=limit)
        return jsonify({"items": items, "total": len(items)})
    except Exception as e:
        logger.warning(f"/api/internal-recommendations 失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/interactions")
def api_interactions():
    try:
        from knowledge.sqlite_store import get_interactions
        limit = request.args.get("limit", 50, type=int)
        item_id = request.args.get("item_id")
        items = get_interactions(item_id=item_id, limit=limit)
        return jsonify({"items": items, "total": len(items)})
    except Exception as e:
        logger.warning(f"/api/interactions 失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/interact", methods=["POST"])
def api_interact():
    try:
        from skills.feedback_skill import record_interaction
        data = request.get_json() or {}
        ok = record_interaction(
            item_id=data.get("item_id", ""),
            interaction_type=data.get("type", "read"),
            batch_id=data.get("batch_id"),
            score=data.get("score"),
            context=data.get("context"),
        )
        return jsonify({"ok": ok})
    except Exception as e:
        logger.warning(f"/api/interact 失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/career-goals")
def api_career_goals():
    try:
        from skills.career_goal_skill import extract_career_goals
        goals = extract_career_goals()
        return jsonify(goals)
    except Exception as e:
        logger.warning(f"/api/career-goals 失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/recommendations/stats")
def api_recommendation_stats():
    try:
        from knowledge.sqlite_store import get_recommendation_stats
        stats = get_recommendation_stats()
        return jsonify(stats)
    except Exception as e:
        logger.warning(f"/api/recommendations/stats 失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/system")
def api_system():
    import platform
    db_path = _BASE_DIR / "data" / "knowledge.db"
    chroma_path = _BASE_DIR / "data" / "chroma_db"

    db_size = os.path.getsize(db_path) if db_path.exists() else 0
    chroma_size = 0
    if chroma_path.exists():
        for f in chroma_path.rglob("*"):
            if f.is_file():
                chroma_size += os.path.getsize(f)

    return jsonify({
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "db_size_mb": round(db_size / 1024 / 1024, 2),
        "chroma_size_mb": round(chroma_size / 1024 / 1024, 2),
        "project_root": str(_BASE_DIR),
    })


# ── Agent 手动触发 ──

_jobs: dict[str, dict] = {}  # job_id → {status, output, error, started_at, finished_at}
_job_lock = threading.Lock()

AGENT_CONFIG = {
    "career": {
        "name": "Career Agent",
        "description": "岗位搜索+匹配评分+简历定制",
        "command": [
            sys.executable, "-m", "agents.career_agent",
            "--search-only", "--engine", "cdp", "--platform", "both", "--max-results", "15"
        ],
        "timeout": 300,
    },
    "recommendation": {
        "name": "Knowledge Recommendation",
        "description": "知识库回顾+五维打分+MMR精选TOP5",
        "command": [sys.executable, "-m", "agents.recommendation_agent", "--run"],
        "timeout": 120,
    },
    "digest": {
        "name": "Daily Digest",
        "description": "飞书同步+知识库回顾+网络发现 → 邮件推送",
        "command": [
            sys.executable, "-c",
            "import logging; logging.basicConfig(level=logging.INFO, "
            "format='%(asctime)s [%(name)s] %(levelname)s: %(message)s');"
            "from skills.daily_digest_skill import send_daily_digest; "
            "send_daily_digest()"
        ],
        "timeout": 120,
    },
}


def _run_agent_job(job_id: str, agent_id: str):
    config = AGENT_CONFIG[agent_id]
    with _job_lock:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["output"] = f"[{time.strftime('%H:%M:%S')}] 开始执行: {config['name']}...\n"

    try:
        proc = subprocess.run(
            config["command"],
            capture_output=True, text=True,
            timeout=config["timeout"],
            cwd=str(_BASE_DIR),
            env={**os.environ, "PYTHONPATH": str(_BASE_DIR / "src")},
        )
        output = proc.stdout + proc.stderr
        with _job_lock:
            _jobs[job_id]["output"] += output
            _jobs[job_id]["status"] = "done" if proc.returncode == 0 else "failed"
            _jobs[job_id]["exit_code"] = proc.returncode
            _jobs[job_id]["finished_at"] = time.time()
            status_text = "完成" if proc.returncode == 0 else f"失败 (exit={proc.returncode})"
            _jobs[job_id]["output"] += f"\n[{time.strftime('%H:%M:%S')}] {status_text}\n"
    except subprocess.TimeoutExpired:
        with _job_lock:
            _jobs[job_id]["status"] = "timeout"
            _jobs[job_id]["output"] += f"\n[{time.strftime('%H:%M:%S')}] 超时 ({config['timeout']}s)\n"
            _jobs[job_id]["finished_at"] = time.time()
    except Exception as e:
        with _job_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["output"] += f"\n错误: {e}\n"
            _jobs[job_id]["finished_at"] = time.time()


@app.route("/api/run/<agent_id>", methods=["POST"])
def api_run_agent(agent_id):
    if agent_id not in AGENT_CONFIG:
        return jsonify({"error": f"Unknown agent: {agent_id}"}), 404

    job_id = uuid.uuid4().hex[:12]
    with _job_lock:
        _jobs[job_id] = {
            "id": job_id,
            "agent": agent_id,
            "status": "pending",
            "output": "",
            "started_at": time.time(),
            "finished_at": None,
            "exit_code": None,
        }

    t = threading.Thread(target=_run_agent_job, args=(job_id, agent_id), daemon=True)
    t.start()

    return jsonify({"job_id": job_id, "agent": agent_id, "status": "started"})


@app.route("/api/run/<job_id>/status")
def api_run_status(job_id):
    with _job_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "id": job["id"],
        "agent": job["agent"],
        "status": job["status"],
        "output": job["output"],
        "exit_code": job["exit_code"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
    })


# ── 启动 ──

if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", "5000"))
    print(f"\n  Knowledge Agent Dashboard")
    print(f"  → http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
