# MCP_INTEGRATION.md —— 麦当劳 MCP 接入说明

本文件说明「麦门回忆卡」实际使用了哪些麦当劳 MCP Server 与 Tool、调用流程是什么、以及业务价值在哪里。

---

## 1. 使用的 MCP Server

| 项目 | 值 |
|---|---|
| Server 名称 | `mcd-mcp`（麦当劳中国官方 MCP 服务） |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP |
| 认证方式 | 请求头 `Authorization: Bearer <MCP_TOKEN>` |
| 服务地域 | 中国大陆（不含港澳台） |
| 限流 | 每 Token 每分钟最多 600 次请求，超出返回 429 |
| 开放平台 | https://open.mcd.cn/mcp |
| 官方文档 | https://github.com/M-China/mcd-mcp-server |

---

## 2. 实际使用的 Tool（仅 3 个，全部只读）

| Tool | 用途 | 在本项目中的角色 |
|---|---|---|
| `query-my-account` | 查询账户积分（可用/累计/冻结/即将过期） | 生成「当前积分」卡 |
| `order-list` | 查询近期的到店/外送历史订单 | 生成「订单概览」「订单记录」「状态未知记录」「门店记录」「数据覆盖说明」卡。**入参无任何参数** |
| `query-my-coupons` | 查询用户可用的优惠券列表 | 生成「券摘要」卡。**返回 Markdown 文本（非 JSON）**，分页参数 `page`/`pageSize` 实测生效 |

### 2.1 未使用的相关 Tool（说明原因）

| Tool | 未使用原因 |
|---|---|
| `query-nearby-stores` | **明确不用于「门店足迹」**。附近门店 ≠ 去过，用它充当历史足迹是不诚实的 |
| `mall-order-list` | 商城订单与餐饮订单口径不同，本次范围外 |
| `list-nutrition-foods` | 本作品**不做营养/热量结论**（订单 ≠ 摄入） |
| `query-meal-detail` | 餐品明细在 `order-list` 返回中是否可取得**尚未验证**，故不作为 MVP 依赖 |
| `calculate-price` | 价格试算属于点餐场景，与「回顾」定位无关 |

### 2.2 ⛔ 绝对不调用的写操作 Tool

以下 7 个工具在本项目中**永不调用**，代码层已做拦截（`source.writeToolsInvoked` 必须为空，否则渲染器拒绝渲染）：

`create-order`、`cancel-order`、`mall-create-order`、`party-order-create`、
`auto-bind-coupons`、`draw-lottery`、`delivery-create-address`

**理由**：本作品定位为只读回顾工具。下单、兑换、领券、抽奖都会对用户账户产生真实副作用（扣款、扣积分、领券不可撤销），与「诚实回顾」的产品定位冲突，也不符合参赛作品的审慎原则。

---

## 3. 调用流程

```
用户请求「生成我的麦门回忆卡」
        │
        ▼
[1] 取数（只读，三个调用）
     ├─ query-my-account   → 账户积分
     ├─ order-list         → 订单记录
     └─ query-my-coupons   → 优惠券列表
     记录每个调用的成功/失败状态
        │
        ▼
[2] 结构观察（关键步骤）
     打印/查看原始返回，确认：
       时间跨度 / 是否分页 / 是否含门店 / 是否含餐品明细 /
       是否含状态字段 / 时间格式与时区 / 积分字段名
     ⚠️ 任何无法确认的项 → 登记到 unknowns
        │
        ▼
[3] 归一化
     转换为 schema/normalized.schema.json（包内 references/normalized.schema.json）定义的结构
     订单号脱敏 · 状态映射并保留 statusRaw · isCompleted 仅对 completed 为 true
        │
        ▼
[4] 降级判定
     数据为空 / 记录过少 / 时间不可解析 / 分页受限 → 按规则隐藏或标注
        │
        ▼
[5] 渲染
     方式 A：交给 index.html 导入，或 renderer/render.py 生成静态页
     方式 B：按卡片顺序直接输出文本
        │
        ▼
[6] 覆盖范围复核
     每张卡都带覆盖说明；禁用「全量/完整/这一年/年度」字样
```

---

## 4. 业务价值

### 4.1 对用户

- **一次调用看清状态**：积分、券、近期订单，不用在 App 里翻多个页面；
- **可信**：明确告诉你数据覆盖到哪、哪些不确定，不会用漂亮的假数字骗你；
- **零风险**：全只读，不会产生任何扣款或积分变动。

### 4.2 对 MCP 生态

- 演示了官方 MCP 在**"回顾/汇总"类场景**（而非"点单"类场景）的用法；
- 只用了 3 个工具，证明低耦合接入也能做出完整产品；
- 全部只读，不触碰任何写操作，是**最低风险的 MCP 集成范式**。

---

## 5. ✅ 真实接入验证结果（2026-10-10 实测）

**已在本机通过 WorkBuddy 已配置的 `mcd-mcp` 连接器完成真实只读调用。**
三个白名单工具全部调用成功，**未调用任何写工具**。

> 本节只记录**字段名、调用是否成功、分页与状态规则**等脱敏信息。
> **不记录任何个人数值、门店名、账户标识、券码或图片链接。**

### 5.1 调用结果汇总

| Tool | 调用结果 | 返回形态 | 备注 |
|---|---|---|---|
| `query-my-account` | 成功（`code=200`） | JSON | 字段已实测确认 |
| `order-list` | 成功（`code=200`） | JSON，`data` 为**空对象** | 调用成功但未返回订单记录 |
| `query-my-coupons` | 成功 | **Markdown 文本**（非 JSON） | 分页参数实测生效 |

**重要**：`order-list` 的空返回是 `{}` 而非 `[]`——**连 `list` 键都不存在**。
解析层必须同时处理「`list` 键缺失」与「`list` 为空数组」两种情形，否则会误报解析失败。

### 5.2 实测确认的字段映射

| 归一化字段 | 官方原始字段 | 实测类型 | 说明 |
|---|---|---|---|
| `account.available` | `data.availablePoint` | string | **字符串型数值**，需转换，不是 JSON number |
| `account.accumulated` | `data.accumulativePoint` | string | 同上 |
| `account.frozen` | `data.frozenPoint` | string | 同上 |
| `account.expiringSoon` | `data.currentMouthExpirePoint` | string | 官方字段名拼写为 `Mouth`（非 `Month`），**照抄保留不改写** |
| 币种 | `data.currency` | string | 值为「麦享会积分」 |
| 账户标识 | `data.accountId` | string | **敏感**，仅保留在私有目录，不入公开材料/样例/ZIP |

`order-list` 服务端声明的响应结构（**本次无样本，属声明而非实测**）：

```
data.list[].orderId          订单编码（敏感，须脱敏）
data.list[].orderType        订单类型
data.list[].createTime       下单时间
data.list[].beType           门店类型
data.list[].beCode           BE 编码
data.list[].storeCode        门店编码
data.list[].storeName        门店名称
data.list[].orderStatus      订单状态
data.list[].orderProductList[].productCode / productName / quantity / comboItemList[]
data.list[].realTotalAmount  总金额（不渲染）
```

### 5.3 分页与时间窗口（实测结论）

| 项目 | 结论 |
|---|---|
| `order-list` 入参 | **无任何参数**（schema 为 `additionalProperties: false` 且未声明属性）→ 无法通过参数控制分页 |
| `order-list` 时间窗口 | **仍未确认**（本次无数据，无时间跨度可观察） |
| `order-list` 分页 | **仍未确认**（无数据可验证，工具亦未暴露分页参数） |
| `query-my-coupons` 入参 | `page`（string，默认 1，**最多 5 页**）、`pageSize`（string，默认 200，**最大 200**） |
| `query-my-coupons` 分页 | **实测生效**：`pageSize=1&page=2` 正确返回第 2 页，抬头同步变为 `第 2/2 页` |
| 券返回格式 | **Markdown 文本**，抬头 `共 N 张可用优惠券 | 第 X/Y 页 | 每页 Z 条`；无 JSON 结构可供 `JSON.parse` |

### 5.4 仍未确认项（如实记录，已登记进 `unknowns`）

| # | 未确认项 | 原因 |
|---|---|---|
| Q1 | `order-list` 时间窗口 | 本次无订单返回，无跨度可观察；工具入参为空无法探测 |
| Q2 | `order-list` 分页能力 | 工具无分页参数，且无数据可验证 |
| Q3 | `orderStatus` 取值枚举 | 无样本，不知 `completed` / `cancelled` / `refunded` 对应的原始字面值 |
| Q4 | `createTime` 格式与时区 | 无样本 |
| Q5 | 券的唯一标识字段 | 官方以 Markdown 渲染返回，未暴露券 ID |
| Q6 | 券在超大数据量下的分页边界行为 | 本账号券数未触及 5 页 / 200 条上限 |

**处理原则**：以上未确认项一律登记到归一化数据的 `unknowns` 中，
**不猜测、不填 0、不把「大概是这样」写死进解析逻辑**。

---

## 6. 安全与合规

| 项目 | 做法 |
|---|---|
| Token 存储 | 仅存于用户本机 MCP 连接器配置；项目文件**只允许环境变量占位符** |
| Token 上传 | **不进行任何上传**；渲染器不联网 |
| 订单号 | 归一化时**必须脱敏**（如 `ORD-***-001`） |
| 个人信息 | 不记录手机号、地址、真实姓名 |
| 写操作 | 全部禁止，代码层拦截 |
| 数据出境 | 不涉及，所有处理在本机完成 |

---

## 7. 免责

本作品为麦当劳程序员创意开发大赛参赛作品，由参赛者独立开发，**非麦当劳官方产品**。
项目输出仅供参考，不构成医疗、营养或其他专业建议；餐品信息、价格及供应状态以麦当劳官方渠道的实时结果为准。
