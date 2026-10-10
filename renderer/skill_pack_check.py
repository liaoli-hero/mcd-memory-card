#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
skill_pack_check.py —— 技能打包一致性校验（零第三方依赖，可选增强）

校验目标：避免「开发侧 SKILL.md」与「正式安装入口 ZIP 内的 SKILL.md」出现版本分叉
或 YAML 语法错误（历史上出现过 description_en 值内含 ASCII 冒号导致 YAML 解析失败）。

检查项：
  P1  两份 SKILL.md 均存在，且都有合法的 --- frontmatter 块
  P2  frontmatter 可被 YAML 解析（若环境有 PyYAML 则用真解析器；否则用内置严格解析器）
  P3  两份 frontmatter 解析结果完全一致（无版本分叉）
  P4  必需键齐备（name / description / version / allowed-tools）
  P5  allowed-tools 只含白名单三工具，且不含任何写工具
  P6  打包目录 skill/ 内被 SKILL.md 引用的文件真实存在
  P7  ZIP 存在、结构与 skill/ 一致、且含 mcd-memory-card/SKILL.md
  P8  YAML 值的引号规范：未加引号的纯量值里不得出现 "ASCII 冒号+空格"（本次缺陷根因）

用法：
  python renderer/skill_pack_check.py [--repo <仓库根>]

退出码：0 = 全部通过；1 = 存在失败项。
"""

import argparse
import os
import re
import sys
import zipfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

WRITE_TOOLS = [
    "create-order", "cancel-order", "mall-create-order", "party-order-create",
    "auto-bind-coupons", "draw-lottery", "delivery-create-address",
]
READ_TOOLS = ["query-my-account", "order-list", "query-my-coupons"]

# 打包后 SKILL.md 里必须存在的引用（相对于 skill/ 目录）
REQUIRED_PACKAGED_FILES = [
    "SKILL.md",
    "references/normalized.schema.json",
    "scripts/index.html",
    "scripts/render.py",
    "templates/fictional-full.json",
    "templates/fictional-partial.json",
    "templates/fictional-empty.json",
]

PAIRS = [("根 SKILL.md", "SKILL.md"), ("打包 SKILL.md", os.path.join("skill", "SKILL.md"))]

_results = []


def check(name, ok, detail=""):
    _results.append((name, bool(ok), detail))
    flag = "PASS" if ok else "FAIL"
    line = "  [%s] %s" % (flag, name)
    if detail and not ok:
        line += "  -> " + str(detail)[:220]
    elif detail:
        line += "  (" + str(detail)[:120] + ")"
    print(line)
    return bool(ok)


def split_frontmatter(text):
    """返回 frontmatter 文本；没有则返回 None。"""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    return text[3:end]


def parse_yaml_strict(fm_text):
    """
    内置的严格 frontmatter 解析器（PyYAML 不可用时的兜底）。
    只支持 "key: value" 的扁平结构，但对本缺陷（值内含 ASCII 冒号+空格）会明确报错。
    返回 (dict, errors)
    """
    data, errors = {}, []
    for lineno, raw in enumerate(fm_text.splitlines(), 1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":
            errors.append("第 %d 行：出现意外的缩进（本模型不支持嵌套）" % lineno)
            continue
        if ":" not in line:
            errors.append("第 %d 行：不是 key: value 结构" % lineno)
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not key:
            errors.append("第 %d 行：键名为空" % lineno)
            continue
        # 未加引号的值里若出现 ASCII 冒号+空格，YAML 会报 mapping values are not allowed here
        if value[:1] not in ("'", '"') and re.search(r":\s", value):
            errors.append(
                "第 %d 行：键 %s 的值未加引号却含『ASCII 冒号+空格』，YAML 将解析失败，"
                "请用双引号包裹该值" % (lineno, key)
            )
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        data[key] = value
    return data, errors


def load_frontmatter(path):
    if not os.path.isfile(path):
        return None, None, ["文件不存在：%s" % path]
    text = open(path, encoding="utf-8").read()
    fm = split_frontmatter(text)
    if fm is None:
        return None, text, ["缺少 --- frontmatter 块"]
    try:
        import yaml  # 可选依赖
    except ImportError:
        data, errs = parse_yaml_strict(fm)
        return data, text, errs
    try:
        return yaml.safe_load(fm), text, []
    except Exception as e:
        return None, text, ["PyYAML 解析失败：%s: %s" % (type(e).__name__, str(e)[:160])]


def main():
    ap = argparse.ArgumentParser(description="技能打包一致性校验")
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    help="仓库根目录，默认为本脚本上一级")
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)
    os.chdir(repo)

    print("=" * 68)
    print("麦门回忆卡 · 技能打包一致性校验")
    print("仓库根：%s" % repo)
    try:
        import yaml  # noqa: F401
        print("YAML 解析器：PyYAML（真解析器）")
    except ImportError:
        print("YAML 解析器：内置严格解析器（未安装 PyYAML）")
    print("=" * 68)

    # ---------- P1 / P2 / P3 ----------
    print("\nP1-P3 frontmatter 存在性、可解析性、一致性")
    parsed = {}
    for label, rel in PAIRS:
        data, _text, errs = load_frontmatter(rel)
        parsed[label] = data
        check("%s 存在且有 frontmatter" % label, data is not None or not errs,
              "；".join(errs))
        check("%s frontmatter 可被 YAML 解析" % label, not errs, "；".join(errs))

    vals = [parsed[l] for l, _ in PAIRS]
    if all(v is not None for v in vals):
        same = vals[0] == vals[1]
        detail = ""
        if not same:
            diff = []
            for k in sorted(set(vals[0]) | set(vals[1])):
                if vals[0].get(k) != vals[1].get(k):
                    diff.append("%s: %r != %r" % (k, vals[0].get(k), vals[1].get(k)))
            detail = "；".join(diff)
        check("两份 frontmatter 完全一致（无版本分叉）", same, detail)
    else:
        check("两份 frontmatter 完全一致（无版本分叉）", False, "存在无法解析的一方")

    # ---------- P4 必需键 ----------
    print("\nP4 必需键齐备")
    for label, _ in PAIRS:
        d = parsed.get(label) or {}
        missing = [k for k in ("name", "description", "version", "allowed-tools") if k not in d]
        check("%s 含必需键" % label, not missing, "缺少：" + ", ".join(missing))

    # ---------- P5 工具白名单 ----------
    print("\nP5 工具白名单（只读三件套，且不含写工具）")
    for label, _ in PAIRS:
        d = parsed.get(label) or {}
        at = d.get("allowed-tools", "")
        tools = [t.strip() for t in str(at).split(",") if t.strip()]
        extra = [t for t in tools if t not in READ_TOOLS]
        check("%s allowed-tools 只含只读三工具" % label, not extra, "多出：" + ", ".join(extra))
        bad = [t for t in tools if t in WRITE_TOOLS]
        check("%s allowed-tools 不含任何写工具" % label, not bad, "含写工具：" + ", ".join(bad))

    # ---------- P6 打包目录内引用有效 ----------
    print("\nP6 打包目录 skill/ 内被引用文件真实存在")
    for rel in REQUIRED_PACKAGED_FILES:
        p = os.path.join("skill", rel)
        check("skill/%s 存在" % rel, os.path.isfile(p))

    # 打包 SKILL.md 不得再出现旧的 schema/ 路径引用
    sp = os.path.join("skill", "SKILL.md")
    if os.path.isfile(sp):
        stext = open(sp, encoding="utf-8").read()
        check("打包 SKILL.md 无旧引用 'schema/normalized.schema.json'",
              "schema/normalized.schema.json" not in stext,
              "仍存在旧路径，应为 references/normalized.schema.json")
        check("打包 SKILL.md 使用 references/normalized.schema.json",
              "references/normalized.schema.json" in stext)

    # ---------- P7 ZIP 结构 ----------
    print("\nP7 ZIP 结构与 skill/ 一致")
    zip_path = "mcd-memory-card-skill.zip"
    if check("ZIP 文件存在", os.path.isfile(zip_path), zip_path):
        try:
            z = zipfile.ZipFile(zip_path)
            bad_crc = z.testzip()
            check("ZIP 完整性（testzip）", bad_crc is None, "损坏项：" + str(bad_crc))
            names = z.namelist()
            check("ZIP 含 mcd-memory-card/SKILL.md", "mcd-memory-card/SKILL.md" in names,
                  str(names)[:200])
            for rel in REQUIRED_PACKAGED_FILES:
                want = "mcd-memory-card/" + rel
                check("ZIP 含 %s" % want, want in names)
            # 包内 SKILL.md 与 skill/SKILL.md 内容一致
            inner = z.read("mcd-memory-card/SKILL.md").decode("utf-8")
            outer = open(sp, encoding="utf-8").read()
            check("ZIP 内 SKILL.md 与 skill/SKILL.md 内容一致", inner == outer,
                  "二者不一致，请重新打包")
        except zipfile.BadZipFile as e:
            check("ZIP 可打开", False, str(e))

    # ---------- P8 引号规范 ----------
    print("\nP8 YAML 引号规范（未加引号的值不得含 ASCII 冒号+空格）")
    for label, rel in PAIRS:
        if not os.path.isfile(rel):
            check("%s 引号规范" % label, False, "文件不存在")
            continue
        fm = split_frontmatter(open(rel, encoding="utf-8").read())
        if fm is None:
            check("%s 引号规范" % label, False, "无 frontmatter")
            continue
        _d, errs = parse_yaml_strict(fm)
        quote_errs = [e for e in errs if "冒号" in e]
        check("%s 引号规范" % label, not quote_errs, "；".join(quote_errs))

    # ---------- 汇总 ----------
    total = len(_results)
    failed = [n for n, ok, _ in _results if not ok]
    print("\n" + "=" * 68)
    print("通过 %d 项，失败 %d 项" % (total - len(failed), len(failed)))
    if failed:
        print("失败项：")
        for n in failed:
            print("  - " + n)
    print("=" * 68)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
