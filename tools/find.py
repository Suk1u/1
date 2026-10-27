#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""find.py — 按中文名搜装扮（含已下架）

索引由 index_build.py 建。只要索引里有，下架的也能搜出来。

用法:
    python find.py 欧皇
    python find.py 欧皇 --delisted        # 只看下架的
    python find.py 欧皇 --json
    python find.py --id 120730201         # 按 id 反查
    python find.py --list --limit 30
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data") if os.path.isdir(os.path.join(ROOT, "data")) else HERE

INDEX = os.path.join(DATA, "garb_index.json")
MALL = os.path.join(DATA, "mall_ids.json")

PUNCT = re.compile(r"[\s·・\-_/\\|,，。.、:：;；!！?？()（）\[\]【】\"'“”‘’]+")


def norm(s):
    return PUNCT.sub("", (s or "").lower())


def load_items():
    if not os.path.exists(INDEX):
        return []
    with open(INDEX, encoding="utf-8") as f:
        o = json.load(f)
    items = o.get("items") or {}
    return list(items.values()) if isinstance(items, dict) else items


def load_mall():
    """在售 id 集合。没有就当全未知"""
    if not os.path.exists(MALL):
        return None
    try:
        with open(MALL, encoding="utf-8") as f:
            return set(json.load(f).get("ids", []))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("q", nargs="?", default="", help="中文名关键词")
    ap.add_argument("--id", type=int, default=0)
    ap.add_argument("--delisted", action="store_true", help="只看下架的")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--all", action="store_true", help="连套装子件（表情/卡片）一起显示")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    items = load_items()
    if not items:
        print("索引是空的。先跑:")
        print("  python index_build.py walk-seeds")
        print("  python index_build.py neighbors --span 20")
        sys.exit(1)

    mall = load_mall()

    def status_of(it):
        if not it.get("suit", True):
            return "part"          # 套装子件，不参与在售判定
        if mall is None:
            return "unknown"
        return "onsale" if it["item_id"] in mall else "delisted"

    if a.id:
        hits = [x for x in items if x.get("item_id") == a.id]
    elif a.list or not a.q:
        hits = list(items)
    else:
        nq = norm(a.q)
        hits = [x for x in items if nq in norm(x.get("name"))]
        hits.sort(key=lambda x: (norm(x.get("name")) != nq, len(x.get("name") or "")))

    if not a.all:
        # 默认只看「一套装扮」，滤掉它的子件
        suits = [x for x in hits if x.get("suit", True)]
        if suits:
            hits = suits
    if a.delisted:
        hits = [x for x in hits if status_of(x) == "delisted"]

    if not hits:
        extra = ""
        if mall is None:
            extra = "\n（还没有在售目录，跑 index_build.py walk-seeds 才能区分在售/下架）"
        print("没搜到。索引里 %d 条，换个更短的关键词试试。%s" % (len(items), extra))
        sys.exit(2)

    hits = hits[:a.limit]

    if a.json:
        out = []
        for x in hits:
            y = dict(x)
            y["status"] = status_of(x)
            out.append(y)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return

    print("%-12s %-26s %-8s %-10s %s" % ("item_id", "名称", "state", "在售?", "销量"))
    print("-" * 78)
    for x in hits:
        st = status_of(x)
        tag = {"onsale": "在售", "delisted": "★下架", "unknown": "?", "part": "部件"}[st]
        print("%-12s %-26s %-8s %-10s %s" % (
            x["item_id"], str(x.get("name"))[:24], x.get("state") or "-",
            tag, x.get("sale_count") or "-"))
    print("\n共 %d 条" % len(hits))
    if mall is None:
        print("提示：没有在售目录，区分不了在售/下架。跑 index_build.py walk-seeds")


if __name__ == "__main__":
    main()
