/**
 * capture_record.js — 抓包记录器
 *
 * 把命中的响应压成一条记录，塞进 $persistentStore 的环形缓冲。
 * 面板由 capture_view.js 提供。
 *
 * 参数（argument）：
 *   cap=<条数上限，默认 60>
 *   full=<1|0，是否存完整 body，默认 0（只存前 2KB 预览）>
 *   skip=<正则，命中则跳过，可选>
 */

'use strict';

var ARG = {};
(function () {
  var raw = (typeof $argument !== 'undefined' && $argument) ? String($argument) : '';
  raw.split('&').forEach(function (kv) {
    if (!kv) return;
    var i = kv.indexOf('=');
    if (i < 0) return;
    var k = kv.slice(0, i), v = kv.slice(i + 1);
    try { v = decodeURIComponent(v); } catch (e) {}
    ARG[k] = v;
  });
})();

var CAP = parseInt(ARG.cap || '60', 10) || 60;
var FULL = ARG.full === '1';
var PREVIEW_LEN = FULL ? 200000 : 2048;

// only=<正则>：URL 必须命中才记。默认只盯装扮/商城/收藏集这一片。
var ONLY_SRC = ARG.only !== undefined ? ARG.only : 'garb|suit|mall|search|vas|digital|collect|space';
var ONLY = null;
try { if (ONLY_SRC) ONLY = new RegExp(ONLY_SRC, 'i'); } catch (e) {}

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

function save(list) {
  try {
    $persistentStore.write(JSON.stringify(list), KEY);
  } catch (e) {
    // 超限就砍半重试
    try { $persistentStore.write(JSON.stringify(list.slice(0, Math.floor(list.length / 2))), KEY); } catch (e2) {}
  }
}

function topKeys(body) {
  try {
    var o = JSON.parse(body);
    if (o && typeof o === 'object' && !Array.isArray(o)) return Object.keys(o).slice(0, 12);
    if (Array.isArray(o)) return ['[array ' + o.length + ']'];
  } catch (e) {}
  return null;
}

/* 找出「像列表」的数组，返回路径和长度，帮判断哪个接口是列表 */
function findList(body) {
  var o;
  try { o = JSON.parse(body); } catch (e) { return null; }
  var best = null;
  (function walk(n, path) {
    if (Array.isArray(n)) {
      if (n.length >= 3 && n.every(function (x) { return x && typeof x === 'object' && !Array.isArray(x); })) {
        if (!best || n.length > best.n) best = { path: path || '/', n: n.length };
      }
      for (var i = 0; i < n.length && i < 3; i++) walk(n[i], path + '/' + i);
    } else if (n && typeof n === 'object') {
      for (var k in n) walk(n[k], path + '/' + k);
    }
  })(o, '');
  return best;
}

(function main() {
  var url = (typeof $request !== 'undefined' && $request) ? $request.url : '';
  var method = (typeof $request !== 'undefined' && $request && $request.method) ? $request.method : 'GET';
  var status = (typeof $response !== 'undefined' && $response && $response.status) ? $response.status : 0;
  var headers = (typeof $response !== 'undefined' && $response && $response.headers) ? $response.headers : {};
  var ct = headers['Content-Type'] || headers['content-type'] || '';
  var body = (typeof $response !== 'undefined' && $response && $response.body) ? $response.body : '';

  // 面板自己的请求不记
  if (url.indexOf('__bili_capture') >= 0) { $done({}); return; }
  if (ONLY && !ONLY.test(url)) { $done({}); return; }

  var rec = {
    ts: Date.now(),
    m: method,
    url: url,
    st: status,
    ct: String(ct).split(';')[0],
    sz: body ? body.length : 0
  };

  if (body && /json|javascript|text/i.test(ct)) {
    var k = topKeys(body);
    if (k) rec.keys = k;
    var lst = findList(body);
    if (lst) rec.list = lst;
    rec.preview = body.slice(0, PREVIEW_LEN);
    if (body.length > PREVIEW_LEN) rec.trunc = true;
  } else if (body) {
    rec.preview = '[非文本 ' + body.length + ' 字节]';
  }

  var list = load();
  list.unshift(rec);
  if (list.length > CAP) list = list.slice(0, CAP);
  save(list);

  $done({});
})();
