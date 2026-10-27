/**
 * capture_view.js — 抓包面板
 *
 * 访问 https://api.bilibili.com/__bili_capture 看结果。
 *   ?clear=1   清空
 *   ?json=1    返回原始 JSON
 *   ?q=关键字  预置筛选
 */

'use strict';

(function () {

var KEY = 'bili_capture_v1';

function load() {
  try {
    var raw = $persistentStore.read(KEY);
    if (!raw) return [];
    var o = JSON.parse(raw);
    return Array.isArray(o) ? o : [];
  } catch (e) {
    return [];
  }
}

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function pad(n) { return n < 10 ? '0' + n : '' + n; }

function hhmmss(ts) {
  var d = new Date(ts);
  return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
}

function kb(n) {
  if (!n) return '-';
  if (n < 1024) return n + 'B';
  return (n / 1024).toFixed(1) + 'K';
}

function pathOf(u) {
  try {
    var m = String(u).match(/^https?:\/\/[^/]+(\/[^?]*)/);
    return m ? m[1] : u;
  } catch (e) { return u; }
}

function queryOf(u) {
  var i = String(u).indexOf('?');
  return i < 0 ? '' : String(u).slice(i + 1);
}

var url = (typeof $request !== 'undefined' && $request && $request.url) ? $request.url : '';
var qs = queryOf(url);

if (/[?&]clear=1/.test(url)) {
  $persistentStore.write('[]', KEY);
  $done({
    response: {
      status: 200,
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
      body: '<!DOCTYPE html><meta charset="utf-8"><body style="background:#0d0f14;color:#e8ecf4;font:15px -apple-system;padding:40px;text-align:center">已清空<br><br><a href="/__bili_capture" style="color:#fb7299">返回</a></body>'
    }
  });
  return;
}

var list = load();

if (/[?&]json=1/.test(url)) {
  $done({
    response: {
      status: 200,
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify(list, null, 1)
    }
  });
  return;
}

var preQ = '';
var mq = /[?&]q=([^&]*)/.exec(url);
if (mq) { try { preQ = decodeURIComponent(mq[1]); } catch (e) {} }

var rows = list.map(function (r, i) {
  var hit = /search|mall|garb|suit/i.test(r.url) ? ' hot' : '';
  var listTag = r.list
    ? '<span class="tag">列表 ' + esc(r.list.path) + ' ×' + r.list.n + '</span>'
    : '';
  var keys = (r.keys || []).join(', ');
  return '' +
    '<div class="row' + hit + '" data-u="' + esc(r.url.toLowerCase()) + '">' +
      '<div class="hd" onclick="tg(this)">' +
        '<span class="m ' + esc(r.m) + '">' + esc(r.m) + '</span>' +
        '<span class="st s' + (r.st >= 400 ? 'e' : r.st >= 300 ? 'w' : 'o') + '">' + esc(r.st) + '</span>' +
        '<span class="t">' + hhmmss(r.ts) + '</span>' +
        '<span class="sz">' + kb(r.sz) + '</span>' +
        '<span class="p">' + esc(pathOf(r.url)) + '</span>' +
      '</div>' +
      '<div class="bd">' +
        '<div class="url">' + esc(r.url) + '</div>' +
        '<div class="meta">' + esc(r.ct) + listTag + '</div>' +
        (keys ? '<div class="keys">keys: ' + esc(keys) + '</div>' : '') +
        (r.preview ? '<pre>' + esc(r.preview) + (r.trunc ? '\n… 已截断' : '') + '</pre>' : '') +
      '</div>' +
    '</div>';
}).join('');

var html = [
  '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
  '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">',
  '<title>抓包 ' + list.length + '</title><style>',
  ':root{--bg:#0d0f14;--pn:#161a22;--ln:#232936;--fg:#e8ecf4;--dm:#8b95a8;--pk:#fb7299}',
  '*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);',
  'font:14px/1.5 -apple-system,"PingFang SC",sans-serif;padding-bottom:40px}',
  'header{position:sticky;top:0;z-index:9;background:rgba(13,15,20,.94);backdrop-filter:blur(12px);',
  'border-bottom:1px solid var(--ln);padding:12px 14px}',
  'h1{margin:0 0 8px;font-size:15px;font-weight:600}',
  'h1 b{color:var(--pk)}',
  'input{width:100%;padding:9px 12px;border-radius:10px;border:1px solid var(--ln);',
  'background:var(--pn);color:var(--fg);font-size:14px;outline:none;-webkit-appearance:none}',
  'input:focus{border-color:var(--pk)}',
  '.bar{display:flex;gap:8px;margin-top:8px}',
  '.bar a{flex:1;text-align:center;padding:7px;border-radius:8px;border:1px solid var(--ln);',
  'color:var(--dm);text-decoration:none;font-size:13px}',
  '.bar a:active{background:var(--pn)}',
  '.row{border-bottom:1px solid var(--ln);background:var(--pn)}',
  '.row.hot{background:#1a1620}',
  '.hd{display:flex;align-items:center;gap:8px;padding:10px 12px;cursor:pointer}',
  '.m{font-size:10px;font-weight:700;padding:1px 5px;border-radius:4px;background:#2a3140;color:var(--dm)}',
  '.m.GET{background:#123a2e;color:#4ade80}.m.POST{background:#3a2a12;color:#fbbf24}',
  '.st{font-size:11px;font-variant-numeric:tabular-nums}',
  '.st.so{color:#4ade80}.st.sw{color:#fbbf24}.st.se{color:#fb7299}',
  '.t{font-size:11px;color:var(--dm);font-variant-numeric:tabular-nums}',
  '.sz{font-size:11px;color:var(--dm);font-variant-numeric:tabular-nums;min-width:42px;text-align:right}',
  '.p{flex:1;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
  '.bd{display:none;padding:0 12px 12px}',
  '.row.open .bd{display:block}',
  '.url{font-size:11px;color:var(--dm);word-break:break-all;margin-bottom:6px}',
  '.meta{font-size:11px;color:var(--dm);margin-bottom:6px}',
  '.tag{display:inline-block;margin-left:8px;padding:1px 6px;border-radius:4px;',
  'background:#3a1f2b;color:var(--pk);font-size:10px}',
  '.keys{font-size:11px;color:#7c8aa5;margin-bottom:6px;word-break:break-all}',
  'pre{margin:0;padding:10px;background:#0a0c11;border:1px solid var(--ln);border-radius:8px;',
  'font-size:11px;line-height:1.5;overflow:auto;max-height:340px;white-space:pre-wrap;word-break:break-all}',
  '.empty{padding:60px 20px;text-align:center;color:var(--dm);line-height:2}',
  'code{background:var(--pn);padding:2px 6px;border-radius:4px;font-size:12px}',
  '</style></head><body>',
  '<header><h1>抓包 <b>' + list.length + '</b> 条</h1>',
  '<input id="q" placeholder="筛 URL，比如 search / mall / garb" value="' + esc(preQ) + '">',
  '<div class="bar"><a href="/__bili_capture?json=1">JSON</a>',
  '<a href="/__bili_capture?clear=1" onclick="return confirm(\'清空？\')">清空</a></div></header>',
  list.length ? rows : '<div class="empty">还没有抓到东西<br><br>确认 MITM 已开、证书已信任<br>然后去 App 里操作几下</div>',
  '<script>',
  'var q=document.getElementById("q");',
  'function flt(){var v=q.value.trim().toLowerCase();',
  'document.querySelectorAll(".row").forEach(function(r){',
  'r.style.display=(!v||r.dataset.u.indexOf(v)>=0)?"":"none";});}',
  'q.addEventListener("input",flt);flt();',
  'function tg(el){el.parentNode.classList.toggle("open");}',
  'window.tg=tg;',
  '</script></body></html>'
].join('');

$done({
  response: {
    status: 200,
    headers: { 'Content-Type': 'text/html; charset=utf-8' },
    body: html
  }
});
})();
