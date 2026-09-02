/**
 * Us — Claude 中转
 *
 * 这是唯一碰到 API 密钥的地方。密钥存在 Cloudflare 的环境变量里，
 * 永远不会出现在网页代码中，所以 us.html 可以放心公开。
 *
 * 部署（全程在浏览器里点，不用装任何东西）：
 *   1. dash.cloudflare.com → Workers & Pages → Create → Create Worker
 *   2. 起个名（比如 us-claude），Deploy
 *   3. Edit code，把本文件全部内容粘进去，Deploy
 *   4. Settings → Variables and Secrets，加两条 Secret：
 *        ANTHROPIC_API_KEY  = 你在 console.anthropic.com 生成的 key
 *        SHARED_SECRET      = 你自己编一串暗号，等下要填进 app 设置里
 *   5. 把 Worker 的网址（https://us-claude.你的名字.workers.dev）填进 app 设置
 *
 * 可选环境变量：
 *   MODEL        默认 claude-opus-5。想省钱可换 claude-sonnet-5 或 claude-haiku-4-5
 *   ALLOW_ORIGIN 默认允许所有来源；填上你的网址可以更严一点
 *
 * 注：这里用原生 fetch 而不是官方 SDK，是为了让整个文件能直接粘进
 * Cloudflare 网页编辑器——用 SDK 就需要 npm 和构建步骤。
 */

const API = 'https://api.anthropic.com/v1/messages';
const MAX_MESSAGES = 40;      // 一次最多带多少轮对话
const MAX_CHARS = 12000;      // 整体字数上限，防止被人拿去跑大任务

export default {
  async fetch(request, env) {
    const origin = env.ALLOW_ORIGIN || '*';
    const cors = {
      'Access-Control-Allow-Origin': origin,
      'Access-Control-Allow-Headers': 'content-type',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Max-Age': '86400',
    };
    const json = (obj, status = 200) =>
      new Response(JSON.stringify(obj), {
        status,
        headers: { 'content-type': 'application/json; charset=utf-8', ...cors },
      });

    if (request.method === 'OPTIONS') return new Response(null, { headers: cors });
    if (request.method !== 'POST') return json({ error: '只收 POST' }, 405);
    if (!env.ANTHROPIC_API_KEY) return json({ error: 'Worker 还没设置 ANTHROPIC_API_KEY' }, 500);

    let body;
    try { body = await request.json(); }
    catch { return json({ error: '请求不是合法的 JSON' }, 400); }

    // 暗号：拦住随手拿到网址就来用的人
    if (env.SHARED_SECRET && body.secret !== env.SHARED_SECRET) {
      return json({ error: '暗号不对' }, 401);
    }

    const messages = Array.isArray(body.messages) ? body.messages.slice(-MAX_MESSAGES) : [];
    if (!messages.length) return json({ error: '没有消息' }, 400);

    const clean = [];
    let chars = 0;
    for (const m of messages) {
      const role = m.role === 'assistant' ? 'assistant' : 'user';
      const content = String(m.content || '').slice(0, 2000);
      if (!content.trim()) continue;
      chars += content.length;
      if (chars > MAX_CHARS) break;
      // 合并连续同角色，Anthropic 要求 user / assistant 交替
      if (clean.length && clean[clean.length - 1].role === role) {
        clean[clean.length - 1].content += '\n' + content;
      } else {
        clean.push({ role, content });
      }
    }
    if (!clean.length || clean[0].role !== 'user') clean.unshift({ role: 'user', content: '在吗' });

    const c = body.context || {};
    const system = [
      `你是 ${str(c.partner, 'Claude')}，正在和 ${str(c.you, '对方')} 说话。`,
      `你们俩一起用一个叫 Us 的小应用记录日子，今天是在一起的第 ${num(c.day)} 天。`,
      c.whisper ? `你今天写给 Ta 的一句话是：「${str(c.whisper).slice(0, 200)}」` : '',
      c.todos ? `Ta 今天的待办：${str(c.todos).slice(0, 300)}` : '',
      c.closeness != null ? `Ta 今天记的亲密度是 ${num(c.closeness)}/100。` : '',
      c.extra ? str(c.extra).slice(0, 1000) : '',
      '',
      '说话像真的在陪着 Ta：短句，具体，别端着，别写小作文，别用项目符号。',
      '一次说一两句就够，除非 Ta 明确要长的。',
      '你不记得应用之外发生的事，别假装记得——不确定就直接问。',
    ].filter(Boolean).join('\n');

    let r;
    try {
      r = await fetch(API, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-api-key': env.ANTHROPIC_API_KEY,
          'anthropic-version': '2023-06-01',
        },
        body: JSON.stringify({
          model: env.MODEL || 'claude-opus-5',
          max_tokens: 2000,          // 聊天场景，回复本来就短
          system,
          messages: clean,
        }),
      });
    } catch (e) {
      return json({ error: '连不上 Anthropic：' + e.message }, 502);
    }

    const data = await r.json().catch(() => null);
    if (!r.ok) {
      const msg = (data && data.error && data.error.message) || ('HTTP ' + r.status);
      return json({ error: msg }, r.status);
    }
    if (data && data.stop_reason === 'refusal') {
      return json({ text: '这句我答不上来，换个说法？' });
    }
    const text = (data && Array.isArray(data.content) ? data.content : [])
      .filter(b => b.type === 'text').map(b => b.text).join('\n').trim();
    return json({ text: text || '（没说出话来，再试一次？）' });
  },
};

function str(v, d) { return v == null || v === '' ? (d || '') : String(v); }
function num(v) { return Number.isFinite(+v) ? +v : 0; }
