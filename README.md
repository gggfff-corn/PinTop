# PinTop

> A lightweight Windows always-on-top window manager with a floating Buddy cat. Pick any window, keep it above others, and manage pinned windows from a hover panel. Built with the Python standard library only.

一个轻量级的 Windows 窗口置顶工具。启动后驻留在后台，点一下悬浮的小猫咪，再点目标窗口，就能把它钉在最前面——再也不怕被别的窗口盖住。

![Platform](https://img.shields.io/badge/platform-Windows-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.12-green?style=flat-square)
![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen?style=flat-square)

---

## ✨ 功能特性

- **持续守护防覆盖**：后台定时检测，一旦目标窗口被盖住或置顶被取消，立刻重新提到最前；检测间隔可调（200–5000 ms）
- **拾取任意窗口**：鼠标点选，支持多窗口同时置顶
- **悬浮小猫咪**：WorkBuddy 风格的机械猫，会呼吸、眨眼、抖耳朵；可拖拽、半透明、始终置顶
- **悬停面板**：鼠标停在猫咪身上弹出已置顶窗口列表，点窗口名即取消该窗口
- **后台运行**：主界面默认隐藏，系统托盘常驻，托盘图标提示已置顶数量
- **全局热键**：`Ctrl + Shift + Alt + T` 一键置顶 / 取消当前窗口（避开 QQ 闪传的 `Ctrl + Alt + T`）
- **不抢焦点**：只改窗口层级，不影响在目标窗口里输入
- **零第三方依赖**：纯 Python 标准库，`ctypes` 调 Win32 API + `tkinter` 界面

## 🚀 快速开始

直接下载 `dist/强制置顶工具.exe`，双击运行即可，无需安装 Python。

程序启动后会隐入后台，屏幕右侧出现一只悬浮的小猫咪。

## 📖 使用说明

| 操作 | 方法 |
| --- | --- |
| 拾取窗口置顶 | 左键单击悬浮猫咪（变成橙色「待命」状态），再单击目标窗口 |
| 取消单个置顶 | 鼠标悬停悬浮猫咪 → 在弹出的面板里点窗口名称或 `✕` |
| 取消全部置顶 | 悬停面板底部的「取消全部」，或主界面的「全部取消」 |
| 热键置顶 / 取消 | 对当前窗口按 `Ctrl + Shift + Alt + T` |
| 取消拾取模式 | 拾取时按 `ESC` |
| 移动悬浮猫咪 | 按住左键拖拽 |
| 打开主界面 | 双击托盘图标，或右键猫咪 →「显示主界面」 |
| 退出 | 托盘右键 →「退出」，或猫咪右键 →「退出」 |

托盘图标右键菜单：**显示主界面 / 拾取窗口置顶 / 退出**。

## 🛠️ 从源码运行 / 构建

需要 Windows + Python 3.12（带 `tkinter`）。

```bash
# 直接运行
python always_on_top.py

# 打包成独立 exe（需先安装 PyInstaller）
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name "强制置顶工具" always_on_top.py
```

生成的 exe 位于 `dist/` 目录。打包前如果 `dist/` 里已有同名 exe 且正被占用，请先关闭程序并删除旧文件。

## 🔧 实现原理

| 功能 | 实现方式 |
| --- | --- |
| 拾取窗口 | `WindowFromPoint` + `GetAncestor(GA_ROOT)` 取顶层窗口句柄 |
| 置顶 | `SetWindowPos(HWND_TOPMOST, SWP_NOMOVE \| SWP_NOSIZE \| SWP_NOACTIVATE)` |
| 守护 | 定时器周期性重新置顶，抢回被覆盖的 z-order，并检测窗口是否已关闭 |
| 排除自身 | 用进程 PID 判断，拒绝置顶本程序自己的窗口（悬浮球 / 主界面 / 托盘窗） |
| 托盘 | 后台线程 + `Shell_NotifyIconW` |
| 悬浮猫咪 | `tkinter.Canvas` 定时重绘，无图片资源、无额外依赖 |
| 全局热键 | `GetAsyncKeyState` 轮询组合键状态 |

## ⚠️ 注意事项

- 仅支持 **Windows** 系统。
- 部分带强反作弊机制的程序（如某些游戏、网银 UKey 控件）会检测并拒绝被外部置顶，这属于目标程序自身限制，工具层面无法绕过。
- 守护间隔设得太小会增加 CPU 占用；默认 1000 ms 在及时性和资源消耗之间比较均衡。

## 📁 项目结构

```
PinTop/
├── always_on_top.py          # 全部源码（单文件，零第三方依赖）
└── dist/
    └── 强制置顶工具.exe       # 可直接运行的独立程序
```

## License

MIT
