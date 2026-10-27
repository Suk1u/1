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

## 文件

```
Surge/bili-garb-mall.sgmodule   模块本体（装这个）
Surge/garb_mall_inject.js       注入脚本，运行时自识别列表结构
Surge/bili-capture.sgmodule     抓包模块（可选）
Surge/capture_record.js         抓包记录
Surge/capture_view.js           抓包面板
Surge/catalog.json              下架装扮库
mall.html                       本地索引浏览器，带中文名搜索框
tools/catalog.py                采集 / 校验 / 快照 / 建库 / 滚雪球
tools/search.py                 本地索引搜索（备选）
tools/garb_api.py               商城接口客户端（搜索 / 详情 / 遍历 / 枚举）
tools/bili.py                   签名 + 接口封装
data/catalog_db.json            名字索引数据库（harvest 产出）
```

---

## 安装

1. Surge → 首页 → 模块 → 安装新模块，填：

```
https://raw.githubusercontent.com/Suk1u/1/main/Surge/bili-garb-mall.sgmodule
```

2. 打开 MITM 并信任证书（`api.bilibili.com` / `app.bilibili.com`）
3. 重启哔哩哔哩，进装扮商城

装上但没效果是正常的 —— **`catalog.json` 现在是空的**。先按下面「建库」填数据。

---

## 建库

下架装扮不在商城列表里，但还穿在人身上。所以 ID 从用户空间捞。

```bash
cd tools

# 1. 从一个或多个用户的空间拉装扮列表
python catalog.py seed --vmids 2,3,4,5 --max-pages 3

# 2. 对每个 ID 调 detail 补齐素材
python catalog.py verify --vmid 2

# 3. 抓一次商城列表（判定哪些是「下架」需要参照）
#    用 Surge 的抓包，或 mitmproxy，把响应存进 capture/ 目录
#    然后：
python catalog.py build
```

`build` 会直接写 `Surge/catalog.json`（在仓库里跑的时候）。提交推送后模块下次刷新就生效，缓存 6 小时。

想写到别处用 `--out <path>`。

**为什么要抓一次商城**：`detail` 只能证明「这个 ID 有效」，证明不了「它下架了」。必须拿商城在售集合做差集，差集里的才是下架。

---

## 按中文名反查 ID

**有服务端搜索。** 之前从二进制里没找到，是因为它不在 IPA 里 —— 抓包之后确认了三个接口，**全部匿名可调，不需要 appkey / sign / access_key**：

| 接口 | 作用 |
|---|---|
| `GET /x/garb/vas/search?key_word=&pn=&ps=&web_location=333.40212` | 按名字搜 |
| `GET /x/garb/v2/mall/suit/detail?item_id=&web_location=333.40212` | 按 id 取套装全貌 |
| `GET /x/garb/v2/mall/home/recommend/list?filtered_item_ids=&...` | 遍历在售目录 |

### 搜索

```bash
python tools/garb_api.py search 欧皇
```

```
关键词 '欧皇'  total=5  返回 1 条
⚠ total 比返回多 4 条 —— 被服务端过滤掉了（多半是下架或非套装）

item_id      名称                         type     价格
------------------------------------------------------------------------
120730201    欧皇萨卡班甲鱼                    1        3900  已售389份
```

**`total` 是过滤前的命中数，`list` 是过滤后的。** 两者不相等，就说明有东西被藏起来了。这是判断「某关键词下有没有下架装扮」最快的信号。

搜索只返回 `goods_type` 1（装扮套装）和 4（收藏集）。

### 详情

```bash
python tools/garb_api.py detail 120730201
```

拿到 `state`、`properties`（含 `sale_time_begin` / `is_hide` / `sale_quantity` / `owner_uid` / `fan_mid`）、以及 `suit_items`：

```
suit_items:
   card           2 件  1690250352002 (欧皇甲鱼粉丝)
   card_bg        1 件  1690250375001 (欧皇甲鱼)
   emoji_package  1 件  1690194013001 (欧皇甲鱼)
   skin           1 件  1690250690001 (欧皇甲鱼)
   space_bg       1 件  1690250416001 (欧皇甲鱼)
```

**只要知道 item_id，下架的也能取到完整数据。** 详情接口不查上架状态。

### 遍历在售目录

`filtered_item_ids` 是个游标 —— 把见过的 id 传进去，返回新的 20 条：

```bash
python tools/garb_api.py walk --rounds 50
```

实测 3 轮拿到 59 个不重复 id。跑够轮数就能把在售目录走一遍，存到 `data/mall_ids.json`。这是算「下架集合」的基准。

### 枚举 id 空间

id 是数字且分块密集（41000–41080 这段 81 个 id 里 70 个有效）：

```bash
python tools/garb_api.py hunt --start 41000 --end 41200
```

命中率大概七成。适合补 5 位数那段老装扮。

### 速率限制（重要）

B站 WAF 对高频很敏感。我连续探测两百多次之后开始返回 **412 Precondition Failed**，之后要等几分钟到几小时才恢复。

工具默认 1.2 秒一次，遇到 412 会指数退避（90s / 180s / 270s）并换一个 buvid 重试。别调快。

### 本地索引（备选）

如果只想要「我记得那个名字」，不折腾 id 空间，还是可以走本地索引 —— 从别人身上采集：

```bash
python tools/catalog.py harvest --seed 2 --max-users 500
python tools/search.py 夏日
```

`mall.html` 顶部也有搜索框。

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
