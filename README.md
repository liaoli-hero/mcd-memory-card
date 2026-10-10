# 麦门回忆卡 · mcd-memory-card

> 把你在麦当劳的订单记录，整理成一组**只陈述事实**的回忆卡片。
> 数据范围逐卡标注，不确定的一律显示为「未知」。

麦当劳程序员创意开发大赛参赛作品。基于麦当劳中国官方 MCP 的**只读**能力构建。

---

## 它解决什么问题

麦当劳的历史订单、积分、优惠券分散在 App 各处，用户很难一眼看清"我最近是什么状态"。
现有点餐助手几乎都在做同一件事：**帮你点单**。

麦门回忆卡做的是另一件事：**帮你诚实回顾**。

它的核心主张是**克制**——宁可少说一句，不说过头一句：

| 常见做法 | 本项目的做法 |
|---|---|
| "你今年吃掉了 47 个巨无霸！" | 只展示**实际取回区间内**的记录条数 |
| "你摄入了 82,000 千卡" | 不输出任何摄入量结论（订单 ≠ 摄入） |
| "你常去的门店有 5 家"（其实是附近门店） | 门店**只能来自订单记录**，附近门店不算足迹 |
| 把取消、退款的订单也算进总数 | 取消/退款**独立统计**，不计入已完成 |
| 状态识别不了就当成"已完成" | 无法确认的一律标 **「状态未知」** 并单列 |

**降级路径本身就是设计的一部分。** 数据稀缺时它诚实地缩小范围，数据完全拿不到时它依然可用且依然不说谎。

---

## 目标用户

- 想知道自己近期在麦当劳的消费/积分状态，但不想翻 App 的用户；
- 在意数据诚实性、反感"AI 一本正经胡说"的用户；
- 想生成一张可截图分享的卡片，用于社交平台记录。

---

## 安装方法

### 方式一：导入技能包（推荐）

本项目已打包为可直接导入的技能包：

```
mcd-memory-card-skill.zip
```

导入步骤（依据 WorkBuddy 官方文档）：

1. 打开 WorkBuddy，点击左侧边栏【专家·技能·连接器】→ 选择【技能】，进入技能市场；
2. 点击市场右上角【添加技能】；
3. 选择【上传技能】，把 `mcd-memory-card-skill.zip` 拖入或点击【选择文件】选中；
4. 导入后系统会自动完成配置，无需额外操作。

安装后可在对话中调用。必要时可在【已安装】列表中随时关闭或重新启用，**无需卸载**。

参考文档：
- 技能市场与安装：https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market
- 技能结构与 frontmatter 规范：https://open.workbuddy.cn/docs/skill

> ⚠️ 本仓库仅**提供**技能包，**不代为安装或上传**。是否安装请自行决定，安装第三方技能前建议先核对权限与脚本内容。

### 技能包内部结构

ZIP 顶层目录为技能名，`SKILL.md` 位于其根部：

```
mcd-memory-card/
├── SKILL.md                      # 技能定义（YAML frontmatter + 指令正文）
├── references/
│   └── normalized.schema.json    # 数据格式定义
├── scripts/
│   ├── index.html                # 单文件网页渲染器
│   └── render.py                 # 本地静态渲染脚本
└── templates/
    ├── fictional-full.json       # 样例：数据完整（纯虚构）
    ├── fictional-partial.json    # 样例：数据部分（纯虚构）
    └── fictional-empty.json      # 样例：数据为空（纯虚构）
```

### 方式二：直接使用渲染器（不需要 MCP）

本项目的 `index.html` 是一个**零依赖单文件**，可脱离技能独立演示：

- 双击 `index.html` 即可在浏览器打开；
- 内置三种**纯虚构示例数据**（完整 / 部分 / 空）；
- 可导入任意符合 `schema/normalized.schema.json` 的 JSON。

此外，`renderer/render.py` 可把归一化 JSON 生成**静态卡片页**。版式上做了区分：
普通页面只突出**积分、券和订单数据可用性提示**；
**字段名、MCP 工具名、数据覆盖表格与未知项清单**等工程说明，折叠在页面底部的
「查看数据说明」中，需要时再展开。没有订单数据时，订单/状态/门店三张空卡会合并为一条简洁提示，
但每张卡仍保留数据范围说明；**未知项一律显示为「未知」，不以 0 代替**。

### 前置条件（仅真实取数时需要）

- WorkBuddy 已配置麦当劳 MCP 连接器（详见 `MCP_INTEGRATION.md`）；
- 需要用户自行到 https://open.mcd.cn/mcp 申请 MCP Token；
- 本项目已在本机完成一次真实只读接入验证，结论见 `MCP_INTEGRATION.md` 第 5 节。

---

## 使用示例

### 示例 1：在 WorkBuddy 里生成回忆卡

```
用户：帮我生成我的麦门回忆卡
Skill：依次调用 query-my-account、order-list、query-my-coupons（只读），
       观察真实返回结构 → 归一化 → 输出卡片
```

### 示例 2：本地查看演示

打开 `index.html` → 点击「示例数据 · 完整 / 部分 / 空」查看三种场景。

### 示例 3：本地渲染静态卡片页

```bash
python renderer/render.py samples/fictional-full.json -o out.html
```

### 示例 4：导入自己归一化后的数据

```bash
# 先在 WorkBuddy 内归一化得到 my-card.json
python renderer/render.py my-card.json -o my-card.html
```

---

## 项目结构

```
mcd-memory-card/                       ← 仓库根目录
├── mcd-memory-card-skill.zip          # 可直接导入 WorkBuddy 的技能包
├── skill/                             # 技能包源目录（ZIP 的内容来源）
│   ├── SKILL.md
│   ├── references/normalized.schema.json
│   ├── scripts/index.html
│   ├── scripts/render.py
│   └── templates/fictional-*.json
├── index.html                         # 零依赖单文件渲染器（演示/导入/打印）
├── renderer/
│   ├── render.py                      # 本地静态卡片渲染脚本（仅标准库）
│   ├── selftest.py                    # Python 侧自测（97 项）
│   ├── browser_check.py               # 浏览器侧自测（CDP，需本机 Edge）
│   └── skill_pack_check.py            # 技能打包一致性校验（33 项，零依赖）
├── schema/
│   └── normalized.schema.json         # 数据格式定义（本项目自定义）
├── samples/
│   ├── fictional-full.json            # 样例：数据完整（纯虚构）
│   ├── fictional-partial.json         # 样例：数据部分（纯虚构）
│   └── fictional-empty.json           # 样例：数据为空（纯虚构）
├── docs/
│   └── 麦当劳开发大赛_第一阶段调研报告.md
├── MCP_INTEGRATION.md                 # MCP 接入说明
├── mcp-config.example.json            # 脱敏配置示例（仅环境变量占位符）
├── CONTEST_DECLARATION.md             # 参赛声明（官方原版，未修改）
├── workbuddy.md                       # WorkBuddy 开发对话记录
└── README.md                          # 本文件
```

---

## 数据口径声明

本项目在数据表述上遵守以下约束，**这些约束在代码中同样被强制执行**：

1. **订单数 ≠ 食用数。** 订单可能被取消、退款，也可能是代下单或分享。本项目只统计状态为「已完成」的记录。
2. **订单 ≠ 摄入。** 本项目**不输出任何热量或营养结论**。
3. **消费记录 ≠ 完整历史。** 官方未定义订单查询的时间窗口，因此所有卡片都随附实际覆盖范围。
4. **附近门店 ≠ 历史足迹。** 门店只能来自订单记录。
5. **未知就是未知。** 无法确认的字段显示为「未知」，绝不填 0、绝不当成已知。

---

## 真实接入状态

**已完成真实只读接入验证（2026-10-10）。** 通过 WorkBuddy 已配置的 `mcd-mcp` 连接器实际调用三个白名单工具：

| Tool | 结果 | 返回形态 |
|---|---|---|
| `query-my-account` | 成功 | JSON，字段已实测确认 |
| `order-list` | 成功 | JSON，`data` 为空对象（无订单记录） |
| `query-my-coupons` | 成功 | Markdown 文本（非 JSON），分页实测生效 |

**未调用任何写工具。** 字段映射、分页结论与仍未确认项详见 `MCP_INTEGRATION.md` 第 5 节。

---

## 已知限制

- **订单样本仍为零。** 本次 `order-list` 调用成功但未返回任何订单记录，因此 `orderStatus` 的取值枚举、`createTime` 的格式与时区、乃至**时间窗口长度**仍属**未确认**。这些项已如实登记进归一化数据的 `unknowns`，**不做猜测**。
- **`order-list` 的实际时间窗口未知。** 官方 README 仅描述为「近期」，未给出天数；该工具入参为空，无法通过参数探测。作品覆盖范围会自动适配实际返回。
- **`order-list` 分页能力未知。** 工具未暴露任何分页参数，且无数据可验证；因此无法确认时，覆盖说明标注为「部分数据」或「无法判断」，**不得写成全量**。
- **本项目不做写操作。** 不提供下单、兑换、领券、抽奖等任何功能，代码层已拦截。
- **公开材料不含任何个人数据。** 真实数值、门店名、账户标识仅存在于本机私有目录，不进入本仓库、样例、ZIP 或开发记录。

---

## 作者与开源许可

项目地址：https://github.com/liaoli-hero/mcd-memory-card

作者：[@liaoli-hero](https://github.com/liaoli-hero)。开发过程中使用 WorkBuddy 与 Codex 辅助，分工及记录见 [workbuddy.md](workbuddy.md)。

源码采用 [MIT License](LICENSE)。麦当劳商标、品牌名称及第三方素材的权利归其权利人所有。

## 参与贡献

本项目为参赛作品，欢迎通过 Issue 反馈问题（**请勿提交任何真实账户数据、Token 或订单号**）。

---

## 声明

本作品为麦当劳程序员创意开发大赛参赛作品，由参赛者独立开发，**非麦当劳官方产品**。
项目输出仅供参考，不构成医疗、营养或其他专业建议；餐品信息、价格及供应状态以麦当劳官方渠道的实时结果为准。

© 2026 参赛者。本项目不构成对麦当劳及其关联方商标的任何授权。
