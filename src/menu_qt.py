#!/usr/bin/env python3
# WProton - menus con mando (Qt)
#
# Copyright (C) 2026  stshunz y colaboradores
#
# Este programa es software libre: puedes redistribuirlo y/o modificarlo bajo
# los terminos de la Licencia Publica General GNU (GPL), version 3 o
# posterior, publicada por la Free Software Foundation.
#
# Se distribuye SIN NINGUNA GARANTIA. Ver <https://www.gnu.org/licenses/>.
#
# ---------------------------------------------------------------------------
# PORTE DE menu_pygame.py A QT.  MISMO CONTRATO, OTRO MOTOR.
#
# Lo que NO cambia (a proposito, para poder cambiar de motor sin tocar bash):
#   * los modos:  list / check / browse / grid / text / progress / canvas
#   * el protocolo de servidor:  req + req.ready -> resp, y stop para parar
#   * los codigos de salida:  0 elegido, 1 cancelado, 2 se perdio la pantalla
#   * el fichero de salida y su marca <salida>.done
#   * el hilo de evdev: el mando se lee de /dev/input, SIN foco de ventana
#
# Lo que SI cambia:
#   * no hay bucle a 60 fps: Qt repinta cuando hay algo que repintar. El
#     temporizador solo corre en las pantallas animadas (reposo, progreso).
#   * el dibujo es QPainter en vez de pygame.draw. Las funciones se llaman
#     igual para que comparar los dos ficheros siga siendo facil.
#   * el video no se elige a mano: Qt acepta una LISTA de plataformas en
#     QT_QPA_PLATFORM ("xcb;wayland") y se queda con la primera que arranca.
#     Ojo: si ninguna vale, Qt aborta el proceso y eso NO se puede capturar
#     desde Python -> por eso se sondea antes, en un proceso aparte.
# ---------------------------------------------------------------------------
import json
import math
import os
import re
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
LIBS = os.path.join(BASE, 'libs_py%d.%d' % sys.version_info[:2])
if os.path.isdir(LIBS):
    sys.path.insert(0, LIBS)

# ---------------------------------------------------------------------------
# 0. ELECCION DE PLATAFORMA (lo que antes era DRIVER_ORDER de SDL)
#
# SDL probaba drivers uno a uno desde Python porque pygame.display.init()
# lanza excepcion y se puede reintentar. Qt no: si el plugin de plataforma no
# carga, la libreria llama a abort() y el proceso muere sin traceback. Asi que
# el sondeo se hace lanzando un python de usar y tirar con cada candidata; la
# que sobreviva se anota en un marcador y ya no se vuelve a sondear.
# ---------------------------------------------------------------------------
IS_GAMESCOPE_SESS = bool(os.environ.get('GAMESCOPE_WAYLAND_DISPLAY')) or \
    os.environ.get('XDG_CURRENT_DESKTOP') == 'gamescope'
_gsw = os.environ.get('GAMESCOPE_WAYLAND_DISPLAY')
if _gsw and os.environ.get('WP_FORCE_WAYLAND'):
    os.environ['WAYLAND_DISPLAY'] = _gsw
    sys.stderr.write('menu_qt: sesion gamescope, WAYLAND_DISPLAY=%s\n' % _gsw)

# El sondeo se cachea POR MODO: cuando WProton reintenta forzando
# wayland no puede reusarse la plataforma que acaba de fallar.
PLAT_MARK = os.path.join(
    BASE, '.menu_qt_plat' + ('_w' if os.environ.get('WP_FORCE_WAYLAND') else ''))


def candidatas():
    if os.environ.get('QT_QPA_PLATFORM'):
        return [os.environ['QT_QPA_PLATFORM']]
    if IS_GAMESCOPE_SESS and os.environ.get('WP_FORCE_WAYLAND'):
        return ['wayland', 'xcb']
    if IS_GAMESCOPE_SESS:
        # Igual que en el motor viejo: en el modo Juego de SteamOS lo que se
        # VE es XWayland. Wayland nativo dibuja pero gamescope no lo muestra.
        return ['xcb', 'wayland']
    if os.environ.get('DISPLAY'):
        return ['xcb', 'wayland']
    return ['wayland', 'xcb']


def sondear_plataforma():
    # Devuelve el nombre de la plataforma que arranca, o '' si ninguna.
    try:
        with open(PLAT_MARK, encoding='utf-8') as fh:
            guardada = fh.read().strip()
        if guardada:
            return guardada
    except OSError:
        pass
    prueba = ('import sys;'
              'from %s.QtWidgets import QApplication;'
              'QApplication([]);sys.exit(0)' % BINDING_NOMBRE)
    for plat in candidatas():
        env = dict(os.environ)
        env['QT_QPA_PLATFORM'] = plat
        env['PYTHONPATH'] = LIBS + os.pathsep + env.get('PYTHONPATH', '')
        try:
            rc = subprocess.call([sys.executable, '-c', prueba], env=env,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, timeout=20)
        except Exception:
            rc = 1
        if rc == 0:
            try:
                with open(PLAT_MARK, 'w', encoding='utf-8') as fh:
                    fh.write(plat)
            except OSError:
                pass
            sys.stderr.write('menu_qt: plataforma %s\n' % plat)
            return plat
        sys.stderr.write('menu_qt: la plataforma %s no arranca\n' % plat)
    return ''


# ---------------------------------------------------------------------------
# 1. ENLACE CON QT: PySide6 (LGPL, oficial de Qt) y PyQt6 como respaldo.
#
# Se usan los nombres LARGOS de los enumerados (Qt.Key.Key_Up, y no Qt.Key_Up)
# porque PyQt6 solo acepta esos; PySide6 acepta ambos. Asi el mismo fichero
# vale con las dos librerias y quien empaquete elige la que tenga a mano.
# ---------------------------------------------------------------------------
BINDING_NOMBRE = ''
try:
    from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
    BINDING_NOMBRE = 'PySide6'
except ImportError:
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: F401
        BINDING_NOMBRE = 'PyQt6'
    except ImportError:
        sys.stderr.write('menu_qt: no hay PySide6 ni PyQt6 (instala con --setup)\n')
        sys.exit(3)

if BINDING_NOMBRE == 'PySide6':
    Signal = QtCore.Signal
else:
    Signal = QtCore.pyqtSignal

Qt = QtCore.Qt
QRect = QtCore.QRect
QRectF = QtCore.QRectF
QPoint = QtCore.QPoint
QColor = QtGui.QColor
QFont = QtGui.QFont
QPainter = QtGui.QPainter
QPixmap = QtGui.QPixmap

K_UP = Qt.Key.Key_Up
K_DOWN = Qt.Key.Key_Down
K_LEFT = Qt.Key.Key_Left
K_RIGHT = Qt.Key.Key_Right
K_RETURN = Qt.Key.Key_Return
K_ESCAPE = Qt.Key.Key_Escape
K_SPACE = Qt.Key.Key_Space
K_TAB = Qt.Key.Key_Tab
K_F1 = Qt.Key.Key_F1
K_F2 = Qt.Key.Key_F2
K_F3 = Qt.Key.Key_F3
K_F11 = Qt.Key.Key_F11
K_F12 = Qt.Key.Key_F12
K_PGUP = Qt.Key.Key_PageUp
K_PGDN = Qt.Key.Key_PageDown
K_BACKSPACE = Qt.Key.Key_Backspace

# ---------------------------------------------------------------------------
# 2. TEMAS (identicos a los del motor viejo: mismo aspecto, otro pincel)
# ---------------------------------------------------------------------------
THEMES = {
    'clasico': {
        'bg': (24, 26, 32), 'bg2': (24, 26, 32),
        'fg': (225, 228, 235), 'dim': (140, 145, 155),
        'sel_bg': (38, 92, 170), 'sel_fg': (255, 255, 255),
        'acc': (120, 200, 130), 'dir': (150, 190, 240),
        'warn': (230, 180, 90), 'kb_bg': (34, 37, 46),
        'panel': None, 'border': (60, 64, 74), 'card': (44, 48, 60),
        'radius': 6, 'pill': False, 'rule': True, 'glow': False,
        'layout': 'simple', 'row': 40,
    },
    'moderno': {
        'bg': (14, 17, 26), 'bg2': (24, 30, 46),
        'fg': (232, 240, 252), 'dim': (128, 142, 168),
        'sel_bg': (26, 60, 82), 'sel_fg': (150, 240, 255),
        'acc': (56, 214, 224), 'dir': (124, 200, 255),
        'warn': (250, 196, 106), 'kb_bg': (20, 26, 40),
        'panel': (22, 28, 42), 'border': (44, 60, 88), 'card': (26, 33, 50),
        'radius': 12, 'pill': True, 'rule': False, 'glow': True,
        'layout': 'panel', 'row': 48,
        'acc2': (168, 120, 255), 'ok': (86, 226, 160),
        'btn': True, 'labelcolor': True, 'shape': 'notch',
    },
    'arcade': {
        'bg': (12, 4, 30), 'bg2': (58, 12, 74),
        'fg': (255, 244, 252), 'dim': (170, 130, 200),
        'sel_bg': (92, 12, 96), 'sel_fg': (255, 255, 255),
        'acc': (255, 46, 147), 'dir': (94, 234, 255),
        'warn': (255, 214, 84), 'kb_bg': (24, 8, 44),
        'panel': (26, 8, 48), 'border': (120, 40, 140), 'card': (36, 12, 60),
        'radius': 0, 'pill': True, 'rule': False, 'glow': True,
        'layout': 'arcade', 'row': 48,
        'acc2': (94, 234, 255), 'ok': (120, 255, 170),
        'scan': True, 'gridbg': True, 'brackets': True,
        'marker': True, 'numbered': True, 'shadow': True,
        'btn': True, 'labelcolor': True, 'shape': 'rect',
    },
    # ------------------------------------------------------------------
    # CRISTAL: el tema que solo existe con el motor Qt.
    #
    # No es "moderno con otros colores". Se apoya en cosas que QPainter hace
    # y el motor viejo no puede sin pintar pixel a pixel:
    #   * orbes de color (degradado radial) y viñeta en los bordes;
    #   * paneles TRANSLUCIDOS de verdad, con el fondo asomando por debajo;
    #   * un brillo conico que gira por el borde de la fila elegida;
    #   * el texto convertido en TRAZO (QPainterPath) para poder rodearlo de
    #     un halo aditivo, en vez de calcarlo desplazado como sombra.
    # Si se elige con el motor pygame, ese no lo conoce y usa "moderno": el
    # ajuste no se pierde y no hay que avisar de nada.
    # ------------------------------------------------------------------
    'cristal': {
        'bg': (10, 14, 24), 'bg2': (22, 28, 48),
        'fg': (238, 244, 255), 'dim': (146, 158, 184),
        'sel_bg': (40, 62, 104), 'sel_fg': (255, 255, 255),
        'acc': (122, 198, 255), 'dir': (168, 190, 255),
        'warn': (255, 198, 120), 'kb_bg': (18, 24, 40),
        'panel': (30, 40, 64), 'border': (96, 124, 176), 'card': (36, 48, 76),
        'radius': 18, 'pill': True, 'rule': False, 'glow': True,
        'layout': 'panel', 'row': 52,
        'acc2': (196, 160, 255), 'ok': (128, 232, 176),
        'btn': True, 'labelcolor': True, 'shape': 'pill',
        # lo propio de este tema
        'glass': True,      # paneles y filas translucidos
        'orbes': True,      # dos focos de color en el fondo
        'vineta': True,     # oscurecido suave en los bordes
        'sheen': True,      # brillo conico giratorio en la seleccion
        'pathtext': True,   # marca y reposo como trazo, con halo
        'tracking': True,   # letra algo mas espaciada en los titulos
        # LAS CARATULAS Y LA FICHA, COMO EN MODERNO.
        #
        # El vidrio esta bien para la lista, pero detras de una portada y de
        # sus datos estorba: el panel translucido deja pasar los orbes y el
        # texto pierde contraste, y la capsula de la rejilla compite con la
        # propia imagen en vez de enmarcarla. Ahi manda la caratula, no el
        # tema, asi que esa parte usa el panel opaco y la seleccion de
        # moderno.
        'media': 'moderno',
    },
}
THEME_NAME = os.environ.get('WP_THEME', 'moderno')
if THEME_NAME not in THEMES:
    THEME_NAME = 'moderno'
TH = THEMES[THEME_NAME]


def C(rgb, alpha=255):
    # atajo: tupla del tema -> QColor
    return QColor(rgb[0], rgb[1], rgb[2], alpha)


BG, FG, HIBG = TH['bg'], TH['fg'], TH['sel_bg']
DIM, ACC, DIRC = TH['dim'], TH['acc'], TH['dir']
WARN, KBBG, RAD = TH['warn'], TH['kb_bg'], TH['radius']

# ---------------------------------------------------------------------------
# 3. IDIOMA (mismo lang/<codigo>.json que el script)
# ---------------------------------------------------------------------------
LANG = os.environ.get('WP_LANG', 'es')
_LANGMAP = {}
if LANG != 'es':
    try:
        with open(os.path.join(os.path.dirname(BASE), 'lang', LANG + '.json'),
                  encoding='utf-8') as _fh:
            _LANGMAP = {k: v for k, v in json.load(_fh).items()
                        if isinstance(v, str) and v and k != '__version__'}
    except Exception:
        _LANGMAP = {}


def L(es, en=None):
    if LANG == 'es':
        return es
    if es in _LANGMAP:
        return _LANGMAP[es]
    return en if en is not None else es


ACTION_X = os.environ.get('WP_ACTION_X') == '1'
# Escala de letra: 1.0 normal, 1.25 grande, 1.5 muy grande (WP_FONT_SCALE).
# Pensada sobre todo para consolas portatiles, donde 24 px se leen mal.
try:
    FSCALE = float(os.environ.get('WP_FONT_SCALE', '1') or '1')
except ValueError:
    FSCALE = 1.0
FSCALE = max(0.8, min(2.0, FSCALE))
try:
    GRID_COLS = int(os.environ.get('WP_GRID_COLS', '0') or '0')
except ValueError:
    GRID_COLS = 0


def FS(px):
    return max(14, int(px * FSCALE))


# Proporcion de la caratula: alto = ancho * ASPECTO.
#   1.5  -> vertical, 2:3, la clasica de las tiendas
#   0.47 -> panoramica, tipo cabecera de Steam (920x430)
#   0.75 -> 4:3, para colecciones de caratulas cuadradas (640x480)
# Cuanto mas ancha, menos caben por fila pero mas grandes se ven.
#
# Viaja en CADA peticion, no solo al arrancar: el proceso de menus es
# persistente, asi que si se leyera una sola vez, cambiar de vista dejaria las
# casillas con la forma anterior y las verticales saldrian en recuadros
# anchos.
ASPECTOS = {'1': 0.47, 'wide': 0.47, '43': 0.75, 'vertical': 1.5, '': 1.5}

# LOS DOS COLORES DE LA MARCA NO DEPENDEN DEL TEMA.
#
# "PROTON" se pintaba con el acento del tema activo, asi que la palabra
# cambiaba de color en cada uno: verde en clasico, rosa en arcade, azul en
# cristal. Pero el morado y el cian de moderno son ya la seña de la marca, y
# una marca que cambia de color no es una marca. El tema sigue mandando en
# todo lo demas -incluida la sombra del arcade, que es suya-, pero estas dos
# letras se quedan quietas.
MORADO_W = (150, 90, 230)     # el morado de la W
CIAN_PROTON = (56, 214, 224)  # el cian de moderno, para "PROTON"
IDLE_PASOS = 10             # pasos de zoom de la onda del reposo
KB_H = 200                  # alto que ocupa el teclado en pantalla


def acortar(p, n=82):
    return p if len(p) <= n else '\u2026' + p[-(n - 1):]

DEV = os.environ.get('WP_DEV') == '1'
CAPT_DIR = os.environ.get('WP_CAPT_DIR', '')
WIN_MARK = os.path.join(BASE, '.menu_windowed')
FULLSCREEN = os.environ.get('WP_MENU_FS') == '1' or not os.path.isfile(WIN_MARK)

# .sh: los juegos de LINUX se lanzan con su propio script. Sin esto no
# aparecian en el navegador y no habia forma de elegirlos.
EXTS_NORMAL = ('.wsquashfs', '.squashfs', '.dwarfs', '.zip', '.7z', '.rar',
               '.001', '.z01', '.exe', '.bat', '.cmd', '.wtgz', '.sh',
               '.appimage', '.AppImage')
# Al IMPORTAR no se enseñan los ya empaquetados (.wsquashfs, .dwarfs): esos ya
# salen solos en la biblioteca y verlos aqui solo confunde.
EXTS_IMPORTAR = ('.zip', '.7z', '.rar', '.001', '.z01',
                 '.exe', '.bat', '.cmd', '.wtgz', '.sh',
                 '.appimage', '.AppImage')

# ---------------------------------------------------------------------------
# 4. LECTURA DE DATOS
#
# Todo esto es python puro: viene tal cual del motor viejo. No depende del
# motor grafico y por eso no habia razon para tocarlo. Si algun dia hay un
# tercer motor, este bloque se saca a un modulo y se comparte.
# ---------------------------------------------------------------------------


def leer_ficha(ruta):
    # Saca del JSON de la tienda de Steam lo que cabe en el panel
    if not ruta or not os.path.isfile(ruta):
        return {}
    try:
        with open(ruta, encoding='utf-8') as fh:
            d = json.load(fh)
        d = list(d.values())[0].get('data', {})
    except Exception:
        return {}

    def lista(clave, tope=2):
        v = d.get(clave) or []
        if isinstance(v, list):
            v = [x.get('description', '') if isinstance(x, dict) else str(x)
                 for x in v[:tope]]
            return ', '.join(x for x in v if x)
        return str(v)

    fecha = (d.get('release_date') or {}).get('date', '') or ''
    ano = ''
    for trozo in str(fecha).replace(',', ' ').split():
        if trozo.isdigit() and len(trozo) == 4:
            ano = trozo
    # La sinopsis viene con etiquetas HTML y entidades: la ficha de Steam es
    # una pagina web, no texto plano.
    sinopsis = d.get('short_description') or ''
    if sinopsis:
        sinopsis = re.sub(r'<[^>]+>', ' ', sinopsis)
        for ent, car in (('&amp;', '&'), ('&quot;', '"'), ('&#39;', "'"),
                         ('&lt;', '<'), ('&gt;', '>'), ('&nbsp;', ' ')):
            sinopsis = sinopsis.replace(ent, car)
        sinopsis = ' '.join(sinopsis.split())
    return {'nombre': d.get('name', ''),
            'ano': ano,
            'dev': lista('developers'),
            'edi': lista('publishers'),
            'gen': lista('genres'),
            'nota': str((d.get('metacritic') or {}).get('score', '') or ''),
            'sinopsis': sinopsis}


def leer_rawg(ruta):
    # La ficha de RAWG, la fuente secundaria. Formato plano, lo escribe
    # rawg_completar en wproton.sh: ya viene con las claves del panel.
    if not ruta or not os.path.isfile(ruta):
        return {}
    try:
        with open(ruta, encoding='utf-8') as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in d.items() if v}


def leer_duracion(ruta):
    # "21.5|44" -> texto para el panel. HowLongToBeat da horas con decimales,
    # y "18.69 h" ni se lee bien ni casa con la fila de "Tiempo" de debajo,
    # que va en "4 h 20 min": se enseña igual que aquella.
    if not ruta or not os.path.isfile(ruta):
        return ''
    try:
        with open(ruta, encoding='utf-8') as fh:
            partes = fh.read().strip().split('|')
    except Exception:
        return ''
    try:
        hist = float(partes[0]) if partes and partes[0] else 0
    except ValueError:
        hist = 0
    if not hist:
        return ''
    horas = int(hist)
    minutos = int(round((hist - horas) * 60))
    if minutos == 60:
        horas, minutos = horas + 1, 0
    if horas and minutos:
        return '%d h %d min' % (horas, minutos)
    if horas:
        return '%d h' % horas
    return '%d min' % minutos


def fmt_horas(seg):
    try:
        seg = int(seg)
    except Exception:
        return ''
    if seg < 60:
        return ''
    if seg < 3600:
        return '%d min' % (seg // 60)
    return '%d h %d min' % (seg // 3600, (seg % 3600) // 60)


# ---------------------------------------------------------------------------
# 4-bis. AYUDA DE CADA OPCION
#
# El panel derecho repetia el texto de la fila y ya esta, o sea que no
# aportaba nada. Aqui se explica QUE HACE cada opcion, que es lo que cuesta
# adivinar cuando buscas algo y no sabes por donde anda.
#
# Se casa por PREFIJO porque muchas opciones llevan un valor detras
# ("Prefijo: propio del juego", "Runner: GE-Proton11-5"). Gana el prefijo mas
# largo que case, para poder afinar casos concretos sin romper los generales.
#
# La tabla es la MISMA que la del motor de pygame, copiada tal cual: son
# textos, no codigo, y tenerlos en dos sitios distintos acabaria con dos
# ayudas distintas para la misma opcion.
# ---------------------------------------------------------------------------
AYUDAS_ES = [
    # --- menu principal ---
    ('Jugar (elegir juego)',
     'Abre la biblioteca para elegir a que jugar. Con Select+X cambias entre '
     'lista, rejilla y caratulas.'),
    ('Jugar al ultimo',
     'Lanza otra vez el ultimo juego, sin pasar por la lista. Con X entras '
     'directo a su configuracion.'),
    ('Jugar al último',
     'Lanza otra vez el ultimo juego, sin pasar por la lista. Con X entras '
     'directo a su configuracion.'),
    ('Añadir un juego',
     'Mete un juego nuevo: un comprimido (zip, rar, 7z), un .exe suelto o una '
     'carpeta. Lo empaqueta y te guia por su configuracion basica.'),
    ('Ajustes de un juego',
     'Cambia el runner, el prefijo, los DLL overrides, el idioma y todo lo '
     'demas de UN juego, sin lanzarlo.'),
    ('Biblioteca y preferencias',
     'Las carpetas donde estan tus juegos, montar discos externos, las '
     'caratulas y el aspecto de los menus.'),
    ('Runners y herramientas',
     'Descargar y elegir versiones de Proton y Wine, y las herramientas del '
     'sistema.'),
    ('Gestion de archivos',
     'Que ocupa cada cosa, limpiar caches, reparar montajes colgados y buscar '
     'restos de juegos que ya borraste.'),
    ('Instalar librerias',
     'Los redistribuibles de Windows: Visual C++, DirectX, codecs de video... '
     'Es lo primero que hay que probar cuando un juego no arranca.'),
    ('Expulsar un disco',
     'Suelta un disco conectado para poder desconectarlo sin perder nada. '
     'Solo salen los que has conectado tu, no los del sistema.'),
    ('Montar un disco',
     'Monta un disco externo o una tarjeta para poder jugar a lo que tenga '
     'dentro. Si su carpeta ya estaba, no pregunta nada.'),
    ('Carátulas y perfiles de la comunidad',
     'Descarga caratulas y fichas de los juegos, y ajustes que ya han '
     'probado otros para que funcionen a la primera.'),
    ('Detener Wine y liberar los juegos montados',
     'Cierra Wine a la fuerza y desmonta todo. Para cuando un juego se cuelga '
     'y deja el sistema a medias.'),
    ('Ver el registro de la última sesión',
     'El log de lo ultimo que paso, con scroll. Es lo que hay que mirar (y '
     'enviar) cuando algo falla y no se sabe por que.'),
    ('Carpetas de juegos',
     'Donde busca WProton tus juegos. Puedes tener varias, por ejemplo una en '
     'la Deck y otra en la tarjeta.'),

    # --- ajustes de un juego ---
    ('Runner (Proton/Wine):',
     'Que version de Proton o Wine usa este juego. Si uno falla, casi siempre '
     'vale la pena probar otro.'),
    ('>> JUGAR AHORA <<',
     'Lanza el juego ya, con los ajustes que tenga puestos.'),
    ('Runner:',
     'Que version de Proton o Wine usa este juego. Si uno falla, casi siempre '
     'vale la pena probar otro.'),
    ('Ejecutable:',
     'El .exe que se lanza. En automatico lo busca solo; cambialo si el juego '
     'trae varios (lanzador, editor, el juego...).'),
    ('Argumentos:',
     'Lo que se le pasa al juego al arrancar, como -windowed o -novr.'),
    ('Prefijo:',
     'La "instalacion de Windows" del juego. Compartido: una para todos. '
     'Propio: solo para este. Incluido: el que trae el archivo dentro.'),
    ('Librerias de este juego:',
     'Las que se le han instalado y quedaron apuntadas. Si su prefijo se '
     'rehace o se borra, WProton se las vuelve a poner solo. Desde aqui se '
     'pueden olvidar.'),
    ('Instalar librerias en el prefijo:',
     'Instala redistribuibles directamente en el prefijo de este juego, sin '
     'tener que elegirlo otra vez desde el menu principal.'),
    ('GAMEID (protonfixes):',
     'Identificador de Steam para que protonfixes aplique los apaños conocidos '
     'de ese juego.'),
    ('DLL overrides:',
     'Fuerza a Wine a cargar una DLL de la carpeta del juego en vez de la '
     'suya. Lo piden dgVoodoo2, ReShade, OptiScaler y los cargadores de mods.'),
    ('Idioma del juego:',
     'Muchos juegos miran el idioma del sistema para decidir en cual arrancan. '
     'Aqui se le puede poner otro solo a este.'),
    ('Variables extra:',
     'Variables de entorno sueltas para casos raros, como PROTON_USE_WINED3D=1.'),
    ('Notas:',
     'Tus apuntes sobre este juego: que hay que tocar para que vaya, donde '
     'guarda las partidas, lo que sea.'),
    ('Favorito:',
     'Los favoritos salen los primeros en la biblioteca.'),
    ('Completado:',
     'Marca que te lo has pasado. Sale en la ficha del juego, para saber de un '
     'vistazo lo que te queda pendiente.'),
    ('Descargar carátulas',
     'Baja de una vez las caratulas de todos los juegos que no la tengan, '
     'desde SteamGridDB. Hace falta una clave gratuita.'),
    ('Clave de RAWG',
     'Opcional y gratuita. Rellena las notas que Steam no trae y las fichas '
     'de los juegos que no estan en Steam. Sin ella todo funciona igual.'),
    ('Descargar datos de los juegos',
     'Baja la ficha de Steam (año, genero, nota, sinopsis) y la duracion de '
     'HowLongToBeat de toda la biblioteca. No repite lo que ya esta.'),
    ('Rendimiento y compatibilidad',
     'MangoHud, GameMode, Fsync, DXVK, HDR, gamescope y demas ajustes de como '
     'corre el juego.'),
    ('Herramientas del prefijo',
     'winecfg, winetricks, importar un .reg, dgVoodoo2, OptiScaler y borrar el '
     'prefijo para empezar de cero.'),
    ('Dejarlo como esta',
     'No toca el estilo de botones. Siempre se puede cambiar despues desde '
     'los ajustes del juego.'),
    ('Teclas del mando .keys (marcar',
     'Para juegos que no soportan mando: cada boton manda una tecla. Si el '
     'juego ya trae un .keys, esto sale solo sin marcar nada.'),
    ('Estilo Xbox',
     'Los nombres de los botones dentro del .keys se leen al estilo Xbox: '
     '"a" es el de abajo y "b" el de la derecha.'),
    ('Batocera',
     'Los nombres de los botones dentro del .keys se leen como en Batocera: '
     '"a" es el de la DERECHA y "b" el de abajo.'),
    ('Añadir: escribir un texto',
     'Una combinacion teclea un texto que guardas antes (tu nombre). NO abre '
     'ninguna ventana, asi que el juego no se minimiza ni pierde el foco.'),
    ('Cambiar el texto', 'Escribir otro texto para esa combinacion.'),
    ('Pulsar Enter al terminar:',
     'Acepta el nombre de una vez. Quitalo si el juego tiene mas campos: el '
     'Enter podria saltar al siguiente o aceptar antes de tiempo.'),
    ('Rellenar: juego de teclado y raton',
     'Deja asignados de golpe los controles tipicos de un juego de PC: WASD '
     'para moverse, el stick derecho como raton y los gatillos como clics. '
     'Para juegos que no detectan mandos.'),
    ('Añadir: teclado en pantalla',
     'Una combinacion que abre un teclado manejable con el mando, para los '
     'juegos que te obligan a escribir un nombre y no soportan mando.'),
    ('Select + A (abajo)',
     'Se mantiene Select y se pulsa el boton de abajo. Si tu mando es de '
     'Nintendo ahi pone B, pero es el mismo.'),
    ('Select + B (derecha)', 'Se mantiene Select y se pulsa el de la derecha.'),
    ('Select + Y (arriba)', 'Se mantiene Select y se pulsa el de arriba.'),
    ('Select + X (izquierda)', 'Se mantiene Select y se pulsa el de la izquierda.'),
    # La prueba recorta las opciones por el "$", asi que ve "Select +" a
    # secas: la etiqueta real se compone en tiempo de ejecucion.
    ('Select +', 'Se mantiene Select y se pulsa el otro boton.'),
    ('Select + L1', 'Se mantiene Select y se pulsa el gatillo superior izquierdo.'),
    ('Select + R1', 'Se mantiene Select y se pulsa el gatillo superior derecho.'),
    ('Hotkey + ',
     'Se mantiene el hotkey (Select) y se pulsa el otro boton.'),
    ('L1 + R1',
     'Los dos gatillos superiores a la vez.'),
    ('Cambiar la combinacion',
     'Elegir otros botones para abrir el teclado en pantalla.'),
    ('Quitarlo',
     'Deja de abrirse el teclado en pantalla. El resto del .keys no se toca.'),
    ('Siempre: el juego solo vera las teclas',
     'El mando se captura: el juego solo recibe las teclas del .keys. Para '
     'juegos que traen su propio soporte de mando y lo usan en vez de las '
     'teclas.'),
    ('Nunca: el juego vera el mando y las teclas',
     'El juego recibe las dos cosas. Para .keys que solo traen atajos, o si '
     'el juego ya funcionaba bien con el mando.'),
    ('Automatico (recomendado)',
     'Se mira el propio .keys: si mapea el movimiento (sticks, cruceta, '
     'gatillos) se captura el mando; si solo trae atajos, no.'),
    ('Nunca (viejo): solo las teclas del .keys',
     'El mando se captura siempre. El juego solo vera las teclas.'),
    ('Siempre (viejo): mando y teclas a la vez',
     'El mando no se captura nunca. Ojo: un juego con soporte de mando puede '
     'ignorar las teclas.'),
    ('¿Que significa esto?',
     'Explica cuando conviene capturar el mando y cuando no.'),
    ('Mando virtual:',
     'Crea un mando de mentira y le copia lo del tuyo, cambiando algo por el '
     'camino. Distinto del .keys: aqui el juego sigue viendo un mando.'),
    ('No usar mando virtual',
     'El juego ve tu mando tal cual, sin que WProton toque nada.'),
    ('Mando Xbox (probar esto primero)',
     'El juego vera un Xbox 360, que es el que todos entienden. Se le pasa '
     'todo tal cual pero como un mando de libro: la cruceta va como eje y '
     'como botones. Arregla los mandos que llegan de forma rara, como la '
     'Steam Deck, que manda la cruceta como botones.'),
    ('Mando DualShock',
     'El juego vera un mando de Sony. Algunos se portan mejor con uno que con '
     'otro, y otros enseñan los botones correctos (X, circulo, cuadrado).'),
    ('Mando Xbox + cruceta al stick',
     'Un Xbox y ademas la cruceta moviendo el stick izquierdo, para juegos '
     'que leen bien la cruceta pero solo hacen caso al stick.'),
    ('Mando DualShock + cruceta al stick',
     'Un mando de Sony y ademas la cruceta moviendo el stick izquierdo.'),
    ('Traducir el modo escritorio de Steam',
     'En el modo escritorio de Steam los botones mandan TECLAS, no botones: A '
     'es Enter, B es Escape, la cruceta son las flechas. Un juego que espere '
     'un mando no recibe nada. Esto lo traduce de vuelta a mando.'),
    ('Mando clasico (para juegos antiguos)',
     'Finge un mando de los de antes: los gatillos van como botones y se '
     'quitan los ejes de mas. Para juegos de DirectInput que se lian con un '
     'mando moderno y se aceleran solos.'),
    ('Mando clasico + cruceta al stick',
     'Las dos cosas: mando de los de antes y la cruceta moviendo el stick.'),

    ('Volver a instalar lo que trae el juego (.bat)',
     'Algunos juegos instalan cosas la primera vez con un .bat. WProton lo '
     'hace una sola vez y luego abre el juego directo. Con esto se repite la '
     'instalacion, por si se corto a medias.'),
    ('El juego NO ve el mando:',
     'Captura el mando en exclusiva mientras el .keys esta activo, como hace '
     'Batocera. Sin esto, un juego con soporte de mando ignora las teclas.'),
    ('Teclado en pantalla:',
     'Donde sale el teclado del mando. Cambialo si tapa justo el sitio donde '
     'el juego te pide escribir.'),
    ('abajo ',   'El teclado sale en la parte de abajo.'),
    ('arriba ',  'El teclado sale arriba, para juegos que piden el texto abajo.'),
    ('centro ',  'El teclado sale en mitad de la pantalla.'),
    ('Estilo Batocera',
     'Como en Batocera: "a" es el boton de la DERECHA y "b" el de abajo, al '
     'estilo Nintendo. Si los botones salen cambiados, prueba a cambiarlo.'),
    ('Estilo de botones:',
     'Como se leen los nombres de los botones dentro del .keys. Xbox: "a" '
     'abajo. Batocera: "a" a la derecha.'),
    ('Mapeador .keys',
     'Convierte los botones del mando en teclas, para juegos que no soportan '
     'mando. Formato de Batocera.'),
    ('Copia de seguridad',
     'Guarda tus partidas fuera del prefijo, para que sobrevivan aunque lo '
     'borres o cambies de runner.'),
    ('Empaquetar con su prefijo',
     'Crea un archivo autosuficiente: el juego Y su prefijo dentro. Sirve para '
     'llevarlo a otro equipo tal cual esta.'),
    ('Borrar prefijo',
     'Deja el prefijo como recien hecho. Se pierde lo instalado en el '
     '(librerias, ajustes de Wine), NO el juego.'),
    ('Añadir este juego a Steam',
     'Mete el juego en tu biblioteca de Steam, con su caratula, para lanzarlo '
     'desde el modo Juego sin pasar por WProton.'),
    ('Raton: ',
     'El mando hace de raton: un stick mueve el puntero y un boton hace clic. '
     'Util en estrategia, aventuras graficas e instaladores.'),
    ('Crear acceso en Steam',
     'Añade el juego a tu biblioteca de Steam para lanzarlo desde el modo '
     'Juego, con su caratula.'),

    # --- rendimiento ---
    ('MangoHud',
     'Enseña FPS, temperaturas y uso de CPU/GPU sobre el juego.'),
    ('GameMode',
     'Le pide al sistema prioridad para el juego mientras se juega.'),
    ('Gamescope',
     'Mete el juego en su propia ventana con escalado y limite de FPS. Hace '
     'falta para el HDR.'),
    ('HDR:',
     'Rango dinamico alto. Necesita gamescope o una sesion Wayland, un monitor '
     'que lo soporte y que el juego lo traiga.'),
    ('Wayland nativo',
     'Que el juego hable Wayland directamente en vez de pasar por XWayland. '
     'Experimental.'),
    ('NTsync',
     'Sincronizacion por kernel, mas rapida que Fsync. Necesita Linux 6.14 o '
     'mas nuevo.'),
    ('Fsync',
     'Sincronizacion rapida entre hilos. Ayuda en juegos que van justos de CPU.'),
    ('DXVK',
     'Traduce DirectX a Vulkan. Async y GPL reducen los tirones al compilar '
     'shaders.'),
    ('FSR',
     'Escalado de AMD: el juego renderiza a menos resolucion y se reescala. '
     'Mas FPS a cambio de nitidez.'),
    ('Abrir winecfg',
     'La configuracion de Wine: version de Windows, unidades, letras, graficos.'),
    ('Abrir winetricks',
     'La herramienta de siempre para instalar librerias y ajustes de Wine, con su interfaz.'),
    ('Configurar dgVoodoo (Cpl)',
     'El panel de dgVoodoo2: resolucion, filtros y como emula las tarjetas antiguas.'),
    ('Instalar dgVoodoo2',
     'Traduce DirectX 1 a 9 y Glide a DirectX 11. Para juegos de los 90 y principios de los 2000.'),
    ('Instalar OptiScaler',
     'Anade escalado moderno (FSR, DLSS, XeSS) a juegos que no lo traen.'),
    ('Importar un fichero .reg',
     'Mete claves en el registro del prefijo. Se usa sobre todo para cambiar el idioma de un juego.'),
    ('Borrar la configuración de este juego',
     'Deja el juego como recien anadido. Se pierden sus ajustes, no el juego.'),
    ('Carátula: buscar en SteamGridDB',
     'Busca la caratula de ESTE juego por nombre, sin bajar las de todos.'),
    ('Carátula: elegir una imagen',
     'Pon una imagen tuya como caratula: un png o jpg de tu disco.'),
    ('Ficha del juego',
     'Los datos de Steam de este juego: año, editor, genero y nota.'),
    ('Ficha de Steam',
     'Año, genero, nota de Metacritic y sinopsis, de la tienda de Steam.'),
    ('Duración (HowLongToBeat)',
     'Cuanto se tarda en pasar el juego, segun HowLongToBeat.'),
    ('Las dos cosas',
     'La ficha de Steam y la duracion, de una pasada.'),
    ('Datos de duración de partida',
     'Instala la libreria que hace falta para consultar HowLongToBeat.'),
    ('Vertical (2:3',
     'La caratula de siempre, alta y estrecha, como en las tiendas.'),
    ('Panorámica',
     'Caratula ancha, como las de la biblioteca de Steam.'),
    ('Cuadrada 4:3',
     'Caratula casi cuadrada, va bien con juegos y sistemas antiguos.'),
    ('Solo verticales',
     'Baja solo las altas y estrechas: menos peticiones y mas rapido.'),
    ('Solo panorámicas',
     'Baja solo las anchas.'),
    ('Solo cuadradas',
     'Baja solo las 4:3.'),
    ('Todas (las tres formas)',
     'Baja las tres. Tarda el triple y gasta el triple de peticiones.'),
    ('Proton oficial de Steam',
     'Usa el Proton que Steam ya tiene instalado. No se descarga nada: se '
     'enlaza, asi que no ocupa sitio y se actualiza con Steam.'),
    ('Proton7-38-Frankenstein',
     'Un Proton a medida para juegos que no funcionan con los normales. '
     'Alojado por WProton.'),
    ('Proton-Experimental',
     'El Proton oficial de Valve. Como no se publica fuera de Steam, se '
     'descarga de donde lo aloja WProton.'),
    ('(incluido:',
     'El Proton o Wine que viene DENTRO del archivo. Si el juego trae tambien '
     'su prefijo, este es el que lo hizo: con otro puede no arrancar.'),
    ('GE-Proton',
     'El Proton de GloriousEggroll. Es el que mejor va en la mayoria de juegos.'),
    ('Proton-CachyOS',
     'Proton compilado para procesadores modernos (x86-64-v3).'),
    ('Proton-LG',
     'Proton de Castro-Fidel, el de PortProton, basado en GE.'),
    ('DWProton',
     'Proton con apanos para juegos anime y gacha.'),
    ('WProton Custom',
     'El runner que WProton instala de serie: Proton Frankenstein. Si lo has '
     'borrado, desde aqui vuelve. No aparece en la lista de descarga porque '
     'se instala solo al principio.'),
    ('Wine-GE',
     'Wine de GloriousEggroll, pensado para juegos que no son de Steam.'),
    ('Wine Kron4ek',
     'Wine limpio, en sus variantes vanilla, staging y tkg.'),
    ('Wine Soda',
     'Wine de Bottles basado en el de Valve.'),
    ('Wine Caffe',
     'Wine de Bottles, version TKG estable.'),
    ('Wine-LG',
     'Wine de Castro-Fidel, el de PortProton.'),
    ('Actualizar GE-Proton',
     'Descarga la ultima version de GE-Proton.'),
    ('Actualizar umu-launcher',
     'Actualiza umu, que es quien lanza los juegos con Proton.'),
    ('Borrar un runner',
     'Quita una version de Proton o Wine para liberar espacio.'),
    ('Borrar runner',
     'Quita una version de Proton o Wine para liberar espacio.'),
    ('default   (el COMPARTIDO',
     'El prefijo que usan todos los juegos en modo compartido. Lo que instales '
     'aqui lo veran todos ellos.'),
    ('Compartido',
     'Una sola instalacion de Windows para todos los juegos. Ocupa poco y se configura una vez.'),
    ('Propio del juego',
     'Una instalacion solo para este juego. Ocupa mas, pero lo que instales no afecta a los demas.'),
    ('Incluido en el wsquashfs',
     'El prefijo que trae el propio archivo, con su registro y sus DLL.'),
    ('El que trae el wsquashfs',
     'El prefijo que trae el propio archivo, con su registro y sus DLL.'),
    ('Prefijo compartido (default)',
     'Lo que instales aqui lo veran todos los juegos en modo compartido.'),
    ('Prefijo de un juego concreto',
     'Elegir un juego e instalar en SU prefijo.'),
    ('Otro prefijo de la lista',
     'Elegir cualquiera de los prefijos que ya existen en disco.'),
    ('Visual C++ y .NET',
     'Lo que piden casi todos los juegos de Windows. Si uno no arranca, empieza por aqui.'),
    ('DirectX y shaders',
     'Las librerias D3DX y los compiladores de shaders que piden muchos juegos.'),
    ('Codecs de video y sonido',
     'Para cuando el juego arranca pero las cinematicas salen en negro o sin sonido.'),
    ('Otros (fuentes',
     'Fuentes de Windows, PhysX, XNA y los prerrequisitos de Unreal.'),
    ('Verlo todo en una sola lista',
     'Todos los redistribuibles juntos, sin categorias.'),
    ('Elegir de una lista',
     'Las DLL mas habituales y las que ya tengas puestas, para marcar y desmarcar.'),
    ('Buscar las DLL que hay en el juego',
     'Mira junto al ejecutable: si alguien dejo ahi una DLL, es que quiere que se cargue.'),
    ('Escribir a mano la cadena entera',
     'Para casos raros: se escribe el WINEDLLOVERRIDES tal cual.'),
    ('Quitar todos',
     'Quita todos los overrides. Los que pusieron dgVoodoo2 u OptiScaler tambien.'),
    ('Crear o editar las teclas',
     'Asigna una tecla a cada boton del mando, uno por uno.'),
    ('Crear un .keys de ejemplo',
     'Crea un fichero de ejemplo con Alt+Tab y Alt+F4, para partir de algo.'),
    ('Ver las teclas asignadas',
     'Enseña que tecla manda cada boton, sin abrir el fichero.'),
    ('Encender: el stick derecho mueve',
     'El mando hace de raton. Util en estrategia, aventuras graficas e instaladores.'),
    ('Apagar el raton',
     'El stick vuelve a ser un stick.'),
    ('Probar el mando',
     'Enseña que botones y ejes llegan de verdad. Para cuando algo no responde.'),
    ('Arreglar permisos del mando',
     'Da acceso a los dispositivos del mando. Si faltan botones o ejes, prueba esto.'),
    ('Instalar evdev',
     'La libreria que necesita el mapeador de teclas.'),
    ('Flechas del teclado',
     'Asignar una flecha: arriba, abajo, izquierda o derecha.'),
    ('Teclas F (F1 a F12)',
     'Asignar una tecla de funcion.'),
    ('Escribir una letra o número',
     'Asignar cualquier tecla escribiendola.'),
    ('Añadir otra carpeta',
     'Otra carpeta donde buscar juegos, ademas de la que ya hay.'),
    ('Elegir otra carpeta',
     'Cambia la carpeta principal de juegos.'),
    ('Usar la carpeta games/',
     'La carpeta que WProton crea junto a si mismo.'),
    ('Olvidar carpetas detectadas',
     'Borra las carpetas que se detectaron solas; se volveran a buscar al jugar.'),
    ('Perfiles de la comunidad',
     'Ajustes que ya han probado otros para juegos que necesitan apanos. Se descargan y se aplican.'),
    ('Perfiles guardados',
     'Los perfiles que tienes descargados: mirarlos o borrarlos.'),
    ('Borrar TODOS los perfiles',
     'Borra los perfiles de la comunidad descargados. Tus ajustes NO se tocan.'),
    ('Buscar en la base de umu',
     'Busca el identificador del juego en la base de umu, para que protonfixes aplique sus apanos.'),
    ('Tamaño por juego',
     'Que ocupa cada juego: el archivo, sus partidas y su prefijo.'),
    ('Mostrar el tamaño de WProton',
     'Lo que ocupa WProton entero: runners, prefijos, caratulas y datos.'),
    ('Limpiar cache de shaders',
     'Borra los shaders compilados. Se regeneran solos y pueden ocupar gigas.'),
    # El texto del aviso empieza con "Copiar:" o "Mover:", y la prueba los
    # extrae como opciones sueltas.
    ('Copiar', 'Se copia lo elegido a la carpeta de destino.'),
    ('Mover', 'Se lleva lo elegido a la carpeta de destino.'),
    ('Copiar o mover ficheros',
     'Lleva un fichero o una carpeta de un sitio a otro sin salir de WProton: '
     'una partida, un .keys, una caratula. No borra nada.'),
    ('Copiar algo a otra carpeta',
     'Se elige que copiar y donde ponerlo. El original se queda donde esta.'),
    ('Mover algo a otra carpeta',
     'Igual que copiar, pero el original desaparece del sitio de origen.'),
    ('¿Para que sirve esto?',
     'Explica para que sirve copiar y mover ficheros desde aqui.'),
    ('>> ESTA CARPETA ENTERA <<',
     'Coge la carpeta en la que estas, con todo lo que tiene dentro.'),
    ('Reparar carpetas tapadas',
     'Cuando algo borra y rehace una carpeta, la superposicion tapa lo que '
     'trae el archivo: el juego deja de ver sus idiomas o su configuracion.'),
    ('Reparar montajes colgados',
     'Limpia lo que deja un juego que se cuelga. Evita tener que reiniciar.'),
    ('Buscar prefijos y saves huerfanos',
     'Restos de juegos que ya borraste y siguen ocupando sitio.'),
    ('Borrar copias de saves antiguas',
     'Quita las copias viejas de partidas, dejando las recientes.'),
    ('Borrar saves del overlay',
     'Borra lo que el juego ha escrito. OJO: ahi estan las partidas guardadas.'),
    ('Comprobar el archivo y ver cuanto ocupa',
     'Verifica que el wsquashfs esta entero y dice lo que ocupa.'),
    ('Comprobar lo descargado',
     'Comprueba las huellas SHA-256 de lo descargado, por si algo vino a medias.'),
    ('Partidas guardadas',
     'Donde guarda el juego, y copias de seguridad para que no se pierdan.'),
    ('Ver donde guarda las partidas',
     'Enseña en que carpeta del prefijo escribe el juego.'),
    ('Sincronizar AHORA con rsync',
     'Copia las partidas a otra carpeta o disco en este momento.'),
    ('Sincronizar la carpeta backups',
     'Manda las copias a otro sitio, a mano con rsync o solo con Syncthing.'),
    ('Preparar carpeta para Syncthing',
     'Deja la carpeta lista para que Syncthing la sincronice entre equipos.'),
    ('Copia de tu configuración',
     'Guarda o recupera TODA tu configuracion en un zip: perfiles, ajustes y datos.'),
    ('Exportar mi configuración',
     'Guarda tus perfiles y ajustes en un zip, para otro equipo o por si acaso.'),
    ('Importar configuración desde un zip',
     'Recupera una copia hecha antes.'),
    ('Añadir lo que falte',
     'Solo mete lo que no tengas. Lo tuyo se queda como esta.'),
    ('Sustituir todo',
     'Machaca tu configuracion con la del zip. Lo que tengas ahora se pierde.'),
    ('Repetir asistente de primera ejecucion',
     'Vuelve a pasar por la configuracion inicial.'),
    ('Instalar/actualizar Python portable',
     'El Python propio de WProton, con pygame. Es lo que dibuja estos menus.'),
    ('Descargar herramientas FUSE',
     'Lo que hace falta para montar los juegos sin instalar nada en el sistema.'),
    ('Descargar herramientas DwarFS',
     'Para usar el formato dwarfs, que comprime mas que squashfs.'),
    ('Descargar extractores GOG',
     'Para poder abrir los instaladores de GOG.'),
    ('Añadir WProton a Steam',
     'Mete WProton en tu biblioteca de Steam, para abrirlo desde el modo Juego.'),
    ('Cambiar las imágenes de WProton en Steam',
     'La caratula y el fondo que se ven en Steam.'),
    ('Acceso directo en el escritorio',
     'Crea un icono para abrir WProton desde el escritorio.'),
    ('Captura de pantalla',
     'Hace una foto de la pantalla pasados unos segundos, para poder colocarte antes.'),
    ('Grabar los menus',
     'Graba un video de los menus. Util para enseñar un fallo.'),
    ('Grabar la pantalla entera',
     'Graba todo lo que se ve. Con algunos juegos sale en negro.'),
    ('Ver la carpeta de capturas',
     'Donde quedan las fotos y los videos.'),
    ('Empaquetar a wsquashfs',
     'Convierte una carpeta de juego en un solo archivo comprimido.'),
    ('Probar el juego (sin empaquetar)',
     'Lanzarlo tal cual esta, para comprobar que va antes de empaquetar.'),
    ('wsquashfs - compatible',
     'El formato de siempre: lo entienden Batocera y PortProton.'),
    ('dwarfs - comprime',
     'Comprime bastante mas y se monta igual de rapido, pero es menos compatible.'),
    ('clasico - el original',
     'El aspecto de siempre, una lista simple.'),
    ('moderno - paneles',
     'Dos paneles y color de acento. Es el que enseña la informacion de la derecha.'),
    ('arcade - synthwave',
     'Como el moderno pero con efecto de pantalla antigua.'),
    ('nombre - alfabetico',
     'Ordena la biblioteca por nombre.'),
    ('recientes - los últimos',
     'Ordena poniendo delante lo ultimo que jugaste.'),
    ('jugados - los de más tiempo',
     'Ordena por horas jugadas.'),
    ('Automático (según el tamaño',
     'WProton elige el tamano segun la pantalla.'),
    ('Grande (recomendado',
     'Letras y filas grandes, para jugar en portatil o en el sofa.'),
    ('Muy grande',
     'Todavia mas grande, para televisiones lejos.'),
    ('Normal',
     'Tamano estandar.'),
    ('Pantalla completa nativa',
     'A la resolucion de la pantalla, sin escalar.'),
    ('Personalizado (escribir argumentos',
     'Escribe tu los argumentos de gamescope.'),
    ('Desactivado',
     'Apagado.'),
    ('Ninguno',
     'Sin ninguno.'),
    ('Configurar (runner, prefijo',
     'Abre los ajustes de este juego.'),
    ('Escribir la clave',
     'Pega aqui tu clave. Se guarda en su fichero, no en settings.conf.'),
    ('Quitar la clave',
     'Borra la clave guardada.'),
    ('Para qué sirve',
     'Explica para que hace falta esto y que pasa si no lo pones.'),
    ('El del sistema',
     'Usa el idioma que tenga el sistema.'),
    ('Escribir un locale a mano',
     'Para un idioma que no este en la lista, como ko_KR.UTF-8.'),
    ('Último log',
     'El registro de la ultima sesion. Es lo que hay que mirar cuando algo falla.'),
    ('Salir',
     'Cierra WProton.'),
    ('Arreglo mando SteamOS (Steam Input):',
     'Apana los mandos que Steam Input duplica o presenta raro en SteamOS.'),
    ('Carpeta principal:',
     'La carpeta donde WProton busca los juegos.'),
    ('Carátula en la vista de lista:',
     'Que forma de caratula se enseña en el panel de la derecha.'),
    ('Carátulas por fila:',
     'Cuantas caben en la rejilla. Menos por fila, mas grandes.'),
    ('Clic con:',
     'Que boton hace de clic cuando el mando mueve el raton.'),
    ('Mover con:',
     'Que stick mueve el puntero del raton.'),
    ('Velocidad:',
     'Lo rapido que se mueve el puntero.'),
    ('Crear copia de seguridad ahora',
     'Guarda AHORA las partidas de este juego, fuera del prefijo.'),
    ('Restaurar una copia',
     'Recupera unas partidas guardadas antes. Machaca las de ahora.'),
    ('Descargar runners',
     'Baja versiones de Proton y Wine de sus repositorios.'),
    ('Destino rsync:',
     'A donde se copian las partidas al sincronizar: otra carpeta o un disco.'),
    ('Estadísticas:',
     'Contar las veces y el tiempo que juegas. Solo para ti, no se envia a ningun sitio.'),
    ('Esync:',
     'Sincronizacion rapida entre hilos. Si un juego se cuelga al arrancar, prueba a apagarlo.'),
    ('Formato al empaquetar:',
     'wsquashfs para compatibilidad, dwarfs para comprimir mas.'),
    ('Idioma:',
     'El idioma de los menus de WProton (no el de los juegos).'),
    ('LAA (32bit +2GB RAM):',
     'Deja que un juego de 32 bits use mas de 2 GB. Arregla cuelgues en juegos viejos con mods.'),
    ('Mandos por SDL en este prefijo',
     'Hace que Wine lea los mandos por SDL en vez de por hidraw. Es el arreglo '
     'que usa mucha gente cuando Proton no coge bien un mando, sobre todo los '
     'de PlayStation. Solo toca el prefijo de este juego, y se puede deshacer.'),
    ('Mando Sony (DualSense/DS4):',
     'Ajustes propios de los mandos de PlayStation.'),
    ('Mando via SDL',
     'Presenta el mando como uno de Xbox. Necesario en DualSense y DS4 con juegos que solo entienden XInput.'),
    ('Ordenar juegos por:',
     'El orden de la biblioteca: por nombre, por lo ultimo jugado o por horas.'),
    ('Tamaño de la letra:',
     'Lo grande que se ve todo. En portatil conviene grande.'),
    ('Tema de los menus:',
     'El aspecto: clasico, moderno, arcade o cristal (este ultimo solo se ve '
     'con el motor Qt).'),
    ('Motor de los menus:',
     'Con que se dibujan los menus: pygame (ligero, 12 MB) o Qt (se ve mejor, '
     'ocupa 200-300 MB). Los dos conviven; auto usa Qt si esta instalado.'),
    ('Vista de juegos:',
     'Lista, rejilla, caratulas anchas o cuadradas. Tambien se cambia con Select+X.'),
    ('WineD3D (OpenGL, juegos viejos):',
     'Traduce DirectX a OpenGL en vez de a Vulkan. Solo para juegos muy viejos que fallan con DXVK.'),
]

# Prefijos ordenados de mas largo a mas corto: asi "Instalar librerias en el
# prefijo:" gana a "Instalar librerias" y no al reves.
AYUDAS_ES.sort(key=lambda x: -len(x[0]))

def ayuda_de(texto):
    """La explicacion de una opcion de menu, o None si no hay ninguna."""
    if not texto:
        return None
    for prefijo, ayuda in AYUDAS_ES:
        if texto.startswith(prefijo):
            return L(ayuda)
    return None


# ---------------------------------------------------------------------------
# 5. EL MANDO: HILO DE EVDEV
#
# Se conserva ENTERO el del motor viejo, que es la parte mejor probada del
# helper: agrupa nodos por aparato fisico, descarta acelerometros, hace
# histeresis en los ejes y trata Select como modificador. Lo unico que cambia
# es el destino: antes hacia pygame.event.post(), ahora emite una señal de Qt
# con conexion en cola, que es la forma correcta de hablar con el hilo de la
# interfaz sin pisarla.
# ---------------------------------------------------------------------------
import select as _select  # noqa: E402
import struct  # noqa: E402
import threading  # noqa: E402

EV_KEY_RAW, EV_ABS_RAW = 1, 3
IE_FMT = 'llHHi'
IE_SZ = struct.calcsize(IE_FMT)
RAW_BTN = {304: K_RETURN, 315: K_RETURN,
           305: K_ESCAPE, 307: K_SPACE,
           308: K_TAB,
           310: K_F1, 311: K_F2}
SELECT_BTN = 314
DPAD_BTN = {544: K_UP, 545: K_DOWN, 546: K_LEFT, 547: K_RIGHT}
AXIS_KEYS = {0: (K_LEFT, K_RIGHT), 1: (K_UP, K_DOWN),
             16: (K_LEFT, K_RIGHT), 17: (K_UP, K_DOWN)}
BAD_DEV = ('accel', 'gyro', 'imu', 'motion', 'sensor')
_noaccess = set()
home_req = [False]


def parse_input_chunk(data):
    out = []
    for off in range(0, len(data) - IE_SZ + 1, IE_SZ):
        _, _, t, c, v = struct.unpack_from(IE_FMT, data, off)
        out.append((t, c, v))
    return out


def find_raw_pads():
    # Un mando fisico puede exponer varios nodos (xpad crea uno por interfaz,
    # el DualSense saca ademas sus sensores). Si se leen todos, cada pulsacion
    # llega dos veces y el menu salta de dos en dos: se agrupa por "P: Phys="
    # y de cada grupo se deja el primero.
    pads, vistos = [], set()
    try:
        blocks = open('/proc/bus/input/devices').read().split('\n\n')
    except OSError:
        return pads
    for b in blocks:
        name, ev, has_js, phys = '', None, False, ''
        for line in b.split('\n'):
            if line.startswith('N:'):
                name = line.lower()
            elif line.startswith('P:'):
                phys = line.split('=', 1)[-1].strip().split('/')[0]
            elif line.startswith('H:'):
                l2 = line.replace('=', ' ')
                if ' js' in l2:
                    has_js = True
                for tok in l2.split():
                    if tok.startswith('event'):
                        ev = tok
        if not (has_js and ev) or any(k in name for k in BAD_DEV):
            continue
        clave = phys or ev
        if clave in vistos:
            continue
        vistos.add(clave)
        pads.append('/dev/input/' + ev)
    return pads


class Mando(QtCore.QObject):
    # Puente entre el hilo de evdev y la interfaz. La señal se conecta con
    # Qt.QueuedConnection: la tecla se procesa en el hilo de la ventana.
    tecla = Signal(int)
    volver_a_casa = Signal()

    def __init__(self):
        QtCore.QObject.__init__(self)
        # Bandera para que el hilo se olvide de lo que tenia pulsado. La lee
        # y la baja el, no quien la sube: asi no hay que compartir candados
        # por una cosa que solo se pone a cierto.
        self._olvidar = threading.Event()

    def arrancar(self):
        threading.Thread(target=self._bucle, daemon=True).start()

    def olvidar_pulsaciones(self):
        # SE ACABO UN MENU: lo que estuviera pulsado no cuenta para el
        # siguiente. Sin esto, la repeticion automatica de una direccion -o
        # el boton que aun no se ha soltado- seguia disparando y las
        # pulsaciones caian sobre el menu recien abierto. El motor viejo
        # vaciaba la cola de eventos en cada fotograma del reposo por esto
        # mismo; aqui el que las genera es este hilo, asi que se corta en el
        # origen y no en el destino.
        self._olvidar.set()

    def _bucle(self):
        fds, held, ax = {}, {}, {}
        sel_held, sel_combo, sel_desde = [False], [False], [0.0]
        last_scan = 0.0
        REP_FIRST, REP_NEXT = 0.40, 0.15
        TH_ON, TH_OFF = 18000, 12000
        sys.stderr.write('menu_qt: lector de mando activo (/dev/input)\n')
        while True:
            now = time.time()
            if self._olvidar.is_set():
                self._olvidar.clear()
                held.clear()
                ax.clear()
                sel_held[0] = False
                sel_combo[0] = False
                home_req[0] = False
                # Y se tira lo que este esperando en los aparatos: son
                # pulsaciones de antes del cambio de menu.
                for _f in list(fds.values()):
                    try:
                        while True:
                            if not os.read(_f, IE_SZ * 64):
                                break
                    except OSError:
                        pass
            if now - last_scan > 2:
                last_scan = now
                for p in find_raw_pads():
                    if p not in fds:
                        try:
                            fds[p] = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
                            sys.stderr.write('menu_qt: mando via evdev: %s\n' % p)
                        except OSError as e:
                            if p not in _noaccess:
                                _noaccess.add(p)
                                sys.stderr.write('menu_qt: sin acceso a %s (%s)\n' % (p, e))
            try:
                r, _, _ = _select.select(list(fds.values()), [], [],
                                         0.05 if held else 0.5)
            except OSError:
                r = []
            for fd in r:
                try:
                    data = os.read(fd, IE_SZ * 64)
                except OSError:
                    for p, f in list(fds.items()):
                        if f == fd:
                            try:
                                os.close(f)
                            except OSError:
                                pass
                            del fds[p]
                    continue
                for t, c, v in parse_input_chunk(data):
                    if t == EV_KEY_RAW and c in DPAD_BTN:
                        k = DPAD_BTN[c]
                        if v == 1:
                            self.tecla.emit(int(k)); held[k] = time.time() + REP_FIRST
                        else:
                            held.pop(k, None)
                    elif t == EV_KEY_RAW and c == SELECT_BTN:
                        # Select es MODIFICADOR: no se puede actuar al
                        # pulsarlo, hay que esperar a soltarlo y ver si por
                        # medio se uso alguna combinacion. Y solo cuenta la
                        # pulsacion corta: mantenerlo es lo que usa el
                        # guardian para cerrar el juego.
                        if v != 0:
                            sel_held[0] = True
                            sel_combo[0] = False
                            sel_desde[0] = time.time()
                        else:
                            sel_held[0] = False
                            if not sel_combo[0] and (time.time() - sel_desde[0]) < 0.6:
                                home_req[0] = True
                                self.volver_a_casa.emit()
                    elif t == EV_KEY_RAW and c in RAW_BTN and v == 1:
                        if c == 304 and sel_held[0]:
                            sel_combo[0] = True
                            self.tecla.emit(int(K_F11))     # Select+A: pantalla
                        elif c == 307 and sel_held[0]:
                            sel_combo[0] = True
                            self.tecla.emit(int(K_F3))      # Select+X: vista
                        else:
                            self.tecla.emit(int(RAW_BTN[c]))
                    elif t == EV_ABS_RAW and c in (16, 17):
                        neg, pos = AXIS_KEYS[c]
                        for n in (neg, pos):
                            held.pop(n, None)
                        if v != 0:
                            k = pos if v > 0 else neg
                            self.tecla.emit(int(k)); held[k] = time.time() + REP_FIRST
                    elif t == EV_ABS_RAW and c in (0, 1):
                        st = ax.get((fd, c), 0)
                        new = st
                        if st == 0 and abs(v) > TH_ON:
                            new = 1 if v > 0 else -1
                        elif st != 0 and abs(v) < TH_OFF:
                            new = 0
                        if new != st:
                            ax[(fd, c)] = new
                            neg, pos = AXIS_KEYS[c]
                            for n in (neg, pos):
                                held.pop(n, None)
                            if new != 0:
                                k = pos if new > 0 else neg
                                self.tecla.emit(int(k)); held[k] = time.time() + REP_FIRST
            now = time.time()
            for k, t_ in list(held.items()):
                if now >= t_:
                    self.tecla.emit(int(k)); held[k] = now + REP_NEXT


# ---------------------------------------------------------------------------
# 6. ESTADO DE LA PETICION EN CURSO
# ---------------------------------------------------------------------------
K_HDR, K_UP2, K_CANCEL, K_DIR, K_FILE, K_PLAIN = range(6)
HEADER_KINDS = (K_HDR, K_UP2, K_CANCEL)

TECLADO = [
    'ABCDEFGHIJ', 'KLMNOPQRST', 'UVWXYZ0123', '456789 .-_',
]


class Peticion(object):
    # Un menu concreto: que se pide, con que datos y donde se contesta.
    def __init__(self):
        self.modo = 'list'
        self.titulo = ''
        self.salida = ''
        self.arg4 = ''
        self.kind = 'file'
        self.exts = EXTS_NORMAL
        self.info = {}
        self.presel = ''
        self.fav_file = ''
        self.aspecto = ''
        self.items = []          # [tipo, texto, marcado]
        self.gitems = []         # [titulo, imagen, payload, fav]
        self.view = []
        self.cur_path = ''
        self.sel = 0
        self.scroll = 0
        self.filtro = ''
        self.kb_open = False
        self.kb_r = self.kb_c = 0
        self.texto = ''
        self.done = False

    # -- carga -------------------------------------------------------------
    def preparar(self, modo, titulo, salida, arg4=None, kind='file',
                 action_x=None, manifiesto=None, presel=None, fav_file=None,
                 aspecto=None):
        global ACTION_X
        self.__init__()
        self.modo, self.titulo, self.salida = modo, titulo, salida
        self.arg4 = arg4 if arg4 is not None else salida
        self.kind = kind
        self.presel = presel or ''
        self.fav_file = fav_file or ''
        self.aspecto = aspecto or ''
        if action_x is not None:
            ACTION_X = action_x
        if kind == 'keys':
            self.exts = ('.keys',)
        elif kind == 'reg':
            self.exts = ('.reg',)
        elif kind == 'image':
            self.exts = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')
        elif kind == 'importar':
            self.exts = EXTS_IMPORTAR
        elif kind == 'cualquiera':
            self.exts = ()
        else:
            self.exts = EXTS_NORMAL
        if manifiesto and os.path.isfile(manifiesto):
            self._leer_manifiesto(manifiesto)
        if modo in ('list', 'check'):
            self.cargar_opciones()
        elif modo == 'browse':
            self.cargar_dir(self.arg4 or os.path.expanduser('~'))
        elif modo == 'grid':
            self.cargar_grid()
        elif modo == 'text':
            self.texto = self.arg4 or ''
        self.colocar_en_preseleccion()

    def _leer_manifiesto(self, manifiesto):
        # nombre|caratula|favorito|veces|segundos|ficha.json|duracion|...
        try:
            with open(manifiesto, encoding='utf-8') as fh:
                for linea in fh:
                    campos = linea.rstrip('\n').split('|')
                    if not campos or not campos[0].strip():
                        continue
                    while len(campos) < 9:
                        campos.append('')
                    d = {'cov': campos[1], 'fav': campos[2], 'veces': campos[3],
                         'segs': campos[4], 'ficha': campos[5],
                         'hltb': campos[6], 'completado': campos[7],
                         'rawg': campos[8]}
                    d.update(leer_ficha(campos[5]))
                    # RAWG solo RELLENA: lo de Steam manda (sinopsis en
                    # español y datos mas completos).
                    for k, v in leer_rawg(campos[8]).items():
                        if not d.get(k):
                            d[k] = v
                    d['dur'] = leer_duracion(d.get('hltb', ''))
                    self.info[campos[0]] = d
        except Exception:
            self.info = {}

    def cargar_opciones(self):
        self.items = []
        try:
            with open(self.arg4, encoding='utf-8') as f:
                for l in f:
                    l = l.rstrip('\n')
                    if not l.strip():
                        continue
                    if self.modo == 'check':
                        on, _, txt = l.partition('|')
                        self.items.append([K_PLAIN, txt, on == '1'])
                    else:
                        self.items.append([K_PLAIN, l, False])
        except OSError:
            self.items = []
        self.aplicar_filtro()

    def cargar_grid(self):
        self.gitems = []
        try:
            with open(self.arg4, encoding='utf-8') as fh:
                for linea in fh:
                    campos = linea.rstrip('\n').split('|')
                    if not campos or not campos[0].strip():
                        continue
                    while len(campos) < 4:
                        campos.append('')
                    self.gitems.append(campos[:4])
        except OSError:
            self.gitems = []
        self.aplicar_filtro()

    def cargar_dir(self, path):
        # Navegacion EN PROCESO: no se relanza la ventana por cada carpeta.
        self.cur_path = os.path.realpath(path)
        self.filtro = ''
        self.items = []
        if self.kind == 'dir':
            self.items.append([K_HDR, '>> ' + L('USAR ESTA CARPETA', 'USE THIS FOLDER') + ' <<', False])
        if os.path.dirname(self.cur_path) != self.cur_path:
            self.items.append([K_UP2, '..', False])
        try:
            nombres = sorted(os.listdir(self.cur_path), key=lambda s: s.lower())
        except OSError:
            nombres = []
        dirs, files = [], []
        for n in nombres:
            if n.startswith('.'):
                continue
            p = os.path.join(self.cur_path, n)
            if os.path.isdir(p):
                dirs.append([K_DIR, n + '/', False])
            elif self.kind == 'dir':
                continue
            elif not self.exts or n.lower().endswith(self.exts):
                files.append([K_FILE, n, False])
        self.items += dirs + files
        self.aplicar_filtro()

    # -- filtro ------------------------------------------------------------
    @staticmethod
    def _match(text, f):
        # Coincidencia por PREFIJO de palabra: "s" -> solo titulos con alguna
        # palabra que empiece por s, no cualquiera que contenga una s.
        words = text.lower().replace('_', ' ').replace('-', ' ').replace('.', ' ').split()
        for tok in f.split():
            if not any(w.startswith(tok) for w in words):
                return False
        return True

    def aplicar_filtro(self):
        f = self.filtro.lower().strip()
        if self.modo == 'grid':
            if f:
                self.view = [i for i, it in enumerate(self.gitems)
                             if self._match(it[0], f)]
            else:
                self.view = list(range(len(self.gitems)))
        else:
            if f:
                self.view = [i for i, it in enumerate(self.items)
                             if it[0] in HEADER_KINDS or self._match(it[1], f)]
            else:
                self.view = list(range(len(self.items)))
        self.sel = 0
        self.scroll = 0

    def colocar_en_preseleccion(self):
        # Volver a la lista donde estabas: si el que llama dice sobre que
        # juego abrir, se busca y se deja seleccionado.
        if not self.presel or not self.view:
            return
        for pos, idx in enumerate(self.view):
            nombre = self.gitems[idx][0] if self.modo == 'grid' else self.items[idx][1]
            if nombre == self.presel:
                self.sel = pos
                return

    # -- acceso ------------------------------------------------------------
    def nombre_actual(self):
        if not self.view:
            return ''
        idx = self.view[self.sel]
        return self.gitems[idx][0] if self.modo == 'grid' else self.items[idx][1]

    def escribir(self, texto):
        try:
            with open(self.salida, 'w', encoding='utf-8') as f:
                f.write(texto)
        except OSError:
            pass

    def marcar_cierre_limpio(self):
        # Si esta marca falta, es que el proceso murio de golpe.
        try:
            with open(self.salida + '.done', 'w') as fh:
                fh.write('ok')
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 6-bis. CARATULAS: LECTURA ESCALADA Y EN SEGUNDO PLANO
#
# Lo que hacia el motor viejo, y por que se cambia:
#
#   * pygame.image.load() decodifica la imagen ENTERA -una portada de Steam
#     son 600x900, y las "hero" pasan de 1920 de ancho- y solo despues se
#     escala a la casilla. QImageReader.setScaledSize() decodifica YA al
#     tamaño de destino: se ahorra el grueso del trabajo, no un retoque.
#
#   * las caches eran diccionarios con tope que, al llenarse, SE VACIABAN
#     ENTERAS (COVER_CACHE a las 40 entradas, _imgcache a las 120). En una
#     biblioteca grande eso significa recargar del disco cada vez que vuelves
#     a pasar por la misma fila. QPixmapCache es LRU y con presupuesto en
#     bytes: tira lo que menos se usa, no lo todo.
#
#   * la carga era sincrona: abrir la rejilla se paraba a leer las portadas
#     visibles antes de dibujar nada. Ahora se pide al pool de hilos y la
#     rejilla sale al instante; las portadas van apareciendo.
#
# REGLA QUE NO SE PUEDE SALTAR: QPixmap solo se toca en el hilo de la
# interfaz. Por eso el hilo trabajador devuelve un QImage (que si es seguro
# fuera de la GUI) y la conversion a QPixmap se hace al recibirlo.
# ---------------------------------------------------------------------------
CACHE_MB = 48
try:
    CACHE_MB = max(8, int(os.environ.get('WP_COVER_CACHE_MB', '48')))
except ValueError:
    pass


_forma_cache = {}


def es_ancha(ruta):
    # ¿La caratula es mas ancha que alta? Con QImageReader basta con leer la
    # CABECERA del fichero: da el tamaño sin decodificar la imagen, que es
    # justo lo que hacia falta y lo que el motor viejo no podia evitar (alli
    # se cargaba entera solo para preguntar por sus medidas).
    if not ruta:
        return False
    if ruta not in _forma_cache:
        try:
            tam = QtGui.QImageReader(ruta).size()
            forma = bool(tam.isValid() and tam.width() > tam.height())
        except Exception:
            forma = False
        # Con tope, como las demas: una entrada por caratula vista, y en una
        # biblioteca grande eso crece sin parar.
        if len(_forma_cache) > 300:
            _forma_cache.clear()
        _forma_cache[ruta] = forma
    return _forma_cache[ruta]


class BusImagenes(QtCore.QObject):
    lista = Signal(str, object)      # clave, QImage ya escalado


class TareaImagen(QtCore.QRunnable):
    def __init__(self, clave, ruta, ancho, alto, bus):
        QtCore.QRunnable.__init__(self)
        self.clave, self.ruta = clave, ruta
        self.ancho, self.alto, self.bus = ancho, alto, bus
        self.setAutoDelete(True)

    def run(self):
        img = QtGui.QImage()
        try:
            lector = QtGui.QImageReader(self.ruta)
            lector.setAutoTransform(True)     # respeta la orientacion EXIF
            tam = lector.size()
            if tam.isValid() and tam.width() > 0 and tam.height() > 0:
                if self.alto:
                    # CABE ENTERA, sin deformarla. Estirar hasta llenar la
                    # casilla achataba las portadas verticales en la vista
                    # ancha, que fue justo lo que se arreglo en su dia.
                    esc = min(self.ancho / float(tam.width()),
                              self.alto / float(tam.height()))
                else:
                    esc = self.ancho / float(tam.width())
                lector.setScaledSize(QtCore.QSize(
                    max(1, int(tam.width() * esc)),
                    max(1, int(tam.height() * esc))))
            img = lector.read()
        except Exception:
            img = QtGui.QImage()
        self.bus.lista.emit(self.clave, img)


# ---------------------------------------------------------------------------
# 7. LA VENTANA
#
# Un solo QWidget que se pinta entero a mano. Podria haber sido un
# QListWidget con hoja de estilos, y para un menu de escritorio seria lo
# sensato; pero aqui el aspecto (la rejilla en fuga, el escaneado CRT, las
# esquinas de HUD, la caratula grande) es el producto, y reproducirlo con
# QSS costaria mas que pintarlo. Los widgets de Qt entran donde aportan:
# el editor de texto y las barras de progreso.
# ---------------------------------------------------------------------------
class Pantalla(QtWidgets.QWidget):

    termina = Signal(int)      # codigo de salida de la peticion en curso

    def __init__(self, pet):
        QtWidgets.QWidget.__init__(self)
        self.pet = pet
        self.estado = ''            # texto de la pantalla de reposo
        self.en_reposo = True
        # Caratulas: cache LRU con presupuesto, peticiones en vuelo y las que
        # no se pudieron leer (para no reintentarlas en cada repintado).
        QtGui.QPixmapCache.setCacheLimit(CACHE_MB * 1024)
        self.bus_img = BusImagenes()
        self.bus_img.lista.connect(self.imagen_lista)
        self.pool = QtCore.QThreadPool(self)
        self.pool.setMaxThreadCount(
            max(1, min(4, QtCore.QThread.idealThreadCount())))
        self.pendientes = set()
        self.malas = set()
        # Un repintado por cada portada que llega serian decenas seguidas al
        # abrir la rejilla: se juntan en uno solo cada 40 ms.
        self.repintar_pronto = QtCore.QTimer(self)
        self.repintar_pronto.setSingleShot(True)
        self.repintar_pronto.setInterval(40)
        self.repintar_pronto.timeout.connect(self.update)
        self.t0 = time.time()
        # Antirrebote: un mando puede mandar la misma tecla por dos caminos
        # (evdev y el teclado del compositor) y la lista saltaba de dos en dos.
        self._ultima = [0, 0.0]
        self.DEBOUNCE = 0.06
        # Tiempo a partir del cual se hace caso al mando. Al abrir un menu se
        # pone un poco por delante: las señales que ya iban por el camino
        # cuando se cerro el anterior llegan aqui, y sin esta pausa el menu
        # nuevo se comia la pulsacion que cerro el viejo.
        self.sordo_hasta = 0.0
        self.mando = None
        self.ultimo_progreso = L('Preparando...', 'Preparing...')
        self.setWindowTitle('WProton')
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        # Fuentes: se crean una vez. Qt las escala solo por punto, asi que
        # basta con recalcular los tamaños al cambiar de resolucion.
        self.calcular_metricas()
        # Latido para las pantallas animadas. En las quietas se para: no hay
        # razon para gastar bateria repintando una lista que no se mueve.
        self.latido = QtCore.QTimer(self)
        self.latido.timeout.connect(self.update)
        self.reajustar_latido()

    # -- tipografia y medidas ---------------------------------------------
    def calcular_metricas(self):
        # TAMAÑOS FIJOS, COMO EN EL MOTOR VIEJO, no proporcionales a la
        # ventana. El menu de pygame usa px fijos y deja que la pantalla
        # grande simplemente quepa mas; si aqui se escalara con la altura, el
        # mismo tema se veria distinto en cada equipo y dejarian de ser
        # comparables. Lo que si cambia es la escala de letra del usuario
        # (WP_FONT_SCALE) y el HiDPI, que Qt aplica solo.
        #
        # El 0,75: pygame.font.Font(None, N) toma N como ALTO de linea, y
        # QFont.setPixelSize toma el cuerpo. Sin el factor, la misma cifra da
        # una letra visiblemente mayor en Qt.
        def f(px, bold=False, ancha=False):
            ft = QFont('DejaVu Sans')
            ft.setPixelSize(max(10, int(FS(px) * 0.75)))
            ft.setBold(bold)
            if ancha and TH.get('tracking'):
                # Espaciado entre letras: Qt lo ajusta con precision
                # subpixel, y en un titulo grande se nota mucho.
                ft.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
            return ft
        self.f_tit = f(34, True, ancha=True)
        self.f_it = f(30)
        self.f_sm = f(24)
        self.f_kb = f(28)
        self.fm_tit = QtGui.QFontMetrics(self.f_tit)
        self.fm_it = QtGui.QFontMetrics(self.f_it)
        self.fm_sm = QtGui.QFontMetrics(self.f_sm)
        self.calcular_disposicion()

    def calcular_disposicion(self):
        # Todo lo que depende del titulo, del modo y del tamaño de ventana.
        # Es apply_layout() + compute_layout() del motor viejo, juntos: alli
        # estaban separados porque uno se llamaba al cambiar de peticion y el
        # otro al cambiar de ventana; aqui los dos casos pasan por aqui.
        pet = self.pet
        W, H = self.width(), self.height()
        self.PANEL_UI = TH.get('layout') in ('panel', 'arcade')
        self.ARCADE = TH.get('layout') == 'arcade'
        self.T_FONT = self.f_tit if len(pet.titulo) < 60 else self.f_it
        fm_t = QtGui.QFontMetrics(self.T_FONT)
        self.TITLE_LINES = self.partir_titulo(pet.titulo, fm_t, min(912, W - 220))
        self.T_LH = FS(34) if self.T_FONT is self.f_tit else FS(30)
        self.HEAD = int(22 * FSCALE) + len(self.TITLE_LINES) * self.T_LH + 14
        self.ROW = max(TH['row'], int(TH['row'] * FSCALE))
        top = (self.HEAD + 30) if pet.modo == 'browse' else self.HEAD
        if self.PANEL_UI and pet.modo == 'grid':
            # en rejilla no hay panel lateral: todo el ancho para las portadas
            self.LIST_X, self.LIST_Y = 20, self.HEAD + 16
            self.LIST_H = H - self.LIST_Y - 76
            self.LIST_W = W - 40
            self.SIDE_W = self.SIDE_X = 0
        elif self.PANEL_UI:
            self.LIST_X, self.LIST_Y = 20, self.HEAD + 16
            self.LIST_H = H - self.LIST_Y - 76
            if pet.modo in ('list', 'check', 'browse') and W >= 820:
                self.SIDE_W = max(240, int(W * 0.34))
                self.SIDE_X = W - self.SIDE_W - 20
                self.LIST_W = self.SIDE_X - self.LIST_X - 16
            else:
                self.SIDE_W = self.SIDE_X = 0
                self.LIST_W = W - 40
        else:
            self.LIST_X, self.LIST_Y = 16, top
            self.LIST_W, self.LIST_H = W - 32, H - top - 60
        self.VIS_FULL = max(1, self.LIST_H // self.ROW)
        self.VIS_KB = max(1, (self.LIST_H - KB_H) // self.ROW)

    def vis(self):
        return self.VIS_KB if self.pet.kb_open else self.VIS_FULL

    def partir_titulo(self, texto, fm, maxw):
        lineas = []
        for cruda in (texto or '').split('\n'):
            actual = ''
            for palabra in cruda.split():
                prueba = (actual + ' ' + palabra).strip()
                if actual and fm.horizontalAdvance(prueba) > maxw:
                    lineas.append(actual)
                    actual = palabra
                else:
                    actual = prueba
            lineas.append(actual)
        return lineas[:6] or ['']

    def reajustar_latido(self):
        # 30 fps solo cuando hay algo que animar. Con los temas moderno y
        # arcade eso incluye la lista: el marcador late y los titulos largos
        # de la fila elegida se desplazan.
        anima = (self.en_reposo
                 or self.pet.modo in ('progress', 'canvas')
                 or TH.get('marker') or TH.get('glow'))
        if anima:
            if not self.latido.isActive():
                self.latido.start(33)
        else:
            self.latido.stop()
            self.update()

    def resizeEvent(self, ev):
        self.calcular_metricas()
        # La cache NO se vacia: la clave lleva el tamaño, asi que las de la
        # medida anterior envejecen solas y, si se vuelve al tamaño de antes
        # (ventana <-> pantalla completa), siguen ahi.
        QtWidgets.QWidget.resizeEvent(self, ev)

    # -- primitivas del tema ----------------------------------------------
    def hbar(self, p, rect, c1, c2):
        # Barra con degradado horizontal (cabecera y seleccion del moderno)
        g = QtGui.QLinearGradient(rect.left(), 0, rect.right(), 0)
        g.setColorAt(0.0, C(c1))
        g.setColorAt(1.0, C(c2))
        p.fillRect(rect, g)

    def vbar(self, p, rect, c1, c2):
        # Degradado vertical: da relieve de boton a las filas
        g = QtGui.QLinearGradient(0, rect.top(), 0, rect.bottom())
        g.setColorAt(0.0, C(c1))
        g.setColorAt(1.0, C(c2))
        p.fillRect(rect, g)

    @staticmethod
    def notch(rect, n=15):
        # Cantos cortados en diagonal (arriba-derecha y abajo-izquierda)
        x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
        return QtGui.QPolygon([QPoint(x, y), QPoint(x + w - n, y),
                               QPoint(x + w, y + n), QPoint(x + w, y + h),
                               QPoint(x + n, y + h), QPoint(x, y + h - n)])

    def boton_notch(self, p, rect, activo):
        # Moderno: capsula achaflanada, relleno plano y pestaña de acento
        pts = self.notch(rect)
        if activo:
            relleno = tuple(min(255, int(c * 0.34) + 18) for c in ACC)
        else:
            relleno = TH['card']
        p.setPen(QtGui.QPen(C(ACC if activo else TH['border']), 2 if activo else 1))
        p.setBrush(C(relleno))
        p.drawPolygon(pts)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(ACC if activo else TH['border']))
        p.drawRect(rect.x(), rect.y() + (0 if activo else 8),
                   6 if activo else 3, rect.height() - (0 if activo else 16))
        if activo:
            p.setBrush(C(TH.get('acc2', ACC)))
            p.drawRect(rect.x() + rect.width() - 15, rect.y(), 15, 3)

    def boton_pill(self, p, rect, activo):
        # Cristal: capsula translucida. En reposo casi no se ve -solo un velo
        # y un filo-; al elegirla se enciende y le da la vuelta un brillo
        # conico, que es un degradado alrededor de un centro y no existe como
        # tal en el motor viejo.
        r = QRectF(rect)
        p.setPen(Qt.PenStyle.NoPen)
        g = QtGui.QLinearGradient(0, rect.top(), 0, rect.bottom())
        if activo:
            g.setColorAt(0.0, C(TH['sel_bg'], 214))
            g.setColorAt(1.0, C(TH['card'], 150))
        else:
            g.setColorAt(0.0, C(TH['card'], 104))
            g.setColorAt(1.0, C(TH['card'], 56))
        p.setBrush(QtGui.QBrush(g))
        p.drawRoundedRect(r, RAD, RAD)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if activo and TH.get('sheen'):
            con = QtGui.QConicalGradient(rect.center().x(), rect.center().y(),
                                         (time.time() * 90.0) % 360.0)
            con.setColorAt(0.0, C(ACC, 255))
            con.setColorAt(0.25, C(TH.get('acc2', ACC), 190))
            con.setColorAt(0.5, C(ACC, 60))
            con.setColorAt(0.75, C(TH.get('acc2', ACC), 190))
            con.setColorAt(1.0, C(ACC, 255))
            p.setPen(QtGui.QPen(QtGui.QBrush(con), 2))
        else:
            p.setPen(QtGui.QPen(C(TH['border'], 70), 1))
        p.drawRoundedRect(r, RAD, RAD)
        # filo claro en el borde de arriba: el vidrio recoge la luz
        p.setPen(QtGui.QPen(QColor(255, 255, 255, 54 if activo else 26), 1))
        p.drawLine(rect.x() + RAD, rect.y() + 1,
                   rect.x() + rect.width() - RAD, rect.y() + 1)
        p.setPen(Qt.PenStyle.NoPen)

    def boton(self, p, rect, activo):
        # Fila con aspecto de boton: relieve, borde y brillo superior
        if TH.get('shape') == 'pill':
            self.boton_pill(p, rect, activo)
            return
        if TH.get('shape') == 'notch':
            self.boton_notch(p, rect, activo)
            return
        if activo:
            base = tuple(min(255, int(c * 0.42)) for c in ACC)
            self.vbar(p, rect, base, TH['panel'])
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QtGui.QPen(C(ACC), 2))
            p.drawRoundedRect(QRectF(rect), RAD, RAD)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(ACC))
            p.drawRoundedRect(QRectF(QRect(rect.x() + 2, rect.y() + 4,
                                           5, rect.height() - 8)), 2, 2)
        else:
            c1 = tuple(min(255, c + 14) for c in TH['card'])
            self.vbar(p, rect, c1, TH['card'])
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QtGui.QPen(C(TH['border']), 1))
            p.drawRoundedRect(QRectF(rect), RAD, RAD)
            p.setPen(Qt.PenStyle.NoPen)
        # brillo sutil en el borde superior
        hl = tuple(min(255, c + (46 if activo else 22)) for c in TH['card'])
        p.setBrush(C(hl))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(rect.x() + 3, rect.y() + 1, rect.width() - 6, 1)

    def seleccion(self, p, rect):
        # clasico: barra plana | moderno: tarjeta | arcade: barra con marcador
        # cristal: la misma capsula de vidrio que las filas, para que la
        # rejilla y el teclado no parezcan de otro tema
        if TH.get('shape') == 'pill':
            self.boton_pill(p, rect, True)
            return
        if TH.get('marker'):
            self.hbar(p, rect, TH['sel_bg'], TH['bg'])
            # El latido: el borde se enciende y se apaga. Es el mismo reloj
            # que usa la onda del reposo, para que la pantalla respire igual
            # en los menus y entre ellos.
            pulso = 0.55 + 0.45 * abs(((time.time() * 1.6) % 2.0) - 1.0)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QtGui.QPen(C(tuple(int(c * pulso) for c in ACC)), 2))
            p.drawRect(rect)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(ACC))
            p.drawRect(rect.x(), rect.y(), 6, rect.height())
            p.drawPolygon(QtGui.QPolygon([
                QPoint(rect.x() + 14, rect.y() + rect.height() // 2),
                QPoint(rect.x() + 4, rect.y() + 8),
                QPoint(rect.x() + 4, rect.y() + rect.height() - 8)]))
            return
        if TH['pill']:
            self.seleccion_moderno(p, rect)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(TH['sel_bg']))
            p.drawRoundedRect(QRectF(rect), RAD, RAD)

    def texto_halo(self, p, x, y, font, texto, color, halo=None, pasadas=2):
        # EL TEXTO COMO FIGURA, NO COMO TEXTO.
        #
        # QPainterPath.addText convierte las letras en contorno. Eso permite
        # rodearlas con un trazo cada vez mas ancho y transparente y sumarlo
        # (CompositionMode_Plus): un halo de verdad, que se acumula donde se
        # cruzan los trazos. El motor viejo solo podia calcar el texto
        # desplazado, que es una sombra, no un resplandor.
        #
        # Dos pasadas bastan: con mas se emborrona y cuesta el triple.
        fm = QtGui.QFontMetrics(font)
        camino = QtGui.QPainterPath()
        camino.addText(float(x), float(y + fm.ascent()), font, texto)
        p.save()
        if halo:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for k in range(pasadas, 0, -1):
                pluma = QtGui.QPen(C(halo, int(26 + 16 * (pasadas - k))),
                                   2 + 4 * k)
                pluma.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                pluma.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pluma)
                p.drawPath(camino)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(color))
        p.drawPath(camino)
        p.restore()
        return fm.horizontalAdvance(texto)

    def seleccion_moderno(self, p, rect):
        # La tarjeta de "moderno": barra con degradado, borde de acento y la
        # pestaña de la izquierda. Cristal la reutiliza en la rejilla.
        self.hbar(p, rect, TH['sel_bg'], TH['panel'])
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QtGui.QPen(C(ACC), 1))
        p.drawRoundedRect(QRectF(rect), RAD, RAD)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(ACC))
        p.drawRoundedRect(QRectF(QRect(rect.x() + 2, rect.y() + 5,
                                       5, rect.height() - 10)), 3, 3)

    def marca(self, p, x, y, font, color=None):
        # "WPROTON" con la W en morado y el resto en el color de acento.
        # Devuelve el ancho, para poder colocar lo que va detras.
        fm = QtGui.QFontMetrics(font)
        c_w = color if color else MORADO_W
        c_r = color if color else CIAN_PROTON
        if TH.get('pathtext') and color is None:
            ancho_w = self.texto_halo(p, x, y, font, 'W', c_w, MORADO_W)
            return ancho_w + self.texto_halo(p, x + ancho_w, y, font,
                                             'PROTON', c_r, CIAN_PROTON)
        p.setFont(font)
        p.setPen(C(c_w))
        p.drawText(QPoint(x, y + fm.ascent()), 'W')
        ancho_w = fm.horizontalAdvance('W')
        p.setPen(C(c_r))
        p.drawText(QPoint(x + ancho_w, y + fm.ascent()), 'PROTON')
        return ancho_w + fm.horizontalAdvance('PROTON')

    def estrella(self, p, cx, cy, r, color):
        # Estrella de cinco puntas dibujada a mano: el simbolo tipografico no
        # existe en la fuente por defecto y un asterisco quedaba pobre.
        pts = []
        for i in range(10):
            ang = math.pi / 2 + i * math.pi / 5
            rad = r if i % 2 == 0 else r * 0.45
            pts.append(QtCore.QPointF(cx + rad * math.cos(ang),
                                      cy - rad * math.sin(ang)))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(color))
        p.drawPolygon(QtGui.QPolygonF(pts))

    def chip(self, p, x, y, tecla, texto, font):
        # "Pastilla" de ayuda: [A] elegir
        fm = QtGui.QFontMetrics(font)
        p.setFont(font)
        bw = fm.horizontalAdvance(tecla) + 16
        alto = FS(24)
        rect = QRect(x, y, bw, alto)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(ACC))
        if self.ARCADE:
            p.drawRect(rect)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QtGui.QPen(C(TH.get('acc2', ACC)), 1))
            p.drawRect(rect)
        else:
            p.drawRoundedRect(QRectF(rect), 8, 8)
        p.setPen(C(TH['bg']))
        p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), tecla)
        p.setPen(C(DIM))
        p.drawText(QRect(x + bw + 8, y, 400, alto),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                   texto)
        return x + bw + 16 + fm.horizontalAdvance(texto)

    # -- texto de fila: recorte, marquesina y colores ----------------------
    def recortar(self, texto, fm, maxw):
        return fm.elidedText(texto, Qt.TextElideMode.ElideRight, maxw)

    def texto_fila(self, p, texto, font, color, x, y, maxw, activo):
        # Si el texto no cabe: en la fila elegida se desplaza (marquesina), en
        # las demas se recorta. Antes se salia de la tarjeta e invadia el panel.
        fm = QtGui.QFontMetrics(font)
        p.setFont(font)
        p.setPen(C(color))
        ancho = fm.horizontalAdvance(texto)
        base = y + fm.ascent()
        if ancho <= maxw:
            p.drawText(QPoint(x, base), texto)
            return
        if not activo:
            p.drawText(QPoint(x, base), self.recortar(texto, fm, maxw))
            return
        p.save()
        p.setClipRect(QRect(x, y - 2, maxw, self.ROW))
        p.drawText(QPoint(x - int((ancho - maxw) * self.vaiven(ancho - maxw)), base),
                   texto)
        p.restore()

    @staticmethod
    def vaiven(sobra):
        # Ida y vuelta con pausa en los extremos. Cuanto mas largo el texto,
        # mas despacio: si no, un titulo muy largo pasaba disparado.
        periodo = 2.2 + sobra / 70.0
        tt = (time.time() % (periodo * 2)) / periodo
        f = tt if tt <= 1.0 else 2.0 - tt
        return max(0.0, min(1.0, (f - 0.14) / 0.72))

    @staticmethod
    def segmentos(label, base):
        # "Prefijo: compartido" -> etiqueta en acento, valor en blanco.
        # "MangoHud: ON" -> ON en verde, OFF apagado.
        if not TH.get('labelcolor') or ':' not in label:
            return [(label, base)]
        k, _, v = label.partition(':')
        # "arcade - synthwave: ..." no es etiqueta+valor, es una descripcion
        if ' - ' in k or len(k) > 36:
            return [(label, base)]
        # Unos dos puntos DENTRO de un parentesis no separan etiqueta y valor:
        # son parte del texto, como la proporcion "(2:3)".
        if k.count('(') > k.count(')'):
            return [(label, base)]
        segs = [(k + ':', TH.get('acc2', ACC))]
        v = v.strip()
        if v:
            low = v.lower()
            if low in ('on', 'si'):
                segs.append((' ' + v, TH.get('ok', ACC)))
            elif low in ('off', 'no'):
                segs.append((' ' + v, DIM))
            else:
                segs.append((' ' + v, base))
        return segs

    def pintar_segmentos(self, p, segs, font, x, y, maxw, activo):
        fm = QtGui.QFontMetrics(font)
        p.setFont(font)
        base = y + fm.ascent()
        anchos = [fm.horizontalAdvance(t) for t, _ in segs]
        total = sum(anchos)
        if total <= maxw:
            cx = x
            for (t, col), an in zip(segs, anchos):
                p.setPen(C(col))
                p.drawText(QPoint(cx, base), t)
                cx += an
            return
        if not activo:
            cx, resto = x, maxw
            for (t, col), an in zip(segs, anchos):
                p.setPen(C(col))
                if an <= resto:
                    p.drawText(QPoint(cx, base), t)
                    cx += an
                    resto -= an
                else:
                    p.drawText(QPoint(cx, base), self.recortar(t, fm, resto))
                    break
            return
        p.save()
        p.setClipRect(QRect(x, y - 2, maxw, self.ROW))
        cx = x - int((total - maxw) * self.vaiven(total - maxw))
        for (t, col), an in zip(segs, anchos):
            p.setPen(C(col))
            p.drawText(QPoint(cx, base), t)
            cx += an
        p.restore()

    # -- pintado -----------------------------------------------------------
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.pintar_fondo(p)
        try:
            if self.en_reposo:
                self.pintar_reposo(p)
            elif self.pet.modo == 'progress':
                self.pintar_progreso(p)
            elif self.pet.modo == 'text':
                self.pintar_texto(p)
            else:
                self.pintar_menu(p)
        except Exception as e:
            # Un fallo dibujando no puede tumbar el servidor: se anota y se
            # sigue, que el usuario aun tiene sus menus.
            sys.stderr.write('menu_qt: al pintar: %s\n' % e)
        if TH.get('vineta'):
            self.pintar_vineta(p)
        if TH.get('scan'):
            self.pintar_escaneado(p)
        p.end()

    def pintar_fondo(self, p):
        w, h = self.width(), self.height()
        if TH.get('gridbg'):
            # Cielo degradado + horizonte con rejilla en fuga (synthwave)
            hz = int(h * 0.42)
            g = QtGui.QLinearGradient(0, 0, 0, hz)
            g.setColorAt(0.0, C(TH['bg2']))
            g.setColorAt(1.0, C(TH['bg']))
            p.fillRect(0, 0, w, hz, g)
            p.fillRect(0, hz, w, h - hz, C(TH['bg']))
            p.fillRect(0, hz - 2, w, 2, C(ACC))
            p.setPen(QtGui.QPen(C(TH['border']), 1))
            vp = w // 2
            for k in range(-14, 15):
                p.drawLine(vp + k * 46, hz, vp + k * 300, h)
            yy, paso = hz + 6, 6
            while yy < h:
                p.drawLine(0, yy, w, yy)
                paso = int(paso * 1.42) + 1
                yy += paso
        elif TH.get('orbes'):
            # Degradado en DIAGONAL y dos focos de color encima. Con SDL esto
            # habria que resolverlo pintando cada pixel; aqui son tres
            # rellenos y los hace la propia libreria.
            g = QtGui.QLinearGradient(0, 0, w, h)
            g.setColorAt(0.0, C(TH['bg']))
            g.setColorAt(0.55, C(TH['bg2']))
            g.setColorAt(1.0, C(TH['bg']))
            p.fillRect(0, 0, w, h, g)
            for cx, cy, rad, color in (
                    (w * 0.16, h * 0.12, w * 0.42, TH['acc']),
                    (w * 0.88, h * 0.86, w * 0.46, TH['acc2'])):
                orbe = QtGui.QRadialGradient(cx, cy, rad)
                orbe.setColorAt(0.0, C(color, 54))
                orbe.setColorAt(0.55, C(color, 18))
                orbe.setColorAt(1.0, C(color, 0))
                p.fillRect(0, 0, w, h, orbe)
        elif TH['bg'] == TH['bg2']:
            p.fillRect(0, 0, w, h, C(TH['bg']))
        else:
            g = QtGui.QLinearGradient(0, 0, 0, h)
            g.setColorAt(0.0, C(TH['bg']))
            g.setColorAt(1.0, C(TH['bg2']))
            p.fillRect(0, 0, w, h, g)

    def pintar_vineta(self, p):
        # Oscurecido suave hacia los bordes: centra la mirada y disimula que
        # la pantalla completa de una consola portatil es muy ancha.
        w, h = self.width(), self.height()
        v = QtGui.QRadialGradient(w / 2.0, h / 2.0, max(w, h) * 0.72)
        v.setColorAt(0.0, QColor(0, 0, 0, 0))
        v.setColorAt(0.62, QColor(0, 0, 0, 0))
        v.setColorAt(1.0, QColor(0, 0, 0, 150))
        p.fillRect(0, 0, w, h, v)

    def pintar_escaneado(self, p):
        # Velo CRT. En pygame era una superficie pregenerada; aqui son lineas
        # sueltas y sale mas barato que guardar un pixmap del tamaño de la
        # pantalla y rehacerlo en cada cambio de resolucion.
        p.setPen(QtGui.QPen(QColor(0, 0, 0, 46), 1))
        for y in range(0, self.height(), 3):
            p.drawLine(0, y, self.width(), y)

    def pintar_panel_solido(self, p, rect):
        # El panel de "moderno": relleno opaco, esquinas de HUD si el tema las
        # pide y un borde fino. Se saca aparte porque cristal lo usa para la
        # ficha aunque todo lo demas sea de vidrio.
        if TH['panel'] is None:
            return
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(TH['panel']))
        p.drawRoundedRect(QRectF(rect), RAD, RAD)
        if TH.get('brackets'):
            x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
            ln, t = 26, 3
            p.setBrush(C(ACC))
            for (cx, cy, dx, dy) in ((x, y, 1, 1), (x + w, y, -1, 1),
                                     (x, y + h, 1, -1), (x + w, y + h, -1, -1)):
                p.drawRect(min(cx, cx + dx * ln), cy - (t if dy < 0 else 0), ln, t)
                p.drawRect(cx - (t if dx < 0 else 0), min(cy, cy + dy * ln), t, ln)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QtGui.QPen(C(TH['border']), 1))
        p.drawRoundedRect(QRectF(rect), RAD, RAD)
        p.setPen(Qt.PenStyle.NoPen)

    def pintar_panel(self, p, rect):
        if TH['panel'] is None:
            return
        if TH.get('glass'):
            # CRISTAL DE VERDAD: el relleno es translucido y el fondo -con sus
            # orbes- se ve por debajo. Encima, dos filos de un pixel: claro
            # arriba y oscuro abajo, que es lo que da el relieve de vidrio.
            p.setPen(Qt.PenStyle.NoPen)
            g = QtGui.QLinearGradient(0, rect.top(), 0, rect.bottom())
            g.setColorAt(0.0, C(TH['panel'], 176))
            g.setColorAt(1.0, C(TH['bg'], 132))
            p.setBrush(QtGui.QBrush(g))
            p.drawRoundedRect(QRectF(rect), RAD, RAD)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QtGui.QPen(C(TH['border'], 96), 1))
            p.drawRoundedRect(QRectF(rect), RAD, RAD)
            p.setPen(QtGui.QPen(QColor(255, 255, 255, 40), 1))
            p.drawLine(rect.x() + RAD, rect.y() + 1,
                       rect.x() + rect.width() - RAD, rect.y() + 1)
            p.setPen(Qt.PenStyle.NoPen)
            return
        self.pintar_panel_solido(p, rect)

    def pintar_cabecera(self, p):
        # Cabecera de marca a todo lo ancho, con acento y contador
        pet = self.pet
        W = self.width()
        hh = self.HEAD - 6
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(TH['panel']))
        p.drawRect(0, 0, W, hh)
        self.hbar(p, QRect(0, hh - 3, W, 3), ACC, TH.get('acc2', ACC))
        if self.ARCADE:
            # sombra de un color y encima la marca a dos colores
            self.marca(p, 27, 19, self.f_tit, TH['acc2'])
        ancho_marca = self.marca(p, 24, 16, self.f_tit)
        bx = 24 + ancho_marca + 16
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(TH['border']))
        p.drawRect(bx - 8, 14, 2, hh - 34)
        p.setFont(self.T_FONT)
        fm = QtGui.QFontMetrics(self.T_FONT)
        p.setPen(C(FG))
        for i, linea in enumerate(self.TITLE_LINES):
            p.drawText(QPoint(bx, 16 + i * self.T_LH + fm.ascent()),
                       self.recortar(linea, fm, W - bx - 150))
        if pet.view:
            texto = '%d/%d' % (pet.sel + 1, len(pet.view))
            bw = self.fm_sm.horizontalAdvance(texto) + 18
            rect = QRect(W - bw - 20, 18, bw, FS(24))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(ACC))
            p.drawRoundedRect(QRectF(rect), 12, 12)
            p.setFont(self.f_sm)
            p.setPen(C(TH['bg']))
            p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), texto)

    def pintar_pie(self, p, chips):
        W, H = self.width(), self.height()
        fy = H - 46
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(TH['panel']))
        p.drawRect(0, fy - 8, W, 54)
        self.hbar(p, QRect(0, fy - 10, W, 2), TH.get('acc2', ACC), ACC)
        x = 24
        for k, t in chips:
            x = self.chip(p, x, fy + 6, k, t, self.f_sm)
            if x > W - 160:
                break

    # -- menu: lista, seleccion multiple, navegador y rejilla --------------
    def pintar_menu(self, p):
        pet = self.pet
        self.pintar_cabecera(p)
        if self.PANEL_UI:
            self.pintar_panel(p, QRect(self.LIST_X - 6, self.LIST_Y,
                                       self.LIST_W + 12, self.LIST_H))
            if self.SIDE_W:
                self.pintar_ficha(p, QRect(self.SIDE_X, self.LIST_Y,
                                           self.SIDE_W, self.LIST_H))
        else:
            if pet.modo == 'browse':
                p.setFont(self.f_sm)
                p.setPen(C(DIM))
                p.drawText(QPoint(24, self.HEAD - 8 + self.fm_sm.ascent()),
                           acortar(pet.cur_path))
            ry = (self.HEAD + 20) if pet.modo == 'browse' else (self.HEAD - 8)
            p.setPen(QtGui.QPen(C(TH['border']), 1))
            p.drawLine(24, ry, self.width() - 24, ry)
        if pet.modo == 'grid':
            self.pintar_rejilla(p)
        else:
            self.pintar_filas(p)
        self.pintar_barra_scroll(p)
        self.pintar_busqueda(p)
        if pet.kb_open:
            self.pintar_teclado(p)
        else:
            self.pintar_pie(p, self.chips())

    def pintar_filas(self, p):
        pet = self.pet
        vis = self.vis()
        if pet.sel < pet.scroll:
            pet.scroll = pet.sel
        elif pet.sel >= pet.scroll + vis:
            pet.scroll = pet.sel - vis + 1
        if not pet.view and pet.filtro:
            p.setFont(self.f_it)
            p.setPen(C(WARN))
            p.drawText(QPoint(self.LIST_X + 14,
                              self.LIST_Y + 14 + self.fm_it.ascent()),
                       L("(sin coincidencias para '%s')",
                         "(nothing matches '%s')") % pet.filtro)
            return
        for i in range(pet.scroll, min(pet.scroll + vis, len(pet.view))):
            y = self.LIST_Y + 8 + (i - pet.scroll) * self.ROW
            rect = QRect(self.LIST_X, y - 4, self.LIST_W, self.ROW - 6)
            activo = (i == pet.sel and not pet.kb_open)
            if TH.get('btn'):
                self.boton(p, rect, activo)
                if activo and TH.get('marker'):
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(C(ACC))
                    p.drawPolygon(QtGui.QPolygon([
                        QPoint(self.LIST_X + 20, y + self.ROW // 2 - 4),
                        QPoint(self.LIST_X + 10, y + 2),
                        QPoint(self.LIST_X + 10, y + self.ROW - 14)]))
            else:
                if self.PANEL_UI and not activo:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(C(TH['card']))
                    p.drawRoundedRect(QRectF(rect), RAD, RAD)
                if activo:
                    self.seleccion(p, rect)
            kind, txt, marcado = pet.items[pet.view[i]]
            favorito = False
            if pet.modo == 'check':
                label = ('[x] ' if marcado else '[  ] ') + txt
                color = ACC if marcado else FG
            elif kind == K_DIR:
                label, color = txt, DIRC
            elif kind in HEADER_KINDS:
                label, color = txt, (ACC if kind == K_HDR else DIM)
            else:
                label, color = txt, FG
                # Marca de favorito en la propia lista: al pulsar R1 se ve al
                # momento cual esta marcado, sin mirar el panel.
                if pet.modo == 'list' and pet.info.get(txt, {}).get('fav') == '1':
                    favorito = True
            tx = self.LIST_X + (18 if self.PANEL_UI else 14)
            if TH.get('numbered'):
                p.setFont(self.f_sm)
                p.setPen(C(ACC if activo else TH['border']))
                p.drawText(QPoint(self.LIST_X + 28, y + 12 + self.fm_sm.ascent()),
                           '%02d' % (i + 1))
                tx += 46
            ty = y + (6 if self.PANEL_UI else 0)
            tw = self.LIST_X + self.LIST_W - tx - 18
            if TH.get('shadow'):
                self.texto_fila(p, label, self.f_it, (0, 0, 0),
                                tx + 2, ty + 2, tw, activo)
            if favorito:
                # Estrella a la DERECHA: delante quedaba pegada al nombre. Se
                # reserva su hueco para que un titulo largo no la pise.
                tw -= FS(26)
                self.estrella(p, self.LIST_X + self.LIST_W - FS(24),
                              y + self.ROW // 2, FS(8), TH.get('acc2', ACC))
            if kind in HEADER_KINDS or pet.modo == 'check':
                self.texto_fila(p, label, self.f_it, color, tx, ty, tw, activo)
            else:
                self.pintar_segmentos(p, self.segmentos(label, color),
                                      self.f_it, tx, ty, tw, activo)

    def pintar_barra_scroll(self, p):
        # Avisa de que hay mas opciones de las que caben en pantalla
        pet = self.pet
        total = len(pet.view)
        vis = self.filas_rejilla() * self.columnas() if pet.modo == 'grid' else self.vis()
        if total <= vis:
            return
        x = (self.LIST_X + self.LIST_W + 2) if self.PANEL_UI else (self.width() - 14)
        y = self.LIST_Y + 8
        alto = self.LIST_H - 16
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(TH['card']))
        p.drawRoundedRect(QRectF(QRect(x, y, 4, alto)), 2, 2)
        h_pulgar = max(24, int(alto * vis / float(total)))
        pos = int((alto - h_pulgar) * pet.scroll / float(max(1, total - vis)))
        p.setBrush(C(ACC))
        p.drawRoundedRect(QRectF(QRect(x, y + pos, 4, h_pulgar)), 2, 2)

    def aspecto(self):
        return ASPECTOS.get(self.pet.aspecto or '', 1.5)

    def medidas_rejilla(self):
        # Tamaño de caratula segun la pantalla. LA REGLA QUE MANDA ES LA
        # ALTURA: la caratula debe caber en su fila con holgura (2 filas en
        # monitores, 1 fila grande en portatiles). Repartiendo solo el ancho,
        # en un monitor de sobremesa salian gigantes.
        #
        # Devuelve (columnas, ancho_img, alto_img, alto_casilla).
        asp = self.aspecto()
        # Margen a la derecha para el indicador de desplazamiento: sin el, las
        # caratulas anchas de la ultima columna se metian debajo de la barra.
        avail_w = (self.LIST_W if self.PANEL_UI else (self.width() - 40)) - 18
        avail_h = max(120, self.LIST_H - 16)
        forzadas = GRID_COLS
        if forzadas > 0 or avail_h < 620:
            filas = 1 if avail_h < 620 else 2
        else:
            filas = 2
        h_max = int(avail_h / filas) - 48
        w_desde_h = int(h_max / asp)
        w = self.width()
        w_cap = 190 if w <= 1400 else (210 if w <= 1920 else 240)
        if asp < 1:
            # horizontales: mas anchas, caben menos por fila
            w_cap = int(w_cap * 2.1)
        if forzadas > 0:
            # columnas fijadas por el usuario: la caratula se calcula para que
            # QUEPAN esas columnas. Antes se mantenia el tamaño y con muchas
            # columnas se salian de la pantalla.
            cols = forzadas
            gcw = max(80, avail_w // forzadas)
            img_w = max(90, gcw - 26)
            if int(img_w * asp) + 48 > int(avail_h / filas):
                img_w = max(90, int((int(avail_h / filas) - 48) / asp))
        else:
            img_w = max(120, min(w_desde_h, w_cap))
            gcw = img_w + 26
            cols = max(3, min(9, avail_w // gcw))
            if cols * gcw > avail_w:
                # EL MINIMO DE TRES COLUMNAS NO PUEDE SALIRSE DE LA PANTALLA.
                #
                # Con caratulas panoramicas en una Deck salian tres de 399 px
                # = 1275, y el ancho util son 1222: la tercera se cortaba por
                # la derecha. El minimo se respeta encogiendo la caratula, que
                # es lo que se queria decir con "al menos tres".
                img_w = max(90, avail_w // cols - 26)
        img_h = max(40, int(img_w * asp))
        return max(1, cols), img_w, img_h, img_h + 48

    def columnas(self):
        return self.medidas_rejilla()[0]

    def filas_rejilla(self):
        _, _, _, alto_casilla = self.medidas_rejilla()
        return max(1, self.LIST_H // alto_casilla)

    def pintar_rejilla(self, p):
        pet = self.pet
        cols, img_w, img_h, alto_casilla = self.medidas_rejilla()
        filas_vis = max(1, self.LIST_H // alto_casilla)
        fila_sel = pet.sel // cols
        if fila_sel < pet.scroll:
            pet.scroll = fila_sel
        elif fila_sel >= pet.scroll + filas_vis:
            pet.scroll = fila_sel - filas_vis + 1
        # Las casillas se centran en el ancho util: con caratulas anchas
        # sobraba sitio a la derecha y la rejilla quedaba descolgada.
        paso_x = img_w + 26
        sobra = max(0, self.LIST_W - 18 - cols * paso_x)
        x0 = self.LIST_X + sobra // 2 + 13
        for pos in range(pet.scroll * cols,
                         min(len(pet.view), (pet.scroll + filas_vis) * cols)):
            n = pos - pet.scroll * cols
            r, c = divmod(n, cols)
            x = x0 + c * paso_x
            y = self.LIST_Y + 8 + r * alto_casilla
            fila = pet.gitems[pet.view[pos]]
            activo = (pos == pet.sel)
            if activo:
                marco = QRect(x - 8, y - 8, img_w + 16, alto_casilla - 8)
                if TH.get('media') == 'moderno':
                    self.seleccion_moderno(p, marco)
                else:
                    self.seleccion(p, marco)
            pix = self.imagen(fila[1], img_w, img_h)
            if pix is not None:
                p.drawPixmap(x, y, pix)
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(TH['card']))
                p.drawRoundedRect(QRectF(QRect(x, y, img_w, img_h)), RAD, RAD)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QtGui.QPen(C(TH['border']), 1))
            p.drawRect(x, y, img_w, img_h)
            p.setPen(Qt.PenStyle.NoPen)
            if str(fila[3]) == '1':
                self.estrella(p, x + img_w - FS(14), y + FS(14),
                              FS(9), TH.get('acc2', ACC))
            self.texto_fila(p, fila[0], self.f_sm, FG if activo else DIM,
                            x, y + img_h + 6, img_w, activo)

    def pintar_ficha(self, p, rect):
        # Panel derecho: el detalle de lo elegido. En la lista de juegos
        # enseña ademas la CARATULA y los datos, para que la lista no sea solo
        # una columna de nombres.
        pet = self.pet
        if TH.get('media') == 'moderno':
            self.pintar_panel_solido(p, rect)
        else:
            self.pintar_panel(p, rect)
        px = rect.x() + 16
        py = rect.y() + 14
        ancho = rect.width() - 32
        tope = rect.bottom()
        p.setFont(self.f_sm)
        p.setPen(C(TH.get('acc2', ACC)))
        p.drawText(QPoint(px, py + self.fm_sm.ascent()),
                   L('SELECCION', 'SELECTION'))
        py += 26
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(TH['border']))
        p.drawRect(px, py, ancho, 1)
        py += 14

        if not pet.view:
            p.setFont(self.f_it)
            p.setPen(C(DIM))
            p.drawText(QPoint(px, py + self.fm_it.ascent()), L('(vacio)', '(empty)'))
            py += 28
        else:
            nombre = pet.nombre_actual()
            datos = pet.info.get(nombre)
            titulo = (datos or {}).get('nombre') or nombre
            for ext in ('.wsquashfs', '.squashfs', '.dwarfs'):
                if titulo.lower().endswith(ext):
                    titulo = titulo[:-len(ext)]
                    break
            if datos and pet.modo == 'list':
                py = self.pintar_caratula_panel(p, datos, rect, px, py, ancho)
            # QUE HACE LA OPCION ELEGIDA. Solo en los menus normales: en la
            # biblioteca ese sitio lo ocupan los datos del juego.
            ayuda = ayuda_de(titulo) if not datos else None
            p.setFont(self.f_it)
            p.setPen(C(FG))
            # con ayuda debajo, el titulo se recorta a 3 lineas para dejarle sitio
            for linea in self.partir_titulo_en(titulo, self.fm_it, ancho - 2,
                                               3 if (datos or ayuda) else 6):
                p.drawText(QPoint(px, py + self.fm_it.ascent()), linea)
                py += 28
            if ayuda:
                py += 10
                p.setFont(self.f_sm)
                p.setPen(C(DIM))
                for linea in self.partir_titulo_en(ayuda, self.fm_sm, ancho - 2, 10):
                    if py > tope - 24:
                        break
                    p.drawText(QPoint(px, py + self.fm_sm.ascent()), linea)
                    py += 20
            if datos and pet.modo == 'list':
                py = self.pintar_datos(p, datos, px, py, ancho, tope)
        if pet.modo == 'browse':
            py += 8
            p.setFont(self.f_sm)
            p.setPen(C(TH.get('acc2', ACC)))
            p.drawText(QPoint(px, py + self.fm_sm.ascent()), L('CARPETA', 'FOLDER'))
            py += 22
            p.setPen(C(DIM))
            for linea in self.partir_titulo_en(pet.cur_path, self.fm_sm, ancho - 2, 4):
                p.drawText(QPoint(px, py + self.fm_sm.ascent()), linea)
                py += 20
        if pet.filtro:
            py += 10
            p.setFont(self.f_sm)
            p.setPen(C(WARN))
            p.drawText(QPoint(px, py + self.fm_sm.ascent()),
                       L('BUSCANDO: %s', 'SEARCHING: %s') % pet.filtro)
            py += 20
            # Si la busqueda no deja ver nada hay que decirlo Y decir como
            # quitarla: una pantalla vacia con un filtro puesto parece que no
            # hay ficheros, no que estan escondidos.
            if not pet.view:
                aviso = L('Nada coincide con esa busqueda. Pulsa B para quitarla.',
                          'Nothing matches that search. Press B to clear it.')
                for linea in self.partir_titulo_en(aviso, self.fm_sm, ancho - 2, 3):
                    p.drawText(QPoint(px, py + self.fm_sm.ascent()), linea)
                    py += 20

    def pintar_caratula_panel(self, p, datos, rect, px, py, ancho):
        # LAS TRES FORMAS, CADA UNA CON SU SITIO.
        #
        # Las verticales se limitan a 240 px de ancho: mas grandes se comen el
        # panel y no dejan hueco a los datos. Las panoramicas y las 4:3 son
        # mucho mas bajas para el mismo ancho, asi que pueden ocupar el panel
        # entero y se ven bastante mejor. El tope de ALTO tambien cambia:
        # 0,45 del panel para las anchas y 0,55 para las verticales.
        #
        # La forma se saca del fichero, no del ajuste de vista: en la lista
        # conviven caratulas de varios origenes y el ajuste solo dice como se
        # quiere la REJILLA.
        ruta = datos.get('cov') or ''
        if not ruta:
            return py
        ancha = es_ancha(ruta)
        ancho_max = ancho if ancha else min(rect.width() - 24, 240)
        alto_max = int(self.LIST_H * (0.45 if ancha else 0.55))
        try:
            tam = QtGui.QImageReader(ruta).size()
        except Exception:
            tam = None
        if tam is not None and tam.isValid() and tam.width() > 0:
            # Se calcula el alto real a partir de la cabecera del fichero, y
            # si se pasa se reduce el ancho. Asi el hueco es el correcto desde
            # el primer fotograma, antes incluso de que la imagen se cargue.
            alto = int(ancho_max * tam.height() / float(tam.width()))
            if alto > alto_max:
                ancho_max = max(60, int(ancho_max * alto_max / float(alto)))
                alto = alto_max
        else:
            alto = int(ancho_max * (0.47 if ancha else 1.5))
        cx = rect.x() + (rect.width() - ancho_max) // 2
        pix = self.imagen(ruta, ancho_max, alto)
        if pix is not None:
            p.drawPixmap(cx, py, pix)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(TH['card']))
            p.drawRect(cx, py, ancho_max, alto)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QtGui.QPen(C(TH['border']), 1))
        p.drawRect(cx - 2, py - 2, ancho_max + 4, alto + 4)
        p.setPen(Qt.PenStyle.NoPen)
        return py + alto + 14

    def pintar_datos(self, p, datos, px, py, ancho, tope):
        # SIEMPRE LAS MISMAS FILAS, EN EL MISMO ORDEN, aunque el dato no este.
        # Enseñando solo las que tienen valor, cada juego mostraba unas
        # cuantas distintas y el panel bailaba: la nota, por ejemplo, solo la
        # traen los juegos con puntuacion de Metacritic, y parecia que
        # faltaba informacion en unos si y en otros no.
        py += 6
        SIN = L('—')
        edi = datos.get('edi') or ''
        if edi and edi == datos.get('dev'):
            edi = ''            # no repetir la misma empresa dos veces
        veces = datos.get('veces') or '0'
        filas = [
            (L('Año', 'Year'), datos.get('ano') or SIN),
            (L('Desarrollo', 'Developer'), datos.get('dev') or SIN),
            (L('Edición', 'Publisher'), edi or SIN),
            (L('Género', 'Genre'), datos.get('gen') or SIN),
            (L('Nota', 'Score'),
             ('%s/100' % datos['nota']) if datos.get('nota') else SIN),
            (L('Duración', 'Length'), datos.get('dur') or SIN),
            (L('Jugado', 'Played'),
             (L('%s veces', '%s times') % veces) if veces != '0'
             else L('nunca', 'never')),
            (L('Tiempo', 'Time'), fmt_horas(datos.get('segs')) or SIN),
        ]
        if datos.get('completado') == '1':
            filas.append((L('Estado', 'Status'), L('COMPLETADO', 'COMPLETED')))
        p.setFont(self.f_sm)
        for etiqueta, valor in filas:
            if py > tope - 26:
                break
            p.setPen(C(DIM))
            p.drawText(QPoint(px, py + self.fm_sm.ascent()), etiqueta)
            # el valor va a la derecha; si no cabe, se recorta con puntos
            hueco = ancho - self.fm_sm.horizontalAdvance(etiqueta) - 10
            v = self.recortar(str(valor), self.fm_sm, max(20, hueco))
            p.setPen(C(TH.get('acc2', ACC)))
            p.drawText(QPoint(px + ancho - self.fm_sm.horizontalAdvance(v),
                              py + self.fm_sm.ascent()), v)
            py += 22
        # La sinopsis, con lo que quede de panel. Va la ultima porque es lo
        # unico que puede ocupar mucho y lo que menos se necesita de un vistazo.
        sino = datos.get('sinopsis') or ''
        if sino and py < tope - 40:
            py += 8
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(TH['border']))
            p.drawRect(px, py, ancho, 1)
            py += 10
            p.setPen(C(DIM))
            for linea in self.partir_titulo_en(sino, self.fm_sm, ancho - 2, 12):
                if py > tope - 22:
                    break
                p.drawText(QPoint(px, py + self.fm_sm.ascent()), linea)
                py += 19
        return py

    def partir_titulo_en(self, texto, fm, maxw, tope):
        lineas = []
        for cruda in (texto or '').split('\n'):
            actual = ''
            for palabra in cruda.split():
                prueba = (actual + ' ' + palabra).strip()
                if actual and fm.horizontalAdvance(prueba) > maxw:
                    lineas.append(actual)
                    actual = palabra
                    if len(lineas) >= tope:
                        break
                else:
                    actual = prueba
            if actual and len(lineas) < tope:
                lineas.append(actual)
            if len(lineas) >= tope:
                break
        return lineas[:tope]

    def imagen(self, ruta, ancho, alto=None):
        # Devuelve la caratula lista, o None si todavia no lo esta. Quien
        # pinta NO espera: dibuja el hueco y se repinta cuando llegue.
        if not ruta or ancho <= 0:
            return None
        clave = '%s|%d|%d' % (ruta, ancho, alto or 0)
        pix = QtGui.QPixmapCache.find(clave)
        if pix is not None and not pix.isNull():
            return pix
        if clave in self.malas or clave in self.pendientes:
            return None
        if not os.path.isfile(ruta):
            self.malas.add(clave)
            return None
        self.pendientes.add(clave)
        self.pool.start(TareaImagen(clave, ruta, ancho, alto, self.bus_img))
        return None

    def imagen_lista(self, clave, img):
        # Llega desde el pool: aqui ya estamos en el hilo de la interfaz, que
        # es el unico sitio donde se puede crear un QPixmap.
        self.pendientes.discard(clave)
        if img is None or img.isNull():
            self.malas.add(clave)
            return
        try:
            ancho = int(clave.rsplit('|', 2)[1])
            alto = int(clave.rsplit('|', 2)[2])
        except (IndexError, ValueError):
            return
        pix = QPixmap.fromImage(img)
        if alto:
            # Se centra sobre el fondo de la casilla y se guarda YA compuesta:
            # asi pintar es un solo drawPixmap, sin cuentas por fotograma.
            lienzo = QPixmap(ancho, alto)
            lienzo.fill(C(TH.get('card', TH['bg'])))
            q = QPainter(lienzo)
            q.drawPixmap((ancho - pix.width()) // 2,
                         (alto - pix.height()) // 2, pix)
            q.end()
            pix = lienzo
        QtGui.QPixmapCache.insert(clave, pix)
        if not self.repintar_pronto.isActive():
            self.repintar_pronto.start()

    def caches_resumen(self):
        # Para DIAG_TIEMPOS, igual que en el motor viejo: saber cuanto se esta
        # gastando antes de suponerlo.
        return 'cache=%d KiB pendientes=%d ilegibles=%d hilos=%d' % (
            QtGui.QPixmapCache.cacheLimit(), len(self.pendientes),
            len(self.malas), self.pool.maxThreadCount())

    # -- busqueda y teclado en pantalla -----------------------------------
    def pintar_busqueda(self, p):
        if not self.pet.filtro:
            return
        texto = L('buscar', 'search') + ': ' + self.pet.filtro
        ancho = self.fm_sm.horizontalAdvance(texto) + 24
        rect = QRect(self.width() - ancho - 24, self.HEAD + 2,
                     ancho, self.fm_sm.height() + 10)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(KBBG))
        p.drawRoundedRect(QRectF(rect), 0 if self.ARCADE else 8,
                          0 if self.ARCADE else 8)
        p.setFont(self.f_sm)
        p.setPen(C(ACC))
        p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), texto)

    def pintar_teclado(self, p):
        pet = self.pet
        W, H = self.width(), self.height()
        kw, kh, gap = FS(52), FS(42), 6
        cols = max(len(f) for f in TECLADO)
        tw = cols * (kw + gap)
        th = len(TECLADO) * (kh + gap) + 60
        x0 = (W - tw) // 2
        y0 = H - th - 40
        marco = QRect(x0 - 16, y0 - 46, tw + 32, th + 46)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(KBBG))
        p.drawRoundedRect(QRectF(marco), RAD, RAD)
        if TH.get('brackets'):
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QtGui.QPen(C(ACC), 1))
            p.drawRect(marco)
            p.setPen(Qt.PenStyle.NoPen)
        p.setFont(self.f_it)
        p.setPen(C(ACC))
        p.drawText(QPoint(marco.x() + 16, marco.y() + 8 + self.fm_it.ascent()),
                   (pet.texto if pet.modo == 'text' else pet.filtro) or '_')
        for r, fila in enumerate(TECLADO):
            for c, ch in enumerate(fila):
                rect = QRect(x0 + c * (kw + gap), y0 + r * (kh + gap), kw, kh)
                activo = (r == pet.kb_r and c == pet.kb_c)
                if activo:
                    self.seleccion(p, rect)
                else:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(C(TH['card']))
                    p.drawRoundedRect(QRectF(rect), RAD, RAD)
                p.setFont(self.f_kb)
                p.setPen(C(TH['sel_fg'] if activo else FG))
                p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter),
                           ch if ch != ' ' else '\u2423')
        self.pintar_pie(p, [('A', L('escribir', 'type')),
                            ('B', L('borrar', 'delete')),
                            ('Y', L('cerrar', 'close'))])

    # -- editor de texto ---------------------------------------------------
    def pintar_texto(self, p):
        pet = self.pet
        W = self.width()
        self.pintar_cabecera(p)
        rect = QRect(48, self.HEAD + 30, W - 96, self.ROW + 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(TH['card']))
        p.drawRoundedRect(QRectF(rect), RAD, RAD)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QtGui.QPen(C(ACC), 2))
        p.drawRoundedRect(QRectF(rect), RAD, RAD)
        p.setFont(self.f_it)
        p.setPen(C(FG))
        cursor = '|' if int(time.time() * 2) % 2 else ' '
        p.drawText(rect.adjusted(16, 0, -16, 0),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                   pet.texto + cursor)
        pet.kb_open = True
        self.pintar_teclado(p)

    # -- progreso ----------------------------------------------------------
    def pintar_progreso(self, p):
        # Lee "pct|texto" del fichero de estado. Con "DONE" se cierra sola:
        # antes se quedaba esperando a que la mataran a los 0,6 segundos.
        pet = self.pet
        W, H = self.width(), self.height()
        self.pintar_cabecera(p)
        crudo = ''
        try:
            with open(pet.arg4, encoding='utf-8') as fh:
                crudo = fh.readline().rstrip('\n')
        except Exception:
            crudo = ''
        if crudo.startswith('DONE'):
            self.terminar(0)
            return
        a, _, texto = crudo.partition('|')
        try:
            pct = max(0, min(100, int(float(a or 0))))
        except ValueError:
            pct = 0
        if texto:
            self.ultimo_progreso = texto
        texto = self.ultimo_progreso
        p.setFont(self.f_it)
        p.setPen(C(FG))
        p.drawText(QPoint(30, self.HEAD + 24 + self.fm_it.ascent()),
                   self.recortar(texto, self.fm_it, W - 60))
        bx, by = 30, self.HEAD + 74
        bw, bh = W - 60, FS(26)
        radio = 0 if self.ARCADE else RAD
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(TH['card']))
        p.drawRoundedRect(QRectF(QRect(bx, by, bw, bh)), radio, radio)
        relleno = ACC if TH.get('glow') else TH['sel_bg']
        if pct > 0:
            lleno = QRect(bx, by, max(bh, int(bw * pct / 100.0)), bh)
            if TH.get('glow'):
                self.hbar(p, lleno, TH.get('acc2', ACC), ACC)
            else:
                p.setBrush(C(relleno))
                p.drawRoundedRect(QRectF(lleno), radio, radio)
        else:
            # SIN PORCENTAJE: un bloque que va y viene. Es lo que hay que
            # enseñar cuando de verdad no se sabe cuanto queda -no una barra
            # quieta al 0, que parece colgada, ni un porcentaje inventado-.
            # Mismo recorrido y misma velocidad que en el motor viejo.
            t0 = (time.time() * 220) % (bw * 2)
            xx = t0 if t0 < bw else (bw * 2 - t0)
            p.setBrush(C(relleno))
            p.drawRoundedRect(QRectF(QRect(bx + max(0, min(bw - 140, int(xx) - 70)),
                                           by, 140, bh)), radio, radio)
        if TH['panel'] is not None:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QtGui.QPen(C(TH['border']), 1))
            p.drawRoundedRect(QRectF(QRect(bx, by, bw, bh)), radio, radio)
            p.setPen(Qt.PenStyle.NoPen)
        p.setFont(self.f_sm)
        p.setPen(C(DIM))
        if pct:
            p.drawText(QPoint(bx, by + bh + 8 + self.fm_sm.ascent()), '%d%%' % pct)
        p.drawText(QPoint(24, H - 40 + self.fm_sm.ascent()),
                   L('Espera, esto puede tardar...',
                     'Please wait, this may take a while...'))

    # -- reposo: la pantalla que se ve ENTRE menus -------------------------
    def pintar_reposo(self, p):
        # LA ONDA DE ZOOM SOBRE "WPROTON", letra a letra.
        #
        # Es el mismo efecto del motor viejo y con los mismos numeros, porque
        # el ritmo esta ajustado a ojo y cambiarlo se nota: ciclo de 2,6 s,
        # separacion de 1/(n+3) entre letras y ventana de 0,22. Asi se mueven
        # DOS letras como mucho, la onda acaba sobre el 82% del ciclo y queda
        # una pausa antes de volver a empezar.
        #
        # Alli las siete letras se pre-renderizaban en diez tamaños porque
        # componer texto en cada fotograma con SDL cuesta. Aqui no hace falta
        # guardar imagenes: basta con escalar el pincel. Lo que SI se conserva
        # es la discretizacion en diez pasos, y no por herencia: Qt cachea los
        # glifos POR TAMAÑO, asi que una escala continua seria un tamaño nuevo
        # en cada fotograma y no acertaria la cache ni una vez.
        W, H = self.width(), self.height()
        # EL MISMO TAMAÑO QUE EN EL MOTOR VIEJO.
        #
        # Alli la medida es max(48, W//14) pasada a pygame.font.Font, que la
        # entiende como ALTO DE LINEA. QFont.setPixelSize toma el cuerpo, que
        # es menor, asi que sin el 0,75 -el mismo factor que usan las demas
        # fuentes de este fichero- las letras salian como un tercio mas
        # grandes y el reposo no pegaba con el resto de los menus.
        base_px = max(FS(24), int(max(48, W // 14) * 0.75))
        f = QFont('DejaVu Sans')
        f.setBold(True)
        f.setPixelSize(base_px)
        fm = QtGui.QFontMetrics(f)
        letras = 'WPROTON'
        anchos = [fm.horizontalAdvance(c) for c in letras]
        ancho_total = sum(anchos)
        alto = fm.height()
        by = H // 2 - alto
        ahora = time.time()
        x = (W - ancho_total) // 2
        for i, letra in enumerate(letras):
            u = ((ahora % 2.6) / 2.6 - i / (len(letras) + 3.0)) / 0.22
            lift = math.sin(u * math.pi) if 0 < u < 1 else 0.0
            paso = max(0, min(IDLE_PASOS - 1, int(round(lift * (IDLE_PASOS - 1)))))
            esc = 1.0 + 0.35 * (paso / float(IDLE_PASOS - 1))
            col = MORADO_W if i == 0 else CIAN_PROTON
            cx = x + anchos[i] / 2.0
            cy = by + alto / 2.0
            p.save()
            # Crece desde su CENTRO: desde la esquina se iria hacia abajo y a
            # la derecha en vez de agrandarse en su sitio.
            p.translate(cx, cy)
            p.scale(esc, esc)
            p.translate(-cx, -cy)
            if self.ARCADE:
                p.setFont(f)
                p.setPen(C(TH['acc2']))
                p.drawText(QPoint(int(x) + 3, by + fm.ascent() + 3), letra)
            if TH.get('pathtext'):
                # El halo crece CON la letra: la que esta en lo alto de la
                # onda brilla mas, asi la ola se ve aunque se mire de lejos.
                self.texto_halo(p, int(x), by, f, letra, col, col,
                                pasadas=1 + int(lift > 0.35))
            else:
                p.setFont(f)
                p.setPen(C(col))
                p.drawText(QPoint(int(x), by + fm.ascent()), letra)
            p.restore()
            x += anchos[i]
        if self.estado:
            p.setFont(self.f_it)
            fm2 = self.fm_it
            ancho = fm2.horizontalAdvance(self.estado)
            y = by + alto + FS(24)
            p.setPen(C(FG))
            p.drawText(QPoint((W - ancho) // 2, y + fm2.ascent()), self.estado)
            # Y tres puntos que van apareciendo, para que se vea que sigue vivo
            puntos = '.' * (int(time.time() * 2) % 4)
            if puntos:
                p.drawText(QPoint((W + ancho) // 2 + FS(6), y + fm2.ascent()),
                           puntos)

    def chips(self):
        pet = self.pet
        if pet.modo == 'check':
            return [('A', L('marcar', 'toggle')), ('Start', L('aceptar', 'accept')),
                    ('B', L('volver', 'back')), ('Y', L('buscar', 'search'))]
        if pet.modo == 'browse':
            return [('A', L('abrir', 'open')), ('B', L('atras', 'back')),
                    ('Y', L('buscar', 'search'))]
        if ACTION_X:
            return [('A', L('jugar', 'play')), ('X', L('config', 'config')),
                    ('Y', L('buscar', 'search')), ('L1', L('ficha', 'info')),
                    ('R1', L('favorito', 'favourite')),
                    ('Sel+X', L('vista', 'view')), ('B', L('volver', 'back'))]
        return [('A', L('elegir', 'choose')), ('B', L('volver', 'back')),
                ('Y', L('buscar', 'search')), ('Sel+A', L('pantalla', 'screen'))]

    # -- entrada -----------------------------------------------------------
    def keyPressEvent(self, ev):
        # Teclado real: ademas de las teclas de navegacion, escribir filtra
        # la lista (type-ahead), igual que en el motor viejo.
        txt = ev.text()
        if self.tecla(ev.key()):
            return
        if txt and txt.isprintable() and not self.en_reposo:
            self.pet.filtro += txt
            self.pet.aplicar_filtro()
            self.update()

    def tecla(self, k):
        # Punto UNICO de entrada: aqui llegan el teclado y el mando. Que sea
        # el mismo camino es lo que hace que no haya funciones que solo
        # respondan al teclado (el fallo clasico de estos menus).
        ahora = time.time()
        if ahora < self.sordo_hasta:
            return True
        if k == self._ultima[0] and (ahora - self._ultima[1]) < self.DEBOUNCE:
            return True
        self._ultima = [k, ahora]
        if self.en_reposo:
            return True
        pet = self.pet
        if k == K_F11:
            self.alternar_pantalla_completa(); return True
        if k == K_F12:
            self.captura(); return True
        if pet.kb_open:
            return self.tecla_teclado(k)
        if k in (K_UP, K_DOWN, K_LEFT, K_RIGHT):
            self.mover(k); return True
        if k in (K_PGUP, K_PGDN):
            paso = max(1, self.vis() - 2)
            self.saltar(-paso if k == K_PGUP else paso); return True
        if k == K_RETURN:
            self.aceptar(); return True
        if k == K_ESCAPE:
            self.cancelar(); return True
        if k == K_TAB:
            pet.kb_open = True; self.update(); return True
        if k == K_BACKSPACE:
            pet.filtro = pet.filtro[:-1]
            pet.aplicar_filtro(); self.update(); return True
        if k == K_SPACE:
            if pet.modo == 'check':
                self.alternar_marca()
            elif ACTION_X:
                self.accion('CONFIG')
            return True
        if k == K_F1 and ACTION_X:
            self.accion('INFO'); return True
        if k == K_F2:
            self.marcar_favorito(); return True
        if k == K_F3:
            self.alternar_vista(); return True
        return False

    def tecla_teclado(self, k):
        pet = self.pet
        if k == K_UP:
            pet.kb_r = (pet.kb_r - 1) % len(TECLADO)
        elif k == K_DOWN:
            pet.kb_r = (pet.kb_r + 1) % len(TECLADO)
        elif k == K_LEFT:
            pet.kb_c = (pet.kb_c - 1) % len(TECLADO[pet.kb_r])
        elif k == K_RIGHT:
            pet.kb_c = (pet.kb_c + 1) % len(TECLADO[pet.kb_r])
        elif k == K_RETURN:
            ch = TECLADO[pet.kb_r][min(pet.kb_c, len(TECLADO[pet.kb_r]) - 1)]
            if pet.modo == 'text':
                pet.texto += ch
            else:
                pet.filtro += ch
                pet.aplicar_filtro()
        elif k == K_ESCAPE:
            if pet.modo == 'text':
                pet.texto = pet.texto[:-1]
            else:
                pet.filtro = pet.filtro[:-1]
                pet.aplicar_filtro()
        elif k == K_TAB:
            if pet.modo == 'text':
                pet.escribir(pet.texto)
                self.terminar(0)
                return True
            pet.kb_open = False
        pet.kb_c = min(pet.kb_c, len(TECLADO[pet.kb_r]) - 1)
        self.update()
        return True

    def mover(self, k):
        pet = self.pet
        if not pet.view:
            return
        if pet.modo == 'grid':
            cols = self.columnas()
            paso = {K_UP: -cols, K_DOWN: cols, K_LEFT: -1, K_RIGHT: 1}[k]
        else:
            if k in (K_LEFT, K_RIGHT):
                paso = -10 if k == K_LEFT else 10
            else:
                paso = -1 if k == K_UP else 1
        self.saltar(paso)

    def saltar(self, paso):
        pet = self.pet
        if not pet.view:
            return
        pet.sel = max(0, min(len(pet.view) - 1, pet.sel + paso))
        self.update()

    def aceptar(self):
        pet = self.pet
        if pet.modo == 'grid':
            if not pet.view:
                return
            pet.escribir(pet.gitems[pet.view[pet.sel]][2])
            self.terminar(0)
            return
        if not pet.view:
            return
        kind, txt, _ = pet.items[pet.view[pet.sel]]
        if pet.modo == 'check':
            pet.escribir('|'.join(t for k, t, on in pet.items if on))
            self.terminar(0)
        elif pet.modo == 'browse':
            if kind == K_HDR:
                pet.escribir(pet.cur_path); self.terminar(0)
            elif kind == K_UP2:
                pet.cargar_dir(os.path.dirname(pet.cur_path)); self.update()
            elif kind == K_DIR:
                pet.cargar_dir(os.path.join(pet.cur_path, txt[:-1])); self.update()
            else:
                pet.escribir(os.path.join(pet.cur_path, txt)); self.terminar(0)
        else:
            pet.escribir(txt)
            self.terminar(0)

    def volver_a_casa(self):
        # SELECT solo = volver al menu principal. No depende de ninguna tecla
        # y funciona en cualquier modo, igual que en el motor viejo.
        home_req[0] = False
        if self.en_reposo:
            return
        self.pet.escribir('WPACT:HOME|')
        self.terminar(0)

    def cancelar(self):
        pet = self.pet
        if pet.filtro:
            pet.filtro = ''
            pet.aplicar_filtro()
            self.update()
            return
        if pet.modo == 'browse':
            padre = os.path.dirname(pet.cur_path)
            if padre != pet.cur_path:
                pet.cargar_dir(padre)
                self.update()
                return
        self.terminar(1)

    def alternar_marca(self):
        pet = self.pet
        if not pet.view:
            return
        fila = pet.items[pet.view[pet.sel]]
        fila[2] = not fila[2]
        self.update()

    def accion(self, nombre):
        # Devuelve "WPACT:<accion>|<lo elegido>" y cierra: WProton hace lo
        # suyo y vuelve a abrir la lista donde estaba.
        pet = self.pet
        if not pet.view:
            return
        if pet.modo == 'grid':
            payload = pet.gitems[pet.view[pet.sel]][2]
        else:
            payload = pet.items[pet.view[pet.sel]][1]
        pet.escribir('WPACT:%s|%s' % (nombre, payload))
        self.terminar(0)

    def marcar_favorito(self):
        pet = self.pet
        if not pet.view:
            return
        nombre = pet.nombre_actual()
        if pet.modo == 'grid':
            fila = pet.gitems[pet.view[pet.sel]]
            fila[3] = '0' if str(fila[3]) == '1' else '1'
        else:
            datos = pet.info.setdefault(nombre, {'fav': '0'})
            datos['fav'] = '0' if datos.get('fav') == '1' else '1'
        if pet.fav_file:
            try:
                with open(pet.fav_file, 'a', encoding='utf-8') as fh:
                    fh.write(nombre + '\n')
            except OSError:
                pass
        self.update()

    def alternar_vista(self):
        pet = self.pet
        if pet.modo not in ('list', 'grid'):
            return
        pet.escribir('WPACT:VISTA|%s' % pet.nombre_actual())
        self.terminar(0)

    # -- ventana -----------------------------------------------------------
    def alternar_pantalla_completa(self):
        if self.isFullScreen():
            self.showNormal()
            self.resize(960, 680)
            try:
                open(WIN_MARK, 'w').close()
            except OSError:
                pass
        else:
            self.showFullScreen()
            try:
                os.remove(WIN_MARK)
            except OSError:
                pass

    def captura(self):
        destino = CAPT_DIR or os.path.join(BASE, 'capturas')
        try:
            os.makedirs(destino, exist_ok=True)
            ruta = os.path.join(destino, time.strftime('menu-%Y%m%d-%H%M%S.png'))
            self.grab().save(ruta)
            sys.stderr.write('menu_qt: captura -> %s\n' % ruta)
        except Exception as e:
            sys.stderr.write('menu_qt: no se pudo capturar (%s)\n' % e)

    # -- fin de sesion -----------------------------------------------------
    def terminar(self, rc):
        self.pet.marcar_cierre_limpio()
        if self.mando is not None:
            self.mando.olvidar_pulsaciones()
        self.sordo_hasta = time.time() + 0.25
        self.termina.emit(rc)


# ---------------------------------------------------------------------------
# 8. SERVIDOR DE MENUS
#
# Protocolo intacto: <dir>/req + <dir>/req.ready -> <dir>/resp, y <dir>/stop
# para parar. La diferencia con el motor viejo es que aqui no hay un bucle
# bloqueante por peticion: el estado vive en la ventana y un temporizador
# mira si ha llegado algo. Asi el mando y el repintado siguen atendidos
# aunque una peticion tarde.
# ---------------------------------------------------------------------------
def desescapa(v):
    out, i = [], 0
    while i < len(v):
        if v[i] == '\\' and i + 1 < len(v):
            if v[i + 1] == 'n':
                out.append('\n'); i += 2; continue
            if v[i + 1] == '\\':
                out.append('\\'); i += 2; continue
        out.append(v[i]); i += 1
    return ''.join(out)


class Servidor(QtCore.QObject):
    def __init__(self, dirpath, pantalla, pet):
        # CON PADRE, Y NO POR ORDEN.
        #
        # Sin padre, este objeto no tenia quien lo sujetara: en cuanto main()
        # terminaba la linea que lo creaba, Python lo daba por perdido y se lo
        # llevaba, y con el su QTimer, que era su hijo. El resultado era que
        # nadie volvia a mirar si habia peticiones: la ventana seguia viva
        # animando el reposo -su temporizador es otro- y WProton se quedaba
        # esperando una respuesta que ya no iba a escribir nadie.
        #
        # Colgandolo de la ventana vive lo que viva ella, que es justo lo que
        # queremos. En el motor viejo esto no podia pasar porque el servidor
        # era un bucle while dentro de una funcion, no un objeto.
        QtCore.QObject.__init__(self, pantalla)
        self.dir = dirpath
        self.pantalla = pantalla
        self.pet = pet
        self.req = os.path.join(dirpath, 'req')
        self.ready = os.path.join(dirpath, 'req.ready')
        self.resp = os.path.join(dirpath, 'resp')
        self.stop = os.path.join(dirpath, 'stop')
        self.desde = 0.0        # desde cuando una peticion no hay quien la lea
        pantalla.termina.connect(self.contestar)
        self.reloj = QtCore.QTimer(self)
        self.reloj.timeout.connect(self.mirar)
        self.reloj.start(66)        # 15 veces por segundo, como el reposo viejo
        sys.stderr.write('menu_qt: servidor de menus en %s\n' % dirpath)

    def mirar(self):
        if os.path.isfile(self.stop):
            try:
                os.remove(self.stop)
            except OSError:
                pass
            sys.stderr.write('menu_qt: servidor detenido\n')
            QtWidgets.QApplication.instance().quit()
            return
        if not os.path.isfile(self.ready):
            self.desde = 0.0
            return
        try:
            with open(self.req, encoding='utf-8') as fh:
                campos = fh.read().split('\n')
        except OSError:
            campos = []
        while len(campos) < 10:
            campos.append('')
        campos = [desescapa(c) for c in campos[:10]]
        (modo, titulo, salida, arg4, kind, ax, manif, presel, favf, aspec) = campos

        # EL TEXTO DEL REPOSO SE ATIENDE SIEMPRE, tambien con un menu abierto.
        #
        # Antes se ignoraba mientras habia menu, pero la marca se quedaba
        # puesta, y esa marca sin atender era la que hacia que la siguiente
        # peticion se leyera a medias. Consumirla aqui cierra el agujero por
        # el otro lado. El motor viejo no podia hacerlo -su bucle esta parado
        # dentro de la sesion- y por eso convivia con ello.
        if modo == 'idle':
            self.pantalla.estado = titulo
            self.quitar_marca()
            return
        if not modo:
            # Peticion a medias. NO se contesta y NO se quita la marca: quien
            # la mando esta a punto de terminar de escribirla y volvera a
            # ponerla. Contestar aqui era peor que el problema: WProton lo
            # leia como "cancelado" y encadenaba menus que se cerraban solos.
            ahora = time.time()
            if not self.desde:
                self.desde = ahora
            elif ahora - self.desde > 5.0:
                sys.stderr.write('menu_qt: peticion ilegible 5 s; se descarta\n')
                self.quitar_marca()
                self.desde = 0.0
                self.contestar(1)
            return
        self.desde = 0.0
        if not self.pantalla.en_reposo:
            # Menu de verdad con otro ya abierto: no deberia pasar -quien
            # pide espera su respuesta- pero si pasa, se deja la marca para
            # atenderla al terminar, no se pierde la peticion.
            return
        self.quitar_marca()
        t0 = time.time()
        if os.environ.get('DIAG_TIEMPOS') == '1':
            sys.stderr.write('menu_qt: peticion %s manifiesto=%s aspecto=%s\n'
                             % (modo, manif or '(ninguno)', aspec or '(ninguno)'))
        # Cuidado con "arg4 or None": la cadena VACIA es falsa y acababa
        # colandose la ruta del temporal en el editor de texto.
        self.pet.preparar(modo, titulo, salida,
                          arg4 if arg4 != '' else None,
                          kind or 'file', ax == '1', manif or None,
                          presel or None, favf or None, aspec or None)
        # Si se pidio "volver a casa" mientras se preparaba el menu, esa
        # peticion es de la pantalla ANTERIOR: cerraria la recien abierta.
        home_req[0] = False
        # Cambio de menu: se descarta lo que llegue en el cuarto de segundo
        # siguiente. Es lo que tarda en soltarse un boton.
        self.pantalla.sordo_hasta = time.time() + 0.25
        # Las portadas ilegibles se olvidan al abrir un menu nuevo: si se
        # acaba de descargar una caratula que faltaba, tiene que salir sin
        # reiniciar WProton.
        self.pantalla.malas.clear()
        self.pantalla.en_reposo = False
        # El titulo nuevo puede ocupar mas lineas: la cabecera, la lista y el
        # panel lateral se recalculan antes de dibujar nada.
        self.pantalla.calcular_disposicion()
        self.pantalla.estado = ''
        self.pantalla.reajustar_latido()
        self.pantalla.update()
        if os.environ.get('DIAG_TIEMPOS') == '1':
            sys.stderr.write('menu_qt: preparado en %d ms | %s\n'
                             % ((time.time() - t0) * 1000,
                                self.pantalla.caches_resumen()))
            sys.stderr.flush()

    def quitar_marca(self):
        try:
            os.remove(self.ready)
        except OSError:
            pass

    def contestar(self, rc):
        try:
            with open(self.resp, 'w', encoding='utf-8') as fh:
                fh.write(str(rc))
        except OSError:
            pass
        self.pantalla.en_reposo = True
        self.pantalla.estado = ''
        self.pantalla.reajustar_latido()
        self.pantalla.update()


# ---------------------------------------------------------------------------
# 9. PUNTO DE ENTRADA
#
#   menu_qt.py <modo> <titulo> <salida> [arg4] [tipo]  -> una peticion
#   menu_qt.py server <carpeta>                        -> servidor
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        sys.stderr.write('uso: menu_qt.py <modo> <titulo> <salida> [arg4] [tipo]\n')
        return 2
    plat = sondear_plataforma()
    if not plat:
        # Igual que el motor viejo cuando no habia video: se sale con un
        # codigo que WProton entiende para caer a los menus de texto.
        sys.stderr.write('menu_qt: sin pantalla utilizable; menus de texto\n')
        return 3
    os.environ['QT_QPA_PLATFORM'] = plat
    # Escalado por HiDPI: en la Steam Deck y en los portatiles con pantalla
    # densa, sin esto los menus salen diminutos.
    os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName('WProton')
    pet = Peticion()
    pantalla = Pantalla(pet)
    if FULLSCREEN:
        pantalla.showFullScreen()
    else:
        pantalla.resize(960, 680)
        pantalla.show()
    pantalla.raise_()
    pantalla.activateWindow()

    mando = Mando()
    pantalla.mando = mando
    mando.tecla.connect(pantalla.tecla, Qt.ConnectionType.QueuedConnection)
    mando.volver_a_casa.connect(pantalla.volver_a_casa,
                                Qt.ConnectionType.QueuedConnection)
    if sys.argv[1] != 'canvas':
        mando.arrancar()

    if sys.argv[1] == 'server':
        # Ademas del padre, un nombre: main() sigue en la pila mientras corre
        # app.exec(), asi que esta referencia dura toda la sesion.
        servidor = Servidor(sys.argv[2], pantalla, pet)
        pantalla.servidor = servidor
        pantalla.en_reposo = True
        pantalla.reajustar_latido()
        return app.exec()

    # Peticion suelta: los mismos argumentos posicionales de siempre... Y LAS
    # MISMAS VARIABLES DE ENTORNO.
    #
    # Aqui solo caben cinco argumentos, asi que el resto -manifiesto, fichero
    # de favoritos, preseleccion y proporcion de la caratula- viaja por el
    # entorno. Es lo que hace el motor viejo y lo que WProton da por hecho:
    # sin esto, cuando el servidor no esta disponible y se abre un menu
    # suelto, la lista sale sin caratula ni datos en el panel y la rejilla
    # dibuja todas las casillas verticales aunque la vista sea panoramica.
    modo = sys.argv[1]
    titulo = sys.argv[2] if len(sys.argv) > 2 else ''
    salida = sys.argv[3] if len(sys.argv) > 3 else ''
    arg4 = sys.argv[4] if len(sys.argv) > 4 else None
    kind = sys.argv[5] if len(sys.argv) > 5 else 'file'
    pet.preparar(modo, titulo, salida, arg4, kind,
                 os.environ.get('WP_ACTION_X') == '1',
                 os.environ.get('WP_LIST_INFO') or None,
                 os.environ.get('WP_PRESEL') or None,
                 os.environ.get('WP_FAV_FILE') or None,
                 os.environ.get('WP_GRID_BANNER') or None)
    pantalla.en_reposo = (modo == 'canvas')
    pantalla.reajustar_latido()

    codigo = [1]

    def fin(rc):
        codigo[0] = rc
        app.quit()
    pantalla.termina.connect(fin)
    app.exec()
    return codigo[0]


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
