# -*- coding: utf-8 -*-
"""给上游 zed.iss 打补丁，产出汉化版可用的 Inno Setup 脚本。

用法:
    python -I patch_zed_iss.py <上游 zed.iss> <输出 iss>

上游每改一次 zed.iss，这份补丁就多一次考验——所以三处改动都用字符串
替换而非直接改写文件，并带断言：一旦上游改了那几行，脚本会立刻报错，
而不是默默产出错误的安装包。

补丁内容:
  1. appx/* 那行没有 `#ifexist` 保护，源码里缺 appx 包时 Inno 直接编译报错。
     汉化版不打 explorer_command_injector 的 appx（包标识固定，会和官方
     Zed 撞车），所以把它和 [UninstallRun] 里对应的卸载挂钩一起条件化。
  2. 关掉语言选择对话框——安装程序本身应跟随系统语言。
  3. 加一页使用说明。绿色包里的「使用说明.txt」是 UTF-8，用记事本打开可能
     乱码，所以同内容改由 Inno 自己的界面控件展示（Inno 用 Unicode，
     不受系统 ANSI 代码页影响）。
"""
import io
import sys

BS = chr(92)  # 反斜杠。直接写字面量容易在多层转义里出错，这里显式拼。

README_PASCAL = """
{ ===== 汉化版附加：向导中显示使用说明 ===== }
procedure InitializeWizard();
var
  ReadmePage: TOutputMsgWizardPage;
begin
  ReadmePage := CreateOutputMsgPage(
    wpSelectTasks,
    '使用说明',
    'Zed 汉化版已准备好安装',
    '界面语言跟随系统——中文系统下自动显示中文。' + #13#10 +
    '想让语言不受系统影响，可设环境变量 ZED_UI_LANGUAGE：' + #13#10 +
    '    ZED_UI_LANGUAGE=zh   强制中文' + #13#10 +
    '    ZED_UI_LANGUAGE=en   强制英文' + #13#10 + #13#10 +
    '命令面板（Ctrl+Shift+P）里中英文都可以搜索。' + #13#10 +
    '本版不会自动更新，不会被官方英文版覆盖。');
end;
"""


def patch(text):
    files_line = (
        'Source: "{#ResourcesDir}' + BS + 'appx' + BS + '*"; '
        'DestDir: "{app}' + BS + 'appx";  '
        'BeforeInstall: RemoveAppxPackage; AfterInstall: AddAppxPackage; '
        'Flags: ignoreversion; Check: IsWindows11OrLater'
    )
    assert files_line in text, "找不到 [Files] 里的 appx 行，上游 iss 可能改过"

    uninstall_line = (
        'Filename: "powershell.exe"; Parameters: "Invoke-Command -ScriptBlock '
        '{{Remove-AppxPackage -Package ""{#AppxFullName}""}"; '
        'Check: IsWindows11OrLater; Flags: shellexec waituntilterminated runhidden'
    )
    assert uninstall_line in text, "找不到 [UninstallRun] 里的 appx 行，上游 iss 可能改过"

    guard = '#ifexist ResourcesDir + "' + BS + 'appx' + BS + 'zed_explorer_command_injector.appx"'
    text = text.replace(files_line, guard + "\n" + files_line + "\n#endif")
    text = text.replace(uninstall_line, guard + "\n" + uninstall_line + "\n#endif")

    assert "ShowLanguageDialog=auto" in text, "找不到 ShowLanguageDialog=auto，上游 iss 可能改过"
    text = text.replace("ShowLanguageDialog=auto", "ShowLanguageDialog=no")

    assert "[Code]" in text, "上游 iss 里没有 [Code] 段"
    text = text.rstrip("\r\n") + "\n" + README_PASCAL
    return text


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    patched = patch(io.open(src, encoding="utf-8").read())
    # 显式写出 CRLF：Inno 的脚本解析器对换行不敏感，但保持与上游一致便于比对
    io.open(dst, "w", encoding="utf-8", newline="\r\n").write(patched)
    print("已写出", dst)


if __name__ == "__main__":
    main()
