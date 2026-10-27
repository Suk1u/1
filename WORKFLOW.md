# 下架皮肤 / 装扮 · Surge 模块工作流

> 一句话：**离线建库 → CDN 分发 → 响应注入**。模块本身不爬数据，只做最后一步改写。

---

## 一、三层架构

```
┌─────────────────────────────────────────────────────────────┐
│  ① 采集层         GitHub Actions，每 4 小时                 │
│                                                             │
│   walk-seeds ──→ 在售目录 (mall_ids.json)                    │
│   users      ──→ 我的装扮 (garb_index.json)   ← 下架在这里   │
│   themes     ──→ 皮肤部件 (themes.json)                      │
│   collections──→ 收藏集大厅 (collections.json)               │
│                        │                                    │
│                        ▼                                    │
│   export     ──→ Surge/catalog.json        （装扮）          │
│              ──→ Surge/catalog-themes.json （皮肤）          │
└────────────────────────┬────────────────────────────────────┘
                         │ git push
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  ② 分发层         raw.githubusercontent.com                  │
│                                                             │
│   .sgmodule  ← 模块定义                                     │
│   .js        ← 注入脚本                                     │
│   catalog*.json ← 数据                                      │
└────────────────────────┬────────────────────────────────────┘
                         │ Surge 拉取 + 缓存 6h
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  ③ 拦截层         Surge http-response 脚本                  │
│                                                             │
│   命中 pattern → 解析 JSON → 找列表数组 → 按 catalog 追加   │
│                → 返回改写后的 body                          │
└─────────────────────────────────────────────────────────────┘
```

**为什么这么分**：爬数据慢、会被 412 限流、要签名；注入要实时。把重活挪到离线，手机上只留一次 JSON 改写。

---

## 二、装扮模块（已通）

```
bili-garb-mall.sgmodule
  └─ pattern: ^https://(api|app)\.bilibili\.com/x/(garb|garb-digital)
     script:  garb_mall_inject.js
     catalog: catalog.json      ← 69 条，63 条下架
```

流程：

1. 你在装扮商城翻页 → H5 请求商城列表接口
2. Surge 拦下响应，脚本扫出列表数组（`/data/list`）
3. 认出 `item_id` / `name` / `cover` / `sale_status`
4. 把 catalog 里 `status=delisted` 的条目克隆成同样形状追加进去
5. 状态改成「在售」值（否则 H5 会自己过滤掉）
6. 名称加「（已下架）」、价格改「已下架」、角标改灰

**关键**：脚本运行时自己识别 schema，不硬编码字段名。商城改版也能跑。

---

## 三、皮肤模块（差最后一步）

### 3.1 皮肤是什么

**皮肤 = 套装里的 `skin` 部件**，不是独立商品。

```
suit_items:
  card / card_bg / emoji_package / pendant / skin / space_bg / thumbup / loading / play_icon
                                          ↑
                                        皮肤在这
```

取法：`suit/detail?item_id=<套装id>` → `suit_items.skin[0].item_id` → 再查一次拿到 37 个字段（配色 / 背景 / 图标 / zip 包）。

`themes.py` 已经把这一步做完了，数据在 `data/themes.json`，导出在 `Surge/catalog-themes.json`。

### 3.2 和装扮模块的差别：只差一个 pattern

注入脚本本身**完全通用**——它不认识「装扮」也不认识「皮肤」，只认识「列表数组 + ID 字段 + 名称字段 + 封面字段」。

所以皮肤模块只需要：

|         |                           |                       |
| ------- | ------------------------- | --------------------- |
| 项       | 装扮模块                      | 皮肤模块                  |
| pattern | `/x/(garb\|garb-digital)` | **待填**（见下）            |
| catalog | `catalog.json`            | `catalog-themes.json` |
| 脚本      | `garb_mall_inject.js`     | **同一个**               |

### 3.3 唯一缺口：皮肤列表接口的 URL

`bili-universal` 里没有主题列表接口——皮肤走的是装扮中心那个 H5，和装扮共用一套。所以静态分析拿不到。

**补法（一次就够）**：

1. 装 `bili-capture.sgmodule`，MITM 开着
2. App 里进 **我的 → 装扮 → 主题**（或装扮详情页的主题页签）
3. Safari 打开 `https://api.bilibili.com/__bili_capture`，筛 `theme` 或 `skin`
4. 看那条请求的 URL 和响应 `keys`

拿到之后：

```diff
  [Script]
- garb-skin-inject = type=http-response,pattern=<待填>,...
+ garb-skin-inject = type=http-response,pattern=^https:\/\/api\.bilibili\.com\/x\/garb\/v1\/theme\/list,...
```

**不用改脚本。** 一次改完，永久生效。

### 3.4 皮肤模块的完整流程

```
采集（已通）                    分发（已通）              拦截（待 pattern）
─────────────────              ─────────────           ─────────────────
themes.py build                catalog-themes.json      Surge 拦主题列表响应
  ↓                              ↓                        ↓
每个套装抽 skin               4 条，3 条下架            追加下架皮肤
  ↓                              ↓                        ↓
themes.json                    raw.githubusercontent    名称加后缀、状态改在售
                                                          ↓
                                                        皮肤列表里出现
```

---

## 四、数据怎么流动（时序）

```
GitHub Actions                GitHub Raw                iPhone / Surge
──────────────                ──────────                ──────────────
每 4 小时跑一次
  walk-seeds ──┐
  users      ──┤
  themes     ──┼→ data/*.json
  collections──┘        │
                        ▼
  export ──────→ Surge/catalog*.json
                        │
                        └──── git push ────→ raw.githubusercontent
                                                    │
                                                    │ 模块首次请求时拉取
                                                    ▼
                                              $persistentStore 缓存 6h
                                                    │
  你翻商城 ──────────────────────────────────────→ 响应被拦
                                                    │
                                             读缓存 catalog
                                                    │
                                             追加下架条目
                                                    │
                                             返回改写后的 JSON
                                                    ▼
                                              页面渲染出来
```

---

## 五、为什么必须离线建库

| 步骤      | 能不能放手机上 | 原因                    |
| ------- | ------- | --------------------- |
| 拉在售目录   | 不能      | 要几十轮请求，Surge 脚本没这耐心   |
| 采「我的装扮」 | 不能      | 同上，且要遍历多个 vmid        |
| 抽皮肤部件   | 不能      | 每套装一次 `suit/detail`，慢 |
| 注入响应    | **必须**  | 要实时，且要看得到页面           |

另外 B站 WAF 对高频敏感，连打两百多次就 412。离线跑在 GitHub 的 IP 上，慢慢来不心疼。

---

## 六、当前状态

| 环节         | 状态                       |
| ---------- | ------------------------ |
| 在售目录采集     | ✅ `walk-seeds`，260 个 id  |
| 我的装扮采集     | ✅ `users`，69 条 / 63 下架   |
| 皮肤提取       | ✅ `themes.py`，4 条 / 3 下架 |
| 收藏集采集      | ✅ `collections.py`，19 条  |
| 导出         | ✅ `export --themes`      |
| 装扮注入模块     | ✅ 已装可用                   |
| **皮肤注入模块** | ⚠️ **缺 pattern，需一次抓包**   |
| 自动更新       | ✅ Actions 每 4 小时         |

---

## 七、落地检查清单

**装扮模块**

- [x] 装 `bili-garb-mall.sgmodule`
- [x] MITM 信任证书
- [x] `catalog.json` 非空（现在 69 条）
- [ ] 实机验证：商城列表里能看到「（已下架）」条目

**皮肤模块**

- [x] 皮肤数据已导出（`catalog-themes.json`，3 条下架）
- [ ] 抓一次主题页，拿到列表接口 URL
- [ ] 填进 `.sgmodule` 的 `pattern`
- [ ] 实机验证

---

## 八、失败时看哪里

| 现象        | 查什么                                    |
| --------- | -------------------------------------- |
| 模块装了没反应   | Surge 日志里有没有 `[garb]` 前缀的输出            |
| 有日志但没注入   | `catalog` 里 `status=delisted` 的条数是不是 0 |
| 注入了但页面不显示 | `force=1` 有没有开（H5 会按状态过滤）              |
| 条目重复      | 正常，每页都会追加一批，翻页会重复                      |
| 点进去买不了    | 预期，服务端照样校验                             |
