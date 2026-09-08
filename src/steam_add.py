#!/usr/bin/env python3
# WProton - accesos directos de Steam
#
# Copyright (C) 2026  stshunz y colaboradores
#
# Este programa es software libre: puedes redistribuirlo y/o modificarlo bajo
# los terminos de la Licencia Publica General GNU (GPL), version 3 o
# posterior, publicada por la Free Software Foundation.
#
# Se distribuye SIN NINGUNA GARANTIA. Ver <https://www.gnu.org/licenses/>.
# WPROTON_STEAMADD_V1 - anade un acceso directo no-Steam a shortcuts.vdf
# uso: steam_add.py <shortcuts.vdf> <nombre> <exe> <startdir> <launchopts> <icono>
import sys, os, struct, zlib

VDF, NAME, EXE, STARTDIR, OPTS, ICON = sys.argv[1:7]

def parse(data):
    # parser minimo del VDF binario de shortcuts
    pos = [0]
    def u8():
        b = data[pos[0]]; pos[0] += 1; return b
    def cstr():
        end = data.index(b'\x00', pos[0])
        sres = data[pos[0]:end].decode('utf-8', 'replace')
        pos[0] = end + 1
        return sres
    def obj():
        out = {}
        while True:
            t = u8()
            if t == 0x08:
                return out
            k = cstr()
            if t == 0x00:
                out[k] = obj()
            elif t == 0x01:
                out[k] = cstr()
            elif t == 0x02:
                out[k] = struct.unpack('<I', data[pos[0]:pos[0]+4])[0]
                pos[0] += 4
            else:
                raise ValueError('tipo %d' % t)
    t = u8(); root_key = cstr()
    assert t == 0x00
    return {root_key: obj()}

def ser_obj(d):
    out = b''
    for k, v in d.items():
        kb = k.encode('utf-8') + b'\x00'
        if isinstance(v, dict):
            out += b'\x00' + kb + ser_obj(v) + b'\x08'
        elif isinstance(v, int):
            out += b'\x02' + kb + struct.pack('<I', v & 0xFFFFFFFF)
        else:
            out += b'\x01' + kb + str(v).encode('utf-8') + b'\x00'
    return out

def serialize(root):
    (k, v), = root.items()
    return b'\x00' + k.encode() + b'\x00' + ser_obj(v) + b'\x08\x08'

if os.path.isfile(VDF) and os.path.getsize(VDF) > 2:
    root = parse(open(VDF, 'rb').read())
else:
    root = {'shortcuts': {}}
key = 'shortcuts' if 'shortcuts' in root else list(root)[0]
sc = root[key]

# ya existe uno con el mismo LaunchOptions? -> actualizar en vez de duplicar
idx = None
for i, e in sc.items():
    if isinstance(e, dict) and e.get('LaunchOptions', '') == OPTS:
        idx = i
        break
if idx is None:
    nums = [int(i) for i in sc.keys() if i.isdigit()]
    idx = str(max(nums) + 1 if nums else 0)

appid = (zlib.crc32((EXE + NAME).encode()) | 0x80000000) & 0xFFFFFFFF
sc[idx] = {
    'appid': appid, 'AppName': NAME, 'Exe': '"%s"' % EXE,
    'StartDir': '"%s"' % STARTDIR, 'icon': ICON, 'ShortcutPath': '',
    'LaunchOptions': OPTS, 'IsHidden': 0, 'AllowDesktopConfig': 1,
    'AllowOverlay': 1, 'OpenVR': 0, 'Devkit': 0, 'DevkitGameID': '',
    'DevkitOverrideAppID': 0, 'LastPlayTime': 0, 'FlatpakAppID': '',
    'tags': {'0': 'WProton'},
}
open(VDF, 'wb').write(serialize(root))
print('OK idx=%s appid=%d' % (idx, appid))
