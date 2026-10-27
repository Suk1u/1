#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_all.py — 拉全站装扮目录

搜索接口的 key_word 传 `*` 会返回全部，实测 5282 条，能翻到第 265 页。
ps 上限 100，所以 53 个请求就拉完。

    python fetch_all.py              # 全量拉取
    python fetch_all.py --resume     # 断点续跑
    python fetch_all.py --stats      # 看统计
    python fetch_all.py --grep 猫     # 在本地结果里搜

结果存 data/all_garbs.json。
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
OUT = os.path.join(DATA, "all_garbs.json")

WILDCARD = "*"
PS = 100          # 服务端上限，ps=200 也只给 99


def load():
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    return {"total": 0, "done_pages": [], "items": {}}


def save(db):
    os.makedirs(DATA, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)


def fetch_page(pn, ps=PS):
    d = garb_api.get("/x/garb/vas/search", {
        "key_word": WILDCARD, "pn": pn, "ps": ps,
        "web_location": garb_api.WEB_LOCATION,
    })
    if d.get("code") != 0:
        return None, d
    data = d.get("data") or {}
    return data, d


def slim(x):
    """只留有用的字段，别把整个响应塞进库"""
    return {
        "item_id": x.get("item_id"),
        "sub_item_id": x.get("sub_item_id"),
        "goods_type": x.get("goods_type"),
        "name": x.get("name") or "",
        "cover": x.get("cover") or "",
        "price": x.get("price"),
        "sale_count": x.get("sale_count_desc") or "",
        "button": x.get("button_type") or "",
        "jump": x.get("jump_url") or "",
        "sale_start": x.get("sale_start"),
        "show_start": x.get("show_start"),
    }


def cmd_fetch(a):
    db = load()
    done = set(db.get("done_pages") or [])

    first, raw = fetch_page(1, a.ps)
    if first is None:
        print("首页失败:", raw.get("code"), raw.get("message"))
        sys.exit(1)

    total = first.get("total") or 0
    db["total"] = total
    pages = (total + a.ps - 1) // a.ps
    print("全站 %d 条，%d 页（ps=%d）" % (total, pages, a.ps))

    added = 0
    for pn in range(1, pages + 1):
        if pn in done:
            continue
        if pn == 1:
            data = first
        else:
            data, raw = fetch_page(pn, a.ps)
            if data is None:
                print("  第 %d 页失败 %s，跳过" % (pn, raw.get("message")))
                time.sleep(3)
                continue
        lst = data.get("list") or []
        for x in lst:
            iid = x.get("item_id")
            if iid is None:
                continue
            k = str(iid)
            if k not in db["items"]:
                added += 1
            db["items"][k] = slim(x)
        done.add(pn)
        db["done_pages"] = sorted(done)

        if pn % 10 == 0 or pn == pages:
            save(db)
            print("  [%d/%d] 本次新增 %d，累计 %d 条"
                  % (pn, pages, added, len(db["items"])))
        time.sleep(a.sleep)

    save(db)
    print("\n完成：%d 条（服务端说 %d）" % (len(db["items"]), total))


def cmd_stats(a):
    db = load()
    items = list(db["items"].values())
    if not items:
        print("还没有数据。先跑 python fetch_all.py")
        sys.exit(1)

    from collections import Counter
    types = Counter(x.get("goods_type") for x in items)
    btns = Counter(x.get("button") for x in items)
    print("共 %d 条（服务端报告 %s）" % (len(items), db.get("total")))
    print("goods_type:", dict(types))
    print("button    :", dict(btns))
    print("已拉页数  :", len(db.get("done_pages") or []))
    print("\n样例:")
    for x in items[:5]:
        print("  %-12s %-24s %s" % (x["item_id"], x["name"][:22], x["sale_count"]))


def cmd_grep(a):
    db = load()
    items = list(db["items"].values())
    if not items:
        print("还没有数据。先跑 python fetch_all.py")
        sys.exit(1)

    import re
    pat = re.compile(a.grep, re.I)
    hits = [x for x in items if pat.search(x.get("name") or "")]
    print("命中 %d / %d\n" % (len(hits), len(items)))
    print("%-12s %-28s %-6s %-10s %s" % ("item_id", "名称", "type", "button", "销量"))
    print("-" * 76)
    for x in hits[:a.limit]:
        print("%-12s %-28s %-6s %-10s %s" % (
            x["item_id"], x["name"][:26], x.get("goods_type"),
            x.get("button"), x.get("sale_count")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", action="store_true", help="续跑（默认就会跳过已拉页）")
    ap.add_argument("--ps", type=int, default=PS)
    ap.add_argument("--sleep", type=float, default=garb_api.DEFAULT_SLEEP)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--grep", default="")
    ap.add_argument("--limit", type=int, default=60)
    a = ap.parse_args()

    if a.stats:
        cmd_stats(a)
    elif a.grep:
        cmd_grep(a)
    else:
        cmd_fetch(a)


if __name__ == "__main__":
    main()
