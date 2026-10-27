#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bili.py — 哔哩哔哩 App API 客户端（装扮线）

签名材料取自 bili-universal 9.1.2，文件偏移 0x1a0ab120。
"""

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request

APPKEY = "27eb53fc9058f8c3"
APPSEC = "c2ed53a74eeefe3cf99fbd01d8c9c375"
BUILD = "90102100"
MOBI_APP = "iphone"
PLATFORM = "ios"
UA = "Mozilla/5.0 BiliDroid/9.1.2 os/ios"

BASE = "https://app.bilibili.com"


def sign(params):
    p = dict(params)
    p["appkey"] = APPKEY
    p["ts"] = str(int(time.time()))
    p["build"] = BUILD
    p["mobi_app"] = MOBI_APP
    p["platform"] = PLATFORM
    qs = urllib.parse.urlencode(sorted(p.items()))
    p["sign"] = hashlib.md5((qs + APPSEC).encode()).hexdigest()
    return p


def call(url, params, access_key="", retries=2, delay=0.4):
    p = dict(params)
    if access_key:
        p["access_key"] = access_key
    p = sign(p)
    qs = urllib.parse.urlencode(sorted(p.items()))
    sep = "&" if "?" in url else "?"
    req = urllib.request.Request(url + sep + qs, headers={"User-Agent": UA})
    last = None
    for _ in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            last = e
            time.sleep(delay)
    raise last


# ------------------------------------------------------------------ 装扮线

def garb_list(vmid, ps=20, pn=1, ak=""):
    """某用户的装扮列表 → data.list[] { garbId, images[]{ imageId } }"""
    return call(BASE + "/x/v2/space/garb/list",
                {"vmid": vmid, "ps": ps, "pn": pn}, ak)


def garb_detail(vmid, garb_id, image_id, ak=""):
    """装扮详情 → data { garbId, imageId, smallImage, largeImage, isOwn ... }"""
    return call(BASE + "/x/v2/space/garb/detail",
                {"vmid": vmid, "garb_id": garb_id, "image_id": image_id}, ak)


def space_home(vmid, ak=""):
    """空间首页 → data.garb 块（含 mall 路由）"""
    return call(BASE + "/x/v2/space", {"vmid": vmid}, ak)


def collection_hall(vmid, ak=""):
    """收藏集大厅 → data.sidebar_info 里一堆 *JumpUrl"""
    return call("https://api.bilibili.com/x/garb/right/collection/aggregation_info",
                {"vmid": vmid}, ak)


# ------------------------------------------------------------------ 解析

def iter_garb_from_list(resp):
    """从 garb/list 响应里摊出 (garb_id, image_id, name, title)"""
    data = (resp or {}).get("data") or {}
    for it in (data.get("list") or []):
        gid = it.get("garbId") or it.get("garb_id")
        if not gid:
            continue
        name = it.get("name") or ""
        title = it.get("garbTitle") or it.get("garb_title") or ""
        for im in (it.get("images") or []):
            iid = im.get("imageId") or im.get("image_id")
            if iid:
                yield int(gid), int(iid), name, title
