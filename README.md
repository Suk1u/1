# bilibili 装扮商城 · 显示已下架装扮

一个 Surge 模块。拦截哔哩哔哩装扮商城的列表响应，把**已经下架、商城列表里查不到**的装扮注入进去，让它们照常显示、能看能点。

```
┌─────────────┐   response    ┌──────────────┐   注入后    ┌──────────┐
│ 装扮商城 H5  │ ◄──────────── │ Surge 脚本   │ ◄───────── │ 原响应    │
└─────────────┘               └──────────────┘             └──────────┘
                                     ▲
                                     │ catalog.json
                              已下架装扮 ID 库
```

---

> 完整架构和落地清单见 **`WORKFLOW.md`**。

## 文件

```
Surge/bili-garb-mall.sgmodule   注入模块（装这个）
Surge/garb_mall_inject.js       注入脚本，运行时自识别列表结构
Surge/catalog.json              下架装扮库（index_build export 产出）
Surge/catalog-themes.json       下架皮肤库（export --themes 产出）
Surge/catalog-all.json          全站装扮目录（4786 条，565 KB）
Surge/bili-garb-search.sgmodule 搜索模块（App 内搜索 + 独立搜索页）
Surge/bili-garb-live.sgmodule   现取模块（不建库，填 vmid 即用）
Surge/garb_search_view.js       搜索页
Surge/bili-garb-skin.sgmodule   皮肤注入模块（待填 pattern）
tools/theme_probe.py            主题接口探测 / 学习 / 合并验证
tools/fetch_all.py              全站目录拉取（key_word=*）
tools/pipeline.py               全自动流水线（六步串起来）
Surge/bili-capture.sgmodule     抓包模块（可选）
Surge/capture_record.js         抓包记录
Surge/capture_view.js           抓包面板
mall.html                       本地索引浏览器，带中文名搜索框

tools/garb_api.py               接口客户端（商城搜索 / 详情 / 我的装扮）
tools/index_build.py            索引构建 + 导出
tools/find.py                   按中文名搜，标注在售/下架
tools/themes.py                 提取装扮里的主题部件
tools/collections.py            采集收藏集（含下架）

data/garb_index.json            名字索引（主数据）
data/mall_ids.json              在售目录
data/seed_vmids.txt             采集种子（装扮收藏大户）
data/themes.json                主题部件（配色 + 包地址）
data/collections.json           收藏集 / 合集 / 装扮 大厅条目
```

---

## 安装

1. Surge → 首页 → 模块 → 安装新模块，填：

```
https://raw.githubusercontent.com/Suk1u/1/main/Surge/bili-garb-mall.sgmodule
```

2. 打开 MITM 并信任证书（`api.bilibili.com` / `app.bilibili.com`）
3. 重启哔哩哔哩，进装扮商城

装好后模块会从 `Surge/catalog.json` 拉库，里面现在有 69 条（63 条下架）。想扩充看下面「建库」。

---

## 全自动流水线

一条命令跑完整套：

```bash
python tools/pipeline.py --budget 1500
```

六步，每步都查新鲜度，跑过的跳过；预算用完就停，下次接着跑：

```
① 全站目录    key_word=* 拉 4786 条        新鲜 7 天内跳过
② 找 owner    从装扮的 owner_uid 反推 UP 主  新鲜 3 天内跳过
③ 排大户      查每个 owner 拥有多少套        新鲜 2 天内跳过
④ 采装扮      从大户的「我的装扮」拿 garb_id + item_id + 名字
⑤ 判状态      sale_surplus / detail 空
⑥ 导出        catalog.json / catalog-themes.json
```

### 为什么是「找 owner」而不是「爬关注链」

`x/relation/followings` 要登录态，CI 里跑不了。

但每个装扮的 `suit/detail` 里有 `properties.owner_uid`——**做这套装扮的 UP 主**。这些人自己往往收藏最多。从全站目录里抽样拿 owner_uid，再查他们拥有几套，就是天然的「大户榜」。

### 实测一轮

```
② 找 owner   → 19 个
③ 排大户      → 9 个拥有 50 套（ps=50 上限，实际可能更多）
              3493131766991076(50) 672197118(50) 670729222(50)
              3493134470220310(50) 5888511(50) 15938156(49) ...
④ 采装扮      → 索引 69 → 444 条，102 秒
⑤ 判状态      → 19 gone / 102 onsale / 8 soldout / 315 待判
⑥ 导出        → catalog.json 444 条
```

一次跑 102 秒索引涨 6.4 倍。CI 每 4 小时接着跑，剩下的 315 条会慢慢判完，同时继续找新的大户。

### 手动控制

```bash
python tools/pipeline.py --only 4,5,6        # 只跑采装扮/判状态/导出
python tools/pipeline.py --budget 600        # 10 分钟
python tools/pipeline.py --limit 20          # 每步最多处理 20 个
python tools/pipeline.py --dry               # 只看计划不动手
```

---

## 建库

下架装扮只在「我的装扮」里。所以索引从已拥有列表采集，不是从商城。

```bash
# 1. 拉全量在售目录（用来判定「在售 / 下架」）
python tools/index_build.py walk-seeds --rounds 30

# 2. 从种子用户的「我的装扮」采集（含下架）
python tools/index_build.py users --vmids $(paste -sd, data/seed_vmids.txt) --no-follow

# 3. 导出给 Surge 模块吃的 catalog.json
python tools/index_build.py export
```

`export` 会写 `Surge/catalog.json`，只保留 `status=delisted` 的条目。提交推送后模块下次刷新就生效（缓存 6 小时）。

三步跑完一次，索引里就有东西了。之后靠 GitHub Action 定时扩（每 4 小时一次）。

**为什么必须拉在售目录**：`我的装扮` 只告诉你「谁拥有什么」，分不出在售还是下架。拿商城在售集合做差集，差集里的才是下架。

---

## 状态到底怎么分

先纠正一个容易搞错的地方：**下架不等于搜不到**。

用 `suit/detail` 的真实字段判，只有三种：

| status | 判定依据 | 搜索能搜到？ | 商城列表显示？ |
|---|---|---|---|
| `onsale` | `sale_surplus > 0` | ✅ | ✅ |
| `soldout` | `sale_surplus == 0` | ✅ | ❌ |
| `gone` | `suit/detail` 返回空 | ❌ | ❌ |

实测 69 条：**43 在售 / 8 售罄 / 18 已移除**。

**关键**：`soldout` 和 `gone` 是两件事。

- **售罄** —— 商品记录还在，搜索索引里有，按名字搜得到，只是买不了
- **已移除** —— 商品记录被删了，`suit/detail` 查不到，搜索也搜不到

### 售罄具体是什么

B站 装扮绝大多数是**限量发售**。`suit/detail` 里两个字段说明一切：

```
sale_quantity   10000     总发行量
sale_surplus    0         剩余库存
```

`sale_surplus` 归零就是售罄。四个实测样本：

| 装扮 | 总发行 | 剩余 | 已售 | 结论 |
|---|---:|---:|---|---|
| 七海Nana7mi VR | 10,000 | **0** | 1万+ | 售罄 |
| BML2021 | 50,000 | 37,833 | 1万+ | 在售 |
| EveOneCat2 | 1,000,000 | 675,437 | 30万+ | 在售 |
| 雫るる制服ver. | 30,000 | 17,707 | 1万+ | 在售 |

相关字段：

| 字段 | 含义 |
|---|---|
| `sale_quantity` | 总发行量 |
| `sale_surplus` | 剩余库存，**0 = 售罄** |
| `sale_quantity_limit` | 是否限量（`true` 才会计库存） |
| `sale_buy_num_limit` | 单账号限购数（实测都是 100） |
| `sale_reserve_switch` | 是否需要预约 |
| `next_activity` | **有值说明还有后续活动**（补货 / 折扣） |

`七海Nana7mi` 的 `next_activity` 是 `null` —— 没有补货计划，就是真的没了。
`BML2021` 和 `EveOneCat2` 有 `open_platform_vip_discount`，说明还有大会员折扣活动。

**售罄之后**：持有者照样能穿，详情页还能打开，搜索还能搜到，只是官方渠道买不到。

### 为什么「我的装扮」能拿到已移除的

B站 存了两套互不相干的记录：

| | 键 | 内容 | 商品删了会怎样 |
|---|---|---|---|
| **商品库** | `item_id` | 名称、库存、价格、部件 | 记录消失，`suit/detail` 返回空 |
| **持有库** | `mid` + `garb_id` | 名称、立绘、持有编号 | **不受影响**，一直在 |

`x/v2/space/garb/list?vmid=X` 读的是**持有库**，所以：

```
item_id       garb_title              状态      立绘
211450401     椿屋小奈Yomi·永恒花嫁     gone      4 张
3898          2021拜年纪              gone      4 张
```

这两条 `suit/detail` 都查不到，但「我的装扮」返回得**比商城还全**：

```json
{
  "garb_title": "椿屋小奈Yomi·永恒花嫁",
  "item_id": 211450401,
  "garb_id": 1713863778001,
  "fans_number": "NO.000003",
  "images": [".../42961345.jpg", ".../e17830f0.jpg", ".../357989f9.jpg", ".../a2dbdc74.jpg"]
}
```

**立绘直接在列表响应里**，不用再调任何接口。

所以 `gone` 那批的获取路径只有一条：

```
别人的「我的装扮」 → garb_title + item_id + garb_id + 立绘
```

这也解释了为什么这个项目一开始的方向是对的 —— 下架的确实只在「我的装扮」里，但原因不是「商城搜不到」，而是**商品记录删了、持有记录还在**。

所以「下架装扮搜不到」这个说法只对 `gone` 成立。真正下架但记录还在的，搜名字是能出来的。

### 为什么之前判错了

我一开始用「`item_id` 不在商城推荐流里」判定下架。**这是错的** —— 推荐流只有 260 个，是抽样，不是全量目录。拿抽样做差集，会把大量还在卖的商品误判成下架。

正确的做法是调 `suit/detail` 看 `sale_surplus`：

```bash
python tools/index_build.py classify --refresh
```

---

## 按中文名搜

```bash
python tools/find.py 明日方舟
```

```
item_id      名称                        在售?
--------------------------------------------
55655        明日方舟                      在售
2010         明日方舟                      在售
5359         明日方舟音律联觉                 在售
39220        明日方舟·灯下定影                ★已移除
```

`--delisted` 只列售罄 + 已移除的。

### 搜不到的怎么办

`gone` 那批连 `suit/detail` 都查不到，搜索索引里也没有。只能从**别人的「我的装扮」**里翻出来 —— 因为持有记录是独立的，商品记录删了，用户的持有还在。

```bash
python tools/index_build.py users --vmids $(paste -sd, data/seed_vmids.txt) --no-follow
```

这也是为什么 `我的装扮` 是唯一能捞到 `gone` 的入口。

### 商城搜索（只出在售 + 售罄）

```
GET /x/garb/vas/search?key_word=&pn=&ps=&web_location=333.40212
```

匿名可调。`total` 是过滤前命中数，`list` 是过滤后 —— 差值通常来自非套装商品（表情包、卡片），不一定是下架。

```bash
python tools/garb_api.py search 欧皇
python tools/garb_api.py detail 120730201
```

### 速率

B站 WAF 对高频敏感，连打两百多次会 412，要等冷却。工具默认 1.2 秒一次 + 指数退避。

---

## 全站装扮目录

搜索接口的 `key_word` 传 `*` 会返回全部：

```
GET /x/garb/vas/search?key_word=*&pn=1&ps=100
→ total = 5282
```

`ps` 上限 100（传 200 也只给 99），所以 53 个请求拉完。

```bash
python tools/fetch_all.py            # 全量拉，约 1 分钟
python tools/fetch_all.py --stats
python tools/fetch_all.py --grep 猫   # 本地搜
```

实测拉到 **4786 / 5282**（90%）。差的那 496 是分页漂移——搜索结果的排序在多次请求之间会变，翻页会漏。多扫几轮能补，但不是必须。

导出给搜索页用的紧凑格式在 `Surge/catalog-all.json`（565 KB）：

```json
[item_id, name, cover, owned(0/1), garb_id, goods_type]
```

### 两套 id，这是「应用」的边界

| | 是什么 | 谁给 | 用途 |
|---|---|---|---|
| `item_id` | 商品 id（9 位为主） | 搜索 / 详情 | 查资料 |
| `garb_id` | 装扮 id（13 位或 4-5 位） | **只有「我的装扮」给** | `dress` 应用 |

`suit/detail` 里的 `suit_items[].item_id` 也不是 `garb_id`——BML2021 的 suit_items 是 5202/5222/5221…，而它作为用户装扮时 `garb_id` 是另一套编号。

**结论**：

- **搜索全部装扮** → ✅ 4786 条，`catalog-all.json`
- **应用** → 只有 `garb_id` 已知的才行，而 `garb_id` 只出现在「我的装扮」里
- **「我的装扮」只列已拥有的** → 所以能应用的 = 已拥有的

下架的装扮如果**你已经拥有**，`garb_id` 在列表里，`dress` 服务端 `isOwn=true` 通过 —— 能搜、能穿。
没拥有的，`garb_id` 根本不知道，连请求都构造不出来。

搜索页里 `status=owned` 的才有 `garb_id`，详情里会显示「可以」并给出 dress 参数；`status=catalog` 的显示「不行 —— 缺 garb_id」。

---

## 在 App 里搜下架装扮

装这个模块：

```
https://raw.githubusercontent.com/Suk1u/1/main/Surge/bili-garb-search.sgmodule
```

它做两件事：

### ① App 内搜索注入

拦截 `x/garb/vas/search`，把库里名字命中的下架装扮追加到搜索结果。

```
你在商城搜「七海」
  ↓
官方返回：七海Nana7mi（售罄）
  ↓
模块追加：美波七海（已下架）
  ↓
搜索结果里两条都在
```

**按关键词过滤**：脚本从请求 URL 里读 `key_word`，只注入名字包含它的条目。搜「明日方舟」不会冒出「七海」。

一次最多注入 20 条，不撑爆列表。

### ② 独立搜索页

Safari 打开：

```
https://api.bilibili.com/__garb_search
```

一个完整的搜索界面，输入中文名模糊匹配（忽略空格标点）。

**列表**：立绘 + 状态标签（已移除 / 售罄 / 在售 / 皮肤）+ `garb_id / image_id`

**点开详情**：

- 大图轮播（`images[]` 多张时左右滑，底部有指示点）
- 状态、`garb_id`、`image_id`、持有编号、配色模式
- 按钮：复制 item_id / 复制 garb_id / 下载主题包（皮肤才有）/ 打开官方详情页

数据来自 `catalog.json` + `catalog-themes.json`，和模块共用。

### 覆盖范围

搜得到多少，取决于 `catalog.json` 里有多少。现在 69 条（43 在售 / 8 售罄 / 18 已移除）。

扩充靠 Actions 每 4 小时跑一次，或手动：

```bash
python tools/index_build.py users --vmids $(paste -sd, data/seed_vmids.txt) --no-follow
python tools/index_build.py classify
python tools/index_build.py export --themes
```

---

## 不建库：现取模式

前面那套（Actions 采集 → 导出 catalog → 模块读）覆盖广，但要等 CI 跑。**如果只想搜自己账号里的装扮，有更省事的路**：

```
https://raw.githubusercontent.com/Suk1u/1/main/Surge/bili-garb-live.sgmodule
```

装之前改一个地方——把 `vmid=2` 换成你自己的 UID（点开自己空间，地址栏 `/space/` 后面那串数字）。

改完就完事了，不用建库、不用 CI、不用 GitHub。

### 它怎么工作的

模块里带了一份 MD5 实现，**自己在 JS 里算签名**：

```
1. 你在商城搜「七海」
2. 模块拦下响应
3. 同时用你的 vmid 调 x/v2/space/garb/list（appkey + ts + sign 现场算）
4. 拿到你「我的装扮」里的全部装扮
5. 按关键词过滤，追加到搜索结果
```

签名逻辑和 `tools/garb_api.py` 里那套完全一致，只是从 Python 搬到了 JS：

```js
sign = md5(sorted_query + appsec)
```

`appkey` / `appsec` 从 IPA 二进制里提的，iOS 那对。

### 缓存

拉一次存 `$persistentStore`，6 小时有效。不重复请求。

### 两种模式对比

| | 建库（`bili-garb-search`） | 现取（`bili-garb-live`） |
|---|---|---|
| 覆盖 | 所有种子用户采到的（69 条，跨账号） | **只有你自己账号的** |
| 依赖 | GitHub Actions + raw CDN | 无 |
| 首次延迟 | 0（读缓存） | 一次 API 往返 |
| 能搜到别人的下架装扮 | ✅ | ❌ |
| 需要改配置 | 不用 | 填 vmid |

**建议两个都装**：现取兜底（自己的收藏一定在），建库补全（别人的收藏）。

### 实测

vmid=2（b站官方）现取到 7 套：

```
211450401  椿屋小奈Yomi·永恒花嫁（我的装扮）
39495      蕾蕾大表哥（我的装扮）
32296      EveOneCat2（我的装扮）
5235       BML2021（我的装扮）
3898       2021拜年纪（我的装扮）
2575       七海Nana7mi（我的装扮）
1157       如果历史是一群喵（我的装扮）
```

其中 211450401 和 3898 连 `suit/detail` 都查不到（商品记录已删），照样拿得到。

### 后缀

现取模式默认标「（我的装扮）」而不是「（已下架）」——因为它不判断状态，只说明「这是你收藏里的」。要改就改 `argument` 里的 `suffix=`。

---

## 主题装扮

**「主题」不是独立商品，是套装里的一个部件。**

每个套装在 `suit_items` 下挂 9 类部件，其中 `skin` 就是主题：

```
suit_items:
   card / card_bg / emoji_package / pendant / skin / space_bg / thumbup / loading / play_icon
                                    ↑
                                  主题在这
```

取法：

```bash
python tools/themes.py build      # 遍历索引，抽出每个套装的 skin
python tools/themes.py list       # 列出
python tools/themes.py show 5224  # 看完整配置
python tools/themes.py pack 5224  # 只打印 zip 地址
```

```
theme_id     套装           名称                     mode     包
----------------------------------------------------------------------------------
39489        39495        蕾蕾大表哥                  light    有
32264        32296        EveOneCat2             dark     有
5224         5235         BML2021                dark     有
2574         2575         七海Nana7mi              dark     有
```

### 一个主题里有什么

`GET /x/garb/v2/mall/suit/detail?item_id=<theme_id>` 返回 37 个字段：

```
color                #ffffff          主色
color_mode           dark             亮/暗
color_second_page    #454078          二级页配色
head_bg / head_tab_bg / side_bg / tail_bg      各区块背景图
tail_icon_*          10 个图标（普通/选中 × main/myself/dynamic/channel/shop）
image_cover / image_preview                    封面和预览
package_url          .../garb/zip/xxx.zip      ★ 主题包
package_md5          041cb8b5...
ver                  1622174043
```

`package_url` 实测可下：`application/zip`，879 KB，公开无鉴权。

也就是说**拿到 theme_id 就等于拿到整套主题资源**——配色、背景、图标、包。

### 下架套装的主题还在吗

在。主题是套装的子件，走同一个 `suit/detail`，不查上架状态。BML2021 这套已经下架，主题 5224 照样能查、包照样能下。

---

## 收藏集

**能拿，但只到「收藏集」这一层。**

收藏集大厅是公开的：

```
GET /x/garb/right/collection/aggregation_info?vmid=X
```

匿名可调，返回混装三类：

| biz_type | 含义 | biz_id 是 | item_id 是 |
|---|---|---|---|
| 1 | 装扮 | item_id | 形象 id |
| 2 | 收藏集 | **act_id** | **card_type_id** |
| 3 | 合集 | 合集 id | 字符串 id |

每条还带 `title.title`（名称）、`extra.owned`/`total`（持有/总数）、`detail_jump_url`、`item.extra.unusable_reason`（权益失效原因）。

**包含已下架的** —— 实测 vmid=2 的 10 条里有已下架装扮，收藏集也一样。

```bash
python tools/collections.py collect --vmids 2,524387426,7420522
python tools/collections.py list
python tools/collections.py list --type 2      # 只看收藏集
```

```
类型     biz_id     card_type_id     名称                     持有
--------------------------------------------------------------------
收藏集    108760     1754382100001    永雏塔菲叮咚集                7/9
收藏集    107827     1748424094009    明前奶绿·童话梦境              7/8
收藏集    106950     1762244847002    凸变英雄X                  1/31
收藏集    106917     1743418082017    rurudo箱庭少女之梦           14/16
收藏集    103874     1727081954034    幻星乐园                   29/53
```

### 限制：每用户只出 10 条

`ps` 被服务端忽略（永远 10），翻页游标 `last_id`/`last_type`/`pn`/`offset`/`page` 全试过，**都不推进**。`simple_list` 返回 `total=21` 但 `list` 恒空，大概要登录态。

所以策略和多用户采集一样：**多喂 vmid，每个贡献 10 条**。工具会在总数大于 10 时打警告。

### 单卡明细还没打通

`x/vas/dlc_act/act/card/detail?act_id=&card_type_id=` 返回空。
`x/garb/digital/card/detail?vmid=&card_id=&use_scene=1` 能通（code=0），schema 是：

```
card_type_id  card_id  card_type  card_status  card_name
card_no  card_cnt  card_img  video_list  holding_rate  card_scarcity
horizontal_card_light_url / vertical_card_light_url ...
```

但 `card_id` 传 `card_type_id` 拿到的全是 0，参数语义还没对上。**要往下挖得先抓一次收藏集详情页。**

---

## 能不能「假装拥有」本地用起来

分两种，效果完全不同。

### 装扮套装 —— 只能骗显示

套装是**服务端状态**。`x/v2/space/garb/dress` 服务端校验 `isOwn`，客户端说了不算。

能做的只有：拦截 `x/v2/space` 或 `space/garb/detail` 的响应，把立绘 URL 换成下架那套的。本地看自己空间「穿上了」，但：

- 服务端记录没变
- 别人看你还是原样
- 点「穿戴」按钮，服务端照样拒

**纯视觉，不是真拥有。**

### 主题 / 皮肤 —— 有真实的本地化空间

这块不一样。`BFCMultiThemePkg` 的字段说明了一切：

```objc
themeId  name  version
resourcePath     本地路径
downloadUrl      下载地址
md5Str           校验
themeDic         主题定义（35 个字段）
isOffical  canChange  isForce  needUpdate
stime  etime     有效期
```

**主题是本地包**。客户端流程是：

```
拿列表 → 下载 zip 到 resourcePath → 校验 md5Str → 从 themeDic 应用
```

`BFCMultiTheme` 的方法也印证了：`initLocalThemes` / `switchThemeWithId:` / `getValidPkg` / `_localThemeArray`。

所以只要能把一个包塞进主题列表，客户端会自己下载、校验、应用 —— **本地真的换掉**，不经过任何「你拥没拥有」的检查。

### 数据已经备好了

`export --themes` 现在多导一份 `packages`，形状就是 `BFCMultiThemePkg`：

```json
{
  "themeId": 5224,
  "name": "BML2021",
  "downloadUrl": "https://i0.hdslb.com/bfs/garb/zip/7355fde4....zip",
  "md5Str": "041cb8b510b3ee6486f696cf3f1a0d0e",
  "themeDic": { ...35 个字段，配色/背景/图标全在... },
  "isOffical": true, "canChange": true, "isForce": false,
  "stime": 0, "etime": 0
}
```

实测 4 个包，其中 `七海Nana7mi` 是售罄状态，`BML2021` / `蕾蕾大表哥` / `EveOneCat2` 在售。

### 缺的还是那一步

主题列表接口的 URL 仍然不知道（皮肤走装扮中心那个 H5，包里没有）。

抓到之后用 `theme_probe.py` 一条龙：

```bash
# 1. 分析抓包，判断像不像主题列表，给出要填的 pattern
python tools/theme_probe.py learn --capture capture/xxx.json

# 2. 真的合并一遍，看效果
python tools/theme_probe.py simulate --capture capture/xxx.json

# 3. 填进模块
#    pattern=^https://////api//.bilibili//.com///x///garb///v2///mall///theme///list
#    mode=theme
#    catalog=.../catalog-themes.json
```

`learn` 的判断标准：数组元素同时有 id 类字段（`themeId`/`id`）和资源类字段（`downloadUrl`/`themeDic`/`resourcePath`）。

实测（用 mock 抓包）：

```
找到 1 个候选：
    2 个  /data/theme_list
        字段  themeId, name, downloadUrl, md5Str, resourcePath, themeDic, isOffical, canChange

=== 建议配置 ===
  pattern   ^https://////api//.bilibili//.com///x///garb///v2///mall///theme///list
  mode      theme
```

`simulate` 会把 4 个包（含 35 个字段的 themeDic）合并进列表，写到 `preview-theme.json` 供 diff。

注入逻辑只按 `themeId` 去重 —— 已有的不重复塞，缺的补上。

### 一句话总结

| | 装扮套装 | 主题 / 皮肤 |
|---|---|---|
| 状态存在哪 | 服务端 | 本地包 |
| 能骗显示 | ✅ | ✅ |
| 能真的用 | ❌ 服务端校验 | ✅ 只要包能下能校验 |
| 缺什么 | 无（已能做） | 列表接口 URL |

---

## 抓包

配套的抓包模块，用来确认商城到底调了哪些接口（比如搜索有没有 `status` 参数）。

**装**：

```
https://raw.githubusercontent.com/Suk1u/1/main/Surge/bili-capture.sgmodule
```

**看**：Safari 打开

```
https://api.bilibili.com/__bili_capture
```

Surge 会把请求短路掉，直接返回本地面板，不会真的打到服务器。

### 面板里有什么

| 列 | 含义 |
|---|---|
| 方法 / 状态码 / 时间 | 基本元信息 |
| 大小 | 响应体字节数 |
| 路径 | 去掉 query 的 URL |
| `列表 /data/list ×20` | **自动识别出来的列表数组**，路径和长度 |
| `keys:` | 响应 JSON 的顶层字段 |
| 预览 | 前 2KB body |

点一行展开看完整 URL 和预览。搜索类、商城类的条目会高亮。

底部两个按钮：`JSON` 拿原始数据、`清空` 重置缓冲。

### 默认只抓装扮相关

`only` 参数默认是 `garb|suit|mall|search|vas|digital|collect|space`，避免被心跳、埋点刷屏。

想抓全部就把 `argument` 里的 `only=` 删掉：

```
argument=cap=100
```

其他参数：

| 键 | 默认 | 说明 |
|---|---|---|
| `cap` | 60 | 缓冲条数 |
| `full` | 0 | 存完整 body（默认只存 2KB 预览） |
| `only` | 见上 | URL 正则，命中才记 |

### 已经用它找到的东西

抓了一次商城，摸出完整接口：

```
GET  /x/garb/vas/search                      名字搜索
POST /x/garb/vas/search/recommend            搜索页推荐流
GET  /x/garb/v2/mall/suit/detail             套装详情（按 item_id）
GET  /x/garb/v2/mall/home/recommend/list     首页推荐流（filtered_item_ids 可当游标）
GET  /x/garb/mall_v2/home                    首页（banner / 分类 / 新上架）
GET  /x/garb/mall_v2/nav                     导航
GET  /x/garb/popup                           弹窗
POST /x/garb/vas/exposure/report             曝光埋点
```

全部不需要 appkey / sign / access_key，Python 直接能调 —— 见 `tools/garb_api.py`。

还想再挖的话，把面板筛 `garb`，把商城里每个页面点一遍，看还漏了哪些。

---

## 工作原理

### 1. 运行时识别列表结构

不预设字段名。脚本拿到响应后：

- 递归找「元素 ≥3、每个元素都是对象」的数组
- 按 `长度 × 有ID字段 × 层级浅` 打分选最优
- 取所有条目的**键并集**当字段表
- 取**字段最全的那条**当克隆模板
- 自动识别 `id_fields` / `name_fields` / `cover_fields` / `count_fields` / `status_field`

所以商城改版、加字段、换命名，脚本大概率还是能跑。真跑不动就开 `debug=1` 看识别结果。

### 2. 注入时改哪些字段

| 字段 | 处理 |
|---|---|
| 主 ID | 设成 catalog 的 `garb_id`（`act_id` 跳过，那是活动号） |
| 名称 | 原名 + `（已下架）` |
| 封面 | catalog 的 `large`，没有就用 `small` |
| 状态 | **改成「在售」的值** |
| 价格 | `0` / `"已下架"` |
| 库存 | `0` |
| 角标 | `"已下架"`，颜色改灰 |
| 含 `item_id=` 的 URL | 正则替换成新 ID |
| 列表总数 | `+ 注入数` |

### 3. 为什么状态要改成「在售」

H5 商城几乎肯定在客户端按 `sale_status` 过滤。塞一条 `sale_status=0` 进去，接口返回了，页面照样不渲染 —— 白干。

所以注入时把状态改成「在售」值让它过前端过滤，同时用名称后缀、灰色角标、`已下架` 价格把它标出来。**看得见，但不会骗自己。**

---

## 参数

模块的 `argument` 可改：

| 键 | 默认 | 说明 |
|---|---|---|
| `catalog` | 本仓库 raw 地址 | 目录 JSON 的 URL |
| `suffix` | `（已下架）` | 名称后缀 |
| `force` | `1` | 是否改成在售状态 |
| `debug` | `0` | 打印识别结果到 Surge 日志 |

自己 fork 后记得把 `script-path` 和 `catalog` 都换成自己的地址。

---

## 限制

- **点进去买不了**。服务端照样校验，这是预期的。
- **只有列表页生效**。分页翻到第 2 页是新的响应，会重新注入，但每页都会追加同一批条目 —— 嫌重复就把 `catalog` 控制小一点。
- **商城改版可能失效**。结构识别是启发式的，不是硬编码。
- **不碰原生装扮接口**。`x/v2/space/garb/*` 那条线跟这个模块无关。

---

## 相关

- 装扮商城是 H5，`BBPhoneGarbWebViewController` 只是个 WKWebView 壳，商城地址由服务端下发（`garbMallJumpUrl`），客户端没有开关
- 下架过滤发生在服务端，所以只能从响应侧改
- 原生装扮详情接口 `x/v2/space/garb/detail` 的入参只有 `vmid` / `garb_id` / `image_id`，**没有状态位** —— 这是 `tools/` 能取到素材的原因

---

## 免责

仅供个人学习与客户端行为研究。数据来自你自己的账号，改动只发生在你本地。
