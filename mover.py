# -*- coding: utf-8 -*-
"""下载整理助手：列出最新下载，手动多选移动；开启「自动存放」后新下载完成的文件自动移到目标文件夹。"""
import ctypes
import json
import os
import shutil
import stat
import sys
import time
from ctypes import wintypes
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QFileSystemWatcher, QRectF, QPointF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPainterPath, QFont, QAction, QPolygonF, QPen
from PySide6.QtWidgets import (QApplication, QWidget, QLabel, QPushButton, QCheckBox, QTreeWidget,
                               QTreeWidgetItem, QHBoxLayout, QVBoxLayout, QSplitter, QFileDialog,
                               QMessageBox, QSystemTrayIcon, QMenu, QAbstractItemView, QHeaderView)

APP = '下载整理助手'
# 浏览器下载中的临时文件，不处理
TEMP_EXT = {'.crdownload', '.part', '.partial', '.tmp', '.download', '.opdownload', '.!ut', '.bc!', '.td', '.xltd'}
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
OLD_STARTUP_LNK = os.path.join(os.environ.get('APPDATA', ''), r'Microsoft\Windows\Start Menu\Programs\Startup', f'{APP}.lnk')

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)


# ---------------------------------------------------------------- 文件位置

def data_dir():
    if getattr(sys, 'frozen', False):
        d = os.path.dirname(sys.executable)
        try:
            probe = os.path.join(d, f'.probe_{os.getpid()}')
            open(probe, 'w').close()
            os.remove(probe)
            return d
        except OSError:
            d = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'DownloadMover')
            os.makedirs(d, exist_ok=True)
            return d
    return os.path.dirname(os.path.abspath(__file__))


DATA = os.environ.get('DM_DATA_DIR') or data_dir()   # DM_DATA_DIR / DM_MUTEX 只给测试用
MUTEX_NAME = os.environ.get('DM_MUTEX') or 'Local\\DownloadMover_Single'
CONFIG_PATH = os.path.join(DATA, 'config.json')
HISTORY_PATH = os.path.join(DATA, 'history.json')


def downloads_dir():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as k:
            v, _ = winreg.QueryValueEx(k, '{374DE290-123F-4565-9164-39C4925E467B}')
            return os.path.expandvars(v)
    except OSError:
        return os.path.join(os.path.expanduser('~'), 'Downloads')


def read_json(path, default):
    try:
        with open(path, encoding='utf-8-sig') as f:   # 兼容旧版写的带 BOM 文件
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------- 文件工具

def fmt_size(n):
    if n >= 2 ** 30:
        return f'{n / 2 ** 30:.2f} GB'
    if n >= 2 ** 20:
        return f'{n / 2 ** 20:.1f} MB'
    if n >= 2 ** 10:
        return f'{n / 2 ** 10:.0f} KB'
    return f'{n} B'


def arrive_time(st):
    """文件到达下载文件夹的时间：创建时间和修改时间取较晚的。"""
    return max(st.st_ctime, st.st_mtime)


def should_skip(path, st=None):
    if os.path.splitext(path)[1].lower() in TEMP_EXT:
        return True
    try:
        st = st or os.stat(path)
    except OSError:
        return True
    return bool(st.st_file_attributes & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM))


def is_ready(path):
    """能用独占方式打开 = 浏览器已经写完、没人占用。"""
    kernel32.CreateFileW.restype = wintypes.HANDLE
    h = kernel32.CreateFileW(path, 0x80000000 | 0x40000000, 0, None, 3, 0, None)   # 读写、不共享、只打开已存在
    if h == wintypes.HANDLE(-1).value or h is None:
        return False
    kernel32.CloseHandle(h)
    return True


def move_unique(src, folder):
    """移动单个文件，重名时自动加 (1)(2)…"""
    stem, ext = os.path.splitext(os.path.basename(src))
    dest = os.path.join(folder, stem + ext)
    i = 1
    while os.path.exists(dest):
        dest = os.path.join(folder, f'{stem} ({i}){ext}')
        i += 1
    shutil.move(src, dest)   # 同一个盘是瞬间改名，跨盘会复制后删除
    return dest


def same_dir(a, b):
    return os.path.normcase(os.path.abspath(a)).rstrip('\\') == os.path.normcase(os.path.abspath(b)).rstrip('\\')


def trim_memory():
    try:
        ctypes.windll.psapi.EmptyWorkingSet(ctypes.windll.kernel32.GetCurrentProcess())
    except Exception:
        pass


def make_icon():
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    p.fillPath(path, QColor('#5B8DEF'))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor('white'))
    p.drawRect(QRectF(27, 12, 10, 20))
    p.drawPolygon(QPolygonF([QPointF(17, 30), QPointF(47, 30), QPointF(32, 46)]))
    p.drawRoundedRect(QRectF(14, 49, 36, 5), 2, 2)
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------- 开机自启（写注册表 Run，不用 PowerShell）

def launch_command():
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}" --tray'
    pyw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    return f'"{pyw}" "{os.path.abspath(__file__)}" --tray'


def autostart_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP)
            return True
    except OSError:
        return False


def set_autostart(on):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if on:
            winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, APP)
            except OSError:
                pass


def migrate_old_autostart():
    """旧 PowerShell 版用的是「启动」文件夹里的快捷方式，换成新版的注册表方式。"""
    if os.path.exists(OLD_STARTUP_LNK):
        try:
            os.remove(OLD_STARTUP_LNK)
            set_autostart(True)
        except OSError:
            pass


# ---------------------------------------------------------------- 主窗口

class CheckList(QTreeWidget):
    def __init__(self, headers, widths):
        super().__init__()
        self.setHeaderLabels(headers)
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        for i, w in enumerate(widths):
            self.setColumnWidth(i, w)
        self.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.header().setStretchLastSection(False)
        self.itemClicked.connect(self._toggle_on_click)

    def _toggle_on_click(self, item, col):
        if col != 0:   # 点整行任意位置都能勾选
            item.setCheckState(0, Qt.Unchecked if item.checkState(0) == Qt.Checked else Qt.Checked)

    def items(self):
        return [self.topLevelItem(i) for i in range(self.topLevelItemCount())]

    def checked(self):
        return [it for it in self.items() if it.checkState(0) == Qt.Checked]

    def set_all(self, on):
        for it in self.items():
            it.setCheckState(0, Qt.Checked if on else Qt.Unchecked)


class Mover(QWidget):
    def __init__(self, tray_only):
        super().__init__()
        self.exiting = False
        cfg = read_json(CONFIG_PATH, {})
        self.cfg = {'DownloadDir': downloads_dir(), 'TargetDir': '', 'Auto': False, 'ShowCount': 50}
        for k in self.cfg:
            if cfg.get(k) is not None:
                self.cfg[k] = cfg[k]
        hist = read_json(HISTORY_PATH, [])
        self.history = hist if isinstance(hist, list) else [hist]
        self.pending = {}        # path -> {size, since, added}
        self.undone = {}         # 刚撤销回来的文件 -> 时间，30 秒内不自动搬走
        self.known = set()       # 下载文件夹里已有的文件名
        self.syncing = False

        self.setWindowTitle(APP)
        self.icon = make_icon()
        self.setWindowIcon(self.icon)
        self.resize(1080, 480)
        self.build_ui()
        self.build_tray()

        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.tick)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.on_dir_changed)

        self.update_labels()
        self.start_watch()
        self.set_auto(bool(self.cfg['Auto']))
        if tray_only:
            trim_memory()
        else:
            self.show_main()

    # ---------- 界面 ----------
    def build_ui(self):
        def btn(text, fn):
            b = QPushButton(text)
            b.clicked.connect(fn)
            return b

        self.lbl_dl = QLabel()
        self.lbl_tg = QLabel()
        for l in (self.lbl_dl, self.lbl_tg):
            l.setTextInteractionFlags(Qt.TextSelectableByMouse)
        r1 = QHBoxLayout(); r1.addWidget(self.lbl_dl, 1)
        r1.addWidget(btn('打开', lambda: os.startfile(self.cfg['DownloadDir'])))
        r1.addWidget(btn('更改', self.change_download))
        r2 = QHBoxLayout(); r2.addWidget(self.lbl_tg, 1)
        r2.addWidget(btn('打开', self.open_target))
        r2.addWidget(btn('更改', self.pick_target))
        self.chk_auto = QCheckBox('自动存放（开启后，新下载完成的文件会自动移到目标文件夹）')
        self.chk_auto.toggled.connect(self.set_auto)
        self.list = CheckList(['名称', '大小', '下载时间'], [360, 90, 140])
        self.status = QLabel()
        r3 = QHBoxLayout()
        r3.addWidget(btn('刷新', lambda: (self.refresh_list(), self.status.setText('已刷新'))))
        r3.addWidget(btn('全选', lambda: self.list.set_all(True)))
        r3.addWidget(btn('全不选', lambda: self.list.set_all(False)))
        r3.addWidget(self.status, 1)
        mv = btn('移动勾选的文件', self.move_checked)
        mv.setMinimumWidth(130)
        r3.addWidget(mv)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(4, 4, 4, 4)
        for x in (r1, r2):
            lv.addLayout(x)
        lv.addWidget(self.chk_auto)
        lv.addWidget(self.list, 1)
        lv.addLayout(r3)

        self.hist = CheckList(['名称', '方式', '时间'], [190, 50, 100])
        r4 = QHBoxLayout()
        r4.addWidget(btn('撤销勾选的', self.undo_checked))
        r4.addWidget(btn('打开所在位置', self.reveal_record))
        r4.addWidget(btn('清空记录', self.clear_history))
        r4.addStretch()
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 4, 4, 4)
        rv.addWidget(QLabel('已完成（勾选后点「撤销」可移回下载文件夹）'))
        rv.addWidget(self.hist, 1)
        rv.addLayout(r4)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([690, 390])
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.addWidget(split)

    def build_tray(self):
        self.tray = QSystemTrayIcon(self.icon, self)
        menu = QMenu()
        menu.addAction('打开主界面', self.show_main)
        self.mi_auto = QAction('自动存放', self, checkable=True)
        self.mi_auto.toggled.connect(self.set_auto)
        menu.addAction(self.mi_auto)
        self.mi_boot = QAction('开机自动启动', self, checkable=True)
        self.mi_boot.setChecked(autostart_enabled())
        self.mi_boot.toggled.connect(set_autostart)
        menu.addAction(self.mi_boot)
        menu.addSeparator()
        menu.addAction('退出', self.quit)
        self.tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.show_main() if r == QSystemTrayIcon.DoubleClick else None)
        self.tray.show()

    def update_labels(self):
        self.lbl_dl.setText('下载文件夹：' + self.cfg['DownloadDir'])
        self.lbl_tg.setText('目标文件夹：' + (self.cfg['TargetDir'] or '（还没选）'))

    def show_main(self):
        self.refresh_list()
        self.refresh_history()
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def save_config(self):
        write_json(CONFIG_PATH, self.cfg)

    def save_history(self):
        write_json(HISTORY_PATH, self.history)

    # ---------- 列表 ----------
    def scan(self):
        d = self.cfg['DownloadDir']
        out = []
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if not e.is_file():
                            continue
                        st = e.stat()
                    except OSError:
                        continue
                    if not should_skip(e.path, st):
                        out.append((e.path, st))
        except OSError:
            pass
        return out

    def refresh_list(self):
        checked = {it.data(0, Qt.UserRole) for it in self.list.checked()}
        files = sorted(self.scan(), key=lambda x: arrive_time(x[1]), reverse=True)[:int(self.cfg['ShowCount'])]
        self.list.clear()
        for p, st in files:
            it = QTreeWidgetItem([os.path.basename(p), fmt_size(st.st_size),
                                  datetime.fromtimestamp(arrive_time(st)).strftime('%Y-%m-%d %H:%M')])
            it.setData(0, Qt.UserRole, p)
            it.setCheckState(0, Qt.Checked if p in checked else Qt.Unchecked)
            it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            self.list.addTopLevelItem(it)

    def refresh_history(self):
        self.hist.clear()
        for i, r in enumerate(self.history):
            it = QTreeWidgetItem([r.get('Name', ''), r.get('Mode', ''), r.get('Time', '')])
            it.setData(0, Qt.UserRole, i)
            it.setCheckState(0, Qt.Unchecked)
            tip = f"从：{r.get('Src', '')}\n到：{r.get('Dest', '')}"
            for c in range(3):
                it.setToolTip(c, tip)
            self.hist.addTopLevelItem(it)

    # ---------- 文件夹设置 ----------
    def pick_folder(self, title, start):
        return QFileDialog.getExistingDirectory(self, title, start if start and os.path.isdir(start) else '')

    def pick_target(self):
        p = self.pick_folder('选择要把下载文件放到哪个文件夹', self.cfg['TargetDir'])
        if not p:
            return False
        p = os.path.normpath(p)
        if same_dir(p, self.cfg['DownloadDir']):
            QMessageBox.information(self, APP, '目标文件夹不能和下载文件夹是同一个。')
            return False
        self.cfg['TargetDir'] = p
        self.save_config()
        self.update_labels()
        return True

    def ensure_target(self):
        t = self.cfg['TargetDir']
        return bool(t and os.path.isdir(t)) or self.pick_target()

    def open_target(self):
        if self.ensure_target():
            os.startfile(self.cfg['TargetDir'])

    def change_download(self):
        p = self.pick_folder('选择浏览器的下载文件夹', self.cfg['DownloadDir'])
        if not p:
            return
        p = os.path.normpath(p)
        if self.cfg['TargetDir'] and same_dir(p, self.cfg['TargetDir']):
            QMessageBox.information(self, APP, '下载文件夹不能和目标文件夹是同一个。')
            return
        self.cfg['DownloadDir'] = p
        self.save_config()
        self.update_labels()
        self.start_watch()
        self.refresh_list()

    # ---------- 移动 / 撤销 ----------
    def move_one(self, src, mode):
        dest = move_unique(src, self.cfg['TargetDir'])
        self.history.insert(0, {'Name': os.path.basename(dest), 'Src': src, 'Dest': dest, 'Mode': mode,
                                'Time': datetime.now().strftime('%m-%d %H:%M')})
        del self.history[200:]
        self.save_history()
        if self.isVisible():
            self.refresh_history()
        return dest

    def move_checked(self):
        items = self.list.checked()
        if not items:
            self.status.setText('先勾选要移动的文件')
            return
        if not self.ensure_target():
            return
        ok, fail = 0, 0
        for it in items:
            try:
                self.move_one(it.data(0, Qt.UserRole), '手动')
                ok += 1
            except OSError:
                fail += 1
        self.refresh_list()
        self.status.setText(f'已移动 {ok} 个' + (f'，{fail} 个失败（可能正在被使用）' if fail else ''))

    def undo_checked(self):
        idx = sorted((it.data(0, Qt.UserRole) for it in self.hist.checked()), reverse=True)
        if not idx:
            self.status.setText('先在右边勾选要撤销的文件')
            return
        ok, fail = 0, []
        for i in idx:
            r = self.history[i]
            if not os.path.isfile(r['Dest']):
                fail.append(f"{r['Name']}（目标文件夹里已经找不到它）")
                del self.history[i]
                continue
            try:
                folder = os.path.dirname(r['Src'])
                os.makedirs(folder, exist_ok=True)
                back = move_unique(r['Dest'], folder)
                self.undone[os.path.normcase(back)] = time.time()
                del self.history[i]
                ok += 1
            except OSError as e:
                fail.append(f"{r['Name']}（{e.strerror or e}）")
        self.save_history()
        self.refresh_history()
        self.refresh_list()
        self.status.setText(f'已撤销 {ok} 个' + (f'，{len(fail)} 个失败' if fail else ''))
        if fail:
            QMessageBox.information(self, APP, '以下文件撤销失败：\n' + '\n'.join(fail))

    def reveal_record(self):
        it = self.hist.currentItem() or next(iter(self.hist.checked()), None)
        if not it:
            self.status.setText('先在右边点选一个文件')
            return
        dest = self.history[it.data(0, Qt.UserRole)]['Dest']
        if os.path.isfile(dest):
            import subprocess
            subprocess.Popen(['explorer', '/select,', os.path.normpath(dest)])
        else:
            self.status.setText('这个文件已经不在目标文件夹里了')

    def clear_history(self):
        if QMessageBox.question(self, APP, '清空后就不能再撤销这些记录了（文件本身不会动）。确定清空？') == QMessageBox.Yes:
            self.history = []
            self.save_history()
            self.refresh_history()

    # ---------- 自动存放 ----------
    def set_auto(self, on):
        if self.syncing:
            return
        if on and not self.ensure_target():
            on = False
        self.syncing = True
        self.chk_auto.setChecked(on)
        self.mi_auto.setChecked(on)
        self.syncing = False
        self.cfg['Auto'] = on
        self.save_config()
        self.tray.setToolTip(f"{APP}（自动存放：{'开' if on else '关'}）")
        self.status.setText('自动存放已开启' if on else '自动存放已关闭')

    def start_watch(self):
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        d = self.cfg['DownloadDir']
        self.known = {os.path.normcase(p) for p, _ in self.scan()} if os.path.isdir(d) else set()
        if os.path.isdir(d):
            self.watcher.addPath(d)

    def on_dir_changed(self, _):
        now = {os.path.normcase(p): p for p, _ in self.scan()}
        for key in set(now) - self.known:      # 新出现的文件（包括 .crdownload 改名成正式名）
            self.add_pending(now[key])
        self.known = set(now)
        if self.isVisible():
            self.refresh_list()

    def add_pending(self, p):
        if not self.cfg['Auto'] or not os.path.isfile(p) or should_skip(p):
            return
        t = self.undone.get(os.path.normcase(p))
        if t and time.time() - t < 30:   # 刚撤销回来的
            return
        now = time.time()
        self.pending[p] = {'size': -1, 'since': now, 'added': now}
        self.timer.start()

    def tick(self):
        """新文件确认下载完（大小 2 秒不变、没被占用）才移动。"""
        for p in list(self.pending):
            info = self.pending[p]
            if not self.cfg['Auto'] or not os.path.isfile(p):
                del self.pending[p]
                continue
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            if size != info['size']:
                info['size'], info['since'] = size, time.time()
                continue
            if size == 0:   # 0 字节可能是浏览器占位文件，等 10 分钟还是空的就不管了
                if time.time() - info['added'] > 600:
                    del self.pending[p]
                continue
            if time.time() - info['since'] < 2 or not is_ready(p):
                continue
            del self.pending[p]
            try:
                d = self.move_one(p, '自动')
                self.tray.showMessage('已自动存放', os.path.basename(d), QSystemTrayIcon.Information, 2000)
            except OSError as e:
                self.tray.showMessage('自动存放失败', f'{os.path.basename(p)}\n{e.strerror or e}',
                                      QSystemTrayIcon.Warning, 3000)
        if not self.pending:
            self.timer.stop()
        if self.isVisible():
            self.refresh_list()

    # ---------- 关闭 ----------
    def closeEvent(self, e):
        if self.exiting:
            e.accept()
            return
        e.ignore()   # 点右上角 X 只是缩到托盘，不退出
        self.hide()
        self.tray.showMessage(APP, '已缩到托盘继续运行，右键托盘图标可退出', QSystemTrayIcon.Information, 1500)
        trim_memory()

    def quit(self):
        self.exiting = True
        self.tray.hide()
        QApplication.quit()


def single_instance():
    """和旧 PowerShell 版用同一个互斥名，两个版本也不会同时运行。"""
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    h = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == 183:   # ERROR_ALREADY_EXISTS
        return None
    return h


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont('Microsoft YaHei UI', 9))
    app.setStyle('Fusion')
    app.setQuitOnLastWindowClosed(False)
    mutex = single_instance()
    if mutex is None:
        QMessageBox.information(None, APP, '下载整理助手已经在运行了，请看屏幕右下角托盘图标。')
        return
    migrate_old_autostart()
    w = Mover(tray_only='--tray' in sys.argv[1:])
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
