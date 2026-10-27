#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipeline.py — 全自动建库流水线

一条命令跑完整套，带时间预算，随时中断随时续。

    ① 拉全站目录      key_word=*，4786 条
    ② 找大户          从装扮的 owner_uid 反推做装扮的 UP 主
    ③ 排大户          查每个 owner 拥有多少套
    ④ 采我的装扮      从大户身上拿 garb_id + item_id + 名字
    ⑤ 判状态          sale_surplus / detail 空
    ⑥ 导出            catalog.json / catalog-themes.json

用法:
    python tools/pipeline.py                    # 默认 25 分钟预算
    python tools/pipeline.py --budget 600       # 10 分钟
    python tools/pipeline.py --only 4,5,6       # 只跑某几步
    python tools/pipeline.py --dry             # 只打印计划

每一步都会检查前一步的产出是否新鲜，不新鲜才跑。
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import garb_api      # noqa: E402
import fetch_all     # noqa: E402
import index_build   # noqa: E402

ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data") if os.path.isdir(os.path.join(ROOT, "data")) else HERE
OWNERS = os.path.join(DATA, "owners.json")

# 新鲜度阈值（秒）
FRESH_CATALOG = 7 * 24 * 3600     # 全站目录 7 天
FRESH_OWNERS = 3 * 24 * 3600      # owner 列表 3 天
FRESH_RANK = 2 * 24 * 3600        # 排行 2 天


def now():
    return time.time()


def load(p, default):
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def save(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


class Ctx:
    def __init__(self, deadline, sleep, dry):
        self.deadline = deadline
        self.sleep = sleep
        self.dry = dry

    def left(self):
        return self.deadline - now()

    def ok(self):
        return self.left() > 20

    def say(self, msg):
        print("  [%4ds] %s" % (int(self.left()), msg), flush=True)


# ---------------------------------------------------------------- ① 全站目录

def step_catalog(ctx):
    db = load(fetch_all.OUT, None)
    if db and db.get("items"):
        age = now() - (db.get("ts") or 0)
        if age < FRESH_CATALOG and len(db["items"]) > 3000:
            ctx.say("全站目录已新鲜（%d 条，%.1f 天前），跳过"
                    % (len(db["items"]), age / 86400))
            return True
    ctx.say("拉全站目录…")
    if ctx.dry:
        return True

    db = db or {"total": 0, "done_pages": [], "items": {}}
    done = set(db.get("done_pages") or [])
    first, raw = fetch_all.fetch_page(1, 100)
    if first is None:
        ctx.say("首页失败: %s" % raw.get("message"))
        return False
    total = first.get("total") or 0
    pages = (total + 99) // 100
    db["total"] = total
    added = 0
    for pn in range(1, pages + 1):
        if not ctx.ok():
            ctx.say("时间到，目录拉到第 %d/%d 页" % (pn, pages))
            break
        if pn in done:
            continue
        if pn == 1:
            data = first
        else:
            data, _ = fetch_all.fetch_page(pn, 100)
            if data is None:
                continue
        for x in (data.get("list") or []):
            iid = x.get("item_id")
            if iid is None:
                continue
            if str(iid) not in db["items"]:
                added += 1
            db["items"][str(iid)] = fetch_all.slim(x)
        done.add(pn)
        db["done_pages"] = sorted(done)
        time.sleep(ctx.sleep)
    db["ts"] = now()
    fetch_all.save(db)
    ctx.say("目录 %d 条（本次 +%d）" % (len(db["items"]), added))
    return True


# ---------------------------------------------------------------- ② 找 owner

def step_owners(ctx):
    ob = load(OWNERS, {"owners": {}, "sampled": [], "ts": 0})
    if ob.get("owners") and now() - ob.get("ts", 0) < FRESH_OWNERS:
        ctx.say("owner 列表已新鲜（%d 个），跳过" % len(ob["owners"]))
        return True
    ctx.say("从装扮反推 owner…")
    if ctx.dry:
        return True

    cat = load(fetch_all.OUT, {"items": {}})
    ids = [int(k) for k in cat.get("items", {})]
    if not ids:
        ctx.say("没有目录，跳过")
        return False

    # 从后往前取（新装扮的 owner 更活跃）
    sampled = set(ob.get("sampled") or [])
    todo = [i for i in ids if i not in sampled]
    todo.sort(reverse=True)
    todo = todo[:ctx.limit or 120]

    got = 0
    for iid in todo:
        if not ctx.ok():
            ctx.say("时间到，采了 %d 个 owner" % got)
            break
        x, _ = garb_api.detail(iid)
        sampled.add(iid)
        if x:
            uid = (x.get("properties") or {}).get("owner_uid")
            if uid and str(uid).isdigit():
                k = str(uid)
                e = ob["owners"].setdefault(k, {"uid": int(uid), "works": 0})
                e["works"] = e.get("works", 0) + 1
                got += 1
        time.sleep(ctx.sleep)

    ob["sampled"] = sorted(sampled)
    ob["ts"] = now()
    save(OWNERS, ob)
    ctx.say("owner %d 个（本次新增采样 %d 条装扮）" % (len(ob["owners"]), len(todo)))
    return True


# ---------------------------------------------------------------- ③ 排大户

def step_rank(ctx):
    ob = load(OWNERS, {"owners": {}})
    owners = list(ob["owners"].values())
    if not owners:
        ctx.say("没有 owner，跳过")
        return False

    todo = [o for o in owners if not o.get("count") or
            now() - o.get("checked", 0) > FRESH_RANK]
    todo.sort(key=lambda o: -o.get("works", 0))
    todo = todo[:ctx.limit or 60]
    ctx.say("查 %d 个 owner 的装扮数量…" % len(todo))
    if ctx.dry:
        return True

    for o in todo:
        if not ctx.ok():
            break
        lst, raw = garb_api.my_garbs(o["uid"], ps=50)
        if raw.get("code") == 0:
            o["count"] = len(lst)
            o["checked"] = now()
            if o["count"] >= 5:
                ctx.say("  %-12s %2d 套" % (o["uid"], o["count"]))
        time.sleep(ctx.sleep)

    save(OWNERS, ob)
    top = sorted(owners, key=lambda x: -(x.get("count") or 0))[:10]
    ctx.say("排行前 10: %s" % ", ".join("%s(%d)" % (o["uid"], o.get("count") or 0) for o in top))
    return True


# ---------------------------------------------------------------- ④ 采装扮

def step_harvest(ctx):
    ob = load(OWNERS, {"owners": {}})
    ranked = [o for o in ob["owners"].values() if (o.get("count") or 0) >= 5]
    ranked.sort(key=lambda o: -(o.get("count") or 0))
    if not ranked:
        ctx.say("没有够格的大户（>=5 套），跳过")
        return False

    ix = index_build.load_index()
    have = set(ix.get("users") or [])
    todo = [o for o in ranked if o["uid"] not in have][:ctx.limit or 40]
    ctx.say("采 %d 个大户的「我的装扮」…" % len(todo))
    if ctx.dry:
        return True

    added = 0
    for o in todo:
        if not ctx.ok():
            ctx.say("时间到，采了 %d 个" % len(have & {x['uid'] for x in todo}))
            break
        lst, raw = garb_api.my_garbs(o["uid"], ps=50)
        if raw.get("code") != 0:
            time.sleep(ctx.sleep)
            continue
        for x in lst:
            iid = x.get("item_id")
            if not iid:
                continue
            k = str(iid)
            it = ix["items"].get(k)
            if it is None:
                added += 1
                it = ix["items"][k] = {"item_id": iid, "name": "", "garb_id": None,
                                       "cover": "", "suit": True, "sources": []}
            it["name"] = x["garb_title"] or it.get("name") or ""
            it["garb_id"] = x.get("garb_id") or it.get("garb_id")
            it["cover"] = x.get("cover") or it.get("cover") or ""
            it["fans_number"] = x.get("fans_number") or it.get("fans_number") or ""
            it["images"] = x.get("images") or it.get("images") or []
            s = "user:%d" % o["uid"]
            if s not in it["sources"]:
                it["sources"].append(s)
        have.add(o["uid"])
        ix["users"] = sorted(have)
        ctx.say("  %-12s %2d 套 → 索引 %d 条" % (o["uid"], len(lst), len(ix["items"])))
        index_build.save_index(ix)
        time.sleep(ctx.sleep)

    index_build.save_index(ix)
    ctx.say("索引 %d 条（本次 +%d），来自 %d 个用户" % (len(ix["items"]), added, len(have)))
    return True


# ---------------------------------------------------------------- ⑤ 判状态

def step_classify(ctx):
    ix = index_build.load_index()
    todo = [v for v in ix["items"].values()
            if v.get("status") not in ("onsale", "soldout", "gone")]
    if not todo:
        ctx.say("状态都判过了，跳过")
        return True
    ctx.say("判 %d 条的状态…" % len(todo))
    if ctx.dry:
        return True

    stat = {"onsale": 0, "soldout": 0, "gone": 0, "unknown": 0}
    n = 0
    for v in todo:
        if not ctx.ok():
            break
        x, _ = garb_api.detail(v["item_id"])
        n += 1
        if not x or not x.get("name"):
            v["status"] = "gone"
        else:
            sp = x.get("sale_surplus")
            v["surplus"] = sp
            v["state"] = x.get("state")
            v["status"] = ("onsale" if isinstance(sp, int) and sp > 0
                           else "soldout" if sp == 0 else "unknown")
        stat[v["status"]] = stat.get(v["status"], 0) + 1
        if n % 20 == 0:
            index_build.save_index(ix)
            ctx.say("  %d/%d %s" % (n, len(todo), stat))
        time.sleep(ctx.sleep)

    index_build.save_index(ix)
    ctx.say("判定 %d 条: %s" % (n, stat))
    return True


# ---------------------------------------------------------------- ⑥ 导出

def export_all():
    """全站目录 → 紧凑数组，给搜索页用

    格式 [item_id, name, cover, owned(0/1), garb_id, goods_type]
    """
    cat = load(fetch_all.OUT, {"items": {}})
    ix = index_build.load_index()
    owned = {str(v["item_id"]): v["garb_id"]
             for v in ix["items"].values() if v.get("garb_id")}
    items = []
    for k, v in cat.get("items", {}).items():
        if v.get("goods_type") not in (1, 4):
            continue
        items.append([v["item_id"], v.get("name") or "", v.get("cover") or "",
                      1 if k in owned else 0, owned.get(k, 0), v.get("goods_type")])
    items.sort(key=lambda x: (-x[3], x[1]))
    out = os.path.join(ROOT, "Surge", "catalog-all.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"generated": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "format": "[item_id, name, cover, owned(0/1), garb_id, goods_type]",
                   "items": items}, f, ensure_ascii=False, separators=(",", ":"))
    print("  全站目录 %d 条 → %s (%.0f KB)"
          % (len(items), out, os.path.getsize(out) / 1024))


def step_export(ctx):
    ctx.say("导出 catalog…")
    if ctx.dry:
        return True
    import argparse as _ap
    index_build.cmd_export(_ap.Namespace(out="", themes=True))
    export_all()
    return True


STEPS = [
    ("① 全站目录", step_catalog),
    ("② 找 owner", step_owners),
    ("③ 排大户", step_rank),
    ("④ 采装扮", step_harvest),
    ("⑤ 判状态", step_classify),
    ("⑥ 导出", step_export),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=1500, help="总时间预算（秒）")
    ap.add_argument("--sleep", type=float, default=garb_api.DEFAULT_SLEEP)
    ap.add_argument("--limit", type=int, default=0, help="每步最多处理多少个")
    ap.add_argument("--only", default="", help="只跑这几步，逗号分隔的序号 1-6")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    only = set(int(x) for x in a.only.split(",") if x.strip().isdigit())
    ctx = Ctx(now() + a.budget, a.sleep, a.dry)
    ctx.limit = a.limit

    t0 = now()
    print("预算 %ds，开始\n" % a.budget)
    for i, (name, fn) in enumerate(STEPS, 1):
        if only and i not in only:
            continue
        print("%s" % name, flush=True)
        if ctx.left() <= 20:
            print("  预算用尽，停在这步之前")
            break
        try:
            fn(ctx)
        except Exception as e:
            print("  出错: %s" % e, flush=True)
        print()

    ix = index_build.load_index()
    items = list(ix.get("items", {}).values())
    from collections import Counter
    c = Counter(v.get("status", "unknown") for v in items)
    print("=" * 50)
    print("耗时 %ds，索引 %d 条" % (int(now() - t0), len(items)))
    print("状态:", dict(c))
    print("用户:", len(ix.get("users") or []))


if __name__ == "__main__":
    main()
