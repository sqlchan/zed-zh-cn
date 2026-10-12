# -*- coding: utf-8 -*-
"""扫描 Zed 源码里的静态 UI 文案，与现有词典比对，报出未收录项。

用法:
    python -I scan_ui_strings.py                    # 用默认路径
    python -I scan_ui_strings.py --root <crates目录> --dict <i18n_dict.tsv>

往词典里加词之前，先用这个脚本看看漏了什么。它只做模式匹配，不做类型分析，
所以候选里混有测试夹具、HTTP 头、示例代码之类的非 UI 字符串，需要人工过目。
脚本会把「来自测试文件」的候选单独标出来，方便先筛掉一大半噪音。
"""
import argparse
import io
import os
import re
import sys

# UI 文案的入口：这些 API 只接受字符串字面量作为要显示的文本
PATTERNS = [
    r'\bLabel::new\(\s*"((?:[^"\\]|\\.)*)"',
    r'\bHighlightedLabel::new\(\s*"((?:[^"\\]|\\.)*)"',
    r'\bButton::new\(\s*"((?:[^"\\]|\\.)*)"',
    r'\bMenuItem::new\(\s*"((?:[^"\\]|\\.)*)"',
    r'\bContextMenuEntry::new\(\s*"((?:[^"\\]|\\.)*)"',
    r'\bSectionHeader::new\(\s*"((?:[^"\\]|\\.)*)"',
    r'\.action\(\s*"((?:[^"\\]|\\.)*)"',
    r'\.entry\(\s*"((?:[^"\\]|\\.)*)"',
    r'\.tooltip\(\s*"((?:[^"\\]|\\.)*)"',
    r'\.placeholder\(\s*"((?:[^"\\]|\\.)*)"',
    r'\.label\(\s*"((?:[^"\\]|\\.)*)"',
    # 结构体里的 UI 文案字段，如 `title: "New File"`
    r'\b(?:title|label|name|header|text|description)\s*:\s*"((?:[^"\\]|\\.)*)"',
    r'\.(?:header|title|text)\(\s*"((?:[^"\\]|\\.)*)"',
]

# 明确不是 UI 文案的整串黑名单
NOT_UI = {
    "Content-Type", "Content-Length", "Authorization", "User-Agent", "Accept",
    "application/json", "text/plain", "text/html", "GET", "POST", "PUT", "DELETE",
}

# 出现在这些路径里的候选，几乎都是测试夹具
TEST_PATH = re.compile(r"(_tests?\.rs|/tests?/|test_context|fixtures?/|/examples/)")

SKIP_DIRS = {"target", ".git", "tests", "test_data", "fixtures", "examples"}


def looks_like_ui(s: str) -> bool:
    """启发式判断一个字符串字面量是否可能是 UI 文案。"""
    if not s or len(s) > 90 or s in NOT_UI:
        return False
    if s.startswith("http") or "://" in s:
        return False
    # 路径 / 文件名 / 扩展名
    if re.match(r"^[\w./\\-]+\.(rs|toml|json|md|ts|js|py|exe|dll|lib|pdb|zip|log|lock|wasm)$", s):
        return False
    if s.startswith(("crates/", "src/", "./", "../", "/", "e2e/", "assets/", "LICENSE")):
        return False
    # 单个标识符 / snake_case / kebab-case / 域样式 key
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", s):
        return False
    if re.match(r"^[a-z0-9]+([_-][a-z0-9]+)+$", s):
        return False
    if re.match(r"^[\w-]+(\.[\w-]+)+$", s):
        return False
    # 纯小写单词（"open"、"file"）：歧义太大，误译风险高，排除
    if s.islower() and " " not in s:
        return False
    if "\\n" in s or "\\t" in s:
        return False
    if not re.search(r"[A-Za-z]", s):
        return False
    return True


def load_dict(path: str) -> set:
    """读词典的全部英文键。"""
    keys = set()
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#") or "\t" not in line:
                continue
            keys.add(line.split("\t", 1)[0])
    return keys


def build_known_set(dict_path: str) -> set:
    """在词典键的基础上，补上「大写回退」能命中的形式。

    `translate()` 未命中时会拿 `to_ascii_uppercase()` 后的串再查一次
    （`upper_dict()`），对应那种先把文案转大写再渲染的按钮。所以词典里
    有 "Open" 就等于 "OPEN" 也已收录，不该再报成缺失。
    注意方向：回退表以「词典键的大写」为键，所以只对全大写候选有效。
    """
    known = load_dict(dict_path)
    upper = {k.upper() for k in known if any(c.islower() for c in k)}
    return known | upper


def scan(root: str):
    hits = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(".rs"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                src = io.open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            rel = os.path.relpath(path, root)
            for pat in PATTERNS:
                for m in re.finditer(pat, src):
                    raw = m.group(1)
                    if looks_like_ui(raw):
                        hits.setdefault(raw, []).append(rel)
    return hits


def main():
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(here, "crates"))
    ap.add_argument("--dict", default=os.path.join(here, "localization", "i18n_dict.tsv"))
    ap.add_argument("--out", default="ui_strings_missing.txt")
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        sys.exit("找不到源码目录: %s" % args.root)
    if not os.path.isfile(args.dict):
        sys.exit("找不到词典: %s" % args.dict)

    known = build_known_set(args.dict)
    hits = scan(args.root)

    missing = []
    for text, paths in hits.items():
        if text in known:
            continue
        from_tests = all(TEST_PATH.search(p) for p in paths)
        missing.append((text, from_tests, sorted(set(paths))[0], len(paths)))

    missing.sort(key=lambda x: (x[1], -x[3], x[0].lower()))
    real = [m for m in missing if not m[1]]

    with io.open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("候选总数 %d，已收录 %d，未收录 %d（其中来自测试文件 %d）\n"
                % (len(hits), len(hits) - len(missing), len(missing), len(missing) - len(real)))
        f.write("\n===== 非测试文件中未收录（真正要补的）=====\n")
        for text, _, where, n in real:
            f.write("%-45s %s\n" % (text, where))
        f.write("\n===== 仅出现在测试文件里（一般是夹具，可忽略）=====\n")
        for text, _, where, n in missing:
            if _:
                f.write("%-45s %s\n" % (text, where))

    print("candidates=%d known=%d missing=%d real=%d -> %s"
          % (len(hits), len(hits) - len(missing), len(missing), len(real), args.out))


if __name__ == "__main__":
    main()
