/**
 * knowledge-agent-webhook v6 — 使用 node:crypto 替代 Web Crypto API
 * 优势: createDecipheriv 可控填充, 无 BufferSource 陷阱
 */

import crypto from 'node:crypto';

interface Env {
  DB: D1Database; IMAGES: R2Bucket;
  WECOM_TOKEN: string; WECOM_AES_KEY: string; WECOM_CORP_ID: string;
  WECOM_CORP_SECRET: string; SYNC_API_KEY: string;
}

// ── 企微 AES-CBC 解密（node:crypto 版）───────────────────────
function decryptWechat(encB64: string, aesKeyB64: string): string {
  const key = Buffer.from(aesKeyB64 + "=", "base64");   // 43→44→32 bytes
  const ciphertext = Buffer.from(encB64.replace(/ /g, "+"), "base64");
  const iv = key.subarray(0, 16);

  console.log(`[aes] key=${key.length}B iv=${iv.length}B cipher=${ciphertext.length}B`);

  const decipher = crypto.createDecipheriv("aes-256-cbc", key, iv);
  decipher.setAutoPadding(true);  // PKCS7

  let decrypted: Buffer;
  try {
    const chunks: Buffer[] = [];
    chunks.push(decipher.update(ciphertext));
    chunks.push(decipher.final());
    decrypted = Buffer.concat(chunks);
  } catch (e: any) {
    console.error(`[aes] final() failed: ${e.message} code=${e.code}`);
    throw e;
  }

  console.log(`[aes] decrypted ${decrypted.length}B hex: ${decrypted.subarray(0, 16).toString('hex')}...`);

  // 格式: random(16) + msg_len(4, big-endian) + xml_content
  if (decrypted.length < 20) throw new Error(`too short: ${decrypted.length}`);
  const msgLen = decrypted.readUInt32BE(16);
  console.log(`[aes] msgLen=${msgLen} avail=${decrypted.length - 20}`);
  if (msgLen === 0 || msgLen > decrypted.length - 20) {
    throw new Error(`bad msgLen=${msgLen} max=${decrypted.length - 20}`);
  }
  return decrypted.subarray(20, 20 + msgLen).toString("utf8");
}

// ── 签名验证 ──────────────────────────────────────────────────
async function verifySig(tok: string, ts: string, non: string, enc: string, sig: string): Promise<boolean> {
  const hash = crypto.createHash("sha1").update([tok, ts, non, enc].sort().join("")).digest("hex");
  return hash === sig;
}

// ── 从 raw URL 取 query 参数（不做 decode）─────────────────
function rawParam(url: string, name: string): string {
  const i = url.indexOf("?"); if (i === -1) return "";
  for (const p of url.slice(i + 1).split("&")) {
    const e = p.indexOf("="); if (e === -1) continue;
    if (p.slice(0, e) === name) return p.slice(e + 1);
  }
  return "";
}

// ── XML 解析 ──────────────────────────────────────────────────
function parseXml(xml: string): Record<string, string> {
  const r: Record<string, string> = {};
  const re = /<(\w+)>(?:<!\[CDATA\[(.*?)\]\]>|(.*?))<\/\1>/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(xml)) !== null) r[m[1]] = m[2] !== undefined ? m[2] : (m[3] || "");
  return r;
}
const getEnc = (b: string) => { const m = b.match(/<Encrypt>(?:<!\[CDATA\[(.*?)\]\]>|(.*?))<\/Encrypt>/); return m ? (m[1] !== undefined ? m[1] : (m[2] || "")) : ""; };

// ── AccessToken 缓存 ─────────────────────────────────────────
let tc: { t: string; e: number } | null = null;
async function getToken(cid: string, cs: string): Promise<string> {
  if (tc && tc.e > Date.now() / 1000 + 300) return tc.t;
  const d = await (await fetch(`https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=${cid}&corpsecret=${cs}`)).json() as any;
  if (!d.access_token) throw new Error(`token err: ${d.errcode}`);
  tc = { t: d.access_token, e: Date.now() / 1000 + (d.expires_in || 7200) };
  return tc.t;
}

// ── 图片 → R2 ────────────────────────────────────────────────
async function imgToR2(mid: string, cid: string, cs: string, imgs: R2Bucket): Promise<string | null> {
  try {
    const tk = await getToken(cid, cs);
    const r = await fetch(`https://qyapi.weixin.qq.com/cgi-bin/media/get?access_token=${tk}&media_id=${mid}`);
    if (!r.ok) return null;
    const ct = r.headers.get("Content-Type") || "";
    if (ct.includes("json")) return null;
    let ext = ".jpg"; if (ct.includes("png")) ext=".png"; else if (ct.includes("gif")) ext=".gif"; else if (ct.includes("webp")) ext=".webp";
    const k = `wechat_${mid}${ext}`;
    const b = await r.arrayBuffer();
    await imgs.put(k, b, { httpMetadata: { contentType: ct } });
    console.log(`[img] ${k} ${b.byteLength}B`);
    return k;
  } catch (e) { console.error(`[img] ${e}`); return null; }
}

function chkApi(req: Request, k: string): boolean {
  const a = req.headers.get("Authorization") || "";
  return (a.startsWith("Bearer ") ? a.slice(7) : a) === k;
}

// ── Routes ──────────────────────────────────────────────────
async function handleVerify(req: Request, env: Env): Promise<Response> {
  const sig    = rawParam(req.url, "msg_signature");
  const ts     = rawParam(req.url, "timestamp");
  const non    = rawParam(req.url, "nonce");
  const echostr = rawParam(req.url, "echostr");

  console.log(`[verify] ts=${ts} echo=${echostr.slice(0, 30)}...`);

  if (!(await verifySig(env.WECOM_TOKEN, ts, non, echostr, sig)))
    return new Response("bad sig", { status: 403 });

  try {
    const content = decryptWechat(echostr, env.WECOM_AES_KEY);
    console.log(`[verify] OK: "${content}"`);
    return new Response(content, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
  } catch (e: any) {
    console.error(`[verify] err: ${e.message}`);
    return new Response(`err: ${e.message}`, { status: 500 });
  }
}

async function handleMsg(req: Request, env: Env): Promise<Response> {
  const sig = rawParam(req.url, "msg_signature");
  const ts  = rawParam(req.url, "timestamp");
  const non = rawParam(req.url, "nonce");
  const body = await req.text();
  const enc = getEnc(body);
  if (!enc) return new Response("no Encrypt", { status: 400 });
  if (!(await verifySig(env.WECOM_TOKEN, ts, non, enc, sig)))
    return new Response("bad sig", { status: 403 });

  const xml = decryptWechat(enc, env.WECOM_AES_KEY);
  const m = parseXml(xml);
  const mt = m["MsgType"] || "", fu = m["FromUserName"] || "u";
  console.log(`[msg] ${mt} from ${fu}`);

  const r: any = { msg_type: mt, from_user: fu };
  if (mt === "text") r.content = m["Content"] || "";
  else if (mt === "link") { r.url = m["Url"]||""; r.title = m["Title"]||""; r.description = m["Description"]||""; }
  else if (mt === "image") { r.media_id = m["MediaId"]||""; if (r.media_id) { const k = await imgToR2(r.media_id, env.WECOM_CORP_ID, env.WECOM_CORP_SECRET, env.IMAGES); if (k) r.image_r2_key = k; } }
  else if (mt === "voice") r.media_id = m["MediaId"]||"";

  const now = Math.floor(Date.now()/1000);
  try {
    const res = await env.DB.prepare(
      `INSERT INTO messages(msg_type,from_user,content,url,title,description,media_id,image_r2_key,created_at) VALUES(?,?,?,?,?,?,?,?,?)`
    ).bind(mt, fu, r.content||null, r.url||null, r.title||null, r.description||null, r.media_id||null, r.image_r2_key||null, now).run();
    console.log(`[msg] D1 #${res.meta.last_row_id}`);
  } catch(e) { console.error(`[msg] D1: ${e}`); }
  return new Response("success", { status: 200 });
}

async function handlePending(req: Request, env: Env): Promise<Response> {
  if (!chkApi(req, env.SYNC_API_KEY)) return new Response("unauth", { status: 401 });
  const l = Math.min(parseInt(new URL(req.url).searchParams.get("limit")||"50"), 200);
  const r = await env.DB.prepare(`SELECT * FROM messages WHERE processed=0 ORDER BY id ASC LIMIT ?`).bind(l).all();
  return Response.json({ messages: r.results });
}

async function handleProcessed(req: Request, env: Env): Promise<Response> {
  if (!chkApi(req, env.SYNC_API_KEY)) return new Response("unauth", { status: 401 });
  const { ids } = await req.json() as { ids: number[] };
  if (!ids?.length) return new Response("bad", { status: 400 });
  const ph = ids.map(()=>"?").join(",");
  await env.DB.prepare(`UPDATE messages SET processed=1,processed_at=? WHERE id IN (${ph})`).bind(Math.floor(Date.now()/1000), ...ids).run();
  return Response.json({ ok: true });
}

async function handleImageGet(req: Request, env: Env, key: string): Promise<Response> {
  if (!chkApi(req, env.SYNC_API_KEY)) return new Response("unauth", { status: 401 });
  const o = await env.IMAGES.get(key);
  if (!o) return new Response("nf", { status: 404 });
  const h = new Headers(); o.writeHttpMetadata(h); h.set("Cache-Control","public,max-age=86400");
  return new Response(o.body, { headers: h });
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const { pathname: p } = new URL(req.url);
    const m = req.method;
    if (m === "OPTIONS") return new Response(null, { headers: { "Access-Control-Allow-Origin":"*","Access-Control-Allow-Methods":"GET,POST,OPTIONS","Access-Control-Allow-Headers":"Authorization,Content-Type" } });
    try {
      if (p === "/wechat/callback" && m === "GET")  return handleVerify(req, env);
      if (p === "/wechat/callback" && m === "POST") return handleMsg(req, env);
      if (p === "/api/pending" && m === "GET")       return handlePending(req, env);
      if (p === "/api/processed" && m === "POST")    return handleProcessed(req, env);
      if (p.startsWith("/api/image/") && m === "GET") return handleImageGet(req, env, decodeURIComponent(p.slice(11)));
      if (p === "/health" && m === "GET") return Response.json({ ok: true, ts: Math.floor(Date.now()/1000) });
      return new Response("nf", { status: 404 });
    } catch (e) { console.error(`[fatal] ${e}`); return new Response("err", { status: 500 }); }
  },
};
