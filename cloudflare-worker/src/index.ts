/**
 * knowledge-agent-webhook v7 — 纯 JS AES-256-CBC 解密
 * 绕开 crypto.subtle / node:crypto，自己实现 AES + PKCS7
 */

interface Env {
  DB: D1Database; IMAGES: R2Bucket;
  WECOM_TOKEN: string; WECOM_AES_KEY: string; WECOM_CORP_ID: string;
  WECOM_CORP_SECRET: string; SYNC_API_KEY: string;
}

// ═══════════════════════════════════════════════════════════════
// Pure JS AES-256 (decrypt only, CBC mode + PKCS7 unpad)
// Reference: FIPS-197, NIST SP 800-38A
// ═══════════════════════════════════════════════════════════════

const SBOX: number[] = [
  0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
  0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
  0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
  0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
  0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
  0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
  0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
  0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
  0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
  0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
  0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
  0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
  0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
  0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
  0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
  0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
];

const INV_SBOX: number[] = [
  0x52,0x09,0x6a,0xd5,0x30,0x36,0xa5,0x38,0xbf,0x40,0xa3,0x9e,0x81,0xf3,0xd7,0xfb,
  0x7c,0xe3,0x39,0x82,0x9b,0x2f,0xff,0x87,0x34,0x8e,0x43,0x44,0xc4,0xde,0xe9,0xcb,
  0x54,0x7b,0x94,0x32,0xa6,0xc2,0x23,0x3d,0xee,0x4c,0x95,0x0b,0x42,0xfa,0xc3,0x4e,
  0x08,0x2e,0xa1,0x66,0x28,0xd9,0x24,0xb2,0x76,0x5b,0xa2,0x49,0x6d,0x8b,0xd1,0x25,
  0x72,0xf8,0xf6,0x64,0x86,0x68,0x98,0x16,0xd4,0xa4,0x5c,0xcc,0x5d,0x65,0xb6,0x92,
  0x6c,0x70,0x48,0x50,0xfd,0xed,0xb9,0xda,0x5e,0x15,0x46,0x57,0xa7,0x8d,0x9d,0x84,
  0x90,0xd8,0xab,0x00,0x8c,0xbc,0xd3,0x0a,0xf7,0xe4,0x58,0x05,0xb8,0xb3,0x45,0x06,
  0xd0,0x2c,0x1e,0x8f,0xca,0x3f,0x0f,0x02,0xc1,0xaf,0xbd,0x03,0x01,0x13,0x8a,0x6b,
  0x3a,0x91,0x11,0x41,0x4f,0x67,0xdc,0xea,0x97,0xf2,0xcf,0xce,0xf0,0xb4,0xe6,0x73,
  0x96,0xac,0x74,0x22,0xe7,0xad,0x35,0x85,0xe2,0xf9,0x37,0xe8,0x1c,0x75,0xdf,0x6e,
  0x47,0xf1,0x1a,0x71,0x1d,0x29,0xc5,0x89,0x6f,0xb7,0x62,0x0e,0xaa,0x18,0xbe,0x1b,
  0xfc,0x56,0x3e,0x4b,0xc6,0xd2,0x79,0x20,0x9a,0xdb,0xc0,0xfe,0x78,0xcd,0x5a,0xf4,
  0x1f,0xdd,0xa8,0x33,0x88,0x07,0xc7,0x31,0xb1,0x12,0x10,0x59,0x27,0x80,0xec,0x5f,
  0x60,0x51,0x7f,0xa9,0x19,0xb5,0x4a,0x0d,0x2d,0xe5,0x7a,0x9f,0x93,0xc9,0x9c,0xef,
  0xa0,0xe0,0x3b,0x4d,0xae,0x2a,0xf5,0xb0,0xc8,0xeb,0xbb,0x3c,0x83,0x53,0x99,0x61,
  0x17,0x2b,0x04,0x7e,0xba,0x77,0xd6,0x26,0xe1,0x69,0x14,0x63,0x55,0x21,0x0c,0x7d,
];

const RCON = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36];

function rotWord(w: number): number {
  return ((w << 8) | (w >>> 24)) >>> 0;
}

function subWord(w: number): number {
  return ((SBOX[(w >>> 24) & 0xff] << 24) |
          (SBOX[(w >>> 16) & 0xff] << 16) |
          (SBOX[(w >>> 8)  & 0xff] << 8)  |
          (SBOX[w          & 0xff])) >>> 0;
}

function keyExpansion256(key: Uint8Array): Uint8Array {
  // AES-256: Nk=8, Nr=14 → 15 round keys × 16 bytes = 240 bytes
  const w = new Uint32Array(60);
  for (let i = 0; i < 8; i++) {
    w[i] = ((key[4*i] << 24) | (key[4*i+1] << 16) | (key[4*i+2] << 8) | key[4*i+3]) >>> 0;
  }
  for (let i = 8; i < 60; i++) {
    let temp = w[i - 1];
    if (i % 8 === 0) {
      temp = subWord(rotWord(temp)) ^ (RCON[i / 8 - 1] << 24);
    } else if (i % 8 === 4) {
      temp = subWord(temp);
    }
    w[i] = (w[i - 8] ^ temp) >>> 0;
  }
  const expanded = new Uint8Array(240);
  for (let i = 0; i < 60; i++) {
    expanded[4*i]   = (w[i] >>> 24) & 0xff;
    expanded[4*i+1] = (w[i] >>> 16) & 0xff;
    expanded[4*i+2] = (w[i] >>> 8)  & 0xff;
    expanded[4*i+3] = w[i]           & 0xff;
  }
  return expanded;
}

function invSubBytes(state: Uint8Array): void {
  for (let i = 0; i < 16; i++) state[i] = INV_SBOX[state[i]];
}

function invShiftRows(state: Uint8Array): void {
  // Row 1: shift right by 1
  let t = state[13]; state[13]=state[9]; state[9]=state[5]; state[5]=state[1]; state[1]=t;
  // Row 2: shift right by 2
  t=state[2]; state[2]=state[10]; state[10]=t;
  t=state[6]; state[6]=state[14]; state[14]=t;
  // Row 3: shift right by 3 (= left by 1)
  t=state[3]; state[3]=state[7]; state[7]=state[11]; state[11]=state[15]; state[15]=t;
}

const gf_mul = (a: number, b: number): number => {
  let r = 0;
  for (let i = 0; i < 8; i++) {
    if (b & 1) r ^= a;
    const hi = a & 0x80;
    a = (a << 1) & 0xff;
    if (hi) a ^= 0x1b;
    b >>= 1;
  }
  return r;
};

function invMixColumns(state: Uint8Array): void {
  for (let c = 0; c < 4; c++) {
    const i = c * 4;
    const a0 = state[i], a1 = state[i+1], a2 = state[i+2], a3 = state[i+3];
    state[i]   = gf_mul(a0,0x0e) ^ gf_mul(a1,0x0b) ^ gf_mul(a2,0x0d) ^ gf_mul(a3,0x09);
    state[i+1] = gf_mul(a0,0x09) ^ gf_mul(a1,0x0e) ^ gf_mul(a2,0x0b) ^ gf_mul(a3,0x0d);
    state[i+2] = gf_mul(a0,0x0d) ^ gf_mul(a1,0x09) ^ gf_mul(a2,0x0e) ^ gf_mul(a3,0x0b);
    state[i+3] = gf_mul(a0,0x0b) ^ gf_mul(a1,0x0d) ^ gf_mul(a2,0x09) ^ gf_mul(a3,0x0e);
  }
}

function addRoundKey(state: Uint8Array, roundKey: Uint8Array, offset: number): void {
  for (let i = 0; i < 16; i++) state[i] ^= roundKey[offset + i];
}

function aes256DecryptBlock(block: Uint8Array, expandedKey: Uint8Array): void {
  // AES-256: Nr = 14, initial round + 13 rounds + final round
  addRoundKey(block, expandedKey, 14 * 16);
  for (let round = 13; round >= 1; round--) {
    invShiftRows(block);
    invSubBytes(block);
    addRoundKey(block, expandedKey, round * 16);
    invMixColumns(block);
  }
  invShiftRows(block);
  invSubBytes(block);
  addRoundKey(block, expandedKey, 0);
}

function aes256CbcDecrypt(ciphertext: Uint8Array, key: Uint8Array, iv: Uint8Array): Uint8Array {
  const blockCount = ciphertext.length / 16;
  const plain = new Uint8Array(ciphertext.length);
  const expandedKey = keyExpansion256(key);

  let prev = iv;
  for (let i = 0; i < blockCount; i++) {
    const offset = i * 16;
    const block = ciphertext.slice(offset, offset + 16);
    aes256DecryptBlock(block, expandedKey);
    for (let j = 0; j < 16; j++) plain[offset + j] = block[j] ^ prev[j];
    prev = ciphertext.slice(offset, offset + 16);
  }
  return plain;
}

function pkcs7Unpad(data: Uint8Array): Uint8Array {
  const pad = data[data.length - 1];
  if (pad === 0 || pad > 16) throw new Error(`bad pad: ${pad}`);
  // Verify all padding bytes
  for (let i = 1; i <= pad; i++) {
    if (data[data.length - i] !== pad) throw new Error(`pad verify fail at ${i}`);
  }
  return data.slice(0, data.length - pad);
}

// ═══════════════════════════════════════════════════════════════
// WeChat message decryption
// ═══════════════════════════════════════════════════════════════

function hex16(d: Uint8Array, n: number): string {
  return Array.from(d.slice(0, n), b => b.toString(16).padStart(2,'0')).join('');
}

async function decryptWechatWebCrypto(encB64: string, aesKeyB64: string): Promise<string> {
  const keyBytes = b64decode(aesKeyB64 + "=");
  const ciphertext = b64decode(encB64.replace(/ /g, "+"));

  // Validate: ciphertext must be multiple of 16 bytes
  if (ciphertext.length % 16 !== 0) {
    throw new Error(`bad cipher len ${ciphertext.length} (not multiple of 16)`);
  }

  const iv = keyBytes.slice(0, 16);
  console.log(`[wc] key=${keyBytes.length}B cipher=${ciphertext.length}B`);

  const cryptoKey = await crypto.subtle.importKey("raw", keyBytes, { name: "AES-CBC" }, false, ["decrypt"]);
  const decrypted = new Uint8Array(await crypto.subtle.decrypt({ name: "AES-CBC", iv }, cryptoKey, ciphertext));
  console.log(`[wc] decrypted ${decrypted.length}B`);

  if (decrypted.length < 20) throw new Error("too short");
  const msgLen = ((decrypted[16] << 24) | (decrypted[17] << 16) | (decrypted[18] << 8) | decrypted[19]) >>> 0;
  console.log(`[wc] msgLen=${msgLen}`);
  if (msgLen === 0 || msgLen > decrypted.length - 20) throw new Error(`bad msgLen=${msgLen}`);
  return new TextDecoder().decode(decrypted.subarray(20, 20 + msgLen));
}

function decryptWechatJS(encB64: string, aesKeyB64: string): string {
  const key = b64decode(aesKeyB64 + "=");
  const ciphertext = b64decode(encB64.replace(/ /g, "+"));

  // Validate: ciphertext must be multiple of 16 bytes
  if (ciphertext.length % 16 !== 0) {
    throw new Error(`bad cipher len ${ciphertext.length} (not multiple of 16)`);
  }

  const iv = key.slice(0, 16);

  const decrypted = aes256CbcDecrypt(ciphertext, key, iv);
  const unpadded = pkcs7Unpad(decrypted);

  if (unpadded.length < 20) throw new Error("too short");
  const msgLen = ((unpadded[16] << 24) | (unpadded[17] << 16) | (unpadded[18] << 8) | unpadded[19]) >>> 0;
  if (msgLen === 0 || msgLen > unpadded.length - 20) throw new Error(`bad msgLen=${msgLen}`);
  return new TextDecoder().decode(unpadded.subarray(20, 20 + msgLen));
}

async function decryptWechat(encB64: string, aesKeyB64: string): Promise<string> {
  // Try Web Crypto API first (correct implementation), fall back to pure JS
  try {
    const r = await decryptWechatWebCrypto(encB64, aesKeyB64);
    console.log("[aes] WebCrypto OK");
    return r;
  } catch(e: any) {
    console.log(`[aes] WebCrypto failed (${e.message}), trying pure JS...`);
    return decryptWechatJS(encB64, aesKeyB64);
  }
}

// ═══════════════════════════════════════════════════════════════
// Utilities
// ═══════════════════════════════════════════════════════════════

function b64decode(b64: string): Uint8Array {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i) & 0xff;
  return bytes;
}

async function sha1hex(s: string): Promise<string> {
  const h = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(h), b => b.toString(16).padStart(2,'0')).join('');
}

async function verifySig(tok: string, ts: string, non: string, enc: string, sig: string): Promise<boolean> {
  return await sha1hex([tok, ts, non, enc].sort().join("")) === sig;
}

function rawParam(url: string, name: string): string {
  const i = url.indexOf("?"); if (i === -1) return "";
  for (const p of url.slice(i+1).split("&")) {
    const e = p.indexOf("="); if (e === -1) continue;
    if (p.slice(0,e) === name) return p.slice(e+1);
  }
  return "";
}

function getEnc(body: string): string {
  // Extract encrypted content from WeChat XML body
  // 's' flag is critical: WeChat XML may contain newlines
  const m = body.match(/<Encrypt>(?:<!\[CDATA\[(.*?)\]\]>|(.*?))<\/Encrypt>/s);
  if (!m) return "";
  const raw = m[1] !== undefined ? m[1] : (m[2] || "");
  // Strip all whitespace (newlines, spaces, tabs) — base64 has none
  return raw.replace(/\s+/g, "");
}
function xmlGet(xml: string, tag: string): string {
  // Extract <tag><![CDATA[content]]></tag> or <tag>content</tag>
  const reCDATA = new RegExp(`<${tag}><!\\[CDATA\\[(.*?)\\]\\]></${tag}>`, 's');
  const m1 = xml.match(reCDATA);
  if (m1) return m1[1];
  const rePlain = new RegExp(`<${tag}>(.*?)</${tag}>`, 's');
  const m2 = xml.match(rePlain);
  return m2 ? m2[1] : "";
}

let tc: { t: string; e: number } | null = null;
async function getToken(cid: string, cs: string): Promise<string> {
  if (tc && tc.e > Date.now()/1000 + 300) return tc.t;
  const d = await (await fetch(`https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=${cid}&corpsecret=${cs}`)).json() as any;
  if (!d.access_token) throw new Error(`token: ${d.errcode}`);
  tc = { t: d.access_token, e: Date.now()/1000 + (d.expires_in||7200) };
  return tc.t;
}

async function imgToR2(mid: string, cid: string, cs: string, imgs: R2Bucket): Promise<string|null> {
  try {
    const tk = await getToken(cid, cs);
    const r = await fetch(`https://qyapi.weixin.qq.com/cgi-bin/media/get?access_token=${tk}&media_id=${mid}`);
    if (!r.ok) return null;
    const ct = r.headers.get("Content-Type")||"";
    if (ct.includes("json")) return null;
    let ext=".jpg"; if(ct.includes("png"))ext=".png"; else if(ct.includes("gif"))ext=".gif"; else if(ct.includes("webp"))ext=".webp";
    const k=`wechat_${mid}${ext}`;
    const b=await r.arrayBuffer();
    await imgs.put(k,b,{httpMetadata:{contentType:ct}});
    console.log(`[img] ${k} ${b.byteLength}B`);
    return k;
  }catch(e){console.error(`[img] ${e}`);return null;}
}

function chkApi(req: Request, k: string): boolean {
  const a = req.headers.get("Authorization")||"";
  return (a.startsWith("Bearer ")?a.slice(7):a) === k;
}

// ═══════════════════════════════════════════════════════════════
// Routes
// ═══════════════════════════════════════════════════════════════

async function handleVerify(req: Request, env: Env): Promise<Response> {
  const sig=rawParam(req.url,"msg_signature"), ts=rawParam(req.url,"timestamp");
  const non=rawParam(req.url,"nonce"), echo=decodeURIComponent(rawParam(req.url,"echostr"));
  console.log(`[verify] ts=${ts} echo=${echo.slice(0,30)}...`);
  if(!(await verifySig(env.WECOM_TOKEN,ts,non,echo,sig))) return new Response("bad sig",{status:403});
  try {
    const c = await decryptWechat(echo, env.WECOM_AES_KEY);
    console.log(`[verify] OK: "${c}"`);
    return new Response(c,{headers:{"Content-Type":"text/plain; charset=utf-8"}});
  }catch(e:any){console.error(`[verify] ${e.message}`);return new Response(`err:${e.message}`,{status:500});}
}

async function handleMsg(req: Request, env: Env): Promise<Response> {
  const sig=rawParam(req.url,"msg_signature"), ts=rawParam(req.url,"timestamp"), non=rawParam(req.url,"nonce");
  const body=await req.text();
  console.log(`[msg] bodyLen=${body.length} bodyHead=${body.slice(0,120)}`);
  const enc=getEnc(body);
  console.log(`[msg] encLen=${enc.length} encHead=${enc.slice(0,40)}`);
  if(!enc)return new Response("no Encrypt",{status:400});
  if(!(await verifySig(env.WECOM_TOKEN,ts,non,enc,sig)))return new Response("bad sig",{status:403});
  let xml:string, mt="",fu="u",ct="";
  try {
    xml=await decryptWechat(enc,env.WECOM_AES_KEY);
    console.log(`[msg] OK xml(${xml.length}B)=${xml.slice(0,200)}`);
    mt=xmlGet(xml,"MsgType");fu=xmlGet(xml,"FromUserName");ct=xmlGet(xml,"Content");
    console.log(`[msg] mt=${mt} fu=${fu} ct=${ct.slice(0,60)}`);
  }catch(e:any){
    console.error(`[msg] decrypt FAIL: ${e.message} stack=${e.stack?.slice(0,200)}`);
    // Save debug info for offline analysis
    try {
      const now=Math.floor(Date.now()/1000);
      const debugInfo = JSON.stringify({encLen:enc.length,bodyLen:body.length,err:e.message,ts:now});
      await env.DB.prepare(`INSERT INTO messages(msg_type,from_user,content,description,created_at) VALUES('enc_debug','sys',?,?,?)`).bind(enc.slice(0,2000),debugInfo,now).run();
      console.log(`[msg] saved enc_debug: encLen=${enc.length} bodyLen=${body.length}`);
    }catch(e2){console.error(`[msg] save debug err: ${e2}`);}
    return new Response("success",{status:200});
  }
  const r:any={msg_type:mt,from_user:fu};
  if(mt==="text")r.content=ct;
  else if(mt==="link"){r.url=xmlGet(xml,"Url");r.title=xmlGet(xml,"Title");r.description=xmlGet(xml,"Description");}
  else if(mt==="image"){r.media_id=xmlGet(xml,"MediaId");if(r.media_id){const k=await imgToR2(r.media_id,env.WECOM_CORP_ID,env.WECOM_CORP_SECRET,env.IMAGES);if(k)r.image_r2_key=k;}}
  else if(mt==="voice")r.media_id=xmlGet(xml,"MediaId");
  const now=Math.floor(Date.now()/1000);
  try{const res=await env.DB.prepare(`INSERT INTO messages(msg_type,from_user,content,url,title,description,media_id,image_r2_key,created_at) VALUES(?,?,?,?,?,?,?,?,?)`).bind(mt,fu,r.content||null,r.url||null,r.title||null,r.description||null,r.media_id||null,r.image_r2_key||null,now).run();console.log(`[msg] D1 #${res.meta.last_row_id}`);}catch(e){console.error(`[msg] D1: ${e}`);}
  return new Response("success",{status:200});
}

async function handlePending(req: Request, env: Env): Promise<Response> {
  if(!chkApi(req,env.SYNC_API_KEY))return new Response("unauth",{status:401});
  const l=Math.min(parseInt(new URL(req.url).searchParams.get("limit")||"50"),200);
  const r=await env.DB.prepare(`SELECT * FROM messages WHERE processed=0 ORDER BY id ASC LIMIT ?`).bind(l).all();
  return Response.json({messages:r.results});
}
async function handleProcessed(req: Request, env: Env): Promise<Response> {
  if(!chkApi(req,env.SYNC_API_KEY))return new Response("unauth",{status:401});
  const {ids}=await req.json() as {ids:number[]};
  if(!ids?.length)return new Response("bad",{status:400});
  const ph=ids.map(()=>"?").join(",");
  await env.DB.prepare(`UPDATE messages SET processed=1,processed_at=? WHERE id IN (${ph})`).bind(Math.floor(Date.now()/1000),...ids).run();
  return Response.json({ok:true});
}
async function handleStats(req: Request, env: Env): Promise<Response> {
  if(!chkApi(req,env.SYNC_API_KEY))return new Response("unauth",{status:401});
  const pending=await env.DB.prepare(`SELECT COUNT(*) as c FROM messages WHERE processed=0`).first();
  const total=await env.DB.prepare(`SELECT COUNT(*) as c FROM messages`).first();
  const latest=await env.DB.prepare(`SELECT MAX(created_at) as ts FROM messages`).first();
  return Response.json({pending:(pending as any).c,total:(total as any).c,latest_ts:(latest as any).ts});
}
async function handleImageGet(req: Request, env: Env, key: string): Promise<Response> {
  if(!chkApi(req,env.SYNC_API_KEY))return new Response("unauth",{status:401});
  const o=await env.IMAGES.get(key);
  if(!o)return new Response("nf",{status:404});
  const h=new Headers();o.writeHttpMetadata(h);h.set("Cache-Control","public,max-age=86400");
  return new Response(o.body,{headers:h});
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const {pathname:p}=new URL(req.url); const m=req.method;
    if(m==="OPTIONS")return new Response(null,{headers:{"Access-Control-Allow-Origin":"*","Access-Control-Allow-Methods":"GET,POST,OPTIONS","Access-Control-Allow-Headers":"Authorization,Content-Type"}});
    try{
      if(p==="/wechat/callback"&&m==="GET")return handleVerify(req,env);
      if(p==="/wechat/callback"&&m==="POST")return handleMsg(req,env);
      if(p==="/api/pending"&&m==="GET")return handlePending(req,env);
      if(p==="/api/processed"&&m==="POST")return handleProcessed(req,env);
      if(p.startsWith("/api/image/")&&m==="GET")return handleImageGet(req,env,decodeURIComponent(p.slice(11)));
      if(p==="/health"&&m==="GET")return Response.json({ok:true,ts:Math.floor(Date.now()/1000)});
      if(p==="/api/stats"&&m==="GET")return handleStats(req,env);
      return new Response("nf",{status:404});
    }catch(e){console.error(`[fatal] ${e}`);return new Response("err",{status:500});}
  },
};
