/**
 * knowledge-agent-webhook v5 — 所有 buffer 完全独立，逐个 byte copy
 */

interface Env {
  DB: D1Database; IMAGES: R2Bucket;
  WECOM_TOKEN: string; WECOM_AES_KEY: string; WECOM_CORP_ID: string;
  WECOM_CORP_SECRET: string; SYNC_API_KEY: string;
}

// ── 独立 copy ArrayBuffer（全程不共享底层 buffer）─────────
function copyBytes(src: ArrayBuffer, offset: number, length: number): ArrayBuffer {
  const dst = new ArrayBuffer(length);
  new Uint8Array(dst).set(new Uint8Array(src, offset, length));
  return dst;
}

function b64decode(b64: string): ArrayBuffer {
  const clean = b64.replace(/ /g, "+");
  const bin = atob(clean);
  const buf = new ArrayBuffer(bin.length);
  const v = new Uint8Array(buf);
  for (let i = 0; i < bin.length; i++) v[i] = bin.charCodeAt(i);
  return buf;
}

// ── AES-CBC 解密 ──────────────────────────────────────────────
async function decrypt(encB64: string, aesKeyB64: string): Promise<Uint8Array> {
  const keyBuf = b64decode(aesKeyB64 + "=");   // 32 bytes, 独立
  const cipherBuf = b64decode(encB64);          // 64 bytes, 独立
  const iv = copyBytes(keyBuf, 0, 16);          // 16 bytes, 独立

  console.log(`[aes] key=${keyBuf.byteLength} cipher=${cipherBuf.byteLength} iv=${iv.byteLength}`);

  const cryptoKey = await crypto.subtle.importKey(
    "raw", keyBuf, "AES-CBC", false, ["decrypt"]
  );

  const plainBuf = await crypto.subtle.decrypt(
    { name: "AES-CBC", iv }, cryptoKey, cipherBuf
  );

  console.log(`[aes] OK plain=${plainBuf.byteLength}B`);
  return new Uint8Array(plainBuf);
}

// ── PKCS7 unpadding ───────────────────────────────────────────
function unpad(decrypted: Uint8Array): string | null {
  const pad = decrypted[decrypted.length - 1];
  console.log(`[unpad] len=${decrypted.length} pad=${pad}`);
  if (pad > 32 || pad === 0 || pad > decrypted.length) {
    console.error(`[unpad] bad pad`);
    return null;
  }
  const end = decrypted.length - pad;
  if (end < 20) { console.error(`[unpad] too short`); return null; }

  // msg_len at bytes 16-19
  const msgLen = ((decrypted[16] << 24) | (decrypted[17] << 16) | (decrypted[18] << 8) | decrypted[19]) >>> 0;
  console.log(`[unpad] msgLen=${msgLen} max=${end - 20}`);

  if (msgLen === 0 || msgLen > end - 20) {
    console.error(`[unpad] bad msgLen`);
    return null;
  }

  // 独立 copy content 到新 buffer
  const contentBuf = copyBytes(decrypted.buffer, decrypted.byteOffset + 20, msgLen);
  const content = new TextDecoder().decode(contentBuf);
  console.log(`[unpad] OK content="${content.slice(0, 40)}"`);
  return content;
}

// ── Tools ──────────────────────────────────────────────────────
function rawParam(url: string, name: string): string {
  const i = url.indexOf("?"); if (i === -1) return "";
  for (const p of url.slice(i + 1).split("&")) {
    const e = p.indexOf("="); if (e === -1) continue;
    if (p.slice(0, e) === name) return p.slice(e + 1);
  }
  return "";
}

async function sha1hex(s: string): Promise<string> {
  const h = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(h), b => b.toString(16).padStart(2, '0')).join('');
}

async function verifySig(tok: string, ts: string, non: string, enc: string, sig: string): Promise<boolean> {
  return await sha1hex([tok, ts, non, enc].sort().join("")) === sig;
}

function parseXml(xml: string): Record<string, string> {
  const r: Record<string, string> = {};
  const re = /<(\w+)>(?:<!\[CDATA\[(.*?)\]\]>|(.*?))<\/\1>/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(xml)) !== null) r[m[1]] = m[2] !== undefined ? m[2] : (m[3] || "");
  return r;
}

const extEnc = (b: string) => { const m = b.match(/<Encrypt>(?:<!\[CDATA\[(.*?)\]\]>|(.*?))<\/Encrypt>/); return m ? (m[1] !== undefined ? m[1] : (m[2] || "")) : ""; };

// ── AccessToken ────────────────────────────────────────────────
let tc: { t: string; e: number } | null = null;
async function getToken(cid: string, cs: string): Promise<string> {
  if (tc && tc.e > Date.now() / 1000 + 300) return tc.t;
  const d = await (await fetch(`https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=${cid}&corpsecret=${cs}`)).json() as any;
  if (!d.access_token) throw new Error(`token: ${d.errcode}`);
  tc = { t: d.access_token, e: Date.now() / 1000 + (d.expires_in || 7200) };
  return d.access_token;
}

// ── Image → R2 ─────────────────────────────────────────────────
async function imgToR2(mid: string, cid: string, cs: string, imgs: R2Bucket): Promise<string | null> {
  try {
    const tk = await getToken(cid, cs);
    const r = await fetch(`https://qyapi.weixin.qq.com/cgi-bin/media/get?access_token=${tk}&media_id=${mid}`);
    if (!r.ok) return null;
    const ct = r.headers.get("Content-Type") || "";
    if (ct.includes("json")) return null;
    let ext = ".jpg"; if (ct.includes("png")) ext = ".png"; else if (ct.includes("gif")) ext = ".gif"; else if (ct.includes("webp")) ext = ".webp";
    const k = `wechat_${mid}${ext}`;
    const b = await r.arrayBuffer();
    await imgs.put(k, b, { httpMetadata: { contentType: ct } });
    console.log(`[img] ${k}`);
    return k;
  } catch (e) { console.error(`[img] ${e}`); return null; }
}

function chkApi(req: Request, k: string): boolean {
  const a = req.headers.get("Authorization") || "";
  return (a.startsWith("Bearer ") ? a.slice(7) : a) === k;
}

// ── Routes ────────────────────────────────────────────────────
async function handleVerify(req: Request, env: Env): Promise<Response> {
  const sig = rawParam(req.url, "msg_signature");
  const ts  = rawParam(req.url, "timestamp");
  const non = rawParam(req.url, "nonce");
  const echo = rawParam(req.url, "echostr");
  if (!(await verifySig(env.WECOM_TOKEN, ts, non, echo, sig)))
    return new Response("bad sig", { status: 403 });
  try {
    const d = await decrypt(echo, env.WECOM_AES_KEY);
    const c = unpad(d);
    return c ? new Response(c, { headers: { "Content-Type": "text/plain; charset=utf-8" } })
             : new Response("unpad fail", { status: 500 });
  } catch (e: any) { return new Response(`err: ${e.message || e}`, { status: 500 }); }
}

async function handleMsg(req: Request, env: Env): Promise<Response> {
  const sig = rawParam(req.url, "msg_signature");
  const ts  = rawParam(req.url, "timestamp");
  const non = rawParam(req.url, "nonce");
  const body = await req.text();
  const enc = extEnc(body);
  if (!enc) return new Response("no Encrypt", { status: 400 });
  if (!(await verifySig(env.WECOM_TOKEN, ts, non, enc, sig)))
    return new Response("bad sig", { status: 403 });

  const d = await decrypt(enc, env.WECOM_AES_KEY);
  const xml = unpad(d);
  if (!xml) return new Response("decrypt err", { status: 500 });

  const m = parseXml(xml);
  const mt = m["MsgType"] || "", fu = m["FromUserName"] || "u";
  console.log(`[msg] ${mt} from ${fu}`);

  const r: any = { msg_type: mt, from_user: fu };
  if (mt === "text") r.content = m["Content"] || "";
  else if (mt === "link") { r.url = m["Url"]||""; r.title = m["Title"]||""; r.description = m["Description"]||""; }
  else if (mt === "image") { r.media_id = m["MediaId"]||""; if (r.media_id) { const k = await imgToR2(r.media_id, env.WECOM_CORP_ID, env.WECOM_CORP_SECRET, env.IMAGES); if (k) r.image_r2_key = k; } }
  else if (mt === "voice") r.media_id = m["MediaId"]||"";

  try {
    const now = Math.floor(Date.now()/1000);
    const res = await env.DB.prepare(
      `INSERT INTO messages(msg_type,from_user,content,url,title,description,media_id,image_r2_key,created_at) VALUES(?,?,?,?,?,?,?,?,?)`
    ).bind(mt, fu, r.content||null, r.url||null, r.title||null, r.description||null, r.media_id||null, r.image_r2_key||null, now).run();
    console.log(`[msg] D1 #${res.meta.last_row_id}`);
  } catch(e) { console.error(`[msg] D1: ${e}`); }
  return new Response("success", { status: 200 });
}

async function handlePending(req: Request, env: Env): Promise<Response> {
  if (!chkApi(req, env.SYNC_API_KEY)) return new Response("unauth", { status: 401 });
  const l = Math.min(parseInt(new URL(req.url).searchParams.get("limit") || "50"), 200);
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

async function handleImage(req: Request, env: Env, key: string): Promise<Response> {
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
      if (p.startsWith("/api/image/") && m === "GET") return handleImage(req, env, decodeURIComponent(p.slice(11)));
      if (p === "/health" && m === "GET") return Response.json({ ok: true, ts: Math.floor(Date.now()/1000) });
      return new Response("nf", { status: 404 });
    } catch (e) { return new Response("err", { status: 500 }); }
  },
};
