---
name: mcd-memory-card
display_name: 麦门回忆卡
display_name_en: McDonald's Memory Card
description: 通过已配置的麦当劳官方 MCP 只读工具（query-my-account、order-list、query-my-coupons）读取账户积分、历史订单与优惠券，整理成一组诚实的回忆卡片。当用户要求「生成我的麦门回忆卡」「整理我的麦当劳订单记录」「看看我的积分和券」「我的麦当劳消费回顾」时使用。严禁调用任何写工具（下单、兑换、领券、抽奖）。
description_zh: 把麦当劳订单与账户记录整理成一组逐项标注数据范围的诚实卡片，全只读、不下单、不兑换。
description_en: "Turn your McDonald's order and account records into an honest set of cards, each labeled with its actual data coverage. Read-only: never places orders or redeems rewards."
category: productivity
version: 1.0.0
author: 麦门回忆卡 · 参赛团队
allowed-tools: query-my-account, order-list, query-my-coupons
disable-model-invocation: false
user-invocable: true
---

> ## ⚠️ 本文件是开发侧副本，不是安装入口
>
> - **唯一正式安装入口**：仓库根目录的 `mcd-memory-card-skill.zip`。
> - 该 ZIP 内部路径为 `mcd-memory-card/SKILL.md`，即本仓库 `skill/SKILL.md` 的副本，**它是权威版本**。
> - 本文件（仓库根 `SKILL.md`）仅供开发阅读，**不参与打包**，其路径均以**仓库根目录**为基准。
> - 两份 frontmatter 必须完全一致。运行 `python renderer/skill_pack_check.py` 可校验一致性、YAML 可解析性与包内引用有效性；不一致会报错。
>
> 避免版本混淆：**不要**把本文件当作技能导入；导入请用 ZIP。

# 麦门回忆卡（mcd-memory-card）

把麦当劳订单与账户记录，整理成一组**只陈述事实、逐卡标注数据覆盖范围**的回忆卡片。

## 何时使用

- 用户说「生成我的麦门回忆卡」「整理我的麦当劳订单」「看看我的积分和券」；
- 用户希望把自己在麦当劳的历史记录做成可视化卡片（可截图分享）。

## 何时不要使用

- 用户要求**下单、兑换、领券、抽奖、取消订单** → 本 Skill 不做，直接拒绝并说明。
- 用户要求「年度账单」「今年一共吃了几个巨无霸」「我摄入了多少热量」 → **拒绝**，见下文「硬性红线」。

## 前置条件

- WorkBuddy 已配置麦当劳 MCP 连接器（`mcd-mcp`，`https://mcp.mcd.cn`，Streamable HTTP，Bearer Token）。
- 若未配置，**不要尝试自行申请 Token**，提示用户前往 https://open.mcd.cn/mcp 自行申请并配置。

## 允许使用的工具（白名单，仅此三个）

| 工具 | 用途 |
|---|---|
| `query-my-account` | 账户积分 |
| `order-list` | 近期到店/外送历史订单 |
| `query-my-coupons` | 我的可用券 |

### ⛔ 禁止调用的写工具（绝对不允许）

`create-order`、`cancel-order`、`mall-create-order`、`party-order-create`、`auto-bind-coupons`、`draw-lottery`、`delivery-create-address`

**任何情况下都不得调用。** 用户明确要求也不行——本 Skill 的定位就是只读。

## 硬性红线（不可违反）

1. **不得假定官方字段结构。** 官方 README 未公布返回字段。必须先实际调用、观察真实返回，再决定如何解析。无法确认的字段**标为 `unknown`**，并在 `unknowns` 中记录原因，**绝不猜、绝不填 0**。
2. **不得使用「附近门店」代替历史足迹。** 门店只能来自 `order-list` 返回中确认出现的门店。禁止调用 `query-nearby-stores` 充当历史记录。
3. **取消 / 退款不计入完成订单。** `status` 归一化为 `completed` / `cancelled` / `refunded` / `unknown`；只有 `completed` 计入已完成。
4. **未知状态独立展示**，不并入完成、也不并入取消。
5. **不做年度断言。** `order-list` 的时间窗口官方未定义（仅 `mall-order-list` 写了「近一年」）。**禁止**输出「年度总消费」「今年共吃了 N 个」。覆盖范围必须标为实际可确认的区间。
6. **不把订单折算成个人摄入。** 订单 ≠ 食用。**禁止**输出「你摄入了多少热量」。
7. **不做金额炫耀、排行、消费鄙视。** 金额字段仅用于内部核对，不渲染到卡片上。
8. **每张卡都必须保留覆盖范围说明。**

## 执行流程

### 第 1 步：取数

依次调用三个白名单工具。**逐个记录调用结果**：

- 成功 → 加入 `source.tools`；
- 失败 → 记入 `source.toolsFailed`，写明原因（`401` / `429` / 空返回 / 解析失败）；
- `source.writeToolsInvoked` **必须恒为空数组**。

### 第 2 步：观察返回结构（关键，不可跳过）

**在写任何解析代码前**，先打印或查看每个工具的原始返回，确认：

| 待确认 | 影响 |
|---|---|
| `order-list` 实际返回的**时间跨度** | 决定覆盖范围文案 |
| 是否支持**分页**、每页多少 | 决定 `isComplete` 取 `complete`/`partial`/`unknown` |
| 是否含**门店**字段 | 决定是否生成门店卡 |
| 是否含**餐品明细** | 决定是否生成餐品卡（本项目默认不做） |
| 是否含**订单状态**字段 | 决定 `statusRaw` 取值 |
| **时间字段格式与时区** | 决定时间能否正确解析 |
| `query-my-account` 的**积分字段名** | 决定积分能否展示 |

**任何一项无法确认，就在 `unknowns` 中登记，并按第 4 步降级。**
**不要**把「大概应该是这样」写进解析逻辑。

### 第 3 步：归一化

把取到的数据转换为本项目 schema：`schema/normalized.schema.json`（包内路径为 `references/normalized.schema.json`）。

要点：

- `coverage.coverageNote` 是**面向用户的原文**，必须写成一句人话，例如：
  「数据覆盖：2026-09-11 至 2026-10-10 · 仅取回 6 条记录（分页能力未确认，可能仍存在更早记录）」；
- `coverage.isComplete`：确认取全 = `complete`，分页受限 = `partial`，无法判断 = `unknown`；
- 订单 `status` 做归一化映射，**同时保留 `statusRaw` 原文**；
- `isCompleted` 仅当 `status === "completed"` 时为 `true`；
- 订单 `id` **必须脱敏**（如 `ORD-***-001`），不得写入完整真实订单号；
- 门店数组的 `source` 字段固定为 `"order-list"`。

### 第 4 步：数据不足时降级

| 情形 | 降级动作 |
|---|---|
| `order-list` 返回空 / 报错 | 不生成订单、门店、餐品卡；仅保留积分与覆盖说明 |
| 记录数 < 5 | 保留卡片但**不计算「节奏」类指标** |
| 时间字段不可解析 | 只做计数，不展示时间 |
| 分页受限 | 覆盖说明**必须**标注「部分数据」，禁用「全量/完整/这一年」字样 |
| 账户字段名无法确认 | 积分数值显示为 `未知`，**不得填 0** |
| 任何不确定 | 隐藏该卡，或明写「数据不可得」 |

### 第 5 步：渲染

两种方式任选：

**方式 A（推荐）：导出 JSON 交给渲染器**

生成归一化 JSON 后，让用户打开 `index.html` 并点「导入 JSON」；
或本地跑 `python renderer/render.py <归一化JSON> -o out.html` 生成静态卡片页。

**方式 B：直接按卡片结构输出文本**

若无渲染环境，按卡片顺序输出纯文本：当前积分 → 券摘要 → 订单概览 → 订单记录 → 状态未知记录 → 门店记录 → 数据覆盖说明 → 未知项清单。
**每张卡末尾都必须附覆盖范围。**

### 第 6 步：回落

如果 `order-list` 完全失败，**仍然交付**：只展示积分与券，并明确写出「订单记录本次未能获取（原因：<错误码>），因此不生成消费/餐品相关内容——我们不猜测你的历史。」

## 输出卡片清单

| # | 卡片 | 数据来源 | 备注 |
|---|---|---|---|
| 1 | 当前积分 | `query-my-account` | 未知显示「未知」 |
| 2 | 券摘要 | `query-my-coupons` | 只统计数量/类别，不列券码 |
| 3 | 订单概览 | `order-list` | 已完成/取消/退款/未知分列 |
| 4 | 订单记录（已明确状态） | `order-list` | 未知状态不进本卡 |
| 5 | 状态未知的记录 | `order-list` | 独立成段 |
| 6 | 门店记录 | `order-list` | **严禁用附近门店** |
| 7 | 数据覆盖说明 | 全部 | 必出 |
| 8 | 未知项清单 | 全部 | 有未知项时必出 |

## 安全要求

- **不输出、不写入、不记录任何 Token 或密钥。** 若在返回数据中发现疑似 Token，**丢弃并提示用户**。
- 归一化 JSON 中不得包含真实订单号、手机号、地址、真实姓名；门店名可保留，订单号须脱敏。
- **不联网上传**任何用户数据。所有处理在本机完成。
- 配置文件只允许**环境变量占位符**，不得写死真实 Token。

## 参考文件

| 仓库根路径（本文件视角） | 打包后路径（ZIP 内） | 说明 |
|---|---|---|
| `schema/normalized.schema.json` | `references/normalized.schema.json` | 归一化数据模型定义 |
| `samples/fictional-*.json` | `templates/fictional-*.json` | 三种纯虚构样例（完整 / 部分 / 空） |
| `renderer/render.py` | `scripts/render.py` | 本地静态渲染脚本（不联网） |
| `index.html` | `scripts/index.html` | 单文件可视渲染器（含演示模式、导入、打印） |
