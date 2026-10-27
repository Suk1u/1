#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search.py — 按中文名反查装扮 ID

B站 没有服务端的装扮名字检索（`x/emote/package/search` 只搜表情包），
所以只能查本地索引 —— 由 `catalog.py harvest` 采集出来的名字库。

用法:
    python search.py 夏日
    python search.py 夏日 --status delisted
    python search.py 夏日 --json
    python search.py --id 12345
    python search.py --list --limit 50
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def find_db():
    for p in (os.path.join(ROOT, "data", "catalog_db.json"),
              os.path.join(HERE, "catalog_db.json"),
              os.path.join(ROOT, "Surge", "catalog.json")):
        if os.path.exists(p):
            return p
    return None


def load_items(path):
    with open(path, encoding="utf-8") as f:
        o = json.load(f)
    if "items" in o and isinstance(o["items"], dict):     # DB 形态
        return list(o["items"].values())
    return o.get("items", [])                              # 导出形态


PUNCT = re.compile(r"[\s·・\-_/\\|,，。.、:：;；!！?？()（）\[\]【】\"'“”‘’]+")


def norm(s):
    return PUNCT.sub("", (s or "").lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("q", nargs="?", default="", help="中文名关键词")
    ap.add_argument("--id", type=int, default=0, help="按 garb_id 反查")
    ap.add_argument("--status", default="", help="onsale / delisted / unknown")
    ap.add_argument("--list", action="store_true", help="列出全部")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    db = find_db()
    if not db:
        print("找不到索引。先跑: python catalog.py harvest --seed 2 --max-users 200")
        sys.exit(1)

    items = load_items(db)

    if a.id:
        hits = [x for x in items if x.get("garb_id") == a.id]
    elif a.list or not a.q:
        hits = items
    else:
        nq = norm(a.q)
        hits = []
        for x in items:
            hay = norm(x.get("title")) + "|" + norm(x.get("name"))
            if nq in hay:
                # 完全相等排前面
                hits.append(x)
        hits.sort(key=lambda x: (norm(x.get("title")) != nq, -len(x.get("title") or "")))

    if a.status:
        hits = [x for x in hits if x.get("status") == a.status]

    if not hits:
        print("没找到。索引里有 %d 条，试试更短的关键词，或先 harvest 扩充。" % len(items))
        sys.exit(2)

    hits = hits[:a.limit]

    if a.json:
        print(json.dumps(hits, ensure_ascii=False, indent=1))
        return

    print("%-8s %-8s %-10s %-28s %s" % ("garb_id", "image_id", "status", "标题", "素材"))
    print("-" * 96)
    for x in hits:
        print("%-8s %-8s %-10s %-28s %s" % (
            x.get("garb_id"), x.get("image_id"), x.get("status", "?"),
            (x.get("title") or x.get("name") or "")[:26],
            "有" if x.get("large") else "-"))
    print("\n共 %d 条" % len(hits))


if __name__ == "__main__":
    main()
