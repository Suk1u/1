#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""index_build.py — 建「装扮名字索引」

搜索接口只返回在售的，下架的搜不到。但 detail 接口按 item_id 能取到任何状态。
所以：枚举 id → 拉 detail → 存名字。索引建好后就能按名字搜了。

两种模式:
    neighbors  以在售 id 为种子，向两侧探邻居（高效，先跑这个）
    range      扫一段 id 区间（补漏）

用法:
    python index_build.py walk-seeds              # 先拉在售目录当种子
    python index_build.py neighbors --span 20     # 探邻居
    python index_build.py range --start 41000 --end 41200
    python index_build.py stats

断点续跑：进度存在 data/garb_index.json，随时中断随时续。
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import garb_api  # noqa: E402

ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data") if os.path.isdir(os.path.join(ROOT, "data")) else HERE
INDEX = os.path.join(DATA, "garb_index.json")
SEEDS = os.path.join(DATA, "mall_ids.json")


def load_index():
    if os.path.exists(INDEX):
        with open(INDEX, encoding="utf-8") as f:
            return json.load(f)
    return {"items": {}, "probed": [], "seeds": []}


def save_index(ix):
    os.makedirs(DATA, exist_ok=True)
    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump(ix, f, ensure_ascii=False, indent=1)


def probe(ix, iid, sleep):
    """查一个 id，命中就入库。返回 True 表示命中"""
    key = str(iid)
    if key in ix["items"]:
        return True
    x, raw = garb_api.detail(iid)
    ix["probed"].append(iid)
    if x and x.get("name"):
        p = x.get("properties") or {}
        si = x.get("suit_items") or {}
        ix["items"][key] = {
            "item_id": iid,
            "name": x.get("name"),
            "state": x.get("state"),
            "group_id": x.get("group_id"),
            "group_name": x.get("group_name"),
            "part_id": x.get("part_id"),
            # suit=True 才是「一套装扮」；False 是它的子件（表情/卡片/挂件）
            # 真套装：有 properties.type（ip/brand），或者 suit_items 里有 >=3 类部件
            "suit": bool(p.get("type")) or (isinstance(si, dict) and len(si) >= 3),
            "parts": list(si.keys()) if isinstance(si, dict) else [],
            "type": p.get("type"),
            "cover": p.get("image_cover") or p.get("image_cover_long") or "",
            "sale_count": x.get("sale_count_desc") or "",
            "jump": x.get("jump_link") or "",
        }
        time.sleep(sleep)
        return True
    time.sleep(sleep)
    return False


def trim(ix, cap=200000):
    """probed 列表太长就压缩成区间表示"""
    if len(ix["probed"]) <= cap:
        return
    ps = sorted(set(ix["probed"]))
    ranges = []
    s = prev = ps[0]
    for v in ps[1:]:
        if v == prev + 1:
            prev = v
            continue
        ranges.append([s, prev])
        s = prev = v
    ranges.append([s, prev])
    ix["probed_ranges"] = ranges
    ix["probed"] = []
    print("  已探 id 压缩成 %d 个区间" % len(ranges))


# ---------------------------------------------------------------- users

def cmd_users(a):
    """从「我的装扮」采集 —— 这是唯一能拿到下架装扮名字的入口"""
    ix = load_index()
    ix.setdefault("users", [])
    done = set(ix["users"])

    queue = [int(x) for x in a.vmids.replace("\n", ",").split(",") if x.strip().isdigit()]
    seen = 0
    added = 0
    while queue and seen < a.expand:
        vmid = queue.pop(0)
        if vmid in done:
            continue
        done.add(vmid)
        seen += 1

        lst, raw = garb_api.my_garbs(vmid, ps=50, pn=1)
        if raw.get("code") != 0:
            print("  vmid=%s 失败 %s" % (vmid, raw.get("message")))
            time.sleep(a.sleep)
            continue

        for x in lst:
            iid = x.get("item_id")
            if not iid:
                continue
            key = str(iid)
            it = ix["items"].get(key)
            if it is None:
                added += 1
                it = ix["items"][key] = {
                    "item_id": iid, "name": "", "garb_id": None, "cover": "",
                    "suit": True, "sources": [],
                }
            it["name"] = x["garb_title"] or it.get("name") or ""
            it["garb_id"] = x.get("garb_id") or it.get("garb_id")
            it["cover"] = x.get("cover") or it.get("cover") or ""
            it["fans_number"] = x.get("fans_number") or it.get("fans_number") or ""
            it["images"] = x.get("images") or it.get("images") or []
            src = "user:%d" % vmid
            if src not in it["sources"]:
                it["sources"].append(src)

        print("  vmid=%-9s 拥有 %d 套，索引 +%d → %d 条" % (vmid, len(lst), added, len(ix["items"])))
        added = 0

        # 顺着关注链扩
        if a.follow and seen < a.expand:
            try:
                r = garb_api.get("/x/relation/followings",
                                 {"vmid": vmid, "pn": 1, "ps": 50})
                for u in ((r or {}).get("data") or {}).get("list") or []:
                    mid = u.get("mid")
                    if mid and mid not in done:
                        queue.append(mid)
            except Exception:
                pass

        if seen % 20 == 0:
            ix["users"] = sorted(done)
            save_index(ix)
        time.sleep(a.sleep)

    ix["users"] = sorted(done)
    save_index(ix)
    print("\n访问 %d 个用户，索引共 %d 条" % (seen, len(ix["items"])))


# ---------------------------------------------------------------- seeds

def cmd_walk_seeds(a):
    seen = []
    if os.path.exists(SEEDS):
        with open(SEEDS, encoding="utf-8") as f:
            seen = json.load(f).get("ids", [])
    for rnd in range(1, a.rounds + 1):
        lst = garb_api.recommend(seen, ps=20)
        if not lst:
            break
        ids = [x.get("item_id") for x in lst if x.get("item_id")]
        new = [i for i in ids if i not in seen]
        seen.extend(new)
        print("第 %d 轮 新增 %d，累计 %d" % (rnd, len(new), len(set(seen))))
        if not new:
            break
        time.sleep(a.sleep)
    os.makedirs(DATA, exist_ok=True)
    with open(SEEDS, "w", encoding="utf-8") as f:
        json.dump({"ids": sorted(set(seen))}, f)
    print("种子 %d 个 -> %s" % (len(set(seen)), SEEDS))


# ------------------------------------------------------------ neighbors

def cmd_neighbors(a):
    if not os.path.exists(SEEDS):
        print("先跑: python index_build.py walk-seeds")
        sys.exit(1)
    with open(SEEDS, encoding="utf-8") as f:
        seeds = json.load(f).get("ids", [])
    ix = load_index()
    done = set(ix["seeds"])
    todo = [s for s in seeds if s not in done]
    print("种子 %d 个，未探 %d 个，每侧探 %d" % (len(seeds), len(todo), a.span))

    t0 = time.time()
    hit = 0
    total = 0
    for n, s in enumerate(todo, 1):
        if a.budget and time.time() - t0 > a.budget:
            print("\n到时间预算了，先存盘")
            break
        for off in range(-a.span, a.span + 1):
            iid = s + off
            if iid <= 0 or str(iid) in ix["items"]:
                continue
            total += 1
            if probe(ix, iid, a.sleep):
                hit += 1
        ix["seeds"].append(s)
        if n % 10 == 0:
            save_index(ix)
            trim(ix)
            print("  [%d/%d] 种子 %d，本次命中 %d / 探测 %d，索引 %d 条"
                  % (n, len(todo), s, hit, total, len(ix["items"])))
    save_index(ix)
    print("\n完成：命中 %d / 探测 %d，索引共 %d 条" % (hit, total, len(ix["items"])))


# ---------------------------------------------------------------- range

def cmd_range(a):
    ix = load_index()
    already = set(ix["probed"])
    hit = 0
    total = 0
    for iid in range(a.start, a.end + 1, a.step):
        if iid in already:
            continue
        total += 1
        if probe(ix, iid, a.sleep):
            hit += 1
        if total % 50 == 0:
            save_index(ix)
            trim(ix)
            print("  %d..%d  命中 %d / 探测 %d  索引 %d 条"
                  % (a.start, iid, hit, total, len(ix["items"])))
    save_index(ix)
    print("\n完成：命中 %d / 探测 %d，索引共 %d 条" % (hit, total, len(ix["items"])))


def cmd_stats(a):
    ix = load_index()
    items = ix["items"]
    types = {}
    for v in items.values():
        types[v.get("type") or "?"] = types.get(v.get("type") or "?", 0) + 1
    print("索引 %d 条" % len(items))
    print("已探 id %d 个" % len(set(ix["probed"])))
    print("已处理种子 %d 个" % len(ix.get("seeds", [])))
    if types:
        print("类型分布:", types)
    if items:
        sample = list(items.values())[:3]
        print("\n样例:")
        for s in sample:
            print("  %-12s %-24s %s" % (s["item_id"], str(s["name"])[:22], s.get("state")))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    u = sub.add_parser("users")
    u.add_argument("--vmids", required=True, help="起始 vmid，逗号分隔")
    u.add_argument("--expand", type=int, default=200, help="最多访问多少个用户")
    u.add_argument("--follow", action="store_true", default=True)
    u.add_argument("--no-follow", dest="follow", action="store_false")
    u.add_argument("--sleep", type=float, default=1.0)
    u.set_defaults(func=cmd_users)

    w = sub.add_parser("walk-seeds")
    w.add_argument("--rounds", type=int, default=30)
    w.add_argument("--sleep", type=float, default=garb_api.DEFAULT_SLEEP)
    w.set_defaults(func=cmd_walk_seeds)

    n = sub.add_parser("neighbors")
    n.add_argument("--span", type=int, default=20)
    n.add_argument("--sleep", type=float, default=garb_api.DEFAULT_SLEEP)
    n.add_argument("--budget", type=int, default=0, help="时间预算（秒），0 表示不限")
    n.set_defaults(func=cmd_neighbors)

    r = sub.add_parser("range")
    r.add_argument("--start", type=int, required=True)
    r.add_argument("--end", type=int, required=True)
    r.add_argument("--step", type=int, default=1)
    r.add_argument("--sleep", type=float, default=garb_api.DEFAULT_SLEEP)
    r.set_defaults(func=cmd_range)

    s = sub.add_parser("stats"); s.set_defaults(func=cmd_stats)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
