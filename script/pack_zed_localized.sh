#!/usr/bin/env bash
# 把汉化版 Zed 打成两个可分发产物：
#   1) <OUT>/Zed-汉化版-<版本>-x64.zip        绿色免安装包
#   2) <OUT>/Zed-汉化版-<版本>-x64-Setup.exe  Inno Setup 安装程序
#
# 用法（在 Git Bash / MSYS 下）:
#   bash script/pack_zed_localized.sh
# 可用环境变量覆盖:
#   REPO=<仓库根>  OUT=<产物目录>  CONPTY=<ConPTY 包解压目录>
#
# 这是上游 script/bundle-windows.ps1 的精简替代，专为汉化版而写。汉化的
# 词典、Python 辅助脚本和说明文档都在仓库根的 localization/ 目录下。
#
# 前置条件（缺一不可）:
#   * 已用 msvc 工具链 release 编译过：cargo build --release -p zed -p cli
#     产物在 target/x86_64-pc-windows-msvc/release/{zed,cli,auto_update_helper}.exe
#   * 装了 Inno Setup 6（下面的 ISCC 路径按需改）
#   * 装了 7-Zip
#   * 下载解压了 microsoft/terminal 的 ConPTY 包（里面的 OpenConsole.exe 和
#     conpty.dll 比仓库自带的更新；缺失只会让终端"功能受限"，不影响其他功能）
#
# 与上游 script/bundle-windows.ps1 的区别（有意为之的简化）:
#   - 不做代码签名、不上传 Sentry、不下载 AGS（AMD 显卡的可选优化）
#   - 跳过 explorer_command_injector 的 appx（Win11 右键集成）。它的包标识是
#     固定的 ZedIndustries.Zed*，对方若已装官方 Zed 会撞车
#   - zed.iss 用一份就地生成的补丁副本（patch_zed_iss.py），这样每次 git pull
#     上游更新了 zed.iss 也不用手工改
set -euo pipefail

HERE=$(dirname "$(readlink -f "$0")")
# 默认取脚本上一级作为仓库根（脚本位于 <仓库根>/script/ 下），
# 这样 clone 到任何路径都能直接跑，不必改脚本。
REPO=${REPO:-$(dirname "$HERE")}
OUT=${OUT:-$REPO/inno/out}
CONPTY=${CONPTY:-$REPO/inno/conpty}
TARGET=x86_64-pc-windows-msvc
REL="$REPO/target/$TARGET/release"
# 打包暂存目录：放仓库自带的 inno/ 下（该目录已加进 .gitignore）
STAGE="$REPO/inno/localized"
ISCC=${ISCC:-"/c/Users/${USER:-$USERNAME}/AppData/Local/Programs/Inno Setup 6/ISCC.exe"}
SEVENZ=${SEVENZ:-"/c/Program Files/7-Zip/7z.exe"}
# 补丁脚本与汉化其余部分一起放在 localization/ 下
PATCH_ISS="$REPO/localization/tools/patch_zed_iss.py"
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' "$REPO/crates/zed/Cargo.toml" | head -1)

say() { printf '\n=== %s ===\n' "$*"; }

say "版本 $VERSION，产物目录 $OUT"
mkdir -p "$OUT"

for f in "$REL/zed.exe" "$REL/cli.exe" "$REL/auto_update_helper.exe"; do
    [ -f "$f" ] || { echo "缺少编译产物 $f，先跑 cargo build --release -p zed -p cli" >&2; exit 1; }
done

# ---------- 1. 准备安装目录 ----------
say "准备 $STAGE"
rm -rf "$STAGE"
mkdir -p "$STAGE/bin" "$STAGE/tools" "$STAGE/x64"
cp -r "$REPO/crates/zed/resources/windows/." "$STAGE/"

# ConPTY 资源：仓库只自带了 bin/x64/OpenConsole.exe，**没有 conpty.dll**，
# 而 zed.iss 里 conpty.dll 那行没有 #ifexist 保护，缺了会直接编译失败。
# 所以必须从 microsoft/terminal 的 ConPTY 包里取：
#   https://github.com/microsoft/terminal/releases  -> 解压出的
#   runtimes/win-x64/native/conpty.dll
CONPTY_DLL="$CONPTY/runtimes/win-x64/native/conpty.dll"
if [ ! -f "$CONPTY_DLL" ]; then
    echo "缺少 $CONPTY_DLL" >&2
    echo "请下载解压 microsoft/terminal 的 ConPTY 包，或用 CONPTY=<目录> 指定" >&2
    exit 1
fi
cp "$CONPTY_DLL" "$STAGE/conpty.dll"
# OpenConsole.exe 优先用 ConPTY 包里较新的版本，没有就退回仓库自带的那份
CONPTY_OC="$CONPTY/build/native/runtimes/x64/OpenConsole.exe"
if [ -f "$CONPTY_OC" ]; then
    cp "$CONPTY_OC" "$STAGE/x64/OpenConsole.exe"
elif [ -f "$REPO/crates/zed/resources/windows/bin/x64/OpenConsole.exe" ]; then
    cp "$REPO/crates/zed/resources/windows/bin/x64/OpenConsole.exe" "$STAGE/x64/OpenConsole.exe"
else
    echo "找不到 x64 的 OpenConsole.exe" >&2
    exit 1
fi
# arm64 是可选的：zed.iss 里那行有 #ifexist 保护
CONPTY_ARM="$CONPTY/build/native/runtimes/arm64/OpenConsole.exe"
if [ -f "$CONPTY_ARM" ]; then
    mkdir -p "$STAGE/arm64"
    cp "$CONPTY_ARM" "$STAGE/arm64/OpenConsole.exe"
fi

# ---------- 2. 整理成 zed.iss 期待的结构 ----------
mkdir -p "$STAGE/appx"   # 空目录，补丁后的 iss 会跳过它
# 刻意**不**放上游的 bin/zed（那个 493 字节的 shell 包装脚本，给 git-bash 用户用）。
# 它和 bin/zed.exe 在 MSYS 下会被当成同一个文件：要么 cp 报 "File exists"，
# 要么脚本把 3.3MB 的命令行程序整个覆盖成 493 字节。Windows 用户直接调
# bin\zed.exe 即可，功能完全一样。
cp "$REL/zed.exe" "$STAGE/Zed.exe"
cp "$REL/cli.exe" "$STAGE/bin/zed.exe"
cp "$REL/auto_update_helper.exe" "$STAGE/tools/auto_update_helper.exe"

# 校验：几个可执行文件的大小必须合理，否则直接停在这里，别等打完包才发现是空壳
check() {  # check <文件> <最小字节数>
    local size
    size=$(stat -c %s "$1" 2>/dev/null || echo 0)
    if [ "$size" -lt "$2" ]; then
        echo "打包失败：$1 只有 $size 字节（应至少 $2），文件不完整" >&2
        exit 1
    fi
}
check "$STAGE/Zed.exe"                      50000000
check "$STAGE/bin/zed.exe"                  1000000
check "$STAGE/tools/auto_update_helper.exe" 100000
check "$STAGE/conpty.dll"                   10000
check "$STAGE/x64/OpenConsole.exe"          100000

# ---------- 3. 绿色 zip ----------
say "生成绿色包"
ZIPDIR="$OUT/Zed-汉化版-$VERSION-x64"
rm -rf "$ZIPDIR"
# 逐个文件指名复制，不要 `cp -r "$STAGE/bin" "$ZIPDIR/bin"`：
# MSYS 下 cp 对目录参数的语义容易和预期不一致，出过 "File exists" 中断整包。
mkdir -p "$ZIPDIR/bin" "$ZIPDIR/x64"
cp "$STAGE/Zed.exe"             "$ZIPDIR/Zed.exe"
cp "$STAGE/bin/zed.exe"         "$ZIPDIR/bin/zed.exe"
cp "$STAGE/x64/OpenConsole.exe" "$ZIPDIR/x64/OpenConsole.exe"
cp "$STAGE/conpty.dll"          "$ZIPDIR/" 2>/dev/null || true
check "$ZIPDIR/bin/zed.exe" 1000000
cat > "$ZIPDIR/使用说明.txt" <<'TXT'
Zed 汉化版（免安装）
====================

运行：双击 Zed.exe

说明：
  * 界面语言跟随系统。中文系统下自动显示中文。
  * 想让界面语言不受系统影响，设环境变量 ZED_UI_LANGUAGE：
      ZED_UI_LANGUAGE=zh   强制中文
      ZED_UI_LANGUAGE=en   强制英文
  * 命令面板（Ctrl+Shift+P）里中英文都能搜索。
  * 本版不会自动更新，不会被官方英文版覆盖。
  * 卸载：直接删除整个文件夹。配置和缓存不在这里，分别在
    %APPDATA%\Zed 和 %LOCALAPPDATA%\Zed，需要清理时手动删。

命令行：把 bin 目录加到 PATH 后可用 `zed <文件或目录>`。

本文件是 UTF-8 编码，用记事本打开若显示乱码，请改用 VS Code 等编辑器。
TXT
( cd "$OUT" && "$SEVENZ" a -tzip -mx=9 -bso0 -bsp0 \
    "Zed-汉化版-$VERSION-x64.zip" "Zed-汉化版-$VERSION-x64" >/dev/null )
rm -rf "$ZIPDIR"
echo "绿色包: $OUT/Zed-汉化版-$VERSION-x64.zip"

# ---------- 4. 生成补丁版 zed.iss ----------
say "生成 zed.iss 补丁副本"
python -I "$PATCH_ISS" \
    "$REPO/crates/zed/resources/windows/zed.iss" "$OUT/zed-localized.iss"

# ---------- 5. Inno Setup ----------
say "编译安装程序"
# 两个 MSYS 陷阱，缺一不可：
#  1) Git Bash 会把 `/dAppId=...` 当成 POSIX 路径改写，必须关掉参数转换
#     （MSYS2_ARG_CONV_EXCL），否则 ISCC 会报 "You may not specify more than
#     one script filename"；
#  2) ISCC 的 /d 值会被直接拼进 Source: 路径，所以路径值要统一给 Windows
#     形式（cygpath -w），否则会生成带正斜杠的无效路径。
w() { cygpath -w "$1"; }
DEFS=(
  "/dAppId={{8357632E-24A4-4F32-BA97-E575B4D1FE5D}"   # 与 dev 官方包同 ID，装过官方 dev 版会覆盖
  "/dAppIconName=app-icon-dev"
  "/dOutputDir=$(w "$OUT")"
  "/dAppSetupName=Zed-汉化版-$VERSION-x64-Setup"
  "/dAppName=Zed 汉化版"
  "/dAppDisplayName=Zed 汉化版"
  "/dRegValueName=ZedLocalized"
  "/dAppMutex=Zed-Localized-Instance-Mutex"
  "/dAppExeName=Zed"
  "/dResourcesDir=$(w "$STAGE")"
  "/dShellNameShort=Z&ed 汉化版"
  "/dAppUserId=ZedIndustries.Zed.Localized"
  "/dVersion=$VERSION.0"
  "/dSourceDir=$(w "$REPO")"
  "/dAppxFullName=ZedIndustries.Zed_1.0.0.0_neutral__japxn1gcva8rg"
)
MSYS2_ARG_CONV_EXCL='*' "$ISCC" "$(w "$OUT/zed-localized.iss")" "${DEFS[@]}"
echo "安装包: $OUT/Zed-汉化版-$VERSION-x64-Setup.exe"

# ---------- 6. 收尾提示 ----------
cat <<EOF

打包完成。建议装机验证一次（静默安装到临时目录，跑完再卸载）：
  Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOICONS /DIR=D:\\Temp\\zi
  D:\\Temp\\zi\\unins000.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
注意：卸载器必须在**安装目录之外**启动。在安装目录里启动会在删除自身时
弹确认框并卡住，看起来像卸载失败，其实是自删除被占用。
EOF
