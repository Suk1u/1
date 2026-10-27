#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collections.py — 采集收藏集（含已下架）

收藏集没有「我的装扮」那样的完整列表，但收藏集大厅是公开的：
    GET /x/garb/right/collection/aggregation_info?vmid=X
匿名可调，返回该用户收藏大厅的内容，混装三类：
    biz_type=1  装扮
    biz_type=2  收藏集
    biz_type=3  合集

每条带 act_id / card_type_id / 名称 / 持有数 / 跳转链接，**包含已下架的**。

限制：每个用户固定只出 10 条（ps 参数被忽略，翻页游标也打不通）。
所以只能靠多喂 vmid —— 每个用户贡献 10 条。

用法:
    python collections.py collect --vmids 2,524387426
    python collections.py list
    python collections.py list --type 2
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
OUT = os.path.join(DATA, "collections.json")

BIZ = {0: "未知", 1: "装扮", 2: "收藏集", 3: "合集"}


def load():
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    return {"items": {}, "users": []}


def save(db):
    os.makedirs(DATA, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)


def hall(vmid):
    """拉一个用户的收藏集大厅。返回 (items, total)"""
    d = garb_api.get("/x/garb/right/collection/aggregation_info",
                     {"vmid": vmid, "web_location": garb_api.WEB_LOCATION})
    if d.get("code") != 0:
        return [], 0, d
    allr = (d.get("data") or {}).get("all") or {}
    rows = allr.get("result") or []
    out = []
    for x in rows:
        it = x.get("item") or {}
        ex = x.get("extra") or {}
        ce = it.get("card_extra") or {}
        out.append({
            "biz_type": x.get("biz_type"),
            "biz_id": x.get("biz_id"),                 # 收藏集这里是 act_id
            "item_id": x.get("item_id"),               # card_type_id
            "item_type": it.get("item_type"),
            "name": (x.get("title") or {}).get("title") or "",
            "cover": it.get("cover") or "",
            "owned": ex.get("owned"),
            "total": ex.get("total"),
            "completed": ex.get("collection_completed"),
            "jump": ex.get("detail_jump_url") or "",
            "unusable": (it.get("extra") or {}).get("unusable_reason") or "",
            "card_id": ce.get("card_id"),
            "card_number": ce.get("card_number"),
            "scarcity": ce.get("card_scarcity"),
        })
    return out, allr.get("total") or 0, d


def key(x):
    return "%s:%s:%s" % (x.get("biz_type"), x.get("biz_id"), x.get("item_id"))


def cmd_collect(a):
    db = load()
    vmids = [int(v) for v in a.vmids.replace("\n", ",").split(",") if v.strip().isdigit()]
    done = set(db.get("users", []))
    added = 0

    for vmid in vmids:
        if vmid in done and not a.refresh:
            print("  vmid=%s 已采过，跳过" % vmid)
            continue
        rows, total, raw = hall(vmid)
        if raw.get("code") != 0:
            print("  vmid=%-10s 失败 %s" % (vmid, raw.get("message")))
            time.sleep(a.sleep)
            continue
        for x in rows:
            k = key(x)
            if k not in db["items"]:
                added += 1
            x["source"] = vmid
            db["items"][k] = x
        done.add(vmid)
        print("  vmid=%-10s 返回 %-3d（总数 %-3s）→ 累计 %d" % (vmid, len(rows), total, len(db["items"])))
        if total > len(rows):
            print("               ⚠ 只出 %d 条，还有 %d 条翻不到" % (len(rows), total - len(rows)))
        save(db)
        time.sleep(a.sleep)

    db["users"] = sorted(done)
    save(db)
    print("\n新增 %d 条，共 %d 条（来自 %d 个用户）" % (added, len(db["items"]), len(done)))


def cmd_list(a):
    db = load()
    items = list(db["items"].values())
    if a.type:
        items = [x for x in items if x.get("biz_type") == a.type]
    if not items:
        print("还没有数据。先跑: python collections.py collect --vmids 2")
        sys.exit(1)

    print("%-6s %-10s %-16s %-22s %-8s %s" % ("类型", "biz_id", "card_type_id", "名称", "持有", "不可用"))
    print("-" * 88)
    for x in sorted(items, key=lambda y: (y.get("biz_type") or 0, -(y.get("biz_id") or 0))):
        print("%-6s %-10s %-16s %-22s %-8s %s" % (
            BIZ.get(x.get("biz_type"), "?"), x.get("biz_id"), x.get("item_id"),
            str(x.get("name"))[:20],
            "%s/%s" % (x.get("owned"), x.get("total")) if x.get("total") else "-",
            (x.get("unusable") or "")[:16]))
    print("\n共 %d 条" % len(items))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect")
    c.add_argument("--vmids", required=True)
    c.add_argument("--refresh", action="store_true")
    c.add_argument("--sleep", type=float, default=garb_api.DEFAULT_SLEEP)
    c.set_defaults(func=cmd_collect)

    ls = sub.add_parser("list")
    ls.add_argument("--type", type=int, default=0, help="1=装扮 2=收藏集 3=合集")
    ls.set_defaults(func=cmd_list)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
