# -*- coding: utf-8 -*-
"""
强制置顶工具 (Always On Top Manager)
纯标准库：ctypes 调 Win32 API + tkinter 界面，零第三方依赖。

特性：
  1. 启动即后台运行：主界面隐藏，系统托盘常驻图标
  2. 悬浮小球：半透明置顶、可拖拽，单击进入拾取模式
  3. 持续守护：定时把受控窗口重新提到最前，防止被覆盖
  4. 全局热键 Ctrl+Shift+Alt+T 置顶/取消当前窗口（避开 QQ 闪传的 Ctrl+Alt+T）

用法：双击运行，托盘右键菜单可「显示主界面 / 拾取窗口 / 退出」
"""

import ctypes
from ctypes import wintypes
import os
import sys
import time
import math
import threading
import tkinter as tk
from tkinter import ttk, messagebox

# 部分 Python 版本的 wintypes 缺少这些类型，在此补齐
if not hasattr(wintypes, "HCURSOR"):
    wintypes.HCURSOR = wintypes.HANDLE
if not hasattr(wintypes, "LRESULT"):
    wintypes.LRESULT = ctypes.c_ssize_t
if not hasattr(wintypes, "GUID"):
    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]
    wintypes.GUID = _GUID

# ==================== Win32 常量 ====================
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
GA_ROOT = 2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

VK_LBUTTON = 0x01
VK_ESCAPE = 0x1B
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_SHIFT = 0x10
VK_T = 0x54

# 托盘 / 消息
WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
TPM_LEFTALIGN = 0x0000
TPM_RIGHTBUTTON = 0x0002
ID_SHOW, ID_PICK, ID_QUIT = 1, 2, 3
SW_HIDE = 0
WHITENESS = 0x00FF0062
TRANSPARENT_BK = 1
IDC_CROSS = 32515

# ==================== 结构体 ====================
class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uTimeoutOrVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", wintypes.GUID), ("hBalloonIcon", wintypes.HICON)]


WNDPROC = ctypes.WINFUNCTYPE(wintypes.LRESULT, wintypes.HWND,
                             wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HCURSOR),
                ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


# ==================== DLL / 函数 ====================
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)


def _def(dll, name, argtypes, restype):
    func = getattr(dll, name)
    func.argtypes = argtypes
    func.restype = restype
    return func


SetWindowPos = _def(user32, "SetWindowPos",
                    [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                     ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.BOOL)
IsWindow = _def(user32, "IsWindow", [wintypes.HWND], wintypes.BOOL)
IsWindowVisible = _def(user32, "IsWindowVisible", [wintypes.HWND], wintypes.BOOL)
GetWindowTextW = _def(user32, "GetWindowTextW",
                      [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int)
GetWindowTextLengthW = _def(user32, "GetWindowTextLengthW", [wintypes.HWND], ctypes.c_int)
GetClassNameW = _def(user32, "GetClassNameW",
                     [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int)
GetForegroundWindow = _def(user32, "GetForegroundWindow", [], wintypes.HWND)
GetCursorPos = _def(user32, "GetCursorPos", [ctypes.POINTER(POINT)], wintypes.BOOL)
WindowFromPoint = _def(user32, "WindowFromPoint", [POINT], wintypes.HWND)
GetAncestor = _def(user32, "GetAncestor", [wintypes.HWND, wintypes.UINT], wintypes.HWND)
GetAsyncKeyState = _def(user32, "GetAsyncKeyState", [ctypes.c_int], ctypes.c_short)
GetWindowThreadProcessId = _def(user32, "GetWindowThreadProcessId",
                                [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD)
OpenProcess = _def(kernel32, "OpenProcess",
                   [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE)
CloseHandle = _def(kernel32, "CloseHandle", [wintypes.HANDLE], wintypes.BOOL)
QueryFullProcessImageNameW = _def(kernel32, "QueryFullProcessImageNameW",
                                  [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                   ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL)
GetModuleHandleW = _def(kernel32, "GetModuleHandleW", [wintypes.LPCWSTR], wintypes.HMODULE)

Shell_NotifyIconW = _def(shell32, "Shell_NotifyIconW", [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)], wintypes.BOOL)
CreatePopupMenu = _def(user32, "CreatePopupMenu", [], wintypes.HMENU)
AppendMenuW = _def(user32, "AppendMenuW", [wintypes.HMENU, wintypes.UINT,
                                          wintypes.UINT, wintypes.LPCWSTR], wintypes.BOOL)
TrackPopupMenu = _def(user32, "TrackPopupMenu", [wintypes.HMENU, wintypes.UINT,
                                                ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                                wintypes.HWND, ctypes.c_void_p], wintypes.BOOL)
DestroyMenu = _def(user32, "DestroyMenu", [wintypes.HMENU], wintypes.BOOL)
SetForegroundWindow = _def(user32, "SetForegroundWindow", [wintypes.HWND], wintypes.BOOL)
PostMessageW = _def(user32, "PostMessageW", [wintypes.HWND, wintypes.UINT,
                                            wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL)
PostThreadMessageW = _def(user32, "PostThreadMessageW", [wintypes.DWORD, wintypes.UINT,
                                                        wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL)
GetMessageW = _def(user32, "GetMessageW", [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                          wintypes.UINT, wintypes.UINT], wintypes.BOOL)
TranslateMessage = _def(user32, "TranslateMessage", [ctypes.POINTER(wintypes.MSG)], wintypes.BOOL)
DispatchMessageW = _def(user32, "DispatchMessageW", [ctypes.POINTER(wintypes.MSG)], wintypes.LRESULT)
DefWindowProcW = _def(user32, "DefWindowProcW", [wintypes.HWND, wintypes.UINT,
                                                wintypes.WPARAM, wintypes.LPARAM], wintypes.LRESULT)
RegisterClassExW = _def(user32, "RegisterClassExW", [ctypes.POINTER(WNDCLASSEXW)], wintypes.ATOM)
CreateWindowExW = _def(user32, "CreateWindowExW", [wintypes.DWORD, wintypes.LPCWSTR,
                                                  wintypes.LPCWSTR, wintypes.DWORD,
                                                  ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                                  ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                                  wintypes.HINSTANCE, wintypes.LPVOID], wintypes.HWND)
ShowWindow = _def(user32, "ShowWindow", [wintypes.HWND, ctypes.c_int], wintypes.BOOL)
DestroyWindow = _def(user32, "DestroyWindow", [wintypes.HWND], wintypes.BOOL)
LoadCursorW = _def(user32, "LoadCursorW", [wintypes.HINSTANCE, wintypes.LPCWSTR], wintypes.HCURSOR)
SetCursor = _def(user32, "SetCursor", [wintypes.HCURSOR], wintypes.HCURSOR)
GetDC = _def(user32, "GetDC", [wintypes.HWND], wintypes.HDC)
ReleaseDC = _def(user32, "ReleaseDC", [wintypes.HWND, wintypes.HDC], ctypes.c_int)
DestroyIcon = _def(user32, "DestroyIcon", [wintypes.HICON], wintypes.BOOL)

CreateCompatibleDC = _def(gdi32, "CreateCompatibleDC", [wintypes.HDC], wintypes.HDC)
CreateCompatibleBitmap = _def(gdi32, "CreateCompatibleBitmap", [wintypes.HDC, ctypes.c_int, ctypes.c_int], wintypes.HBITMAP)
SelectObject = _def(gdi32, "SelectObject", [wintypes.HDC, wintypes.HGDIOBJ], wintypes.HGDIOBJ)
DeleteObject = _def(gdi32, "DeleteObject", [wintypes.HGDIOBJ], wintypes.BOOL)
DeleteDC = _def(gdi32, "DeleteDC", [wintypes.HDC], wintypes.BOOL)
CreateSolidBrush = _def(gdi32, "CreateSolidBrush", [wintypes.COLORREF], wintypes.HBRUSH)
Ellipse = _def(gdi32, "Ellipse", [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int], wintypes.BOOL)
BitBlt = _def(gdi32, "BitBlt", [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD], wintypes.BOOL)
SetBkMode = _def(gdi32, "SetBkMode", [wintypes.HDC, ctypes.c_int], ctypes.c_int)
SetTextColor = _def(gdi32, "SetTextColor", [wintypes.HDC, wintypes.COLORREF], wintypes.COLORREF)
TextOutW = _def(gdi32, "TextOutW", [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int], wintypes.BOOL)
CreateFontW = _def(gdi32, "CreateFontW", [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                          wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                          wintypes.DWORD, wintypes.LPCWSTR], wintypes.HFONT)
CreateIconIndirect = _def(user32, "CreateIconIndirect", [ctypes.POINTER(ICONINFO)], wintypes.HICON)

try:
    SetProcessDPIAware = _def(user32, "SetProcessDPIAware", [], wintypes.BOOL)
except AttributeError:
    SetProcessDPIAware = None


# ==================== 工具函数 ====================
def get_window_text(hwnd):
    n = GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def get_class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_window_pid(hwnd):
    """取窗口所属进程 PID，用于排除本程序自身的窗口。"""
    pid = wintypes.DWORD(0)
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def get_process_name(hwnd):
    pid = wintypes.DWORD(0)
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return "PID {}".format(pid.value)
    try:
        size = wintypes.DWORD(260)
        buf = ctypes.create_unicode_buffer(260)
        if QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        CloseHandle(h)
    return "PID {}".format(pid.value)


def set_topmost(hwnd, on=True):
    """置顶/取消置顶；SWP_NOACTIVATE 保证不抢键盘焦点。"""
    return bool(SetWindowPos(hwnd, HWND_TOPMOST if on else HWND_NOTOPMOST, 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE))


def make_app_icon():
    """用 GDI 画一个蓝底白字「顶」的 32x32 图标（形象统一）。"""
    hdc_screen = GetDC(0)
    hbm_color = CreateCompatibleBitmap(hdc_screen, 32, 32)
    hbm_mask = CreateCompatibleBitmap(hdc_screen, 32, 32)
    ReleaseDC(0, hdc_screen)

    hdc_color = CreateCompatibleDC(0)
    hdc_mask = CreateCompatibleDC(0)
    old_color = SelectObject(hdc_color, hbm_color)
    old_mask = SelectObject(hdc_mask, hbm_mask)

    BitBlt(hdc_mask, 0, 0, 32, 32, hdc_mask, 0, 0, WHITENESS)  # mask 全白=不透明

    brush = CreateSolidBrush(0x9EC80A)  # COLORREF BGR -> #0AC89E WorkBuddy 青绿
    SelectObject(hdc_color, brush)
    Ellipse(hdc_color, 0, 0, 32, 32)
    DeleteObject(brush)

    font = CreateFontW(-24, 0, 0, 0, 700, 0, 0, 0, 0, 0, 0, 2, 0, "Microsoft YaHei UI")
    old_font = SelectObject(hdc_color, font)
    SetBkMode(hdc_color, TRANSPARENT_BK)
    SetTextColor(hdc_color, 0x00FFFFFF)
    TextOutW(hdc_color, 7, 3, "顶", 1)
    SelectObject(hdc_color, old_font)
    DeleteObject(font)

    SelectObject(hdc_color, old_color)
    SelectObject(hdc_mask, old_mask)
    DeleteDC(hdc_color)
    DeleteDC(hdc_mask)

    info = ICONINFO()
    info.fIcon = True
    info.hbmColor = hbm_color
    info.hbmMask = hbm_mask
    hicon = CreateIconIndirect(ctypes.byref(info))
    DeleteObject(hbm_color)
    DeleteObject(hbm_mask)
    return hicon


# ==================== 系统托盘 ====================
class TrayIcon:
    """后台线程创建隐藏窗口承载 Shell_NotifyIcon，处理右键菜单与双击。"""

    def __init__(self, dispatch, on_show, on_pick, on_quit, tip="强制置顶工具"):
        self.dispatch = dispatch
        self.on_show, self.on_pick, self.on_quit = on_show, on_pick, on_quit
        self.tip = tip
        self.hwnd = None
        self._wndproc_ref = None
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self._ready.wait(timeout=3)

    def _run(self):
        hinstance = GetModuleHandleW(None)
        class_name = "AOT_TrayClass_{}".format(os.getpid())

        @WNDPROC
        def wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_APP + 1:
                event = lparam & 0xFFFF
                if event == WM_RBUTTONUP:
                    pt = POINT()
                    GetCursorPos(ctypes.byref(pt))
                    menu = CreatePopupMenu()
                    AppendMenuW(menu, MF_STRING, ID_SHOW, "显示主界面")
                    AppendMenuW(menu, MF_STRING, ID_PICK, "拾取窗口置顶")
                    AppendMenuW(menu, MF_SEPARATOR, 0, None)
                    AppendMenuW(menu, MF_STRING, ID_QUIT, "退出")
                    SetForegroundWindow(hwnd)
                    TrackPopupMenu(menu, TPM_LEFTALIGN | TPM_RIGHTBUTTON,
                                   pt.x, pt.y, 0, hwnd, None)
                    DestroyMenu(menu)
                    PostMessageW(hwnd, WM_NULL, 0, 0)
                elif event == WM_LBUTTONDBLCLK:
                    self.dispatch(self.on_show)
                return 0
            if msg == WM_COMMAND:
                cmd = wparam & 0xFFFF
                if cmd == ID_SHOW:
                    self.dispatch(self.on_show)
                elif cmd == ID_PICK:
                    self.dispatch(self.on_pick)
                elif cmd == ID_QUIT:
                    self.dispatch(self.on_quit)
                return 0
            return DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc_ref = wndproc
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = wndproc
        wc.hInstance = hinstance
        wc.lpszClassName = class_name
        if not RegisterClassExW(ctypes.byref(wc)):
            self._ready.set()
            return

        hwnd = CreateWindowExW(0, class_name, "AOT Tray", 0, 0, 0, 0, 0,
                               0, 0, hinstance, 0)
        if not hwnd:
            self._ready.set()
            return
        self.hwnd = hwnd
        ShowWindow(hwnd, SW_HIDE)

        self.hicon = make_app_icon()
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_APP + 1
        nid.hIcon = self.hicon
        nid.szTip = self.tip
        Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        self._nid = nid
        self._ready.set()

        msg = wintypes.MSG()
        while GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
            TranslateMessage(ctypes.byref(msg))
            DispatchMessageW(ctypes.byref(msg))

        Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
        DestroyIcon(self.hicon)
        self._stopped.set()

    def set_tip(self, text):
        if getattr(self, "hwnd", None) and IsWindow(self.hwnd):
            self._nid.szTip = text[:127]
            self._nid.uFlags = NIF_TIP
            try:
                Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))
            except Exception:
                pass

    def stop(self):
        if self.hwnd and IsWindow(self.hwnd):
            PostThreadMessageW(self.thread.ident, 0x0012, 0, 0)  # WM_QUIT
            self._stopped.wait(timeout=3)


# ==================== 悬停面板 ====================
class HoverPanel:
    """鼠标悬停悬浮球时弹出，列出已置顶窗口名，点击某行即取消该窗口。"""

    def __init__(self, root, on_cancel_hwnd, on_cancel_all):
        self.root = root
        self.on_cancel_hwnd = on_cancel_hwnd
        self.on_cancel_all = on_cancel_all
        self.items = []            # [(hwnd, title), ...]
        self._hide_job = None
        self.visible = False

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.97)
        self.win.withdraw()

        self.frame = tk.Frame(self.win, bg="#F7FAFF",
                              highlightbackground="#B9C9E0", highlightthickness=1)
        self.frame.pack(fill=tk.BOTH, expand=True)
        self.frame.bind("<Enter>", lambda e: self.cancel_hide())
        self.frame.bind("<Leave>", lambda e: self.schedule_hide())

        # 标题栏
        head = tk.Frame(self.frame, bg="#2B7FE0", height=30)
        head.pack(fill=tk.X)
        tk.Label(head, text="已置顶窗口 · 点击名称取消", bg="#2B7FE0",
                 fg="#F7FBFF", font=("Microsoft YaHei UI", 9, "bold")).pack(
                     side=tk.LEFT, padx=10, pady=5)
        close = tk.Label(head, text="✕", bg="#2B7FE0", fg="#F7FBFF",
                         font=("Microsoft YaHei UI", 10), cursor="hand2")
        close.pack(side=tk.RIGHT, padx=10)
        close.bind("<Button-1>", lambda e: self.hide())

        self.body = tk.Frame(self.frame, bg="#F7FAFF")
        self.body.pack(fill=tk.BOTH, expand=True)

    def set_items(self, items):
        self.items = list(items)
        for w in self.body.winfo_children():
            w.destroy()
        if not self.items:
            tk.Label(self.body, text="（当前没有置顶窗口）", bg="#F7FAFF",
                     fg="#9AA7B8", font=("Microsoft YaHei UI", 9)).pack(
                         padx=12, pady=12, anchor=tk.W)
        else:
            for hwnd, title in self.items:
                short = title if len(title) <= 24 else title[:23] + "…"
                row = tk.Frame(self.body, bg="#F7FAFF")
                row.pack(fill=tk.X, padx=4, pady=1)
                name = tk.Label(row, text=short, bg="#F7FAFF", fg="#2C3A4B",
                                font=("Microsoft YaHei UI", 9), cursor="hand2",
                                anchor=tk.W, justify=tk.LEFT)
                name.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6, pady=4)
                xbtn = tk.Label(row, text="✕", bg="#F7FAFF", fg="#C0392B",
                                font=("Microsoft YaHei UI", 9), cursor="hand2")
                xbtn.pack(side=tk.RIGHT, padx=8)

                def activate(event, h=hwnd):
                    self.on_cancel_hwnd(h)
                    self.hide()

                for widget in (row, name, xbtn):
                    widget.bind("<Button-1>", activate)
                    widget.bind("<Enter>", lambda e, r=row: r.config(bg="#E4EEFC"))
                    widget.bind("<Leave>", lambda e, r=row: r.config(bg="#F7FAFF"))
                # 行内子控件 hover 时同步整行底色
                for widget in (name, xbtn):
                    widget.configure(bg="#F7FAFF")

        foot = tk.Frame(self.body, bg="#F7FAFF")
        foot.pack(fill=tk.X, pady=(4, 4))
        allbtn = tk.Label(foot, text="取消全部", bg="#F7FAFF", fg="#C0392B",
                          font=("Microsoft YaHei UI", 9, "bold"), cursor="hand2")
        allbtn.pack(padx=12, pady=2, anchor=tk.W)
        allbtn.bind("<Button-1>", lambda e: (self.on_cancel_all(), self.hide()))

        # 根据条目数计算高度
        n = max(len(self.items), 1)
        height = 30 + n * 28 + 34
        width = 300
        self.win.geometry("{}x{}".format(width, height))

    def show_at(self, x, y):
        self.cancel_hide()
        self.win.deiconify()
        self.win.lift()
        self.win.geometry("+{}+{}".format(x, y))
        self.visible = True

    def schedule_hide(self):
        self.cancel_hide()
        self._hide_job = self.root.after(1000, self.hide)

    def cancel_hide(self):
        if self._hide_job:
            try:
                self.root.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None

    def hide(self):
        self.cancel_hide()
        self.win.withdraw()
        self.visible = False


# ==================== 悬浮球 ====================
class FloatingBall:
    def __init__(self, root, on_pick, on_show, on_quit,
                 get_pinned, on_cancel_hwnd, on_cancel_all):
        self.root = root
        self.on_pick, self.on_show, self.on_quit = on_pick, on_show, on_quit
        self.picking = False
        self._moved = False

        size = 76
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.95)
        self.win.attributes("-transparentcolor", "white")
        self.win.geometry("{}x{}+{}+{}".format(size, size, sw - size - 30, sh // 2))

        self.canvas = tk.Canvas(self.win, width=size, height=size,
                                bg="white", highlightthickness=0)
        self.canvas.pack()

        # 动画状态
        self._alive = True
        self._t0 = time.monotonic()
        self._phase = 0.0
        self._blink = False
        self._bob = 0.0
        self._ear_twitch = 0.0
        self._draw()

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Button-3>", self._right_click)
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)
        self._arrow = LoadCursorW(0, ctypes.cast(32512, wintypes.LPCWSTR))

        self.panel = HoverPanel(root, on_cancel_hwnd, on_cancel_all)
        self.get_pinned = get_pinned
        self.root.after(80, self._animate)

    def _draw(self):
        """画一只 WorkBuddy 风格的机械猫：青绿圆脸 + 猫耳 + 耳机 + 青绿眼睛。

        支持动态效果：呼吸浮动、眨眼、耳朵抖动、拾取时脉冲光环。
        """
        c = self.canvas
        c.delete("all")
        if self.picking:
            # 拾取模式：暖橙配色，表示「待命拾取」
            body, edge, ear, eye, band = "#F0954B", "#B4621F", "#F7B27A", "#FFF3D6", "#8E4A16"
        else:
            # 常态：WorkBuddy 青绿 #0AC89E 系
            body, edge, ear, eye, band = "#0AC89E", "#079173", "#5FE0BE", "#0B4D3F", "#066B53"

        # 脉冲光环：拾取时明显呼吸，常态时轻微微光
        phase = self._phase
        pulse = (math.sin(phase * (6.0 if self.picking else 2.2)) + 1) / 2.0
        if self.picking:
            pad = 1.5 + pulse * 4.5
            c.create_oval(10 - pad, 12 - pad, 66 + pad, 68 + pad,
                          outline="#D9632B", width=2)
        else:
            pad = pulse * 2.0
            c.create_oval(14 - pad, 18 - pad, 62 + pad, 66 + pad,
                          outline="#A9EFDB", width=1)

        # 投影
        c.create_oval(12, 16, 66, 70, fill="#B9C6CF", outline="")

        # 猫耳（左右两只三角），tw 为抖动偏移
        tw = self._ear_twitch
        c.create_polygon(16 + tw, 26, 22 + tw, 6, 36 + tw, 20,
                         fill=body, outline=edge, width=2)
        c.create_polygon(60 - tw, 26, 54 - tw, 6, 40 - tw, 20,
                         fill=body, outline=edge, width=2)
        c.create_polygon(20 + tw, 22, 23 + tw, 12, 31 + tw, 19, fill=ear, outline="")
        c.create_polygon(56 - tw, 22, 53 - tw, 12, 45 - tw, 19, fill=ear, outline="")

        # 耳机头梁（跨过头顶的弧）
        c.create_arc(12, 8, 64, 50, start=200, extent=140, style="arc",
                     outline=band, width=4)
        # 左右耳罩
        c.create_rectangle(9, 28, 20, 46, fill=band, outline=edge, width=1)
        c.create_rectangle(56, 28, 67, 46, fill=band, outline=edge, width=1)

        # 脸（圆）
        c.create_oval(15, 17, 61, 63, fill=body, outline=edge, width=2)
        # 脸部高光
        c.create_oval(21, 21, 40, 36, fill=ear, outline="")
        # 面罩式五官：深色面罩 + 眼睛（眨眼时变成弯弯的眯眼线）
        c.create_rectangle(24, 34, 52, 50, fill=eye, outline="")
        if self._blink:
            c.create_arc(29, 36, 38, 46, start=195, extent=150,
                         style="arc", outline=body, width=2)
            c.create_arc(39, 36, 48, 46, start=195, extent=150,
                         style="arc", outline=body, width=2)
        else:
            c.create_oval(30, 37, 37, 46, fill=body, outline="")
            c.create_oval(40, 37, 47, 46, fill=body, outline="")
        # 小鼻子
        c.create_polygon(37, 51, 40, 51, 38, 54, fill=eye, outline="")

        # 呼吸浮动：整体上下轻微移动
        if self._bob:
            c.move("all", 0, self._bob)

    def _animate(self):
        """约 12 帧/秒刷新动态表情，纯 Canvas 绘制、无图片依赖。"""
        if not self._alive:
            return
        try:
            t = time.monotonic() - self._t0
            self._phase = t
            # 每 3.6 秒眨一次眼（含一次短促的二次眨）
            cycle = t % 3.6
            self._blink = (0.10 < cycle < 0.24) or (0.42 < cycle < 0.52)
            # 呼吸般缓慢起伏 ±1.1 像素
            self._bob = 1.1 * math.sin(t * 2.1)
            # 每 5.3 秒耳朵抖一下
            ec = t % 5.3
            self._ear_twitch = 2.5 * math.sin(t * 40) if ec < 0.28 else 0.0
            self._draw()
            self.root.after(80, self._animate)
        except Exception:
            pass

    def stop(self):
        """停止动画，避免窗口销毁后回调报错。"""
        self._alive = False

    def refresh_panel(self):
        if self.panel.visible:
            self.panel.set_items(self.get_pinned())

    def set_picking(self, active):
        self.picking = active
        self._draw()
        self.panel.hide()          # 拾取时收起面板
        if active:
            self.win.attributes("-alpha", 1.0)
            SetCursor(LoadCursorW(0, ctypes.cast(IDC_CROSS, wintypes.LPCWSTR)))
        else:
            self.win.attributes("-alpha", 0.92)
            SetCursor(self._arrow)

    def _on_enter(self, event):
        self.win.attributes("-alpha", 1.0)
        self.panel.cancel_hide()
        self.panel.set_items(self.get_pinned())
        bx, by = self.win.winfo_x(), self.win.winfo_y()
        pw = 300
        # 优先放左侧，空间不够放右侧
        px = bx - pw - 8
        if px < 4:
            px = bx + 82
        self.panel.show_at(px, max(4, by - 8))

    def _on_leave(self, event):
        self.win.attributes("-alpha", 0.92)
        self.panel.schedule_hide()

    def _press(self, event):
        self._moved = False
        self._ox, self._oy = event.x, event.y

    def _drag(self, event):
        x = self.win.winfo_x() + event.x - self._ox
        y = self.win.winfo_y() + event.y - self._oy
        self.win.geometry("+{}+{}".format(x, y))
        self._moved = True
        self.panel.hide()

    def _release(self, event):
        if not self._moved:
            self.on_pick()         # 点球体 -> 拾取

    def _right_click(self, event):
        menu = tk.Menu(self.win, tearoff=0)
        menu.add_command(label="拾取窗口置顶", command=self.on_pick)
        menu.add_command(label="显示主界面", command=self.on_show)
        menu.add_separator()
        menu.add_command(label="退出", command=self.on_quit)
        menu.tk_popup(event.x_root, event.y_root)


# ==================== 主程序 ====================
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("强制置顶工具 - Always On Top")
        self.root.geometry("560x520")
        self.root.minsize(500, 460)

        self.pinned = {}
        self.list_hwnds = []
        self.picking = False
        self.pick_start = 0.0
        self.hotkey_prev = False
        self.last_guard = 0.0
        self.closed = False

        self.guard_on = tk.BooleanVar(value=True)
        self.interval_var = tk.IntVar(value=1000)
        self.status = tk.StringVar(value="后台运行中 —— 点击悬浮球或托盘图标操作")

        self._build_ui()
        self.root.withdraw()  # 启动即隐藏，后台运行

        self.tray = TrayIcon(lambda f: self.root.after(0, f),
                             self.show_window, self.start_pick, self.quit_app,
                             tip="强制置顶工具 - 后台运行中")
        self._self_pid = os.getpid()
        self.ball = FloatingBall(root, self.start_pick, self.show_window,
                                 self.quit_app, self.get_pinned_items,
                                 self.cancel_hwnd, self.unpin_all)

        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.root.after(50, self.loop)

    def _build_ui(self):
        # ---- WorkBuddy 青绿主题 ----
        TEAL = "#0AC89E"
        TEAL_DARK = "#079173"
        BG = "#F4F7F9"
        CARD = "#FFFFFF"
        INK = "#22303C"
        MUTED = "#7C8B99"
        self.root.configure(bg=BG)

        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabelframe", background=BG, foreground=INK)
        style.configure("TLabelframe.Label", background=BG, foreground=TEAL_DARK,
                        font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TCheckbutton", background=CARD, foreground=INK)
        # 说明：Windows 的 vista 原生主题会忽略 ttk.Button 的 background，
        # 却保留 foreground=white，导致白字配浅底看不见。这里统一用 tk.Button
        # 显式指定 bg/fg/activebackground，确保任何主题下都清晰可读。
        def make_button(parent, text, command, bg, fg, active_bg, bold=False, side=tk.LEFT):
            return tk.Button(
                parent, text=text, command=command,
                bg=bg, fg=fg, activebackground=active_bg,
                activeforeground=fg, relief=tk.FLAT, bd=0,
                cursor="hand2", highlightthickness=0,
                font=("Microsoft YaHei UI", 10, "bold" if bold else "normal"),
            ).pack(side=side, padx=5, ipady=6)

        # ---- 顶部品牌栏 ----
        header = tk.Frame(self.root, bg=TEAL, height=76)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(header, text="▰  强制置顶工具", bg=TEAL, fg="white",
                 font=("Microsoft YaHei UI", 17, "bold")).pack(anchor=tk.W, padx=18, pady=(14, 0))
        tk.Label(header, text="拾取任意窗口并持续守护，再也不用担心被覆盖",
                 bg=TEAL, fg="#E6FFF7", font=("Microsoft YaHei UI", 9)).pack(
                     anchor=tk.W, padx=19, pady=(4, 0))

        # ---- 已置顶窗口卡片 ----
        frm = ttk.LabelFrame(self.root, text=" 已置顶窗口 ", padding=6)
        frm.pack(fill=tk.BOTH, expand=True, padx=16, pady=(14, 6))
        list_wrap = tk.Frame(frm, bg=CARD, highlightbackground="#DCE6EC",
                             highlightthickness=1)
        list_wrap.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(list_wrap, orient=tk.VERTICAL)
        self.listbox = tk.Listbox(list_wrap, yscrollcommand=scrollbar.set, height=6,
                                  font=("Microsoft YaHei UI", 10), activestyle="none",
                                  bg=CARD, fg=INK, selectbackground=TEAL,
                                  selectforeground="white", relief=tk.FLAT,
                                  highlightthickness=0)
        self.listbox.bind("<Double-Button-1>", lambda e: self.unpin_selected())
        scrollbar.config(command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=4)

        # ---- 按钮 ----
        btnf = tk.Frame(self.root, bg=BG)
        btnf.pack(fill=tk.X, padx=16, pady=8)
        make_button(btnf, "＋ 拾取窗口", self.start_pick, "#0A9B7A", "white", "#07705A", bold=True)
        make_button(btnf, "取消选中", self.unpin_selected, "#EAF6F2", TEAL_DARK, "#D8F0E9")
        make_button(btnf, "全部取消", self.unpin_all, "#EAF6F2", TEAL_DARK, "#D8F0E9")
        make_button(btnf, "隐藏", self.hide_window, "#EAF6F2", TEAL_DARK, "#D8F0E9", side=tk.RIGHT)

        # ---- 守护设置卡片 ----
        setf = ttk.LabelFrame(self.root, text=" 守护设置 ", padding=8)
        setf.pack(fill=tk.X, padx=16, pady=6)
        inner = tk.Frame(setf, bg=CARD)
        inner.pack(fill=tk.X)
        ttk.Checkbutton(inner, text="持续守护（被覆盖时自动重新置顶）",
                        variable=self.guard_on).pack(anchor=tk.W, padx=4, pady=(4, 6))
        row = tk.Frame(inner, bg=CARD)
        row.pack(fill=tk.X, padx=4, pady=(0, 6))
        tk.Label(row, text="检测间隔：", bg=CARD, fg=INK,
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        ttk.Spinbox(row, from_=200, to=5000, increment=100,
                    textvariable=self.interval_var, width=8).pack(side=tk.LEFT, padx=5)
        tk.Label(row, text="毫秒（越小越及时，越大越省资源）", bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)

        # ---- 状态栏 ----
        status_bar = tk.Frame(self.root, bg="#E9F5F0")
        status_bar.pack(fill=tk.X, padx=16, pady=(10, 0))
        tk.Label(status_bar, textvariable=self.status, bg="#E9F5F0", fg=TEAL_DARK,
                 font=("Microsoft YaHei UI", 9)).pack(anchor=tk.W, padx=10, pady=7)

        tk.Label(self.root,
                 text="操作：点悬浮球→点目标窗口置顶；悬停悬浮球→弹出列表，点窗口名取消。",
                 bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 8)).pack(
                     anchor=tk.W, padx=18, pady=(8, 0))
        tk.Label(self.root,
                 text="热键 Ctrl+Shift+Alt+T 置顶/取消当前窗口；拾取时按 ESC 取消。",
                 bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 8)).pack(
                     anchor=tk.W, padx=18, pady=(2, 12))

    # ---- 窗口显示控制 ----
    def show_window(self):
        if self.closed:
            return
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_window(self):
        self.root.withdraw()

    def quit_app(self):
        if self.closed:
            return
        self.closed = True
        for hwnd in list(self.pinned.keys()):
            if IsWindow(hwnd):
                set_topmost(hwnd, False)
        try:
            self.tray.stop()
        except Exception:
            pass
        try:
            self.ball.stop()
            self.ball.panel.hide()
            self.ball.win.destroy()
        except Exception:
            pass
        self.root.destroy()

    # ---- 拾取 ----
    def start_pick(self):
        if self.closed or self.picking:
            return
        self.picking = True
        self.pick_start = time.time()
        self.ball.set_picking(True)
        self.status.set("拾取模式：把鼠标移到目标窗口上，单击左键（ESC 取消）")

    def stop_pick(self):
        self.picking = False
        self.ball.set_picking(False)
        self.status.set("后台运行中 —— 点击悬浮球或托盘图标操作")

    def check_pick(self):
        if GetAsyncKeyState(VK_ESCAPE) & 0x8000:
            self.stop_pick()
            return
        if time.time() - self.pick_start < 0.4:  # 避免把悬浮球自身点击当成目标
            return
        if GetAsyncKeyState(VK_LBUTTON) & 0x8000:
            pt = POINT()
            GetCursorPos(ctypes.byref(pt))
            hwnd = WindowFromPoint(pt)
            hwnd = GetAncestor(hwnd, GA_ROOT)
            self.stop_pick()
            if self.valid_target(hwnd):
                self.pin(hwnd)
            else:
                self.status.set("未选中有效窗口，请重试")

    def valid_target(self, hwnd):
        if not hwnd or not IsWindow(hwnd) or not IsWindowVisible(hwnd):
            return False
        # 排除本程序自身的窗口（悬浮球、主界面、托盘隐藏窗等），
        # 否则点悬浮球拾取时会把球自己置顶
        if get_window_pid(hwnd) == self._self_pid:
            return False
        if hwnd == self.root.winfo_id():
            return False
        cls = get_class_name(hwnd)
        if cls in ("Progman", "WorkerW", "Shell_TrayWnd",
                   "SHELLDLL_DefView", "Windows.UI.Core.CoreWindow"):
            return False
        return bool(get_window_text(hwnd).strip())

    # ---- 置顶管理 ----
    def pin(self, hwnd):
        if hwnd in self.pinned:
            self.status.set("该窗口已经置顶了")
            return
        if not set_topmost(hwnd, True):
            self.status.set("置顶失败：窗口可能已被关闭")
            return
        title = get_window_text(hwnd) or "(无标题窗口)"
        self.pinned[hwnd] = {"title": title, "proc": get_process_name(hwnd)}
        self.refresh_list()
        short = title if len(title) <= 22 else title[:21] + "…"
        self.status.set("✓ 已置顶：{}  （悬停悬浮球可查看/取消）".format(short))
        self._sync_badge()

    def _sync_badge(self):
        n = len(self.pinned)
        self.ball.refresh_panel()
        self.tray.set_tip("强制置顶工具 - 已置顶 {} 个窗口".format(n))

    def get_pinned_items(self):
        return [(h, info["title"]) for h, info in self.pinned.items()]

    def cancel_hwnd(self, hwnd):
        """从悬停面板点击某窗口名：取消该窗口置顶。"""
        self.unpin(hwnd)

    def unpin(self, hwnd):
        if hwnd not in self.pinned:
            return
        if IsWindow(hwnd):
            set_topmost(hwnd, False)
        del self.pinned[hwnd]
        self.refresh_list()
        self._sync_badge()
        self.status.set("已取消置顶（剩余 {} 个）".format(len(self.pinned)))

    def cancel_latest(self):
        """保留给托盘菜单/热键：取消最近置顶的一个窗口（LIFO）。"""
        if not self.pinned:
            return
        hwnd = list(self.pinned.keys())[-1]
        self.unpin(hwnd)

    def unpin_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选中一个窗口")
            return
        self.unpin(self.list_hwnds[sel[0]])

    def unpin_all(self):
        for hwnd in list(self.pinned.keys()):
            self.unpin(hwnd)
        self.status.set("已取消全部置顶")

    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        self.list_hwnds = []
        for hwnd, info in self.pinned.items():
            self.listbox.insert(tk.END, "{}  [{}]".format(info["title"], info["proc"]))
            self.list_hwnds.append(hwnd)

    # ---- 守护 & 热键 ----
    def guard(self):
        changed = False
        for hwnd in list(self.pinned.keys()):
            if not IsWindow(hwnd):
                del self.pinned[hwnd]
                changed = True
                continue
            set_topmost(hwnd, True)
            new_title = get_window_text(hwnd) or "(无标题窗口)"
            if new_title != self.pinned[hwnd]["title"]:
                self.pinned[hwnd]["title"] = new_title
                changed = True
        if changed:
            self.refresh_list()
            self._sync_badge()

    def check_hotkey(self):
        pressed = (bool(GetAsyncKeyState(VK_CONTROL) & 0x8000)
                   and bool(GetAsyncKeyState(VK_SHIFT) & 0x8000)
                   and bool(GetAsyncKeyState(VK_MENU) & 0x8000)
                   and bool(GetAsyncKeyState(VK_T) & 0x8000))
        if pressed and not self.hotkey_prev:
            hwnd = GetAncestor(GetForegroundWindow(), GA_ROOT)
            if hwnd in self.pinned:
                self.unpin(hwnd)
            elif self.valid_target(hwnd):
                self.pin(hwnd)
        self.hotkey_prev = pressed

    def loop(self):
        if self.closed:
            return
        now = time.time()
        interval = max(200, self.interval_var.get()) / 1000.0
        if self.guard_on.get() and now - self.last_guard >= interval:
            self.guard()
            self.last_guard = now
        self.check_hotkey()
        if self.picking:
            self.check_pick()
        self.root.after(50, self.loop)


def main():
    if sys.platform != "win32":
        print("本工具仅支持 Windows 系统")
        return
    if SetProcessDPIAware:
        try:
            SetProcessDPIAware()
        except Exception:
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
