"""打包成 exe：python build.py  →  dist/DownloadMover/DownloadMover.exe 以及 dist/DownloadMover-win64.zip
需要先 pip install -r requirements.txt pyinstaller"""
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = 'DownloadMover'
DIST = os.path.join(HERE, 'dist')
WORK = os.path.join(HERE, 'build')
UNUSED = [
    r'PySide6\opengl32sw.dll', r'PySide6\Qt6Quick*.dll', r'PySide6\Qt6Qml*.dll', r'PySide6\Qt6Pdf*.dll',
    r'PySide6\Qt6Network.dll', r'PySide6\Qt6OpenGL.dll', r'PySide6\Qt6VirtualKeyboard.dll', r'PySide6\Qt6Svg.dll',
    r'PySide6\plugins\imageformats', r'PySide6\plugins\iconengines', r'PySide6\plugins\platforminputcontexts',
    r'PySide6\plugins\networkinformation', r'PySide6\plugins\tls', r'PySide6\translations',
    'libcrypto-*.dll', 'libssl-*.dll', '_ssl.pyd', '_hashlib.pyd',
]


def make_ico(path):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage, QPainter, QPainterPath, QColor, QFont
    from PySide6.QtCore import Qt, QRectF
    app = QApplication.instance() or QApplication([])
    img = QImage(256, 256, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    pp = QPainterPath()
    pp.addRoundedRect(QRectF(8, 8, 240, 240), 56, 56)
    p.fillPath(pp, QColor('#5B8DEF'))
    from PySide6.QtGui import QPolygonF
    from PySide6.QtCore import QPointF
    p.setPen(Qt.NoPen)
    p.setBrush(QColor('white'))   # 下载箭头，和程序里的托盘图标一样
    p.drawRect(QRectF(108, 48, 40, 80))
    p.drawPolygon(QPolygonF([QPointF(68, 120), QPointF(188, 120), QPointF(128, 184)]))
    p.drawRoundedRect(QRectF(56, 196, 144, 20), 8, 8)
    p.end()
    img.save(path)
    del app


def main():
    ico = os.path.join(HERE, 'mover.ico')
    if not os.path.exists(ico):
        make_ico(ico)
    subprocess.check_call([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed',
        '--name', NAME, '--icon', ico, '--exclude-module', 'tkinter',
        '--distpath', DIST, '--workpath', WORK, '--specpath', WORK,
        os.path.join(HERE, 'mover.py')])
    app = os.path.join(DIST, NAME)
    for pat in UNUSED:
        for p in glob.glob(os.path.join(app, '_internal', pat)):
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    zip_base = os.path.join(DIST, f'{NAME}-win64')
    shutil.make_archive(zip_base, 'zip', DIST, NAME)
    print('done:', zip_base + '.zip')


if __name__ == '__main__':
    main()
