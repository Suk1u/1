#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""theme_probe.py — 主题列表接口的探测 / 学习 / 验证

主题（皮肤）走装扮中心那个 H5，包里没有接口地址，必须抓一次。
抓到之后用这个工具：

    python theme_probe.py learn --capture capture/xxx.json
    python theme_probe.py simulate --capture capture/xxx.json
    python theme_probe.py probe

learn     分析抓包，判断像不像主题列表，给出要填的 pattern
simulate  真的把 packages 合并进去，写 preview.json 供对比
probe     试一批候选接口路径（可能白试，但便宜）
"""

import argparse
import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import garb_api  # noqa: E402

ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data") if os.path.isdir(os.path.join(ROOT, "data")) else HERE
CAPTURE = os.path.join(ROOT, "capture") if os.path.isdir(os.path.join(ROOT, "capture")) else os.path.join(HERE, "capture")
THEMES = os.path.join(DATA, "themes.json")

ID_KEYS = ("themeId", "theme_id", "id")
URL_KEYS = ("downloadUrl", "download_url", "package_url", "packageUrl")
DIC_KEYS = ("themeDic", "theme_dic", "themeInfo", "resource")


def is_pkg(o):
    if not isinstance(o, dict):
        return False
    has_id = any(k in o for k in ID_KEYS)
    has_res = any(k in o for k in URL_KEYS) or any(k in o for k in DIC_KEYS) or "resourcePath" in o
    return has_id and has_res


def find_theme_arrays(node, path, out):
    if isinstance(node, list):
        if node and all(is_pkg(x) for x in node):
            out.append((path or "/", node))
        for i, v in enumerate(node):
            find_theme_arrays(v, path + "/" + str(i), out)
    elif isinstance(node, dict):
        for k, v in node.items():
            find_theme_arrays(v, path + "/" + k, out)
    return out


def load_capture(fp):
    with open(fp, encoding="utf-8") as f:
        o = json.load(f)
    return o.get("url", ""), o.get("body", o)


def load_packages():
    """从 themes.json 造 BFCMultiThemePkg 形状的包"""
    if not os.path.exists(THEMES):
        return []
    with open(THEMES, encoding="utf-8") as f:
        themes = json.load(f).get("themes") or {}
    out = []
    for t in themes.values():
        p = t.get("props") or {}
        if not p.get("package_url"):
            continue
        out.append({
            "themeId": t["theme_item_id"],
            "name": t.get("name") or t.get("suit_name") or "",
            "downloadUrl": p.get("package_url"),
            "md5Str": p.get("package_md5") or "",
            "resourcePath": "",
            "themeDic": p,
            "type": 0, "alias": "", "attribute": 0,
            "isOffical": True, "canChange": True,
            "isForce": False, "hideDialog": False, "needUpdate": False,
            "stime": 0, "etime": 0,
            "version": p.get("ver") or 0,
        })
    return out


def navigate(obj, path):
    cur = obj
    for seg in [x for x in path.split("/") if x]:
        cur = cur[int(seg)] if isinstance(cur, list) else cur.get(seg)
        if cur is None:
            return None
    return cur


# ---------------------------------------------------------------- learn

def cmd_learn(a):
    files = [a.capture] if a.capture else sorted(glob.glob(os.path.join(CAPTURE, "*.json")))
    if not files:
        print("没有抓包。先装 bili-capture.sgmodule，进主题页抓一次，把响应存进 capture/")
        sys.exit(1)

    found = []
    for fp in files:
        try:
            url, body = load_capture(fp)
        except Exception:
            continue
        arrs = find_theme_arrays(body, "", [])
        for path, arr in arrs:
            found.append((len(arr), path, url, arr, fp))

    if not found:
        print("这批抓包里没有像「主题包列表」的数组。")
        print("判断标准：元素里同时有 id 类字段（themeId/id）和资源类字段（downloadUrl/themeDic/resourcePath）。")
        print()
        print("可能原因：")
        print("  1. 抓的不是主题页（去「我的 → 装扮 → 主题」或装扮详情页的主题页签）")
        print("  2. 主题列表是嵌在别的大响应里，或者压根是本地读的")
        print("  3. 字段名不在这几个里，把那条响应的 keys 发我")
        sys.exit(2)

    found.sort(key=lambda x: -x[0])
    print("找到 %d 个候选：\n" % len(found))
    for n, path, url, arr, fp in found[:5]:
        print("  %3d 个  %s" % (n, path))
        print("        URL   %s" % url[:110])
        print("        文件  %s" % os.path.basename(fp))
        sample = arr[0]
        keys = list(sample.keys())
        print("        字段  %s%s" % (", ".join(keys[:8]), " ..." if len(keys) > 8 else ""))
        print("        id=%s  url=%s" % (
            next((sample[k] for k in ID_KEYS if k in sample), "-"),
            str(next((sample[k] for k in URL_KEYS if k in sample), "-"))[:60]))
        print()

    best = found[0]
    print("=== 建议配置 ===")
    pat = best[2].split("?")[0]
    pat = pat.replace(".", "\\.").replace("/", "\\/")
    print("  pattern   ^%s" % pat)
    print("  mode      theme")
    print("  catalog   .../Surge/catalog-themes.json")
    print()
    print("把它填进 bili-garb-skin.sgmodule 的 pattern= 里，再跑一次 simulate 验证合并效果。")


# ------------------------------------------------------------- simulate

def cmd_simulate(a):
    fp = a.capture
    if not fp:
        files = sorted(glob.glob(os.path.join(CAPTURE, "*.json")))
        if not files:
            print("没有抓包")
            sys.exit(1)
        fp = files[0]

    url, body = load_capture(fp)
    arrs = find_theme_arrays(body, "", [])
    if not arrs:
        print("这条抓包里没有主题包数组: %s" % fp)
        sys.exit(2)

    arrs.sort(key=lambda x: -len(x[1]))
    path, arr = arrs[0]
    print("目标数组 %s，原有 %d 个" % (path, len(arr)))

    pkgs = load_packages()
    if not pkgs:
        print("themes.json 里没有可用的包，先跑 python themes.py build")
        sys.exit(1)

    have = set()
    for x in arr:
        for k in ID_KEYS:
            if k in x:
                have.add(str(x[k]))
                break

    added = []
    for p in pkgs:
        if str(p["themeId"]) in have:
            continue
        arr.append(p)
        added.append(p)

    print("注入 %d 个（原有 %d → 现在 %d）" % (len(added), len(arr) - len(added), len(arr)))
    for p in added:
        print("   + %-10s %-18s md5=%s" % (p["themeId"], p["name"], p["md5Str"][:10]))

    out = os.path.join(HERE, "preview-theme.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, indent=1)
    print("\n完整结果写到 %s，可以和原抓包 diff。" % out)


# ---------------------------------------------------------------- probe

CANDIDATES = [
    "/x/garb/v2/mall/theme/list",
    "/x/garb/v1/theme/list",
    "/x/garb/v2/theme/list",
    "/x/garb/theme/list",
    "/x/garb/v1/user/theme",
    "/x/garb/mall_v2/theme",
    "/x/garb/v2/mall/theme",
    "/x/garb/theme/pkg/list",
    "/x/garb/v1/theme/pkg",
]


def cmd_probe(a):
    print("试 %d 个候选路径（大概率白试，主题列表可能压根不在服务端）\n" % len(CANDIDATES))
    for p in CANDIDATES:
        d = garb_api.get(p, {"web_location": garb_api.WEB_LOCATION})
        code = d.get("code")
        data = d.get("data")
        if code == 0:
            n = 0
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        n += len(v)
            print("  ✓ %-34s code=0  列表项 %d" % (p, n))
        elif code == "ERR":
            print("  - %-34s 网络失败" % p)
        else:
            print("  · %-34s code=%s" % (p, code))
        time.sleep(1.2)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    l = sub.add_parser("learn"); l.add_argument("--capture", default="")
    l.set_defaults(func=cmd_learn)

    s = sub.add_parser("simulate"); s.add_argument("--capture", default="")
    s.set_defaults(func=cmd_simulate)

    p = sub.add_parser("probe"); p.set_defaults(func=cmd_probe)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
