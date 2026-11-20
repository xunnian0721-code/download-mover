# 下载整理助手 (Download Mover)

一个轻量的 Windows 小工具：列出下载文件夹里最新的文件，可以手动多选一起移到指定文件夹；也可以开启「自动存放」，之后每个新下载完成的文件都会自动移过去。移错了还能一键撤销。

- 下载解压就能用的 exe，不用装 Python，也不用 PowerShell
- 常驻托盘后台运行，后台内存约 50 MB；靠系统文件变动通知发现新文件，空闲时 CPU 基本为 0
- 支持 Chrome / Edge / Firefox 等浏览器：会等下载真正完成（跳过 `.crdownload`、`.part` 等临时文件、等文件不再被占用）再移动
- 目标文件夹有同名文件时自动改名为 `文件名 (1)`，不会覆盖

## 功能

| 功能 | 说明 |
| --- | --- |
| 手动整理 | 列出最新 50 个下载，勾选（可多选）后点「移动勾选的文件」 |
| 自动存放 | 打开开关后，新下载完成的文件自动移到目标文件夹，右下角弹提示 |
| 已完成 / 撤销 | 右侧列表记录每次移动（标明手动/自动），勾选后可撤销，文件移回原下载文件夹 |
| 托盘运行 | 关窗口只是缩到托盘；右键托盘图标可开关自动存放、设置开机自启、退出 |

## 下载使用

1. 到 [Releases](../../releases/latest) 下载 `DownloadMover-win64.zip`。
2. 解压到一个固定的文件夹（以后别挪），双击 `DownloadMover.exe`。
3. 点「目标文件夹」右边的「更改」选好存放位置，之后按需手动移动或打开「自动存放」。

想开机自动启动：右键托盘图标 → 勾选「开机自动启动」。更详细的说明见 [使用说明.txt](使用说明.txt)。

只支持 64 位 Windows 10 / 11。

### 从旧版（PowerShell 版）升级

把旧版的 `config.json`、`history.json` 复制到 `DownloadMover.exe` 旁边，设置和已完成记录都会保留。旧版设置过开机自启的，新版第一次运行时会自动换成新的开机自启方式。

## 从源码运行 / 自己打包

需要 Python 3.11：

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pythonw mover.py
```

运行测试：`.venv\Scripts\python test_mover.py`（用临时文件夹，不影响你的设置）

打包成 exe：

```bat
.venv\Scripts\pip install pyinstaller
.venv\Scripts\python build.py
```

## 文件

| 文件 | 作用 |
| --- | --- |
| `mover.py` | 程序本体（Python + PySide6） |
| `test_mover.py` | 自动测试：模拟浏览器下载、占用、重名、撤销 |
| `build.py` | 打包成 exe |
| `启动下载整理.vbs` | 从源码运行时用的启动器（不弹黑窗） |
| `config.json` / `history.json` | 个人设置和最近 200 条移动记录，运行后自动生成，不会上传 |

用到的开源库：[PySide6](https://doc.qt.io/qtforpython-6/)（LGPL）。

## 许可

[MIT](LICENSE)
