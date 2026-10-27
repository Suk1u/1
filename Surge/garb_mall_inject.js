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
var SUFFIX = ARG.suffix || '（已下架）';
var FORCE_ONSALE = ARG.force !== '0';
var DEBUG = ARG.debug === '1';

var CACHE_KEY = 'bili_garb_catalog_v1';
var CACHE_TTL = 6 * 60 * 60 * 1000;   // 6 小时

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

function findArrays(node, path, out) {
  if (Array.isArray(node)) {
    if (node.length >= 3 && node.every(isObj)) out.push({ path: path || '/', arr: node });
    for (var i = 0; i < node.length; i++) findArrays(node[i], path + '/' + i, out);
  } else if (isObj(node)) {
    for (var k in node) {
      if (Object.prototype.hasOwnProperty.call(node, k)) findArrays(node[k], path + '/' + k, out);
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
    var looksLikeStatus = /(status|state|sale|shelf|online|hide)/i.test(k);

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
  var cands = findArrays(obj, '', []);
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
        var items = o.items || o;
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

  var info = analyze(obj);
  if (!info || !info.arr || info.arr.length < 3) {
    log('[garb] 响应里没有像列表的数组，跳过');
    done();
    return;
  }

  log('[garb] 列表路径 ' + info.path + '，' + info.arr.length + ' 条');
  log('[garb] id=' + info.idFields + ' status=' + info.statusField + '=' + JSON.stringify(info.statusValues));

  getCatalog(function (items) {
    var delisted = (items || []).filter(function (x) {
      return x && x.garb_id && (x.status === 'delisted' || x.status === undefined);
    });

    if (!delisted.length) {
      log('[garb] 目录里没有下架条目');
      done();
      return;
    }

    var added = inject(info, delisted);
    if (!added) {
      log('[garb] 无需注入');
      done();
      return;
    }

    log('[garb] 注入 ' + added + ' 条，' + info.arr.length + ' 条总计');
    done(JSON.stringify(obj));
  });
})();
