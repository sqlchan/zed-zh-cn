# -*- coding: utf-8 -*-
"""枚举 Zed 源码里所有 action，生成命令面板的显示名清单。

用法:
    python -I scan_actions.py [--root <crates目录>] [--out cmd_list.txt]

背景：命令面板里的名字（`editor: add selection above`）在源码里**没有对应
字面量**，是 `command_palette::humanize_action_name` 由 action 的类型名推导
出来的。所以词典没法像普通 UI 文案那样靠搜字面量拿到，只能先把所有 action
枚举出来，再复刻一遍推导规则得到显示名。这个脚本就是干这个的。

覆盖两种声明形式：
    actions!(ns, [A, B]);             /  actions!([A, B]);
    #[derive(..., Action)]
    #[action(namespace = ns, name = "X")]
    pub struct A;

输出每行一个显示名，可直接喂给 build_cmd_dict.py 生成 i18n_commands.tsv。
"""
import argparse
import os
import re
import sys

SKIP_DIRS = ("target", ".git", "examples", "tests")


def humanize(name: str) -> str:
    """逐字符复刻 crates/command_palette/src/command_palette.rs:humanize_action_name

    两处都不能想当然：
      - `::` 变成 ": "（冒号后跟空格），单个 `:` 原样保留；
      - 连续大写按缩写处理（`ADDSelection` → `add selection`），但若缩写后面
        紧跟小写字母，则最后一个大写字母归属下一个单词（`HTTPServer` →
        `http server`，而非 `httpserver`）。
    """
    chars = list(name)
    result = []
    i = 0
    n = len(chars)
    while i < n:
        c = chars[i]
        if c == ":":
            if result and result[-1] == ":":
                result.append(" ")
            else:
                result.append(":")
            i += 1
        elif c == "_":
            result.append(" ")
            i += 1
        elif c.isupper():
            start = i
            i += 1
            while i < n and chars[i].isupper():
                i += 1
            run = chars[start:i]
            if len(run) > 1:
                split_before_last = i < n and chars[i].islower()
                acronym_end = len(run) - 1 if split_before_last else len(run)
                if acronym_end > 0:
                    if not (result and result[-1] == " "):
                        result.append(" ")
                    result.extend(run[:acronym_end])
                if split_before_last:
                    if not (result and result[-1] == " "):
                        result.append(" ")
                    result.extend(run[acronym_end].lower())
            else:
                if not (result and result[-1] == " "):
                    result.append(" ")
                result.extend(c.lower())
        else:
            result.append(c)
            i += 1
    return "".join(result)


ACTIONS_MACRO = re.compile(r"actions!\s*\(")

DERIVE_ACTION = re.compile(
    r"#\[derive\((?P<derive>[^)]*\bAction\b[^)]*)\)\]"
    r"(?P<attrs>(?:\s*#\[[^\]]*\])*)\s*"
    r"pub\s+struct\s+(?P<struct>\w+)",
    re.S,
)


def parse_actions_macro(scan: str):
    """括号配平地取出每个 `actions!(...)` 调用的内容。

    不能用非贪婪的 `actions!\\((.*?)\\]\\)`：文档注释里常出现
    `[\\`FocusNextPart\\`]` 这样的方括号链接，非贪婪正则会提前收尾，
    把整个 block 漏掉。宏体里不会出现字符串字面量中的括号（正文已被掩码），
    所以直接数括号即可。
    """
    calls = []
    for m in ACTIONS_MACRO.finditer(scan):
        depth = 0
        i = m.end() - 1
        while i < len(scan):
            c = scan[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    calls.append(scan[m.end():i])
                    break
            i += 1
    return calls


def split_ns_and_body(inner: str):
    """把 `ns, [ ... ]` 或 `[ ... ]` 拆成 (namespace, body)。"""
    first_bracket = inner.find("[")
    if first_bracket < 0:
        return None
    head = inner[:first_bracket]
    depth = 0
    end = -1
    for i in range(first_bracket, len(inner)):
        if inner[i] == "[":
            depth += 1
        elif inner[i] == "]":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return None
    ns = head.strip().rstrip(",").strip()
    return (ns or None), inner[first_bracket + 1:end]


def attr_value(attrs: str, key: str):
    """在多个 `#[action(...)]` 属性里找 key = value。"""
    for a in re.findall(r"#\[action\(([^)]*)\)\]", attrs):
        m = re.search(rf"\b{key}\s*=\s*(\w+|\"[^\"]*\")", a)
        if m:
            return m.group(1).strip('"')
    return None


def has_flag(attrs: str, flag: str) -> bool:
    return any(
        re.search(rf"\b{flag}\b", a) for a in re.findall(r"#\[action\(([^)]*)\)\]", attrs)
    )


def mask_literals(src: str) -> str:
    """把字符串/字符字面量与注释的内容替换成**等长空格**。

    目的不是解析 Rust，只是让随后的括号计数不被 `"("`、`// }` 这类内容带偏。
    保持偏移不变，这样算出的位置可以直接用于切片。

    这一层是必须的：早期版本直接数括号，terminal.rs 里一个
    `#[cfg(test)] mod domain_tests {\n ... "}" ... }` 因此只删到字符串里的那个
    `}` 就停手，把后面的 `actions!(terminal, [...])` 一起吞掉了。
    """
    out = list(src)
    n = len(src)
    i = 0
    while i < n:
        c = src[i]
        # 行注释
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            nl = src.find("\n", i)
            j = n if nl < 0 else nl
            for k in range(i, j):
                out[k] = " "
            i = j
        # 块注释（Rust 允许嵌套）
        elif c == "/" and i + 1 < n and src[i + 1] == "*":
            depth = 1
            j = i + 2
            while j < n and depth > 0:
                if src.startswith("/*", j):
                    depth += 1
                    j += 2
                elif src.startswith("*/", j):
                    depth -= 1
                    j += 2
                else:
                    j += 1
            for k in range(i, min(j, n)):
                out[k] = " "
            i = j
        # 字符串 / 原始字符串
        elif c == '"' or (c == "r" and src.startswith('r"', i)) or src.startswith("r#", i):
            if c == "r":
                hashes = 0
                j = i + 1
                while j < n and src[j] == "#":
                    hashes += 1
                    j += 1
                if j >= n or src[j] != '"':
                    i += 1
                    continue
                closing = '"' + "#" * hashes
                j += 1
                k = src.find(closing, j)
                k = n if k < 0 else k + len(closing)
            else:
                j = i + 1
                k = j
                while k < n:
                    if src[k] == "\\":
                        k += 2
                        continue
                    if src[k] == '"':
                        k += 1
                        break
                    k += 1
            for x in range(i, min(k, n)):
                out[x] = " "
            i = k
        # 字符字面量。生命周期 `'a` 不能当成字面量吃掉，只有 `'x'` / `'\n'` 才算
        elif c == "'" and i + 2 < n and (src[i + 1] == "\\" or src[i + 2] == "'"):
            j = i + 1
            if src[j] == "\\":
                j += 2
            else:
                j += 1
            j = src.find("'", j)
            j = n if j < 0 else j + 1
            for k in range(i, min(j, n)):
                out[k] = " "
            i = j
        else:
            i += 1
    return "".join(out)


def strip_test_modules(src: str) -> str:
    """移除 `#[cfg(test)]` 与 `#[cfg(any(test, feature = "test-support"))]` 的条目。

    这些 action 不会出现在发布版界面里（如 dock.rs 的 `test_only::ToggleTestPanel`）。

    不能简单 `src[:src.find("#[cfg(test)]")]`：workspace.rs 第 8 行就是
    `#[cfg(test)] mod multi_workspace_tests;` 这样的模块声明，一刀切会把整个
    文件砍掉（一度因此漏掉 92 条 workspace 命令）。

    每个条目的结束位置（在掩码副本上数括号）：
      - 花括号配对归零        -> mod / fn / impl 这类带体的条目
      - depth 已为 0 时的 `}` -> 枚举变体、结构体字段这种裸露条目
      - depth 已为 0 时的 `;` -> `mod x;` 这类声明
      - depth 已为 0 时的 `,` -> `#[cfg(...)] Stub,` 这类枚举变体
    """
    masked = mask_literals(src)
    out = []
    i = 0
    # 锚点在**原文**上找：掩码会把 `"test-support"` 这个字面量也抹平，
    # 正则就匹配不上 `#[cfg(any(test, feature = "test-support"))]` 了。
    needle_re = re.compile(
        r'#\[cfg\((?:test|any\(test,\s*feature\s*=\s*"test-support"\))\)\]'
    )
    while True:
        m = needle_re.search(src, i)
        if m is None:
            out.append(src[i:])
            break
        idx = m.start()
        out.append(src[i:idx])
        j = m.end()
        # 跳过后续属性、空白与行注释，找到条目本体
        while j < len(src):
            while j < len(src) and masked[j] in " \t\r\n":
                j += 1
            if masked.startswith("#[", j):
                close = masked.find("]", j)
                if close < 0:
                    break
                j = close + 1
                continue
            if src.startswith("//", j):
                nl = src.find("\n", j)
                if nl < 0:
                    break
                j = nl + 1
                continue
            break
        k = j
        depth = 0
        while k < len(src):
            c = masked[k]
            if c in "{([":
                depth += 1
            elif c in "})]":
                depth -= 1
                if depth <= 0:
                    k += 1
                    break
            elif depth == 0 and c in ";,":
                k += 1
                break
            k += 1
        i = k
    return "".join(out)


def main():
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(here, "crates"))
    ap.add_argument("--out", default="cmd_list.txt")
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        sys.exit("找不到源码目录: %s" % args.root)

    found = set()
    for dirpath, dirnames, filenames in os.walk(args.root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(".rs"):
                continue
            # 测试文件里的 action 不会出现在真实界面上
            if fn.endswith("_tests.rs") or fn.startswith("test_"):
                continue
            try:
                src = open(os.path.join(dirpath, fn), encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            scan = strip_test_modules(src)

            for inner in parse_actions_macro(scan):
                parsed = split_ns_and_body(inner)
                if parsed is None:
                    continue
                ns, body = parsed
                # 先剥掉行注释，否则文档注释里的英文单词会被当成 action 标识符
                body = "\n".join(re.sub(r"//.*$", "", line) for line in body.splitlines())
                for token in re.split(r"[,\n]", body):
                    token = token.strip()
                    if re.fullmatch(r"[A-Z]\w*", token):
                        found.add(f"{ns}::{token}" if ns else token)

            for m in DERIVE_ACTION.finditer(scan):
                attrs = m.group("attrs")
                struct = m.group("struct")
                if has_flag(attrs, "no_register"):
                    continue
                ns = attr_value(attrs, "namespace")
                name = attr_value(attrs, "name") or struct
                found.add(f"{ns}::{name}" if ns else name)

    display = sorted({humanize(a) for a in found})
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(display) + "\n")

    print("actions=%d display_names=%d -> %s" % (len(found), len(display), args.out))


if __name__ == "__main__":
    main()
