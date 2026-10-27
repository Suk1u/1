#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""themes.py — 提取装扮里的「主题」部件

B站 的「主题装扮」不是独立商品，是**套装里的 skin 部件**。
每个套装在 suit_items.skin 下挂 1 个，item_id 单独可查，带完整配色 + 可下载的 zip 包。

    python themes.py build            # 遍历索引，把每个套装的 skin 抽出来
    python themes.py list             # 列出已提取的主题
    python themes.py show 5224        # 看某个主题的完整配置
    python themes.py pack 5224        # 只打印主题包地址

数据存 data/themes.json。
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
THEMES = os.path.join(DATA, "themes.json")

# 主题里值得单独拎出来的字段
KEY_FIELDS = ("color", "color_mode", "color_second_page",
              "image_cover", "image_preview",
              "head_bg", "head_tab_bg", "side_bg", "tail_bg",
              "package_url", "package_md5", "ver")


def load(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def extract(suit_id):
    """从一个套装里抽出 skin 部件。返回 [{item_id, name, props}] 或 []"""
    x, _ = garb_api.detail(suit_id)
    if not x:
        return []
    si = x.get("suit_items") or {}
    out = []
    for it in (si.get("skin") or []):
        if not isinstance(it, dict):
            continue
        out.append({
            "theme_item_id": it.get("item_id"),
            "suit_item_id": suit_id,
            "suit_name": x.get("name") or "",
            "name": it.get("name") or "",
            "state": it.get("state"),
            "props": it.get("properties") or {},
        })
    return out


def cmd_build(a):
    ix = load(INDEX, {"items": {}})
    suits = [v for v in (ix.get("items") or {}).values() if v.get("suit", True)]
    if a.limit:
        suits = suits[:a.limit]
    db = load(THEMES, {"themes": {}})
    have = db["themes"]

    added = 0
    for n, v in enumerate(suits, 1):
        sid = v["item_id"]
        if any(t.get("suit_item_id") == sid for t in have.values()) and not a.refresh:
            continue
        try:
            got = extract(sid)
        except Exception as e:
            print("  %s 失败: %s" % (sid, e))
            time.sleep(a.sleep)
            continue
        for t in got:
            tid = t["theme_item_id"]
            if tid is None:
                continue
            if str(tid) not in have:
                added += 1
            have[str(tid)] = t
        if got:
            print("  %-12s %-22s → 主题 %s" % (sid, str(v.get("name"))[:20],
                                              [t["theme_item_id"] for t in got]))
        if n % 10 == 0:
            save(THEMES, db)
        time.sleep(a.sleep)

    save(THEMES, db)
    print("\n新增 %d 个主题，共 %d 个" % (added, len(have)))


def cmd_list(a):
    db = load(THEMES, {"themes": {}})
    ts = list(db["themes"].values())
    if not ts:
        print("还没有数据。先跑: python themes.py build")
        sys.exit(1)
    print("%-12s %-12s %-22s %-8s %s" % ("theme_id", "套装", "名称", "mode", "包"))
    print("-" * 82)
    for t in ts:
        p = t.get("props") or {}
        print("%-12s %-12s %-22s %-8s %s" % (
            t["theme_item_id"], t.get("suit_item_id"), str(t.get("name"))[:20],
            p.get("color_mode") or "-", "有" if p.get("package_url") else "-"))
    print("\n共 %d 个" % len(ts))


def cmd_show(a):
    db = load(THEMES, {"themes": {}})
    t = db["themes"].get(str(a.theme_id))
    if not t:
        print("没找到 %s。先跑 themes.py build，或换个 id" % a.theme_id)
        sys.exit(1)
    p = t.get("props") or {}
    print("theme_item_id  %s" % t["theme_item_id"])
    print("suit           %s (%s)" % (t.get("suit_item_id"), t.get("suit_name")))
    print("name           %s" % t.get("name"))
    print("state          %s" % t.get("state"))
    print()
    for k in KEY_FIELDS:
        if k in p:
            print("  %-20s %s" % (k, str(p[k])[:100]))
    if a.json:
        print("\n" + json.dumps(p, ensure_ascii=False, indent=1))


def cmd_pack(a):
    db = load(THEMES, {"themes": {}})
    t = db["themes"].get(str(a.theme_id))
    if not t:
        print("没找到 %s" % a.theme_id)
        sys.exit(1)
    p = t.get("props") or {}
    print(p.get("package_url") or "(无包)")
    if p.get("package_md5"):
        print("# md5:", p["package_md5"])


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build")
    b.add_argument("--limit", type=int, default=0)
    b.add_argument("--refresh", action="store_true")
    b.add_argument("--sleep", type=float, default=garb_api.DEFAULT_SLEEP)
    b.set_defaults(func=cmd_build)

    ls = sub.add_parser("list"); ls.set_defaults(func=cmd_list)

    sh = sub.add_parser("show"); sh.add_argument("theme_id")
    sh.add_argument("--json", action="store_true"); sh.set_defaults(func=cmd_show)

    pk = sub.add_parser("pack"); pk.add_argument("theme_id")
    pk.set_defaults(func=cmd_pack)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
