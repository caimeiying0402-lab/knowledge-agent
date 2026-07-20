#!/usr/bin/env python3
"""AIOS Dashboard — 单文件，零依赖，双击 .command 即可启动"""
import json
import os
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE_DIR = Path(__file__).parent
SRC_DIR = BASE_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

AGENTS = {
    "career": {
        "name": "Career Agent",
        "desc": "岗位搜索(BOSS+猎聘) + AI匹配 + 简历定制",
        "cmd": [sys.executable, "-m", "agents.career_agent", "--search-only",
                "--engine", "cdp", "--platform", "both", "--max-results", "15"],
        "timeout": 300,
        "color": "#3fb950",
    },
    "recommendation": {
        "name": "Knowledge Recommendation",
        "desc": "知识库五维打分 + MMR精选TOP5",
        "cmd": [sys.executable, "-m", "agents.recommendation_agent", "--run"],
        "timeout": 120,
        "color": "#58a6ff",
    },
    "digest": {
        "name": "Daily Digest",
        "desc": "飞书同步 + 知识回顾 + 网络发现 → 邮件推送",
        "cmd": [sys.executable, "-c",
                "import logging; logging.basicConfig(level=logging.INFO, "
                "format='%(asctime)s [%(name)s] %(levelname)s: %(message)s');"
                "from skills.daily_digest_skill import send_daily_digest; "
                "send_daily_digest()"],
        "timeout": 120,
        "color": "#a371f7",
    },
}

# ── Job Store ──
_jobs = {}
_job_lock = threading.Lock()
HTML_PATH = BASE_DIR / "dashboard.html"


def build_html():
    """内嵌 HTML，按钮调用 /api/run/<agent> 后轮询 /api/status/<job>"""
    cards_html = ""
    for aid, cfg in AGENTS.items():
        cards_html += f"""
        <div class="card" onclick="runAgent('{aid}')" id="card-{aid}">
            <div class="card-dot" style="background:{cfg['color']}"></div>
            <div class="card-title">{cfg['name']}</div>
            <div class="card-desc">{cfg['desc']}</div>
            <button class="btn" id="btn-{aid}">▶ 运行</button>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AIOS Control Panel</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'SF Pro', sans-serif;
       background:#0d1117; color:#c9d1d9; padding:24px; min-height:100vh; }}
h1 {{ font-size:1.5rem; margin-bottom:8px; }}
.sub {{ color:#8b949e; font-size:0.85rem; margin-bottom:24px; }}
.grid {{ display:flex; gap:16px; flex-wrap:wrap; margin-bottom:24px; }}
.card {{ background:#161b22; border:1px solid #30363d; border-radius:8px;
         padding:20px; flex:1; min-width:220px; cursor:pointer; transition: all .2s; }}
.card:hover {{ border-color:#58a6ff; }}
.card-dot {{ width:10px; height:10px; border-radius:50%; margin-bottom:12px; }}
.card-title {{ font-size:1.1rem; font-weight:600; margin-bottom:6px; }}
.card-desc {{ font-size:0.8rem; color:#8b949e; margin-bottom:14px; }}
.btn {{ width:100%; padding:8px 0; border:none; border-radius:6px;
        font-size:0.9rem; cursor:pointer; color:#fff; background:#238636; }}
.btn:disabled {{ opacity:.5; cursor:default; }}
.output {{ display:none; background:#0d1117; border:1px solid #30363d;
          border-radius:8px; padding:16px; }}
.output-header {{ display:flex; justify-content:space-between; margin-bottom:8px; }}
.output-title {{ font-weight:600; }}
.output-status {{ font-size:0.85rem; }}
.output-text {{ background:#010409; padding:12px; border-radius:6px;
                 font-family:'SF Mono',Monaco,monospace; font-size:0.78rem;
                 line-height:1.5; max-height:400px; overflow-y:auto;
                 white-space:pre-wrap; word-break:break-all; color:#7ee787; }}
.spin {{ animation:spin 1s linear infinite; }}
@keyframes spin {{ from{{transform:rotate(0deg)}} to{{transform:rotate(360deg)}} }}
</style>
</head>
<body>
<h1>AIOS Control Panel</h1>
<div class="sub">点击卡片运行 Agent，无需终端</div>
<div class="grid">{cards_html}</div>
<div class="output" id="output">
    <div class="output-header">
        <span class="output-title" id="out-title"></span>
        <span class="output-status" id="out-status"></span>
    </div>
    <pre class="output-text" id="out-text"></pre>
</div>

<script>
let currentJob = null, timer = null;

async function runAgent(id) {{
    const btn = document.getElementById('btn-' + id);
    btn.disabled = true; btn.textContent = '⏳ ...';
    document.getElementById('out-title').textContent = '';
    document.getElementById('out-status').innerHTML = '<span style="color:#d2991d">⏳</span>';
    document.getElementById('out-text').textContent = 'Starting...';
    document.getElementById('output').style.display = 'block';

    const res = await fetch('/api/run/' + id, {{method:'POST'}});
    const data = await res.json();
    currentJob = data.job_id;
    document.getElementById('out-title').textContent = data.agent_name;
    timer = setInterval(pollJob, 1000);
}}

async function pollJob() {{
    if (!currentJob) return;
    const res = await fetch('/api/status/' + currentJob);
    const job = await res.json();
    const textEl = document.getElementById('out-text');
    const statusEl = document.getElementById('out-status');

    textEl.textContent = job.output || '';
    textEl.scrollTop = textEl.scrollHeight;

    if (job.status === 'done') {{
        statusEl.innerHTML = '<span style="color:#3fb950">✅</span>';
        clearInterval(timer); resetBtn(job.agent);
    }} else if (job.status === 'failed') {{
        statusEl.innerHTML = '<span style="color:#f85149">❌ exit=' + job.exit_code + '</span>';
        clearInterval(timer); resetBtn(job.agent);
    }} else if (job.status === 'timeout') {{
        statusEl.innerHTML = '<span style="color:#f85149">⏰ Timeout</span>';
        clearInterval(timer); resetBtn(job.agent);
    }} else if (job.status === 'error') {{
        statusEl.innerHTML = '<span style="color:#f85149">❌ Error</span>';
        clearInterval(timer); resetBtn(job.agent);
    }}
}}

function resetBtn(id) {{
    const btn = document.getElementById('btn-' + id);
    if (btn) {{ btn.disabled = false; btn.textContent = '▶ 运行'; }}
}}
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静默

    def _send(self, status, content, ctype="application/json"):
        body = json.dumps(content, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = urlparse(self.path)
        if p.path == "/" or p.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(build_html().encode())
        elif p.path.startswith("/api/status/"):
            job_id = p.path.split("/")[-1]
            with _job_lock:
                job = _jobs.get(job_id)
            if job:
                self._send(200, job)
            else:
                self._send(404, {"error": "not found"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.startswith("/api/run/"):
            agent_id = self.path.split("/")[-1]
            if agent_id not in AGENTS:
                return self._send(404, {"error": f"unknown: {agent_id}"})

            job_id = uuid.uuid4().hex[:10]
            with _job_lock:
                _jobs[job_id] = {
                    "id": job_id, "agent": agent_id, "status": "running",
                    "agent_name": AGENTS[agent_id]["name"],
                    "output": f"[{time.strftime('%H:%M:%S')}] {AGENTS[agent_id]['name']}...\n",
                    "exit_code": None,
                }

            t = threading.Thread(target=_run, args=(job_id, agent_id), daemon=True)
            t.start()
            self._send(200, {"job_id": job_id, "agent_name": AGENTS[agent_id]["name"]})
        else:
            self._send(404, {})  # ← 修复: 确保函数不会返回 None

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()


def _run(job_id, agent_id):
    cfg = AGENTS[agent_id]
    try:
        proc = subprocess.run(
            cfg["cmd"], capture_output=True, text=True,
            timeout=cfg["timeout"], cwd=str(BASE_DIR),
            env={**os.environ, "PYTHONPATH": str(SRC_DIR)},
        )
        output = proc.stdout + proc.stderr
        status = "done" if proc.returncode == 0 else "failed"
        ec = proc.returncode
    except subprocess.TimeoutExpired:
        output = f"\n[{time.strftime('%H:%M:%S')}] 超时 ({cfg['timeout']}s)\n"
        status, ec = "timeout", None
    except Exception as e:
        output = f"\n错误: {e}\n"
        status, ec = "error", None

    with _job_lock:
        _jobs[job_id]["output"] += output
        _jobs[job_id]["status"] = status
        _jobs[job_id]["exit_code"] = ec


def main():
    port = int(os.environ.get("DASHBOARD_PORT", "5099"))
    server = HTTPServer(("0.0.0.0", port), Handler)

    print(f"""
╔══════════════════════════════════════════╗
║       AIOS Control Panel                ║
║                                        ║
║  → http://localhost:{port}                ║
║  → Press Ctrl+C to stop                ║
╚══════════════════════════════════════════╝
""")
    webbrowser.open(f"http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBye.")
        server.shutdown()


if __name__ == "__main__":
    main()
