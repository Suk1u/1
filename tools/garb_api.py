#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""garb_api.py — 装扮商城接口客户端（抓包验证过的真实契约）

这三个接口都是匿名可调，不需要 appkey / sign / access_key。

    search   按中文名搜
    detail   按 item_id 取套装详情
    walk     用 filtered_item_ids 游标遍历全量在售目录
    check    批量查若干 id 的状态
    hunt     枚举 id 区间找装扮

用法:
    python garb_api.py search 欧皇
    python garb_api.py detail 120730201
    python garb_api.py walk --rounds 20
    python garb_api.py check 41042 120730201 118048902
    python garb_api.py hunt --start 41000 --end 41200
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 BiliDroid/9.16.1 os/ios",
      "Referer": "https://www.bilibili.com/"}
HOST = "https://api.bilibili.com"
WEB_LOCATION = "333.40212"

# 默认节奏：1.2 秒一次。B站 WAF 对高频很敏感，连打几百次会开始返回 412，
# 412 之后要等几分钟到几小时才恢复。急不来。
DEFAULT_SLEEP = 1.2

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data") if os.path.isdir(os.path.join(ROOT, "data")) else HERE


COOKIE_FILE = None


def _cookie_path():
    global COOKIE_FILE
    if COOKIE_FILE is None:
        COOKIE_FILE = os.path.join(DATA, "buvid.txt")
    return COOKIE_FILE


def load_cookie():
    """读缓存里的 buvid，没有就去 /x/frontend/finger/spi 领一个"""
    cp = _cookie_path()
    if os.path.exists(cp):
        c = open(cp, encoding="utf-8").read().strip()
        if c:
            return c
    try:
        with urllib.request.urlopen(
                urllib.request.Request(HOST + "/x/frontend/finger/spi", headers=UA),
                timeout=10) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        b3 = (d.get("data") or {}).get("b_3", "")
        b4 = (d.get("data") or {}).get("b_4", "")
        if b3:
            c = "buvid3=%s; buvid4=%s" % (b3, b4)
            os.makedirs(os.path.dirname(cp), exist_ok=True)
            open(cp, "w", encoding="utf-8").write(c)
            return c
    except Exception:
        pass
    return ""


_COOKIE = [None]


def headers():
    if _COOKIE[0] is None:
        _COOKIE[0] = load_cookie()
    h = dict(UA)
    if _COOKIE[0]:
        h["Cookie"] = _COOKIE[0]
    return h


def get(path, params, retries=4, on_412_wait=90):
    """412 是 WAF 限流，指数退避；其它错误短退避"""
    url = HOST + path + "?" + urllib.parse.urlencode(params)
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers())
            with urllib.request.urlopen(req, timeout=12) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 412:
                wait = on_412_wait * (i + 1)
                print("  [412 限流] 等 %ds 再试（%d/%d）" % (wait, i + 1, retries),
                      file=sys.stderr)
                time.sleep(wait)
                _COOKIE[0] = None          # 换一个 buvid 再试
            else:
                time.sleep(0.8 * (i + 1))
        except Exception as e:
            last = e
            time.sleep(0.8 * (i + 1))
    return {"code": "ERR", "message": str(last)[:80]}


# ---------------------------------------------------------------- 接口

def search(kw, pn=1, ps=20):
    """按名字搜。返回 (total, list)；total 可能大于 len(list) —— 服务端有过滤"""
    d = get("/x/garb/vas/search", {"key_word": kw, "pn": pn, "ps": ps,
                                   "web_location": WEB_LOCATION})
    if d.get("code") != 0:
        return 0, [], d
    data = d.get("data") or {}
    return data.get("total") or 0, data.get("list") or [], d


def detail(item_id):
    """按 item_id 取套装。goods_type=1 才有数据，收藏集返回空 data"""
    d = get("/x/garb/v2/mall/suit/detail",
            {"item_id": str(item_id), "web_location": WEB_LOCATION})
    if d.get("code") != 0:
        return None, d
    return d.get("data") or None, d


def recommend(seen_ids, ps=20):
    """推荐流。filtered_item_ids 传已见过的 id，会返回新的"""
    d = get("/x/garb/v2/mall/home/recommend/list", {
        "pn": 1, "ps": ps, "location": "mall_index_buttom_feed",
        "filtered_item_ids": ",".join(str(x) for x in seen_ids),
        "target_part_id": 0, "web_location": WEB_LOCATION,
    })
    if d.get("code") != 0:
        return []
    return (d.get("data") or {}).get("list") or []


# ------------------------------------------------ 我的装扮（需要 app 签名）

APPKEY = "27eb53fc9058f8c3"
APPSEC = "c2ed53a74eeefe3cf99fbd01d8c9c375"
APP_BASE = "https://app.bilibili.com"


def _sign(params):
    p = dict(params)
    p.update({"appkey": APPKEY, "ts": str(int(time.time())),
              "build": "90102100", "mobi_app": "iphone", "platform": "ios"})
    qs = urllib.parse.urlencode(sorted(p.items()))
    p["sign"] = hashlib.md5((qs + APPSEC).encode()).hexdigest()
    return p


def app_get(path, params, retries=3):
    qs = urllib.parse.urlencode(sorted(_sign(params).items()))
    url = APP_BASE + path + "?" + qs
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers())
            with urllib.request.urlopen(req, timeout=12) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = e
            time.sleep(2 * (i + 1) if e.code == 412 else 0.8 * (i + 1))
        except Exception as e:
            last = e
            time.sleep(0.8 * (i + 1))
    return {"code": "ERR", "message": str(last)[:80]}


def my_garbs(vmid, ps=50, pn=1):
    """「我的装扮」—— 已拥有的装扮列表，**包含已下架的**。
    返回 [{garb_title, item_id, garb_id, cover, fans_number}]"""
    import re as _re
    d = app_get("/x/v2/space/garb/list", {"vmid": vmid, "ps": ps, "pn": pn})
    if d.get("code") != 0:
        return [], d
    data = d.get("data") or {}
    out = []
    for x in (data.get("list") or []):
        uri = ((x.get("button") or {}).get("uri") or "")
        m = _re.search(r"[?&]id=(\d+)", uri)
        imgs = x.get("images") or []
        cover = ""
        if imgs and isinstance(imgs[0], dict):
            cover = imgs[0].get("large_image") or imgs[0].get("small_image") or ""
        out.append({
            "garb_title": x.get("garb_title") or "",
            "item_id": int(m.group(1)) if m else None,
            "garb_id": x.get("garb_id"),
            "cover": cover,
            "fans_number": x.get("fans_number") or "",
            "images": [i.get("large_image") for i in imgs if isinstance(i, dict)],
        })
    return out, d


# ---------------------------------------------------------------- 输出

def fmt_row(i, name, state, extra=""):
    return "%-12s %-26s %-8s %s" % (i, str(name)[:24], state or "-", extra)


def cmd_search(a):
    total, lst, raw = search(a.key_word, a.pn, a.ps)
    if raw.get("code") != 0:
        print("失败:", raw.get("code"), raw.get("message"))
        sys.exit(1)
    print("关键词 %r  total=%s  返回 %d 条" % (a.key_word, total, len(lst)))
    if total > len(lst):
        print("⚠ total 比返回多 %d 条 —— 被服务端过滤掉了（多半是下架或非套装）" % (total - len(lst)))
    print()
    print("%-12s %-26s %-8s %s" % ("item_id", "名称", "type", "价格"))
    print("-" * 72)
    for x in lst:
        print(fmt_row(x.get("item_id"), x.get("name"), x.get("goods_type"),
                      "%s  %s" % (x.get("price"), x.get("sale_count_desc") or "")))
    if a.json:
        print("\n" + json.dumps(lst, ensure_ascii=False, indent=1))


def cmd_detail(a):
    x, raw = detail(a.item_id)
    if not x:
        print("无数据:", raw.get("code"), raw.get("message"))
        sys.exit(1)
    if not x.get("name"):
        print("id=%s 存在但不是装扮套装（可能是收藏集/表情包），detail 不适用" % a.item_id)
        sys.exit(2)
    print("item_id   %s" % x.get("item_id"))
    print("name      %s" % x.get("name"))
    print("state     %s" % x.get("state"))
    print("group     %s (%s)  part=%s" % (x.get("group_name"), x.get("group_id"), x.get("part_id")))
    print("surplus   %s   %s" % (x.get("sale_surplus"), x.get("sale_count_desc")))
    print("jump      %s" % x.get("jump_link"))
    p = x.get("properties") or {}
    if p:
        print("\nproperties:")
        for k in ("type", "sale_type", "sale_time_begin", "is_hide", "sale_quantity",
                  "sale_buy_num_limit", "owner_uid", "fan_mid", "desc"):
            if k in p:
                print("   %-20s %s" % (k, str(p[k])[:80]))
    si = x.get("suit_items") or {}
    if si:
        print("\nsuit_items:")
        for k, v in si.items():
            if isinstance(v, list) and v:
                print("   %-14s %d 件" % (k, len(v)))
                for it in v[:6]:
                    print("      %-16s %-24s %s" % (it.get("item_id"), str(it.get("name"))[:22],
                                                    it.get("state")))
    if a.json:
        print("\n" + json.dumps(x, ensure_ascii=False, indent=1))


def cmd_walk(a):
    path = os.path.join(DATA, "mall_ids.json")
    seen = []
    if a.resume and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            seen = json.load(f).get("ids", [])
        print("续跑，已有 %d 个" % len(seen))
    total_new = 0
    for rnd in range(1, a.rounds + 1):
        lst = recommend(seen, ps=a.ps)
        if not lst:
            print("第 %d 轮没数据了" % rnd)
            break
        ids = [x.get("item_id") for x in lst if x.get("item_id")]
        new = [i for i in ids if i not in seen]
        seen.extend(new)
        total_new += len(new)
        print("第 %d 轮：返回 %d，新增 %d，累计 %d" % (rnd, len(ids), len(new), len(set(seen))))
        if not new:
            break
        time.sleep(a.sleep)
    seen = sorted(set(seen))
    os.makedirs(DATA, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "ids": seen},
                  f, ensure_ascii=False, indent=1)
    print("\n写入 %s，共 %d 个 item_id" % (path, len(seen)))


def cmd_check(a):
    print("%-12s %-26s %-8s %s" % ("item_id", "名称", "state", "type"))
    print("-" * 70)
    for i in a.ids:
        x, raw = detail(i)
        if not x or not x.get("name"):
            print("%-12s %-26s %-8s %s" % (i, "-", "无数据", raw.get("code")))
        else:
            print("%-12s %-26s %-8s %s" % (i, str(x.get("name"))[:24], x.get("state"),
                                           (x.get("properties") or {}).get("type")))
        time.sleep(a.sleep)


def cmd_hunt(a):
    """枚举 id 区间，把能取到 name 的收下来"""
    path = os.path.join(DATA, "hunted.json")
    got = {}
    if a.resume and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            got = json.load(f).get("items", {})
        print("续跑，已有 %d 条" % len(got))

    hit = miss = 0
    for i in range(a.start, a.end + 1, a.step):
        x, raw = detail(i)
        if x and x.get("name"):
            got[str(i)] = {
                "item_id": i, "name": x.get("name"), "state": x.get("state"),
                "group_id": x.get("group_id"), "group_name": x.get("group_name"),
                "part_id": x.get("part_id"),
                "type": (x.get("properties") or {}).get("type"),
                "sale_count": x.get("sale_count_desc"),
            }
            hit += 1
            if hit % 25 == 0:
                print("  %d..%d 命中 %d / 扫描 %d" % (a.start, i, hit, hit + miss))
                os.makedirs(DATA, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"items": got}, f, ensure_ascii=False, indent=1)
        else:
            miss += 1
        time.sleep(a.sleep)

    os.makedirs(DATA, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "items": got},
                  f, ensure_ascii=False, indent=1)
    print("\n扫描 %d 个 id，命中 %d，写入 %s" % (hit + miss, hit, path))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search"); s.add_argument("key_word")
    s.add_argument("--pn", type=int, default=1); s.add_argument("--ps", type=int, default=20)
    s.add_argument("--json", action="store_true"); s.set_defaults(func=cmd_search)

    d = sub.add_parser("detail"); d.add_argument("item_id")
    d.add_argument("--json", action="store_true"); d.set_defaults(func=cmd_detail)

    w = sub.add_parser("walk"); w.add_argument("--rounds", type=int, default=10)
    w.add_argument("--ps", type=int, default=20); w.add_argument("--sleep", type=float, default=DEFAULT_SLEEP)
    w.add_argument("--resume", action="store_true"); w.set_defaults(func=cmd_walk)

    c = sub.add_parser("check"); c.add_argument("ids", nargs="+")
    c.add_argument("--sleep", type=float, default=DEFAULT_SLEEP); c.set_defaults(func=cmd_check)

    h = sub.add_parser("hunt"); h.add_argument("--start", type=int, required=True)
    h.add_argument("--end", type=int, required=True)
    h.add_argument("--step", type=int, default=1)
    h.add_argument("--sleep", type=float, default=DEFAULT_SLEEP)
    h.add_argument("--resume", action="store_true"); h.set_defaults(func=cmd_hunt)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
