"""Knowledge Agent Dashboard — 作品集展示网站"""
import json
import logging
import os
import sys
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request

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


# ── 启动 ──

if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", "5000"))
    print(f"\n  Knowledge Agent Dashboard")
    print(f"  → http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
