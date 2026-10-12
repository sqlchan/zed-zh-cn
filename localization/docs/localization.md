# 界面汉化

这份文档讲清楚 Zed 的汉化是怎么做的、怎么在**上游更新后**重新汉化、以及打包分发。
涉及的都是本仓库相对上游 `zed-industries/zed` 的改动，方便接手的人继续维护。

- 适用对象：要维护汉化、重新编译、或给别人打包的人
- 不涉及：自己的语言（跟随系统 + `ZED_UI_LANGUAGE` 覆盖）

## 东西都在哪

汉化**可编辑的部分**全部集中在仓库根的 `localization/` 一个目录里：

| 位置 | 内容 |
| --- | --- |
| `localization/i18n_dict.tsv` | 通用 UI 词典，纯数据，日常改的就是它 |
| `localization/i18n_commands.tsv` | 命令面板词典，由脚本生成 |
| `localization/tools/` | 扫描与打包辅助脚本 |
| `localization/docs/` | 本文件 |

框架层的代码改动挪不走（那是改上游已有的文件），仍在 `crates/` 里，共 6 处收敛点
（见下文）。所以**要看自己相对上游改了什么：`git diff` 看 `crates/`，其余全在
`localization/`**。

## 一句话概括

界面上几乎所有文案最终都会经由少数几个"收敛点"渲染。汉化在这几个点上挂一个
**运行时字典查询**：命中就换成中文，没命中就原样保留英文。字典本身是纯数据
（`localization/i18n_dict.tsv`），和框架代码彻底分开——这正是"上游更新后重新
汉化"代价很低的原因。

## 为什么不用编译期的方案

考虑过、也排除了下面几种做法，理由都在这里，免得后来人重走一遍：

| 方案 | 为什么不用 |
| --- | --- |
| 直接改源码里的字面量 | 上游每次改动同一行都冲突，`git pull` 之后基本无法维护 |
| 依赖 Fluent / gettext 那套标准 i18n | 上游没有，得改动数百个调用点，等于自己维护一个 fork |
| 按子串替换（`text.replace("File", "文件")`） | **会误伤用户数据**：文件名、提交信息、代码内容里的 "File" 也会被替换 |
| 编译期宏（`t!("Open")`） | 每个调用点都要改；且大量文案是运行时拼出来的，宏覆盖不到 |

所以选了「整串精确匹配 + 运行时查表」。整串匹配是关键：只有整个字符串与词条
完全相等才替换，`my_file.txt` 这种用户数据永远不会被当成文案。

## 架构

```
翻译数据                           收敛点（查询方）              被汉化的界面
──────────────────────────────────────────────────────────────────────────────
localization/i18n_dict.tsv      →  ui::i18n::translate()       →  Label / Button / 菜单 / 面板标题
  （3315 条，含 55 条模板）          translate_owned()              绝大部分 UI 文案
                                →  tooltip::Title::Str          →  所有工具提示
                                →  Headline::new                →  标题类文本
                                →  editor placeholder           →  编辑器占位提示
                                →  HighlightedLabel             →  带高亮的标签（如搜索结果）
localization/i18n_commands.tsv  →  ui::i18n::translate_command_name()
  （1355 条）                        ↑ 只被下面几处调用，传进来的必定是 action 名
                                    ├─ command_palette  命令面板
                                    ├─ which_key        按键提示浮层
                                    └─ keymap_editor    快捷键编辑器
```

### 汉化的东西都在一个目录里

词典、脚本、本文件都在仓库根的 `localization/` 下；只有框架层的代码改动在
`crates/` 里（那是改上游已有文件，挪不走）。所以想看自己相对上游改了什么，
`git diff` 看 `crates/`，其余全在 `localization/` 一个目录。

词典跨 crate 引用：`crates/ui/src/i18n.rs` 里
`include_str!("../../../localization/i18n_dict.tsv")`。代价是 `crates/ui` 不再
自包含，`cargo package` 会失败——fork 场景不发布，无所谓。

### 收敛点清单（共 6 处）

改动全部集中在这里，`git diff` 一望即知：

| 文件 | 改了什么 |
| --- | --- |
| [crates/ui/src/components/label/label.rs](../../crates/ui/src/components/label/label.rs) | `Label::new` / `set_text` 走 `translate_owned`。**覆盖面最大**，绝大多数 UI 文案在这里 |
| [crates/ui/src/components/tooltip.rs](../../crates/ui/src/components/tooltip.rs) | `Title::Str` 直接转元素、不走 `Label`，单独查表 |
| [crates/ui/src/styles/typography.rs](../../crates/ui/src/styles/typography.rs) | `Headline` 自行渲染文本，单独查表 |
| [crates/ui/src/components/label/highlighted_label.rs](../../crates/ui/src/components/label/highlighted_label.rs) | 见下方"高亮下标"一节 |
| [crates/editor/src/editor.rs](../../crates/editor/src/editor.rs) | `set_placeholder_text` 查表。placeholder 必然是 UI 文案，不是用户数据 |
| [crates/command_palette/src/command_palette.rs](../../crates/command_palette/src/command_palette.rs) | 命令显示名翻译 + 中英双语搜索 + 高亮位置换算 |

另外三处用到 `translate_command_name`（which_key、keymap_editor），属于同一类改动。

### 语言判定

[crates/ui/src/i18n.rs](../../crates/ui/src/i18n.rs) 的 `ui_language()`，优先级：

1. 环境变量 `ZED_UI_LANGUAGE`（`en` / `zh` / `zh-CN` 都认，只看前缀是不是 `zh`）
2. 系统区域设置（中文 Windows 自动为中文）
3. 兜底英文

结果在 `OnceLock` 里缓存，只算一次。

## 词典格式

`localization/i18n_dict.tsv`，每行 `英文原文<TAB>中文译文`，`#` 开头为注释：

```
Open	打开
Close Window	关闭窗口
```

**模板词条**（55 条）用 `{}` 占位，用于运行时拼出来的文案：

```
Close {} Dock	关闭{}停靠栏
```

匹配规则是 `parts[0] + 任意 + parts[1] + ...`，占位符多的优先（更具体的先匹配），
`任意` 部分的原样内容会填回译文的 `{}` 位置。所以 `Close Left Dock` 能命中成
`关闭左侧停靠栏`，`Close My Weird Dock` 也能命中成 `关闭My Weird Dock停靠栏`。

**大写回退**：`translate()` 第一次没命中时，会拿 `to_ascii_uppercase()` 后的串再查
一次（`upper_dict()`）。因为有些按钮会先把文案转大写再渲染。注意回退表以"词典键
的大写"为键——所以词典里有 `Open`，就能命中 `OPEN`，**不能**反过来。

### 为什么命令词典要单独一个文件

`i18n_commands.tsv` 里是命令面板的显示名，形如 `editor: add selection above`。
这些名字由 action 的类型名自动推导而来（`command_palette::humanize_action_name`），
源码里**没有对应字面量**，所以不能靠搜字符串拿到。

**必须和通用词典分开**：命令名的后半段是单个小写单词——`copy`、`save`、`editor`、
`search`——这些和真实文件名/文件夹名完全撞车。如果放进通用词典，项目面板里一个叫
`copy` 的文件夹会被 `Label::new` 译成中文。分开之后，`translate_command_name` 拿到的
必定是 action 名，不存在这个风险。

## 命令面板的两个额外处理

### 1. `Command.name` 必须保持英文

[crates/command_palette/src/command_palette.rs](../../crates/command_palette/src/command_palette.rs)
里的 `Command::name` 是：

- 命令历史数据库的主键（`write_command_invocation` / `remove_command_history`）
- `Action Invoked` 遥测事件的 `action` 字段值

**翻译只发生在 `display_name()`**，`name` 始终是英文。改这里之前想清楚后果。

### 2. 中英双语搜索 + 高亮位置换算

界面上显示中文，但用户依然会按英文名搜索。所以交给模糊匹配的串是
`中文译文 英文原文` 拼接（`bilingual_search_text`），两种语言都能搜到。

由此带来一个必须处理的副作用：模糊匹配给出的下标是相对**搜索串**的，而渲染用的是
**显示串**，两者长度不同。同时 `editor: move line up` 里的 `:` 和空格会被
`humanize_action_name` 处理，位置完全对不上。所以 `remap_positions()` 在每次
匹配结果出来后换算一次，只保留落在显示名范围内的、且在字符边界上的位置。

### 3. 高亮下标会因翻译而失效

`HighlightedLabel` 的高亮下标是**英文原文的字节偏移**。译文长度不同，偏移必然
对不上——轻则高亮错位，重则索引落在字符中间触发 `debug_panic`，release 下甚至越界。

处理方式：只有在译文与原文一致时才保留高亮，一旦真的翻译了就清空下标。
**丢掉高亮总好过画错或者崩溃。**

## 上游更新后如何重新汉化

这是这套方案存在的意义。`git pull` 之后：

```bash
# 1. 拉上游代码并重新编译
git pull
cargo build --release -p zed -p cli

# 2. 看看命令面板有没有新增命令
cd localization/tools
python -I scan_actions.py --out cmd_list.txt
python -I build_cmd_dict.py --cmd-list cmd_list.txt
#    会报「命令显示名 N，已译 M，待译 K」
#    K > 0 时，待译清单在 cmd_missing.txt

# 3. （有新增命令时）翻译 cmd_missing.txt 里的条目，另存成 TSV，
#    格式是 `英文显示名<TAB>中文`，然后：
python -I build_cmd_dict.py --cmd-list cmd_list.txt --pending 新译.tsv

# 4. 看看普通 UI 文案有没有漏的
python -I scan_ui_strings.py
#    会打印「候选总数 N，已收录 M，未收录 K（其中来自测试文件 T）」
#    明细写在 ui_strings_missing.txt，按「是否只出现在测试文件里」分好组，
#    先看「真正要补的」那组

# 5. （补了词之后）重新编译
cd ../.. && cargo build --release -p zed -p cli
```

`build_cmd_dict.py` **不会丢已有译文**：词典里已存在、且扫描结果里仍出现的条目
原样保留。上游删掉或改名导致失效的条目会被剔除并单独报告——看到"上游已移除"的
提示就说明这些译文作废了。

### 词条失效是这套方案的主要弱点

上游把 `Open File` 改成 `Open a File`，词典里那条就命不中了，界面上退回英文。
不会有报错，也不会崩，只是回到英文。**这是刻意接受的代价**——换来的是
`git pull` 几乎不冲突。`scan_ui_strings.py` 就是用来发现这类漏网的。

## 打包（Windows）

```bash
bash script/pack_zed_localized.sh
```

产出两个文件：

| 产物 | 说明 |
| --- | --- |
| `Zed-汉化版-<版本>-x64.zip` | 绿色免安装包，解压双击 `Zed.exe` |
| `Zed-汉化版-<版本>-x64-Setup.exe` | Inno Setup 安装程序 |

前置条件：release 编译产物齐全、装了 Inno Setup 6、装了 7-Zip、下载解压了
microsoft/terminal 的 ConPTY 包（`CONPTY=<目录>` 指定，默认 `/d/Temp/pkgs/conpty`）。

用到的环境变量可用 `REPO=` / `OUT=` / `CONPTY=` / `ISCC=` / `SEVENZ=` 覆盖。

### 与上游 `bundle-windows.ps1` 的差异

这些差异都是有意为之，不是遗漏：

- 不做代码签名、不上传 Sentry、不下载 AGS（AMD 显卡的可选优化）
- **跳过 `explorer_command_injector` 的 appx**（Win11 右键集成）。它的包标识是固定
  的 `ZedIndustries.Zed*`，对方若已装官方 Zed 会撞车
- `zed.iss` 不直接改，而是由 [patch_zed_iss.py](../tools/patch_zed_iss.py)
  就地生成一份补丁副本。这样 `git pull` 更新了上游 `zed.iss` 也不用手工改——
  补丁用字符串替换 + 断言，上游一改那几行就会立刻报错，而不是默默产出坏包

### 自动更新是关掉的

`release_channel/src/lib.rs` 里 `poll_for_updates()` 对 `Dev` 通道返回 `false`。
`RELEASE_CHANNEL_NAME` 取 `ZED_RELEASE_CHANNEL` 环境变量，没有就用
`zed/RELEASE_CHANNEL` 文件（内容是 `dev`）。普通 `cargo build` 不会设这个环境变量，
所以构建出来的是 dev 通道，**不会自动更新，也就不会被官方英文版覆盖**。

如果哪天想在打包时显式指定，构建前设 `ZED_RELEASE_CHANNEL=dev` 即可。

## 踩过的坑（省得重走）

这些都是实际调试中撞上的，按"症状 → 原因"写：

### 汉化相关

**扫描脚本漏掉 action，界面上个别命令保持英文**
`#[cfg(any(test, feature = "test-support"))]` 可以出现在**不带花括号**的枚举变体上
（`Stub,`）。只按花括号配对来找条目结束位置的循环，会在 depth 0 处遇到 `}` 就
把 depth 减成负数，然后一路吞掉后面的内容。修法是：depth 已经为 0 时遇到 `}`、`;`、`,` 
都算条目结束。

**修了上面那条，反而丢了 16 个 terminal action**
原因更隐蔽：`terminal.rs` 里某个 `#[cfg(test)] mod domain_tests { ... }` 的字符串
字面量里含 `}`，数括号时被它带偏，真正的收尾花括号没被识别，于是把它后面的
`actions!(terminal, [...])` 一起删掉了。修法是先 `_mask_literals()` 把字符串/字符
字面量和注释替换成**等长空格**（保持偏移不变），再在掩码副本上数括号。

**`#[cfg(test)]` 不能一刀切**
`workspace.rs` 第 8 行就是 `#[cfg(test)] mod multi_workspace_tests;` 这样的模块级
声明。`src[:src.find("#[cfg(test)]")]` 会把整个文件砍掉——一度因此漏掉 92 条
workspace 命令。

### 打包相关

**`bin/zed.exe` 变成 493 字节**
上游 `resources/windows/zed.sh`（给 git-bash 用户用的包装脚本）要放到 `bin/zed`。
MSYS 把 `bin/zed` 和 `bin/zed.exe` 当成同一个文件，于是 493 字节的脚本覆盖了
3.3MB 的命令行程序。**修法是不打包那个 shell 脚本**——Windows 用户直接调
`bin\zed.exe` 即可。

**`cp -r "$STAGE/bin" "$ZIPDIR/bin"` 报 "File exists" 中断整包**
`set -e` 下直接终止。改成逐个文件指名复制。

**`mv` 吃掉了 cargo 的构建产物**
脚本里原来用 `mv "$REL/cli.exe" ...`，导致 `target/release` 下再找不到 `cli.exe`，
下次只跑打包脚本就失败。全部改成 `cp`。

**ISCC 报 "You may not specify more than one script filename"**
Git Bash 把 `/dAppId=...` 当成 POSIX 路径改写成了别的形式。加
`MSYS2_ARG_CONV_EXCL='*'` 关掉参数转换。

**/d 定义的路径拼进 Source: 后无效**
ISCC 的 `/d` 值会被直接拼进 `Source:` 路径，必须给 Windows 形式（`cygpath -w`），
不能用 `/d/Temp/...` 这种 POSIX 路径。

**heredoc 吃掉反斜杠**
用 heredoc 往文件里写 Inno 脚本片段时，`"\appx\*"` 会变成 `"ppx\*"`。改成用
独立的 Python 脚本写，并用 `BS = chr(92)` 显式拼反斜杠。

**安装程序编译失败：找不到 conpty.dll**
仓库只自带了 `bin/x64/OpenConsole.exe`，**没有 conpty.dll**，而 iss 里
`Source: "{#ResourcesDir}\conpty.dll"` 那行**没有 `#ifexist` 保护**。必须从
ConPTY 包里取。x64/arm64 的 OpenConsole.exe 那两行有保护，缺了只是跳过。

**卸载"失败"：点了没反应，目录还在**
如果从**安装目录内部**启动 `unins000.exe`，卸载器删除自身时被占用，会弹出确认框
然后卡住，看起来像卸载失败。**从安装目录之外启动**即可，实测 exit=0 且目录清空。

**`使用说明.txt` 在记事本里乱码**
文件是 UTF-8，Windows 记事本按系统 ANSI 代码页探测会误判。指望不了记事本，所以
同内容又由安装程序的界面控件展示了一遍（Inno 用 Unicode，不受代码页影响），
见 `patch_zed_iss.py` 里的 `README_PASCAL`。绿色包里那个 txt 保留了，但补了一行
编码说明。

## 已知的不足

老实说清楚，免得以为已经做完了：

1. **词条会随上游改动失效**（见上文）。词典 3315 条，静态扫描能识别的候选里，
   非测试文件部分还有约 260 条未收录——其中大部分不是 UI 文案（HTTP 头、示例
   代码、测试夹具、代码片段），但也有少量真正的漏网之词。
2. **运行时拼出来的文案覆盖不全**。模板词条只覆盖了 55 种模式，更复杂的拼接
   （多个占位符 + 条件分支）会退回英文。
3. **动态注册的 action 名**收不全。扫描脚本只认源码里能静态看到的 `actions!(...)`
   和 `#[derive(Action)]`。
4. **`window.prompt()` 之类的系统对话框**仍是英文，
   `assets/settings/default.json` 里 `"use_system_prompts": true`。
5. **安装程序的许可协议正文是上游原始英文的** Terms of Service。那是法律文本，
   刻意没有翻译。
