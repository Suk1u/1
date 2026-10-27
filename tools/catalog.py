#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""catalog.py — 装扮 ID 采集 / 校验 / 在售状态判定

流程:
    1. seed    遍历 vmid 列表，从各自空间拉 garb/list，收集 (garb_id, image_id)
    2. verify  对每个 ID 调 garb/detail，补齐素材 + isOwn
    3. build   合并 capture/ 里抓到的商城列表，算出「在售 / 已下架」，导出 catalog.json

用法:
    python catalog.py seed   --vmids 2,3,4,5 --max-pages 3
    python catalog.py verify --vmid 2 --sleep 0.6
    python catalog.py build
    python catalog.py stats
"""

import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bili

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "catalog.json")
CAPTURE_DIR = os.path.join(HERE, "capture")


def load_db():
    if os.path.exists(DB):
        with open(DB, encoding="utf-8") as f:
            return json.load(f)
    return {"items": {}, "seeds": []}


def save_db(db):
    with open(DB, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)


def key(gid, iid):
    return "%d:%d" % (gid, iid)


def touch(db, gid, iid, **fields):
    k = key(gid, iid)
    it = db["items"].setdefault(k, {
        "garb_id": gid, "image_id": iid, "name": "", "title": "",
        "small": "", "large": "", "isOwn": False,
        "in_mall": False, "status": "unknown", "sources": [],
    })
    for f, v in fields.items():
        if v not in (None, "", []):
            it[f] = v
    return it


# ---------------------------------------------------------------- seed

def cmd_seed(a):
    db = load_db()
    vmids = [int(x) for x in a.vmids.split(",") if x.strip()]
    added = 0
    for vmid in vmids:
        if vmid not in db["seeds"]:
            db["seeds"].append(vmid)
        for pn in range(1, a.max_pages + 1):
            try:
                resp = bili.garb_list(vmid, ps=20, pn=pn, ak=a.ak)
            except Exception as e:
                print("  vmid=%s pn=%s 失败: %s" % (vmid, pn, e))
                break
            rows = list(bili.iter_garb_from_list(resp))
            if not rows:
                break
            for gid, iid, name, title in rows:
                before = key(gid, iid) in db["items"]
                touch(db, gid, iid, name=name, title=title,
                      sources=["space:%d" % vmid])
                if not before:
                    added += 1
            print("  vmid=%s pn=%s -> %d 条" % (vmid, pn, len(rows)))
            time.sleep(a.sleep)
    save_db(db)
    print("新增 %d 条，总计 %d 条" % (added, len(db["items"])))


# ---------------------------------------------------------------- verify

def cmd_verify(a):
    db = load_db()
    todo = [v for v in db["items"].values() if not v.get("large")]
    print("待校验 %d 条" % len(todo))
    ok = 0
    for i, it in enumerate(todo, 1):
        try:
            r = bili.garb_detail(a.vmid, it["garb_id"], it["image_id"], a.ak)
        except Exception as e:
            print("  [%d/%d] %s:%s 失败 %s" % (i, len(todo), it["garb_id"], it["image_id"], e))
            time.sleep(a.sleep)
            continue
        d = (r or {}).get("data") or {}
        if not d:
            it["status"] = "dead"
            continue
        it.update({
            "small": d.get("smallImage") or d.get("small_image") or "",
            "large": d.get("largeImage") or d.get("large_image") or "",
            "name": d.get("fansLabel") or d.get("fans_label") or it.get("name") or "",
            "isOwn": bool(d.get("isOwn") if "isOwn" in d else d.get("is_own")),
        })
        ok += 1
        if i % 20 == 0:
            print("  [%d/%d] ok" % (i, len(todo)))
            save_db(db)
        time.sleep(a.sleep)
    save_db(db)
    print("校验成功 %d / %d" % (ok, len(todo)))


# ---------------------------------------------------------------- build

def scan_capture(db):
    """从 capture/ 里的商城响应中提取在售 item_id 集合"""
    on_sale = set()
    files = sorted(glob.glob(os.path.join(CAPTURE_DIR, "*.json")))
    for fp in files:
        try:
            with open(fp, encoding="utf-8") as f:
                obj = json.load(f)
        except Exception:
            continue
        for n in walk_numbers(obj, ("item_id", "itemId", "suit_id", "suitId", "garb_id", "garbId")):
            on_sale.add(n)
    return on_sale


def walk_numbers(obj, key_names):
    """递归找所有指定 key 的整数值"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in key_names and isinstance(v, (int, str)) and str(v).isdigit():
                yield int(v)
            else:
                yield from walk_numbers(v, key_names)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_numbers(v, key_names)


def cmd_build(a):
    db = load_db()
    on_sale = scan_capture(db)
    print("capture 里识别到在售 ID %d 个" % len(on_sale))
    for it in db["items"].values():
        it["in_mall"] = it["garb_id"] in on_sale
        if it.get("status") == "dead":
            continue
        it["status"] = "onsale" if it["in_mall"] else "delisted"
    save_db(db)
    out = os.path.join(HERE, "catalog.json")
    items = sorted(db["items"].values(), key=lambda x: (x["status"] != "delisted", -x["garb_id"]))
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "items": items},
                  f, ensure_ascii=False, indent=1)
    print("导出 %s，共 %d 条" % (out, len(items)))


def cmd_stats(a):
    db = load_db()
    c = {}
    for it in db["items"].values():
        c[it.get("status", "unknown")] = c.get(it.get("status", "unknown"), 0) + 1
    print("总计 %d" % len(db["items"]))
    for k, v in sorted(c.items(), key=lambda x: -x[1]):
        print("  %-10s %d" % (k, v))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed"); s.add_argument("--vmids", required=True)
    s.add_argument("--max-pages", type=int, default=3)
    s.add_argument("--sleep", type=float, default=0.8); s.add_argument("--ak", default="")
    s.set_defaults(func=cmd_seed)

    v = sub.add_parser("verify"); v.add_argument("--vmid", type=int, default=2)
    v.add_argument("--sleep", type=float, default=0.8); v.add_argument("--ak", default="")
    v.set_defaults(func=cmd_verify)

    b = sub.add_parser("build"); b.set_defaults(func=cmd_build)
    st = sub.add_parser("stats"); st.set_defaults(func=cmd_stats)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
