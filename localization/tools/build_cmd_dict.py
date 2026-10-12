# -*- coding: utf-8 -*-
"""把 scan_actions.py 的扫描结果与现有命令词典对账，产出更新后的词典。

用法:
    python -I scan_actions.py --out cmd_list.txt
    python -I build_cmd_dict.py --cmd-list cmd_list.txt \
        --existing ../../localization/i18n_commands.tsv \
        --pending new_rows.tsv --out ../../localization/i18n_commands.tsv

上游更新后重新汉化的流程：
  1. `git pull` 并重新编译（编译本身不需要词典最新，但界面上新功能会显示英文）；
  2. 跑 scan_actions.py 得到最新的 action 显示名清单；
  3. 跑本脚本，它会报出「新增的、词典里还没有的」显示名，写进 pending 文件；
  4. 手工把那份待译清单翻译成中文，另存成 `英文<TAB>中文` 的 TSV，用
     `--pending` 传进来，再跑一次本脚本；
  5. 重新编译，新命令就是中文了。

脚本**不会**丢弃已有译文：词典里已存在、且扫描结果里仍出现的条目原样保留。
已被上游删除的条目会被剔除，并单独报告——这些是上游改动导致失效的词条。
"""
import argparse
import io
import os
import sys


def read_tsv(path):
    """读 `英文<TAB>中文` 词典，返回 {英文: 中文}。"""
    table = {}
    if not path or not os.path.isfile(path):
        return table
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#") or "\t" not in line:
                continue
            en, zh = line.split("\t", 1)
            en, zh = en.strip(), zh.strip()
            if en and zh:
                table[en] = zh
    return table


def read_list(path):
    with io.open(path, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip()]


HEADER = (
    "# 命令面板专用词典：英文显示名<TAB>中文显示名\n"
    "#\n"
    "# 这些名字由 action 的类型名自动推导（见 command_palette::humanize_action_name），\n"
    "# 形如 `editor: add selection above`，无法在源码里逐条找到字面量。\n"
    "#\n"
    "# **刻意与 i18n_dict.tsv 分开**：命令名由单个小写单词组成（`editor`、`copy`、\n"
    "# `cancel`），若混进通用词典，项目面板里同名文件和文件夹会被一起译成中文。\n"
    "# 本文件只由 i18n::translate_command_name 查询，那里拿到的必定是 action 名。\n"
    "#\n"
    "# 由 localization/tools/build_cmd_dict.py 生成，不要手工编辑。\n"
)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(here))

    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd-list", default="cmd_list.txt",
                    help="scan_actions.py 产出的显示名清单")
    ap.add_argument("--existing", default=os.path.join(repo, "localization/i18n_commands.tsv"),
                    help="现有命令词典（作为已有译文来源）")
    ap.add_argument("--pending", help="本次新译的词条（英文<TAB>中文），可省略")
    ap.add_argument("--out", default=os.path.join(repo, "localization/i18n_commands.tsv"))
    ap.add_argument("--missing-out", default="cmd_missing.txt",
                    help="待译清单写出位置")
    args = ap.parse_args()

    if not os.path.isfile(args.cmd_list):
        sys.exit("找不到扫描结果 %s，先跑 scan_actions.py" % args.cmd_list)

    current = read_list(args.cmd_list)
    known = read_tsv(args.existing)
    pending = read_tsv(args.pending)

    # 已有译文优先，本次新译覆盖不了既有条目（避免手滑改错旧译文）
    merged = dict(pending)
    merged.update(known)

    rows = []
    missing = []
    for display in current:
        zh = merged.get(display)
        if zh:
            rows.append("%s\t%s" % (display, zh))
        else:
            missing.append(display)

    stale = sorted(set(known) - set(current))

    if args.out:
        rows.sort()
        with io.open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(HEADER)
            f.write("\n".join(rows) + "\n")

    with io.open(args.missing_out, "w", encoding="utf-8", newline="\n") as f:
        f.write("# 待译：这些命令显示名在词典里还没有中文\n")
        f.write("# 把每行补成 `上面这行<TAB>中文` 后另存为 TSV，用 --pending 传回本脚本\n")
        f.write("# 本次共 %d 条\n\n" % len(missing))
        for d in missing:
            f.write(d + "\n")

    print("命令显示名 %d，已译 %d，待译 %d" % (len(current), len(rows), len(missing)))
    if stale:
        print("上游已移除、词典中失效 %d 条（已从词典剔除）:" % len(stale))
        for s in stale[:20]:
            print("  - %s" % s)
        if len(stale) > 20:
            print("  ... 其余见上方统计")
    else:
        print("词典中没有失效条目")


if __name__ == "__main__":
    main()
