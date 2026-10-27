/**
 * garb_mall_inject.js — 装扮商城显示已下架装扮
 *
 * 拦截装扮商城列表响应，把下架条目注入进去。
 * schema 在运行时自动识别，不依赖预先抓包。
 *
 * 依赖：catalog.json（下架装扮库，由 garb_mall/catalog.py 生成）
 *
 * 模块参数（argument）：
 *   catalog=<catalog.json 的 raw URL>
 *   suffix=<名称后缀，默认「（已下架）」>
 *   force=<1|0，是否把状态改成在售值，默认 1>
 *   debug=<1|0，打印识别结果，默认 0>
 */

'use strict';

/* ---------------------------------------------------------------- 参数 */

var ARG = {};
(function () {
  var raw = (typeof $argument !== 'undefined' && $argument) ? String($argument) : '';
  raw.split('&').forEach(function (kv) {
    if (!kv) return;
    var i = kv.indexOf('=');
    if (i < 0) return;
    var k = kv.slice(0, i);
    var v = kv.slice(i + 1);
    try { v = decodeURIComponent(v); } catch (e) {}
    ARG[k] = v;
  });
})();

var CATALOG_URL = ARG.catalog || '';
var LIVE_VMID = parseInt(ARG.vmid || '0', 10) || 0;   // 设了就现取，不用建库
var MODE = ARG.mode || 'item';   // item=装扮/搜索结果  theme=主题包列表
var SUFFIX = ARG.suffix || '（已下架）';
var FORCE_ONSALE = ARG.force !== '0';
var DEBUG = ARG.debug === '1';

var CACHE_KEY = 'bili_garb_catalog_v1';
var CACHE_TTL = 6 * 60 * 60 * 1000;   // 6 小时

var PUNCT_RE = /[\s·・\-_/\\|,，。.、:：;；!！?？()（）\[\]【】"'“”‘’]+/g;

function norm(s) {
  return String(s || '').toLowerCase().replace(PUNCT_RE, '');
}

// 搜索接口的 key_word —— 有就按名字过滤，没有就全注入（商城浏览场景）
function keywordOf() {
  var u = (typeof $request !== 'undefined' && $request && $request.url) ? $request.url : '';
  var m = /[?&]key_word=([^&]*)/.exec(u);
  if (!m) return '';
  try { return decodeURIComponent(m[1].replace(/\+/g, ' ')); } catch (e) { return ''; }
}

function log() {
  if (DEBUG) console.log.apply(console, arguments);
}

function done(body) {
  if (body === undefined) $done({});
  else $done({ body: body });
}

/* ------------------------------------------------------------ 结构识别 */

var ID_RE = /(^|_)(id|item_id|suit_id|garb_id|act_id)$/i;
var ID_RE_CAMEL = /(Id|ID)$/;
var NAME_RE = /(^|_)(name|title|item_name|suit_name)$/i;
var NAME_RE_CAMEL = /(Name|Title)$/;
var COVER_RE = /(cover|img|image|pic|poster|suit_img)/i;
var COUNT_RE = /(^|_)(total|total_count|count|has_more)$/i;
var COUNT_RE_CAMEL = /(Total|TotalCount|Count|HasMore)$/;

function isObj(x) {
  return x && typeof x === 'object' && !Array.isArray(x);
}

function findArrays(node, path, out, min) {
  min = min || 3;
  if (Array.isArray(node)) {
    var ok = node.length >= min && node.every(isObj);
    // 小数组只在带 ID 字段时才收（搜索结果常常只有 1-2 条）
    if (ok && (min >= 3 || hasIdField(node))) out.push({ path: path || '/', arr: node });
    for (var i = 0; i < node.length; i++) findArrays(node[i], path + '/' + i, out, min);
  } else if (isObj(node)) {
    for (var k in node) {
      if (Object.prototype.hasOwnProperty.call(node, k)) findArrays(node[k], path + '/' + k, out, min);
    }
  }
  return out;
}

function hasIdField(arr) {
  var keys = {};
  arr.slice(0, 5).forEach(function (it) {
    Object.keys(it).forEach(function (k) { keys[k] = 1; });
  });
  return Object.keys(keys).some(function (k) {
    return ID_RE.test(k) || ID_RE_CAMEL.test(k);
  });
}

function scoreArray(path, arr) {
  var s = arr.length * (hasIdField(arr) ? 10 : 1);
  s += Math.max(0, 20 - (path.split('/').length - 1) * 2);
  return s;
}

function detectStatus(keyVals, exclude) {
  exclude = exclude || [];
  var named = null, fallback = null;

  for (var k in keyVals) {
    if (exclude.indexOf(k) >= 0) continue;          // ID / 名称 / 封面字段不参与
    var vals = keyVals[k];
    if (!vals || !vals.length) continue;

    var uniq = {};
    vals.forEach(function (v) { uniq[String(v)] = (uniq[String(v)] || 0) + 1; });
    var keys = Object.keys(uniq);
    if (keys.length < 1 || keys.length > 5) continue;

    var numeric = keys.every(function (v) {
      return /^\d+$/.test(v) || v === 'true' || v === 'false';
    });
    if (!numeric) continue;

    // 全表同值也能当状态（比如全场在售），但优先级最低
    // 只认「名字本身就是状态」的字段；sale_start / sale_time 这类不算
    var looksLikeStatus = /(status|state|shelf|online|hide|sold)/i.test(k);

    if (looksLikeStatus) {
      if (!named || keys.length > Object.keys(named.values).length) {
        named = { field: k, values: uniq };
      }
    } else if (keys.length >= 2) {
      if (!fallback || keys.length < Object.keys(fallback.values).length) {
        fallback = { field: k, values: uniq };
      }
    }
  }

  var best = named || fallback;
  return best ? { field: best.field, values: best.values } : { field: null, values: {} };
}

function pickList(obj) {
  // 先按 >=3 找；找不到再放宽到 >=1（但要带 ID 字段）
  var cands = findArrays(obj, '', [], 3);
  if (!cands.length) cands = findArrays(obj, '', [], 1);
  if (!cands.length) return null;
  cands.sort(function (a, b) { return scoreArray(b.path, b.arr) - scoreArray(a.path, a.arr); });
  return cands[0];
}

function analyze(obj) {
  var picked = pickList(obj);
  if (!picked) return null;

  var arr = picked.arr;
  var path = picked.path;

  var keyUnion = [];
  var seen = {};
  arr.forEach(function (it) {
    Object.keys(it).forEach(function (k) {
      if (!seen[k]) { seen[k] = 1; keyUnion.push(k); }
    });
  });

  var template = arr.reduce(function (a, b) { return Object.keys(b).length > Object.keys(a).length ? b : a; }, arr[0]);

  var keyVals = {};
  arr.forEach(function (it) {
    Object.keys(it).forEach(function (k) {
      var v = it[k];
      if (typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean') {
        (keyVals[k] = keyVals[k] || []).push(v);
      }
    });
  });

  var idFieldsPre = keyUnion.filter(function (k) { return ID_RE.test(k) || ID_RE_CAMEL.test(k); });
  var nameFieldsPre = keyUnion.filter(function (k) { return NAME_RE.test(k) || NAME_RE_CAMEL.test(k); });
  var coverFieldsPre = keyUnion.filter(function (k) { return COVER_RE.test(k); });

  var st = detectStatus(keyVals, idFieldsPre.concat(nameFieldsPre, coverFieldsPre));

  var idFields = keyUnion.filter(function (k) { return ID_RE.test(k) || ID_RE_CAMEL.test(k); })
    .sort(function (a, b) {
      function rank(x) {
        var s = x.toLowerCase();
        if (s.indexOf('item') >= 0) return 0;
        if (s.indexOf('suit') >= 0) return 1;
        if (s.indexOf('garb') >= 0) return 2;
        if (s.indexOf('act') >= 0) return 9;
        return 5;
      }
      return rank(a) - rank(b);
    });

  var countFields = keyUnion.filter(function (k) { return COUNT_RE.test(k) || COUNT_RE_CAMEL.test(k); });

  // 父级上的计数字段（total / has_more 通常在数组的父字典里）
  var parent = obj;
  var segs = path.split('/').filter(function (x) { return x; }).slice(0, -1);
  for (var i = 0; i < segs.length; i++) {
    if (!parent) break;
    parent = Array.isArray(parent) ? parent[parseInt(segs[i], 10)] : parent[segs[i]];
  }
  if (isObj(parent)) {
    Object.keys(parent).forEach(function (k) {
      var v = parent[k];
      if ((typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean')
        && (COUNT_RE.test(k) || COUNT_RE_CAMEL.test(k)) && countFields.indexOf(k) < 0) {
        countFields.push(k);
      }
    });
  }

  // 在售值 = 状态字段里出现最多的那个
  var onsaleValue = null;
  var stKeys = Object.keys(st.values);
  if (stKeys.length) {
    stKeys.sort(function (a, b) { return st.values[b] - st.values[a]; });
    onsaleValue = stKeys[0];
  }

  return {
    path: path,
    arr: arr,
    parent: parent,
    template: template,
    keyUnion: keyUnion,
    idFields: idFields,
    nameFields: keyUnion.filter(function (k) { return NAME_RE.test(k) || NAME_RE_CAMEL.test(k); }),
    coverFields: keyUnion.filter(function (k) { return COVER_RE.test(k); }),
    countFields: countFields,
    statusField: st.field,
    statusValues: st.values,
    onsaleValue: onsaleValue
  };
}

/* ---------------------------------------------------------------- 注入 */

function clone(o) {
  return JSON.parse(JSON.stringify(o));
}

function inject(info, items) {
  if (!info || !info.arr || !items || !items.length) return 0;

  var arr = info.arr;
  var idKey = info.idFields[0];
  if (!idKey) return 0;

  var existing = {};
  arr.forEach(function (it) {
    if (isObj(it) && it[idKey] !== undefined) existing[String(it[idKey])] = 1;
  });

  var added = 0;
  var onSale = info.onsaleValue;

  items.forEach(function (src) {
    var gid = String(src.garb_id);
    if (existing[gid]) return;

    var it = clone(info.template);

    // 清掉模板里不属于字段并集的键
    if (info.keyUnion.length) {
      Object.keys(it).forEach(function (k) {
        if (info.keyUnion.indexOf(k) < 0) delete it[k];
      });
    }

    // ID（跳过 act_id，那是活动号）
    info.idFields.forEach(function (f) {
      if (f.toLowerCase().indexOf('act') >= 0) return;
      if (f in it || info.keyUnion.indexOf(f) >= 0) it[f] = src.garb_id;
    });

    // 名称
    var nm = (src.name || src.title || '装扮') + SUFFIX;
    info.nameFields.forEach(function (f) { if (f in it) it[f] = nm; });

    // 封面
    var img = src.large || src.small || '';
    info.coverFields.forEach(function (f) { if (f in it) it[f] = img; });

    // 状态（绝不能覆盖 ID 字段）
    if (info.statusField && info.statusField in it
        && info.idFields.indexOf(info.statusField) < 0) {
      if (FORCE_ONSALE && onSale !== null) {
        it[info.statusField] = /^\d+$/.test(onSale) ? parseInt(onSale, 10) : onSale;
      }
    }

    // 跳转 URL 里的 item_id 跟着换
    Object.keys(it).forEach(function (k) {
      var v = it[k];
      if (typeof v === 'string' && (v.indexOf('item_id=') >= 0 || v.indexOf('suit_id=') >= 0)) {
        it[k] = v.replace(/(item_id|suit_id)=\d+/g, function (m, g) { return g + '=' + src.garb_id; });
      }
    });

    // 价格 / 库存 / 角标降级
    ['price_str', 'priceStr', 'price_text', 'priceText'].forEach(function (f) {
      if (f in it) it[f] = '已下架';
    });
    ['price', 'sale_price', 'salePrice', 'stock', 'remain', 'left'].forEach(function (f) {
      if (f in it) it[f] = 0;
    });
    ['tag', 'tag_text', 'tagText', 'badge', 'badge_text'].forEach(function (f) {
      if (f in it) it[f] = '已下架';
    });
    ['tag_color', 'tagColor', 'badge_color'].forEach(function (f) {
      if (f in it) it[f] = '#8B95A8';
    });

    arr.push(it);
    existing[gid] = 1;
    added++;
  });

  if (added && isObj(info.parent)) {
    info.countFields.forEach(function (f) {
      if (!(f in info.parent)) return;
      var v = info.parent[f];
      if (typeof v === 'number' && f.toLowerCase().indexOf('more') < 0) info.parent[f] = v + added;
    });
  }

  return added;
}

/* 紧凑 MD5，返回小写 hex */
function md5(s) {
  function rl(n, c) { return (n << c) | (n >>> (32 - c)); }
  function au(x, y) { var l = (x & 0xFFFF) + (y & 0xFFFF); return (((x >> 16) + (y >> 16) + (l >> 16)) << 16) | (l & 0xFFFF); }
  function cmn(q, a, b, x, s, t) { return au(rl(au(au(a, q), au(x, t)), s), b); }
  function ff(a,b,c,d,x,s,t){return cmn((b&c)|((~b)&d),a,b,x,s,t);}
  function gg(a,b,c,d,x,s,t){return cmn((b&d)|(c&(~d)),a,b,x,s,t);}
  function hh(a,b,c,d,x,s,t){return cmn(b^c^d,a,b,x,s,t);}
  function ii(a,b,c,d,x,s,t){return cmn(c^(b|(~d)),a,b,x,s,t);}
  var u = unescape(encodeURIComponent(s));
  var n = u.length, w = [], i;
  for (i = 0; i < n * 8; i += 8) w[i >> 5] = (w[i >> 5] || 0) | (u.charCodeAt(i / 8) << (i % 32));
  w[n >> 2] = (w[n >> 2] || 0) | (0x80 << ((n % 4) * 8));
  var L = (((n + 8) >> 6) + 1) * 16;
  while (w.length < L) w.push(0);
  w[L - 2] = n * 8;
  w[L - 1] = Math.floor(n / 0x20000000);
  var a = 1732584193, b = -271733879, c = -1732584194, d = 271733878;
  for (i = 0; i < L; i += 16) {
    var oa=a,ob=b,oc=c,od=d;
    a=ff(a,b,c,d,w[i],7,-680876936);   d=ff(d,a,b,c,w[i+1],12,-389564586);
    c=ff(c,d,a,b,w[i+2],17,606105819); b=ff(b,c,d,a,w[i+3],22,-1044525330);
    a=ff(a,b,c,d,w[i+4],7,-176418897); d=ff(d,a,b,c,w[i+5],12,1200080426);
    c=ff(c,d,a,b,w[i+6],17,-1473231341);b=ff(b,c,d,a,w[i+7],22,-45705983);
    a=ff(a,b,c,d,w[i+8],7,1770035416); d=ff(d,a,b,c,w[i+9],12,-1958414417);
    c=ff(c,d,a,b,w[i+10],17,-42063);   b=ff(b,c,d,a,w[i+11],22,-1990404162);
    a=ff(a,b,c,d,w[i+12],7,1804603682);d=ff(d,a,b,c,w[i+13],12,-40341101);
    c=ff(c,d,a,b,w[i+14],17,-1502002290);b=ff(b,c,d,a,w[i+15],22,1236535329);
    a=gg(a,b,c,d,w[i+1],5,-165796510); d=gg(d,a,b,c,w[i+6],9,-1069501632);
    c=gg(c,d,a,b,w[i+11],14,643717713);b=gg(b,c,d,a,w[i],20,-373897302);
    a=gg(a,b,c,d,w[i+5],5,-701558691); d=gg(d,a,b,c,w[i+10],9,38016083);
    c=gg(c,d,a,b,w[i+15],14,-660478335);b=gg(b,c,d,a,w[i+4],20,-405537848);
    a=gg(a,b,c,d,w[i+9],5,568446438);  d=gg(d,a,b,c,w[i+14],9,-1019803690);
    c=gg(c,d,a,b,w[i+3],14,-187363961);b=gg(b,c,d,a,w[i+8],20,1163531501);
    a=gg(a,b,c,d,w[i+13],5,-1444681467);d=gg(d,a,b,c,w[i+2],9,-51403784);
    c=gg(c,d,a,b,w[i+7],14,1735328473);b=gg(b,c,d,a,w[i+12],20,-1926607734);
    a=hh(a,b,c,d,w[i+5],4,-378558);    d=hh(d,a,b,c,w[i+8],11,-2022574463);
    c=hh(c,d,a,b,w[i+11],16,1839030562);b=hh(b,c,d,a,w[i+14],23,-35309556);
    a=hh(a,b,c,d,w[i+1],4,-1530992060);d=hh(d,a,b,c,w[i+4],11,1272893353);
    c=hh(c,d,a,b,w[i+7],16,-155497632);b=hh(b,c,d,a,w[i+10],23,-1094730640);
    a=hh(a,b,c,d,w[i+13],4,681279174); d=hh(d,a,b,c,w[i],11,-358537222);
    c=hh(c,d,a,b,w[i+3],16,-722521979);b=hh(b,c,d,a,w[i+6],23,76029189);
    a=hh(a,b,c,d,w[i+9],4,-640364487); d=hh(d,a,b,c,w[i+12],11,-421815835);
    c=hh(c,d,a,b,w[i+15],16,530742520);b=hh(b,c,d,a,w[i+2],23,-995338651);
    a=ii(a,b,c,d,w[i],6,-198630844);   d=ii(d,a,b,c,w[i+7],10,1126891415);
    c=ii(c,d,a,b,w[i+14],15,-1416354905);b=ii(b,c,d,a,w[i+5],21,-57434055);
    a=ii(a,b,c,d,w[i+12],6,1700485571);d=ii(d,a,b,c,w[i+3],10,-1894986606);
    c=ii(c,d,a,b,w[i+10],15,-1051523); b=ii(b,c,d,a,w[i+1],21,-2054922799);
    a=ii(a,b,c,d,w[i+8],6,1873313359); d=ii(d,a,b,c,w[i+15],10,-30611744);
    c=ii(c,d,a,b,w[i+6],15,-1560198380);b=ii(b,c,d,a,w[i+13],21,1309151649);
    a=ii(a,b,c,d,w[i+4],6,-145523070); d=ii(d,a,b,c,w[i+11],10,-1120210379);
    c=ii(c,d,a,b,w[i+2],15,718787259); b=ii(b,c,d,a,w[i+9],21,-343485551);
    a=au(a,oa); b=au(b,ob); c=au(c,oc); d=au(d,od);
  }
  function hex(v){var o='',j;for(j=0;j<4;j++)o+=('0'+((v>>(j*8))&255).toString(16)).slice(-2);return o;}
  return hex(a)+hex(b)+hex(c)+hex(d);
}

/* ---------------------------------------------------------- 主题包模式 */

var THEME_ID_RE = /^(themeId|theme_id|id)$/;
var THEME_URL_RE = /^(downloadUrl|download_url|package_url|packageUrl)$/;

function isThemePkg(o) {
  if (!isObj(o)) return false;
  var hasId = false, hasRes = false, k;
  for (k in o) {
    if (THEME_ID_RE.test(k)) hasId = true;
    if (THEME_URL_RE.test(k) || k === 'themeDic' || k === 'resourcePath') hasRes = true;
  }
  return hasId && hasRes;
}

function findThemeArray(node, path, out) {
  if (Array.isArray(node)) {
    if (node.length && node.every(isThemePkg)) out.push({ path: path || '/', arr: node });
    for (var i = 0; i < node.length; i++) findThemeArray(node[i], path + '/' + i, out);
  } else if (isObj(node)) {
    for (var k in node) {
      if (Object.prototype.hasOwnProperty.call(node, k)) findThemeArray(node[k], path + '/' + k, out);
    }
  }
  return out;
}

function injectThemes(obj, pkgs) {
  var cands = findThemeArray(obj, '', []);
  if (!cands.length) return { added: 0, path: null };
  cands.sort(function (a, b) { return b.arr.length - a.arr.length; });
  var hit = cands[0];
  var arr = hit.arr;

  var have = {};
  arr.forEach(function (x) {
    var id = x.themeId || x.theme_id || x.id;
    if (id !== undefined) have[String(id)] = 1;
  });

  var added = 0;
  pkgs.forEach(function (pkg) {
    var id = String(pkg.themeId);
    if (have[id]) return;   // 已经有的不重复塞
    arr.push(clone(pkg));
    have[id] = 1;
    added++;
  });

  return { added: added, path: hit.path, total: arr.length };
}

/* ------------------------------------------------------------ 现取模式 */

var APPKEY = '27eb53fc9058f8c3';
var APPSEC = 'c2ed53a74eeefe3cf99fbd01d8c9c375';
var LIVE_TTL = 6 * 60 * 60 * 1000;

function signQs(params) {
  var p = {}, k;
  for (k in params) p[k] = params[k];
  p.appkey = APPKEY;
  p.ts = String(Math.floor(Date.now() / 1000));
  p.build = '90102100';
  p.mobi_app = 'iphone';
  p.platform = 'ios';

  var keys = Object.keys(p).sort();
  var qs = keys.map(function (x) {
    return encodeURIComponent(x) + '=' + encodeURIComponent(p[x]);
  }).join('&');

  return qs + '&sign=' + md5(qs + APPSEC);
}

/* 拉某个用户的「我的装扮」，返回和 catalog 一样形状的数组 */
function getLive(vmid, cb) {
  var ck = 'bili_live_garb_' + vmid;
  var cached = null;
  try {
    var raw = $persistentStore.read(ck);
    if (raw) cached = JSON.parse(raw);
  } catch (e) {}

  if (cached && cached.ts && (Date.now() - cached.ts < LIVE_TTL) && cached.items) {
    log('[garb] 现取：用缓存，' + cached.items.length + ' 条');
    cb(cached.items);
    return;
  }

  var url = 'https://app.bilibili.com/x/v2/space/garb/list?' +
            signQs({ vmid: vmid, ps: 50, pn: 1 });

  $httpClient.get({ url: url }, function (err, resp, body) {
    if (err || !body) {
      log('[garb] 现取失败，回退缓存');
      cb(cached ? cached.items : []);
      return;
    }
    var items = [];
    try {
      var d = JSON.parse(body);
      var list = (d.data && d.data.list) || [];
      list.forEach(function (x) {
        var uri = (x.button && x.button.uri) || '';
        var m = /[?&]id=(\d+)/.exec(uri);
        if (!m) return;
        var imgs = x.images || [];
        items.push({
          garb_id: parseInt(m[1], 10),
          image_id: x.garb_id,
          name: x.garb_title || '',
          title: x.garb_title || '',
          large: (imgs[0] && (imgs[0].large_image || imgs[0].small_image)) || '',
          images: imgs.map(function (i) { return i.large_image || i.small_image; }),
          fans_number: x.fans_number || '',
          status: 'live'
        });
      });
    } catch (e) {
      log('[garb] 现取解析失败: ' + e);
    }
    try {
      $persistentStore.write(JSON.stringify({ ts: Date.now(), items: items }), ck);
    } catch (e) {}
    log('[garb] 现取：vmid=' + vmid + ' 拿到 ' + items.length + ' 条');
    cb(items);
  });
}

/* ---------------------------------------------------------------- 目录 */

function readCache() {
  try {
    var raw = $persistentStore.read(CACHE_KEY);
    if (!raw) return null;
    var o = JSON.parse(raw);
    if (!o || !o.items) return null;
    return o;
  } catch (e) {
    return null;
  }
}

function getCatalog(cb) {
  var cached = readCache();
  var fresh = cached && cached.ts && (Date.now() - cached.ts < CACHE_TTL);

  if (fresh) {
    log('[garb] 用缓存目录，' + cached.items.length + ' 条');
    cb(cached.items);
    return;
  }

  if (!CATALOG_URL) {
    log('[garb] 没有 catalog 地址，用缓存');
    cb(cached ? cached.items : []);
    return;
  }

  $httpClient.get({
    url: CATALOG_URL,
    headers: { 'Cache-Control': 'no-cache', 'User-Agent': 'Surge-GarbMall/1.0' }
  }, function (err, resp, body) {
    if (!err && body) {
      try {
        var o = JSON.parse(body);
        // 主题模式优先取 packages
        var items = (MODE === 'theme' && o.packages) ? o.packages : (o.items || o);
        if (Array.isArray(items)) {
          $persistentStore.write(JSON.stringify({ ts: Date.now(), items: items }), CACHE_KEY);
          log('[garb] 目录已更新，' + items.length + ' 条');
          cb(items);
          return;
        }
      } catch (e) {
        log('[garb] 目录解析失败: ' + e);
      }
    }
    log('[garb] 拉取失败，回退缓存');
    cb(cached ? cached.items : []);
  });
}

/* ---------------------------------------------------------------- 主流程 */

function runTheme(obj) {
  getCatalog(function (raw) {
    var pkgs = (raw || []).filter(function (x) { return x && x.themeId && x.downloadUrl; });
    if (!pkgs.length) {
      // catalog 是 themes 文件：packages 在顶层
      log('[garb] 主题模式需要 packages 数组，检查 catalog 是否指向 catalog-themes.json');
      done();
      return;
    }
    var r = injectThemes(obj, pkgs);
    if (!r.added) {
      log('[garb] 主题列表里没找到可注入的位置，或都已存在');
      done();
      return;
    }
    log('[garb] 注入主题 ' + r.added + ' 个 → ' + r.path + '，共 ' + r.total + ' 个');
    done(JSON.stringify(obj));
  });
}

(function main() {
  if (typeof $response === 'undefined' || !$response || !$response.body) {
    done();
    return;
  }

  var obj;
  try {
    obj = JSON.parse($response.body);
  } catch (e) {
    done();
    return;
  }

  if (MODE === 'theme') { runTheme(obj); return; }

  var info = analyze(obj);
  if (!info || !info.arr || info.arr.length < 1) {
    log('[garb] 响应里没有像列表的数组，跳过');
    done();
    return;
  }

  log('[garb] 列表路径 ' + info.path + '，' + info.arr.length + ' 条');
  log('[garb] id=' + info.idFields + ' status=' + info.statusField + '=' + JSON.stringify(info.statusValues));

  function handle(items) {
    var live = !CATALOG_URL && LIVE_VMID > 0;
    // catalog 模式只注入不可买的；现取模式全收（那是你自己的收藏）
    var cand = (items || []).filter(function (x) {
      if (!x || !x.garb_id) return false;
      if (live) return true;
      return x.status === 'gone' || x.status === 'soldout' || x.status === 'delisted';
    });

    // 搜索场景：只注入名字命中的
    var kw = keywordOf();
    if (kw) {
      var nk = norm(kw);
      cand = cand.filter(function (x) {
        return norm(x.name).indexOf(nk) >= 0 || norm(x.title).indexOf(nk) >= 0;
      });
      log('[garb] 关键词 "' + kw + '" 命中 ' + cand.length + ' 条');
    }

    // 一次最多注入 20 条，别把列表撑爆
    if (cand.length > 20) cand = cand.slice(0, 20);

    if (!cand.length) {
      log('[garb] 没有可注入的条目');
      done();
      return;
    }

    var added = inject(info, cand);
    if (!added) {
      log('[garb] 无需注入');
      done();
      return;
    }

    log('[garb] 注入 ' + added + ' 条，' + info.arr.length + ' 条总计');
    done(JSON.stringify(obj));
  }

  if (CATALOG_URL) getCatalog(handle);
  else if (LIVE_VMID > 0) getLive(LIVE_VMID, handle);
  else { log('[garb] 既没有 catalog 也没有 vmid，跳过'); done(); }
})();
