"""下载整理助手测试（用临时文件夹和单独的互斥名，不碰真实设置）：python test_mover.py"""
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = tempfile.mkdtemp(prefix='dm_test_')
DL = os.path.join(ROOT, 'dl')
TG = os.path.join(ROOT, 'target')
DATA = os.path.join(ROOT, 'data')
for d in (DL, TG, DATA):
    os.makedirs(d)
os.environ['DM_DATA_DIR'] = DATA
os.environ['DM_MUTEX'] = 'Local\\DownloadMover_Test'
# 旧版格式的设置（带 BOM）
with open(os.path.join(DATA, 'config.json'), 'w', encoding='utf-8-sig') as f:
    json.dump({'DownloadDir': DL, 'TargetDir': TG, 'Auto': True, 'ShowCount': 50}, f)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
import mover  # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: None)


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def wait(cond, sec, label):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        if cond():
            return
        time.sleep(0.05)
    raise SystemExit('超时：' + label)


try:
    # 下载前已有的文件不会被自动搬
    open(os.path.join(DL, 'old.txt'), 'w').write('old')
    w = mover.Mover(tray_only=False)
    assert w.cfg['Auto'] and w.cfg['TargetDir'] == TG, '读取旧版设置失败'
    print('读取旧版 config.json：OK')

    # 模拟浏览器：先写 .crdownload 并持续变大，再改成正式名
    part = os.path.join(DL, 'movie.mp4.crdownload')
    with open(part, 'wb') as f:
        for _ in range(5):
            f.write(b'x' * 200_000)
            f.flush()
            pump(0.4)
    assert not os.listdir(TG), '临时文件不该被搬'
    os.rename(part, os.path.join(DL, 'movie.mp4'))
    wait(lambda: os.path.exists(os.path.join(TG, 'movie.mp4')), 15, '自动存放')
    print('下载完成后自动存放：OK，目标文件夹 =', os.listdir(TG))
    assert os.path.exists(os.path.join(DL, 'old.txt')), '旧文件不该被搬'

    # 被占用（写着没关）的文件要等释放后才搬
    busy = open(os.path.join(DL, 'busy.zip'), 'wb')
    busy.write(b'y' * 1000)
    busy.flush()
    pump(4)
    assert os.path.exists(os.path.join(DL, 'busy.zip')), '占用中的文件不该被搬'
    busy.close()
    wait(lambda: os.path.exists(os.path.join(TG, 'busy.zip')), 10, '释放后自动存放')
    print('占用中先等待、释放后再搬：OK')

    # 同名自动加 (1)
    open(os.path.join(DL, 'movie.mp4'), 'w').write('again')
    wait(lambda: os.path.exists(os.path.join(TG, 'movie (1).mp4')), 10, '重名')
    print('重名自动改成 movie (1).mp4：OK')

    # 手动移动 + 撤销
    w.set_auto(False)
    open(os.path.join(DL, 'a.pdf'), 'w').write('a')
    w.refresh_list()
    for it in w.list.items():
        if it.text(0) == 'a.pdf':
            it.setCheckState(0, mover.Qt.Checked)
    w.move_checked()
    assert os.path.exists(os.path.join(TG, 'a.pdf'))
    w.refresh_history()
    w.hist.items()[0].setCheckState(0, mover.Qt.Checked)
    w.undo_checked()
    assert os.path.exists(os.path.join(DL, 'a.pdf')) and not os.path.exists(os.path.join(TG, 'a.pdf'))
    print('手动移动、撤销：OK')

    hist = json.load(open(os.path.join(DATA, 'history.json'), encoding='utf-8'))
    print('history.json 记录数', len(hist), [h['Mode'] for h in hist])
    w.quit()
    print('全部通过')
finally:
    shutil.rmtree(ROOT, ignore_errors=True)
