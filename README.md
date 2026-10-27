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
tools/garb_api.py               商城接口客户端（搜索 / 详情 / 我的装扮）
tools/index_build.py            索引构建（我的装扮 / 在售目录 / id 枚举）
tools/find.py                   按中文名搜，含下架
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

## 按中文名搜下架装扮

**下架的装扮只出现在「我的装扮」里。** 商城搜不到，但已拥有列表里还在 —— 这是唯一能拿到名字和 ID 对应关系的地方。

`x/v2/space/garb/list` 一条记录同时给出：

```
garb_title    "2021拜年纪"          ← 中文名
garb_id       3864                  ← 13 位形象 ID
button.uri    ...suit/detail?id=3898 ← 9 位 item_id
images[]      立绘
fans_number   NO.021206             ← 持有编号
```

### 三步

```bash
# 1. 从「我的装扮」采集（自己的 vmid 起步，顺关注链扩）
python tools/index_build.py users --vmids <你的vmid> --expand 300

# 2. 搜
python tools/find.py 拜年

# 3. 只要下架的
python tools/find.py 拜年 --delisted
```

输出：

```
item_id      名称                         state    在售?        销量
------------------------------------------------------------------------------
3898         2021拜年纪                    -        ★下架        -
```

拿到 `item_id` 就能调 `suit/detail` 取全貌，`garb_id` 能调 `space/garb/detail` 取立绘。

### 实测

按 `data/seed_vmids.txt` 里 7 个种子采了一轮，**69 条里 63 条是下架的**：

```
呜米              5829        ★下架
美波七海           5797        ★下架
洛天依9th生日纪念    5766        ★下架
明日方舟           55655       ★下架
明日方舟·灯下定影    39220       ★下架
永雏塔菲·1883      38120       ★下架
神乐七奈           3796        ★下架
领结猫            108947802   ★下架
猫雷Nyaru         36739       ★下架
明日方舟音律联觉     5359        在售
永雏塔菲           33023       在售
```

在售判定靠 `walk-seeds` 拉的全量在售目录做差集。

### 找更多大户

种子里 `647193094`（腾讯招聘）一个人就有 50 套。想找同类账号：

```bash
python tools/index_build.py rank --from-owners --owner-sample 50
```

它会从在售装扮的 `properties.owner_uid` 反推候选（做装扮的 UP 主自己收藏最多），再按拥有套数排序。把结果补进 `data/seed_vmids.txt` 就行。

> 顺关注链扩展（`--follow`）需要登录态，`x/relation/followings` 会返回 `-101 账号未登录`。CI 里跑不了，本地有 access_key 才能用。

### 覆盖范围

索引里有多少，取决于采集了多少人的「我的装扮」。想扩就：

```bash
# 多喂几个大号 vmid（粉丝多的人通常装扮也多）
python tools/index_build.py users --vmids 2,946974,3797584 --expand 500

# 补在售目录，让「在售/下架」判定更准
python tools/index_build.py walk-seeds --rounds 50
```

`--expand` 会顺着关注链滚雪球。断了重跑会跳过已采过的用户。

### 备选：商城搜索

商城搜索接口是有的，但**只返回在售**，救不了下架：

```
GET /x/garb/vas/search?key_word=&pn=&ps=&web_location=333.40212
```

`total` 是过滤前命中数，`list` 是过滤后。试过 30 多个参数、8 个 location 变体、POST body，**没有一个能放出下架项**。

想查在售的用它更快：

```bash
python tools/garb_api.py search 欧皇
python tools/garb_api.py detail 120730201
```

### 速率

B站 WAF 对高频敏感，连打两百多次会开始返回 412，要等冷却。工具默认 1.2 秒一次 + 指数退避。

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
