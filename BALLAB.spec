# -*- mode: python ; coding: utf-8 -*-
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

app_icon = os.path.join('assets', 'ballab_icon.icns' if sys.platform == 'darwin' else 'ballab_icon.ico')
icon_datas = [
    (os.path.join('assets', 'ballab_icon.ico'), 'assets'),
    (os.path.join('assets', 'ballab_icon.icns'), 'assets'),
    (os.path.join('assets', 'ballab_icon_master_1024_transparent.png'), 'assets'),
]
hiddenimports = ['pyqtgraph', 'pyqtgraph.graphicsItems.ViewBox.axisCtrlTemplate_pyqt6', 'pyqtgraph.graphicsItems.PlotItem.plotConfigTemplate_pyqt6', 'pyqtgraph.imageview.ImageViewTemplate_pyqt6', 'scipy.signal', 'scipy.fft', 'scipy.stats', 'scipy.linalg', 'qtm_rt', 'openpyxl']
hiddenimports += collect_submodules('qtm_rt')
hiddenimports += collect_submodules('pyqtgraph')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=icon_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='BALLAB',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=app_icon,
)
