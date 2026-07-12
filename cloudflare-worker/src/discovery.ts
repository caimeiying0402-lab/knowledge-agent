/**
 * Discovery Agent — Cloudflare Worker 版
 * 定时知识发现：分析知识库 → 生成搜索词 → 全网搜索 → AI评分 → 去重 → 入库
 * 
 * 触发器: 每天 06:00, 18:00（UTC+8 对应 UTC 22:00, 10:00）
 * 手动触发: POST /api/discovery/run
 * 查看状态: GET  /api/discovery/stats
 */

interface Env {
  DB: D1Database;
  DEEPSEEK_API_KEY: string;
  WECOM_CORP_ID: string;
  WECOM_CORP_SECRET: string;
  SYNC_API_KEY?: string;
}

interface SearchResult {
  title: string;
  url: string;
  snippet: string;
  source_query: string;
}

interface ScoredItem {
  title: string;
  url: string;
  snippet: string;
  score: number;
  reason: string;
  category: string;
  source_query: string;
}

interface Profile {
  top_interests: Array<{ category: string; tags: string[]; weight: number; reason: string }>;
  preferred_categories: string[];
  knowledge_gaps: string[];
  interest_summary: string;
}

export async function discoveryScheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext) {
    console.log(`[discovery] Cron triggered at ${new Date().toISOString()}`);
    ctx.waitUntil(runDiscovery(env).catch(e => console.error('[discovery] Failed:', e)));
}

export async function discoveryFetch(req: Request, env: Env): Promise<Response> {
  const url = new URL(req.url);
  if (url.pathname === '/api/discovery/run' && req.method === 'POST') {
    const result = await runDiscovery(env);
    return corsJson(result);
  }
  if (url.pathname === '/api/discovery/stats') {
    return corsJson(await getStats(env));
  }
  if (url.pathname === '/api/discovery/profile') {
    return corsJson(await buildProfile(env));
  }
  return new Response('not found', { status: 404 });
}

// ── Main ──

async function runDiscovery(env: Env): Promise<any> {
  const start = Date.now();
  const log: string[] = [];
  const logMsg = (s: string) => { console.log(s); log.push(s); };

  logMsg(`[discovery] Starting cycle...`);

  // 1. Build profile
  logMsg(`[1/5] Building profile...`);
  const profile = await buildProfile(env);
  logMsg(`  interests: ${profile.top_interests.map(i => i.category).join(', ')}`);

  // 2. Generate search queries
  logMsg(`[2/5] Generating queries...`);
  const queries = await generateQueries(profile, env);
  logMsg(`  queries: ${queries.join(', ')}`);

  // 3. Search web
  logMsg(`[3/5] Searching web...`);
  const results = await searchWeb(queries, env);
  logMsg(`  results: ${results.length}`);

  if (results.length === 0) {
    logMsg(`No search results, ending cycle.`);
    return { ok: true, discovered: 0, duration: Date.now() - start, log };
  }

  // 4. Score with AI
  logMsg(`[4/5] Scoring with AI...`);
  const scored = await scoreResults(profile, results, env);
  logMsg(`  scored ≥60: ${scored.length}`);

  if (scored.length === 0) {
    logMsg(`No relevant content, ending cycle.`);
    return { ok: true, discovered: 0, duration: Date.now() - start, log };
  }

  // 5. Deduplicate & save
  logMsg(`[5/5] Deduplicating & saving...`);
  const newItems = await deduplicate(scored, env);
  logMsg(`  new items: ${newItems.length}`);

  if (newItems.length > 0) {
    await saveToD1(newItems, env);
    logMsg(`  saved to D1`);
  }

  return { ok: true, discovered: newItems.length, duration: Date.now() - start, log };
}

// ── Profile ──

async function buildProfile(env: Env): Promise<Profile> {
  // Try to get categories from knowledge_items (if synced from local)
  try {
    const rows = await env.DB.prepare(
      `SELECT category, COUNT(*) as cnt FROM knowledge_items GROUP BY category ORDER BY cnt DESC LIMIT 10`
    ).all();

    if (rows.results && rows.results.length > 0) {
      const interests: Profile['top_interests'] = [];
      for (const row of rows.results) {
        const cat = (row as any).category || '其他';
        const cnt = (row as any).cnt || 0;
        interests.push({
          category: cat, tags: [cat],
          weight: Math.min(100, cnt * 20),
          reason: `知识库中有 ${cnt} 条关于 ${cat} 的内容`,
        });
      }
      return {
        top_interests: interests.slice(0, 6),
        preferred_categories: interests.slice(0, 4).map(i => i.category),
        knowledge_gaps: [],
        interest_summary: interests.slice(0, 3).map(i => i.category).join('、'),
      };
    }
  } catch (e) {
    console.warn('[profile] knowledge_items table not available:', e);
  }

  // Fallback: use default interests based on user's known preferences
  return getDefaultProfile();
}

function getDefaultProfile(): Profile {
  return {
    top_interests: [
      { category: '科技与AI', tags: ['AI', '大模型', 'Agent'], weight: 90, reason: '核心兴趣' },
      { category: '产品与工具', tags: ['SaaS', '效率工具'], weight: 80, reason: '产品经理背景' },
      { category: '职业发展', tags: ['求职', '面试'], weight: 75, reason: '当前求职阶段' },
      { category: '效率方法', tags: ['工作流', '自动化'], weight: 70, reason: '效率提升' },
    ],
    preferred_categories: ['科技与AI', '产品与工具', '职业发展', '效率方法'],
    knowledge_gaps: ['历史人文', '自然科学'],
    interest_summary: 'AI技术、产品设计、职业发展、效率工具',
  };
}

// ── Query Generation ──

async function generateQueries(profile: Profile, env: Env): Promise<string[]> {
  const prompt = `你是一个搜索策略引擎。根据用户的兴趣画像，生成搜索词。

用户兴趣画像：
${JSON.stringify(profile, null, 2)}

要求：
1. 为主要兴趣生成1-2个具体搜索词
2. 搜索词要具体、可搜索
3. 混合"趋势发现"和"深度内容"型
4. 总数4-8个

输出严格JSON数组：["搜索词1", "搜索词2", ...]`;

  const result = await callDeepSeek(prompt, env);
  try {
    const cleaned = result.replace(/\\\`\\\`\\\`json?/g, '').replace(/\\\`\\\`\\\`/g, '').trim();
    const queries = JSON.parse(cleaned);
    return Array.isArray(queries) ? queries.slice(0, 8) : ['AI 最新进展 2026', '编程技术 2026'];
  } catch {
    return ['AI 最新进展 2026', '编程技术 2026'];
  }
}

// ── Search ──

async function searchWeb(queries: string[], env: Env): Promise<SearchResult[]> {
  // Use DuckDuckGo HTML search (no API key needed)
  const all: SearchResult[] = [];
  const seenUrls = new Set<string>();

  for (const query of queries.slice(0, 4)) {
    try {
      const url = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`;
      const resp = await fetch(url, {
        headers: { 'User-Agent': 'Mozilla/5.0 (compatible; KnowledgeAgent/1.0)' },
      });
      const html = await resp.text();

      // Parse search result links
      const linkRegex = /<a[^>]+class="result__a"[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/g;
      const snippetRegex = /<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)<\/a>/g;

      let match: RegExpExecArray | null;
      let linkMatch: RegExpExecArray | null;
      const titles: string[] = [];
      const urls: string[] = [];
      
      // Extract links
      linkMatch = /<a[^>]+class="result__a"[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/g.exec(html);
      while ((match = /<a[^>]+class="result__a"[^>]*href=["\']([^"\']*)["\'][^>]*>([\s\S]*?)<\/a>/g.exec(html)) !== null) {
        const href = match[1].replace(/^\/\//, 'https:');
        const title = match[2].replace(/<[^>]+>/g, '').trim();
        if (href && title && !seenUrls.has(href)) {
          seenUrls.add(href);
          urls.push(href);
          titles.push(title);
        }
      }

      // Extract snippets
      const snippets: string[] = [];
      while ((match = /<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)<\/a>/g.exec(html)) !== null) {
        snippets.push(match[1].replace(/<[^>]+>/g, '').trim());
      }

      for (let i = 0; i < Math.min(urls.length, 5); i++) {
        all.push({
          title: titles[i] || '',
          url: urls[i] || '',
          snippet: snippets[i] || '',
          source_query: query,
        });
      }
    } catch (e) {
      console.warn(`[search] Failed for query "${query}":`, e);
    }
  }

  return all;
}

// ── Scoring ──

async function scoreResults(profile: Profile, results: SearchResult[], env: Env): Promise<ScoredItem[]> {
  if (results.length === 0) return [];

  // Score in batches of 10 to avoid token limits
  const batchSize = 10;
  const allScored: ScoredItem[] = [];

  for (let i = 0; i < results.length; i += batchSize) {
    const batch = results.slice(i, i + batchSize);
    const prompt = `你是一个内容推荐评分引擎。根据用户画像，对搜索结果评分。

用户画像摘要：${profile.interest_summary}
偏好分类：${profile.preferred_categories.join(', ')}

搜索结果：
${batch.map((r, idx) => `[${idx}] 标题: ${r.title}\nURL: ${r.url}\n摘要: ${r.snippet}\n来源: ${r.source_query}`).join('\n---\n')}

评分标准：
- 80-100：强烈匹配，与核心兴趣高度一致
- 60-79：相关可推送
- <60：不推荐

输出严格JSON数组：[{"score": 85, "reason": "匹配理由", "category": "科技与AI"}, ...]
保持数组顺序与输入一致。`;

    const result = await callDeepSeek(prompt, env);
    try {
      const cleaned = result.replace(/\\\`\\\`\\\`json?/g, '').replace(/\\\`\\\`\\\`/g, '').trim();
      const scores = JSON.parse(cleaned);
      if (Array.isArray(scores)) {
        for (let j = 0; j < Math.min(scores.length, batch.length); j++) {
          const s = scores[j];
          if (s.score >= 60) {
            allScored.push({
              ...batch[j],
              score: s.score || 0,
              reason: s.reason || '',
              category: s.category || '其他',
            });
          }
        }
      }
    } catch {
      console.warn('[score] Failed to parse AI response for batch', i);
    }
  }

  return allScored.sort((a, b) => b.score - a.score);
}

// ── Dedup & Save ──

async function deduplicate(items: ScoredItem[], env: Env): Promise<ScoredItem[]> {
  const existing = await env.DB.prepare(
    `SELECT url FROM recommendations WHERE url IN (${items.map(() => '?').join(',')})`
  ).bind(...items.map(i => i.url)).all();

  const existingUrls = new Set((existing.results || []).map((r: any) => r.url));
  return items.filter(i => !existingUrls.has(i.url));
}

async function saveToD1(items: ScoredItem[], env: Env): Promise<void> {
  const now = Math.floor(Date.now() / 1000);
  for (const item of items) {
    try {
      await env.DB.prepare(
        `INSERT INTO recommendations (title, url, snippet, score, reason, category, source_query, created_at) 
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
      ).bind(item.title, item.url, item.snippet, item.score, item.reason, item.category, item.source_query, now).run();
    } catch (e) {
      console.warn(`[save] Failed for ${item.url}:`, e);
    }
  }
}

// ── Stats ──

async function getStats(env: Env): Promise<any> {
  const total = await env.DB.prepare(`SELECT COUNT(*) as c FROM recommendations`).first();
  const last = await env.DB.prepare(`SELECT MAX(created_at) as ts FROM recommendations`).first();
  const byCategory = await env.DB.prepare(
    `SELECT category, COUNT(*) as cnt FROM recommendations GROUP BY category ORDER BY cnt DESC`
  ).all();
  return {
    total: (total as any)?.c || 0,
    last_run: (last as any)?.ts || null,
    by_category: byCategory.results || [],
  };
}

// ── Helpers ──

async function callDeepSeek(prompt: string, env: Env): Promise<string> {
  const resp = await fetch('https://api.deepseek.com/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.DEEPSEEK_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: 'deepseek-chat',
      messages: [
        { role: 'system', content: '你是一个知识发现引擎。只输出要求的格式，不要多余文字。' },
        { role: 'user', content: prompt },
      ],
      temperature: 0,
      max_tokens: 2048,
    }),
  });

  const data: any = await resp.json();
  return data?.choices?.[0]?.message?.content || '';
}

function corsJson(data: any): Response {
  return new Response(JSON.stringify(data), {
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    },
  });
}
