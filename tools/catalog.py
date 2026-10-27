#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""catalog.py — 装扮 ID 采集 / 校验 / 在售状态判定

流程:
    seed      遍历 vmid 列表，从各自空间拉 garb/list，收集 (garb_id, image_id)
    verify    对每个 ID 调 garb/detail，补齐素材 + isOwn
    snapshot  把抓到的商城列表响应压成 ID 快照（data/mall_snapshot.json）
    build     合并快照，算出「在售 / 已下架」，导出 Surge/catalog.json
    stats     看统计

用法:
    python catalog.py seed     --vmids 2,3,4,5 --max-pages 3
    python catalog.py verify   --vmid 2
    python catalog.py snapshot --capture ../capture/xxx.json
    python catalog.py build    --mall data/mall_snapshot.json
    python catalog.py stats
"""

import argparse
import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bili  # noqa: E402

ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(ROOT, "data") if os.path.isdir(os.path.join(ROOT, "data")) else HERE
DB = os.path.join(DATA_DIR, "catalog_db.json")
CAPTURE_DIR = (os.path.join(ROOT, "capture")
               if os.path.isdir(os.path.join(ROOT, "capture"))
               else os.path.join(HERE, "capture"))


def default_out():
    repo = os.path.join(ROOT, "Surge", "catalog.json")
    return repo if os.path.isdir(os.path.dirname(repo)) else os.path.join(HERE, "catalog.json")


def load_db():
    if os.path.exists(DB):
        with open(DB, encoding="utf-8") as f:
            return json.load(f)
    return {"items": {}, "seeds": [], "visited": []}


def save_db(db):
    os.makedirs(os.path.dirname(DB), exist_ok=True)
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
    vmids = [int(x) for x in a.vmids.replace("\n", ",").split(",") if x.strip().isdigit()]
    if a.limit:
        vmids = vmids[:a.limit]
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


# --------------------------------------------------------------- harvest

def cmd_harvest(a):
    """从一个种子集合滚雪球：拉关注链 + 每人的装扮，建 名字 -> ID 索引"""
    db = load_db()
    db.setdefault("visited", [])
    visited = set(db["visited"])

    queue = [int(x) for x in a.seed.replace("\n", ",").split(",") if x.strip().isdigit()]
    if a.resume:
        queue = [v for v in queue if v not in visited] or queue

    added = 0
    users = 0
    while queue and users < a.max_users:
        vmid = queue.pop(0)
        if vmid in visited:
            continue
        visited.add(vmid)
        users += 1

        # 该用户的装扮
        try:
            resp = bili.garb_list(vmid, ps=20, pn=1, ak=a.ak)
            for gid, iid, name, title in bili.iter_garb_from_list(resp):
                before = key(gid, iid) in db["items"]
                touch(db, gid, iid, title=title, sources=["space:%d" % vmid])
                if not before:
                    added += 1
        except Exception as e:
            if a.verbose:
                print("  garb %s: %s" % (vmid, e))

        # 该用户关注的人，入队
        if a.depth_follow and len(visited) < a.max_users:
            try:
                r = bili.call("https://api.bilibili.com/x/relation/followings",
                              {"vmid": vmid, "pn": 1, "ps": 50}, ak=a.ak)
                for u in ((r or {}).get("data") or {}).get("list") or []:
                    mid = u.get("mid")
                    if mid and mid not in visited:
                        queue.append(mid)
            except Exception as e:
                if a.verbose:
                    print("  rel %s: %s" % (vmid, e))

        if users % 20 == 0:
            db["visited"] = sorted(visited)
            save_db(db)
            print("  已访问 %d 用户，索引 %d 条，队列 %d" % (users, len(db["items"]), len(queue)))
        time.sleep(a.sleep)

    db["visited"] = sorted(visited)
    save_db(db)
    print("访问 %d 用户，新增 %d 条，索引总计 %d 条" % (users, added, len(db["items"])))


# ---------------------------------------------------------------- verify

def cmd_verify(a):
    db = load_db()
    todo = [v for v in db["items"].values() if not v.get("large")]
    if a.limit:
        todo = todo[:a.limit]
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


# -------------------------------------------------------------- snapshot

def walk_numbers(obj, key_names):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in key_names and isinstance(v, (int, str)) and str(v).isdigit():
                yield int(v)
            else:
                yield from walk_numbers(v, key_names)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_numbers(v, key_names)


def collect_ids_from_files(files):
    ids = set()
    for fp in files:
        try:
            with open(fp, encoding="utf-8") as f:
                obj = json.load(f)
        except Exception:
            continue
        ids |= set(walk_numbers(obj.get("body", obj),
                                ("item_id", "itemId", "suit_id", "suitId",
                                 "garb_id", "garbId")))
    return ids


def cmd_snapshot(a):
    files = [a.capture] if a.capture else sorted(glob.glob(os.path.join(CAPTURE_DIR, "*.json")))
    ids = collect_ids_from_files(files)
    out = a.out or os.path.join(DATA_DIR, "mall_snapshot.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "ids": sorted(ids)},
                  f, ensure_ascii=False, indent=1)
    print("快照 %d 个 ID -> %s" % (len(ids), out))


# ---------------------------------------------------------------- build

def load_mall_ids(a):
    """优先 --mall 快照，其次 capture/；都没有返回 None（保持原状）"""
    if a.mall:
        if not os.path.exists(a.mall):
            print("快照不存在: %s" % a.mall)
            return None
        with open(a.mall, encoding="utf-8") as f:
            return set(json.load(f).get("ids", []))
    files = sorted(glob.glob(os.path.join(CAPTURE_DIR, "*.json")))
    if not files:
        return None
    return collect_ids_from_files(files)


def cmd_build(a):
    db = load_db()
    mall = load_mall_ids(a)
    if mall is None:
        print("没有商城参照（--mall 或 capture/），保持已有 status 不变")
    else:
        print("商城参照 %d 个 ID" % len(mall))

    for it in db["items"].values():
        if it.get("status") == "dead" or mall is None:
            continue
        it["in_mall"] = it["garb_id"] in mall
        it["status"] = "onsale" if it["in_mall"] else "delisted"

    save_db(db)
    out = a.out or default_out()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    items = sorted(db["items"].values(),
                   key=lambda x: (x.get("status") != "delisted", -x["garb_id"]))
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "items": items},
                  f, ensure_ascii=False, indent=1)
    print("导出 %s，共 %d 条" % (out, len(items)))


def cmd_stats(a):
    db = load_db()
    c = {}
    for it in db["items"].values():
        c[it.get("status", "unknown")] = c.get(it.get("status", "unknown"), 0) + 1
    print("总计 %d，来源 %d 个 vmid" % (len(db["items"]), len(db.get("seeds", []))))
    for k, v in sorted(c.items(), key=lambda x: -x[1]):
        print("  %-10s %d" % (k, v))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed")
    s.add_argument("--vmids", required=True)
    s.add_argument("--max-pages", type=int, default=3)
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--sleep", type=float, default=0.8)
    s.add_argument("--ak", default="")
    s.set_defaults(func=cmd_seed)

    h = sub.add_parser("harvest")
    h.add_argument("--seed", required=True, help="起始 vmid，逗号分隔")
    h.add_argument("--max-users", type=int, default=200)
    h.add_argument("--depth-follow", action="store_true", default=True,
                   help="顺着关注链扩展（默认开）")
    h.add_argument("--no-depth-follow", dest="depth_follow", action="store_false")
    h.add_argument("--resume", action="store_true")
    h.add_argument("--sleep", type=float, default=1.0)
    h.add_argument("--verbose", action="store_true")
    h.add_argument("--ak", default="")
    h.set_defaults(func=cmd_harvest)

    v = sub.add_parser("verify")
    v.add_argument("--vmid", type=int, default=2)
    v.add_argument("--limit", type=int, default=0)
    v.add_argument("--sleep", type=float, default=0.8)
    v.add_argument("--ak", default="")
    v.set_defaults(func=cmd_verify)

    sn = sub.add_parser("snapshot")
    sn.add_argument("--capture", default="")
    sn.add_argument("--out", default="")
    sn.set_defaults(func=cmd_snapshot)

    b = sub.add_parser("build")
    b.add_argument("--mall", default="")
    b.add_argument("--out", default="")
    b.set_defaults(func=cmd_build)

    st = sub.add_parser("stats")
    st.set_defaults(func=cmd_stats)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
