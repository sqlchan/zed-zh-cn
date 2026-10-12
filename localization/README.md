# 汉化（localization）

Zed 界面汉化的全部内容都在这个目录里：

```
localization/
├── README.md              ← 你在这里
├── i18n_dict.tsv          通用 UI 词典（3315 条，含 55 条模板）
├── i18n_commands.tsv      命令面板专用词典（1355 条）
├── docs/
│   └── localization.md    完整说明：原理 + 操作 + 踩坑
└── tools/
    ├── scan_ui_strings.py  扫源码里的 UI 文案，对照词典列出未收录的
    ├── scan_actions.py     枚举所有 action，产出命令显示名清单
    ├── build_cmd_dict.py   把清单与现有命令词典对账，产出更新后的词典
    └── patch_zed_iss.py    给上游 zed.iss 打补丁（打包时用）
```

> **先读 [docs/localization.md](docs/localization.md)**，那里讲清楚了为什么这么设计、
> 上游更新后怎么重新汉化、以及踩过的坑。这里只做目录导航。

## 代码改动在哪里

框架层的改动**不在**本目录，而在 `crates/` 里，共 6 处收敛点（详见上面的文档）。
原因很直接：那是改上游已有的文件，挪不走。用 `git diff` 就能看全。

词典本身是数据，放在本目录，由 `crates/ui/src/i18n.rs` 用
`include_str!("../../../localization/i18n_dict.tsv")` 跨 crate 嵌进二进制。
这样汉化的"可编辑部分"（词典、脚本、文档）全部集中在一处。

> 代价：`crates/ui` 不再是自包含的 crate，`cargo package` 会失败。本项目是
> fork、不发布，可以接受。

## 打包

打包脚本在上游的 `script/` 下（它调用本目录的 `patch_zed_iss.py`）：

```bash
bash script/pack_zed_localized.sh
```

## 三个 Python 脚本

纯标准库、无副作用（只读源码）。跑的时候用 `-I`，避免从当前目录加载同名模块：

```bash
python -I tools/scan_actions.py --out cmd_list.txt
python -I tools/build_cmd_dict.py --cmd-list cmd_list.txt
```

它们**不是**编译或运行 Zed 所必需的，只在维护词典、重新汉化、打包时用。
