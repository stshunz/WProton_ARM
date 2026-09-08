#!/usr/bin/env python3
# WProton - menus con mando
#
# Copyright (C) 2026  stshunz y colaboradores
#
# Este programa es software libre: puedes redistribuirlo y/o modificarlo bajo
# los terminos de la Licencia Publica General GNU (GPL), version 3 o
# posterior, publicada por la Free Software Foundation.
#
# Se distribuye SIN NINGUNA GARANTIA. Ver <https://www.gnu.org/licenses/>.
# Menu/explorador de WProton en pygame: mando via hilo evdev (sin foco),
# navegador persistente, y BUSQUEDA: teclado real (type-ahead) o teclado
# virtual en pantalla para el mando (boton Y).
# Modos:
#   list   <titulo> <salida> <fichero_opciones>
#   check  <titulo> <salida> <fichero_opciones>   ("0|Texto"/"1|Texto")
#   browse <titulo> <salida> <dir_inicial> <file|dir|play|keys>
#   grid   <titulo> <salida> <manifiesto>   (lineas "titulo|imagen|payload")
#   progress <titulo> <fichero_estado>     (el fichero lleva "pct|texto")
#   text   <titulo> <salida> <valor_inicial>  (teclado en pantalla)
#   canvas <titulo> <fichero_estado>       (fondo persistente del modo Juego)
import json
import re, os, sys, time
# math a nivel de modulo: lo usa el latido del reposo. Estaba importado solo
# DENTRO de draw_estrella, asi que fuera de ella no existia y el try de la
# animacion se lo habria tragado en silencio: nunca se habria visto.
import math

BASE = os.path.dirname(os.path.abspath(__file__))
LIBS = os.path.join(BASE, 'libs_py%d.%d' % sys.version_info[:2])
if os.path.isdir(LIBS):
    sys.path.insert(0, LIBS)

os.environ.setdefault('SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS', '1')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
os.environ.setdefault('SDL_VIDEO_CENTERED', '1')
os.environ.setdefault('SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS', '0')
# Pantalla completa: forzada en Batocera, o recordada entre menus con un
# marcador (cada menu es un proceso nuevo, así que la preferencia va a fichero)
# Pantalla completa POR DEFECTO: se ve mejor y es lo que espera quien juega
# con mando. Si el usuario prefiere ventana, lo cambia con Select+A / F11 y
# queda anotado en este marcador.
WIN_MARK = os.path.join(BASE, '.menu_windowed')
FULLSCREEN = os.environ.get('WP_MENU_FS') == '1' or not os.path.isfile(WIN_MARK)
# Orden de drivers de video a probar. En sesión gamescope (modo Juego de
# SteamOS) va primero Wayland: forzar x11/XWayland deja la ventana detras y
# se ve la pantalla en negro. En escritorio, al reves.
IS_GAMESCOPE_SESS = bool(os.environ.get('GAMESCOPE_WAYLAND_DISPLAY')) or \
    os.environ.get('XDG_CURRENT_DESKTOP') == 'gamescope'

# CLAVE en el modo Juego de SteamOS: el compositor NO se llama "wayland-0"
# sino "gamescope-0" (GAMESCOPE_WAYLAND_DISPLAY). Sin decirselo a SDL, este
# no encuentra Wayland, cae a XWayland... y cuando el juego termina y
# gamescope reinicia su XWayland, Xlib mata el proceso con
# "XIO: fatal IO error" (ese error NO se puede capturar desde Python).
# En sesion gamescope se usa X11 (XWayland) por defecto: es lo que SI se ve
# en el modo Juego de SteamOS. Wayland nativo dibuja pero gamescope no llega
# a mostrar la ventana, y el menu parece colgado. Con WP_FORCE_WAYLAND=1 se
# puede probar Wayland (evita los cuelgues de XWayland al cerrar un juego).
_gsw = os.environ.get('GAMESCOPE_WAYLAND_DISPLAY')
if _gsw and os.environ.get('WP_FORCE_WAYLAND'):
    os.environ['WAYLAND_DISPLAY'] = _gsw
    sys.stderr.write('menu_pygame: sesion gamescope, WAYLAND_DISPLAY=%s\n' % _gsw)
if os.environ.get('SDL_VIDEODRIVER'):
    DRIVER_ORDER = [os.environ['SDL_VIDEODRIVER'], None]
elif IS_GAMESCOPE_SESS and os.environ.get('WP_FORCE_WAYLAND'):
    DRIVER_ORDER = ['wayland', 'x11', None]
elif IS_GAMESCOPE_SESS:
    # X11 primero: es el que se ve en el modo Juego (como hasta la 0.90)
    DRIVER_ORDER = ['x11', 'wayland', None]
elif os.environ.get('DISPLAY'):
    DRIVER_ORDER = ['x11', 'wayland', None]
else:
    DRIVER_ORDER = ['wayland', None]
import pygame

# Parametros de la peticion en curso. En modo servidor cambian con cada
# menu; en modo suelto se fijan una vez desde la linea de ordenes.
MODE = TITLE = OUTFILE = ARG4 = ''
BROWSE_KIND = 'file'
BROWSE_EXTS = ()
LIST_INFO = {}          # datos por juego para el panel derecho de la lista
PRESEL = ''             # juego sobre el que abrir la lista (volver donde estabas)
FAV_FILE = ''           # donde se apuntan los favoritos marcados en el menu
COVER_CACHE = {}

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
    # rawg_completar en wproton.sh.
    if not ruta or not os.path.isfile(ruta):
        return {}
    try:
        with open(ruta, encoding='utf-8') as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in d.items() if v}


def leer_duracion(ruta):
    # "21.5|44" -> texto para el panel
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
    # "18.69 h" es demasiada precision y ademas no casa con la fila de
    # "Tiempo" justo debajo, que va en "4 h 20 min". Se enseña igual que
    # aquella: HowLongToBeat da horas con decimales, no un cronometro.
    horas = int(hist)
    minutos = int(round((hist - horas) * 60))
    if minutos == 60:
        horas, minutos = horas + 1, 0
    if horas and minutos:
        return '%d h %d min' % (horas, minutos)
    if horas:
        return '%d h' % horas
    return '%d min' % minutos
# .sh: los juegos de LINUX se lanzan con su propio script. Sin esto no
# aparecian en el navegador y no habia forma de elegirlos.
EXTS_NORMAL = ('.wsquashfs', '.squashfs', '.dwarfs', '.zip', '.7z', '.rar',
               '.001', '.z01', '.exe', '.bat', '.cmd', '.wtgz', '.sh',
               '.appimage', '.AppImage')

# Al IMPORTAR un juego no se enseñan los ya empaquetados (.wsquashfs y
# .dwarfs): esos ya salen solos en la biblioteca, y verlos aqui solo confunde
# —parece que hay que añadirlos otra vez—. Quedan los formatos que si hay que
# importar: comprimidos, ejecutables y carpetas.
EXTS_IMPORTAR = ('.zip', '.7z', '.rar', '.001', '.z01',
                 '.exe', '.bat', '.cmd', '.wtgz', '.sh',
                 '.appimage', '.AppImage')

def set_request(mode, title, outfile, arg4=None, browse_kind='file', action_x=None,
                manifiesto=None, preseleccion=None, fav_file=None, aspecto=None):
    set_aspecto(aspecto)
    global MODE, TITLE, OUTFILE, ARG4, BROWSE_KIND, BROWSE_EXTS, ACTION_X
    global LIST_INFO, PRESEL, FAV_FILE, FILTER, kb_open, kb_r, kb_c
    # El proceso de menus es persistente: sin esto, lo escrito en una busqueda
    # anterior seguia filtrando la pantalla siguiente. Se veian cuatro
    # ficheros de cien y parecia que faltaban; y el teclado en pantalla salia
    # con el texto de antes, al que se le iban sumando letras.
    if FILTER:
        sys.stderr.write('menu_pygame: se limpia la busqueda %r al abrir '
                         'una pantalla nueva\n' % FILTER)
    FILTER = ''
    kb_open = False
    kb_r = kb_c = 0
    PRESEL = preseleccion or ''
    FAV_FILE = fav_file or ''
    LIST_INFO = {}
    if manifiesto and os.path.isfile(manifiesto):
        # nombre|caratula|favorito|veces|segundos|ficha.json|duracion
        # La ficha se lee AQUI: el helper es Python y sabe leer el JSON de
        # Steam mucho mejor que bash a base de tuberias.
        try:
            with open(manifiesto, encoding='utf-8') as fh:
                for linea in fh:
                    campos = linea.rstrip('\n').split('|')
                    if not campos or not campos[0].strip():
                        continue
                    while len(campos) < 9:
                        campos.append('')
                    d = {'cov': campos[1], 'fav': campos[2],
                         'veces': campos[3], 'segs': campos[4],
                         'ficha': campos[5], 'hltb': campos[6],
                         'completado': campos[7], 'rawg': campos[8]}
                    d.update(leer_ficha(campos[5]))
                    # RAWG solo RELLENA: lo de Steam manda, porque trae la
                    # sinopsis en español y datos mas completos.
                    for _k, _v in leer_rawg(campos[8]).items():
                        if not d.get(_k):
                            d[_k] = _v
                    d['dur'] = leer_duracion(d.get('hltb', ''))
                    LIST_INFO[campos[0]] = d
        except Exception:
            LIST_INFO = {}
    MODE, TITLE, OUTFILE = mode, title, outfile
    ARG4 = arg4 if arg4 is not None else outfile
    BROWSE_KIND = browse_kind
    if browse_kind == 'keys':
        BROWSE_EXTS = ('.keys',)
    elif browse_kind == 'reg':
        BROWSE_EXTS = ('.reg',)
    elif browse_kind == 'image':
        BROWSE_EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')
    elif browse_kind == 'importar':
        BROWSE_EXTS = EXTS_IMPORTAR
    elif browse_kind == 'cualquiera':
        # Gestor de ficheros: se ve TODO, con extension o sin ella. Para
        # copiar o mover no se puede filtrar por tipo -una partida guardada
        # puede llamarse "save000" a secas-.
        BROWSE_EXTS = ()
    else:
        BROWSE_EXTS = EXTS_NORMAL
    if action_x is not None:
        ACTION_X = action_x
K_HDR, K_UP2, K_CANCEL, K_DIR, K_FILE, K_PLAIN = range(6)
HEADER_KINDS = (K_HDR, K_UP2, K_CANCEL)

items = []          # [tipo, texto, marcado]
view = []           # indices visibles según el filtro de busqueda
cur_path = ''
sel, scroll = 0, 0
FILTER = ''
kb_open = False
kb_r, kb_c = 0, 0

def _match(text, f):
    # Coincidencia por PREFIJO de palabra: "s" -> solo titulos con alguna
    # palabra que empiece por s (no cualquier titulo que contenga una s).
    # Varias palabras ("sil h"): cada trozo debe ser prefijo de alguna palabra.
    words = text.lower().replace('_', ' ').replace('-', ' ').replace('.', ' ').split()
    for tok in f.split():
        if not any(w.startswith(tok) for w in words):
            return False
    return True

def apply_filter():
    global view, sel, scroll
    if FILTER.strip():
        f = FILTER.lower()
        view = [i for i, it in enumerate(items)
                if it[0] in HEADER_KINDS or _match(it[1], f)]
    else:
        view = list(range(len(items)))
    sel = 0
    scroll = 0

def load_options():
    global items
    items = []
    with open(ARG4, encoding='utf-8') as f:
        for l in f:
            l = l.rstrip('\n')
            if not l.strip():
                continue
            if MODE == 'check':
                on, _, txt = l.partition('|')
                items.append([K_PLAIN, txt, on == '1'])
            else:
                items.append([K_PLAIN, l, False])
    apply_filter()

def load_dir(path):
    # Navegacion EN PROCESO: sin relanzar python/ventana por carpeta
    global items, cur_path, FILTER
    cur_path = os.path.realpath(path)
    FILTER = ''
    items = []
    if BROWSE_KIND == 'dir':
        items.append([K_HDR, '>> USAR ESTA CARPETA <<', False])
    elif BROWSE_KIND == 'cualquiera':
        items.append([K_HDR, '>> ESTA CARPETA ENTERA <<', False])
    elif BROWSE_KIND == 'play':
        items.append([K_HDR, '>> JUGAR ESTA CARPETA <<', False])
    elif BROWSE_KIND not in ('keys', 'image', 'reg'):
        items.append([K_HDR, '>> IMPORTAR ESTA CARPETA <<', False])
    items.append([K_UP2, '.. (subir)', False])
    items.append([K_CANCEL, '<< Cancelar', False])
    try:
        names = sorted(os.listdir(cur_path), key=str.lower)
    except OSError:
        names = []
    for n in names:
        if not n.startswith('.') and os.path.isdir(os.path.join(cur_path, n)):
            items.append([K_DIR, n + '/', False])
    # Si el modo no esta aqui, no se enseña NINGUN fichero: solo carpetas.
    # Al añadir el modo "reg" se olvido esta lista y la pantalla salia sin
    # nada que elegir, aunque la carpeta tuviera .reg dentro.
    if BROWSE_KIND in ('file', 'play', 'keys', 'image', 'importar', 'reg',
                       'cualquiera'):
        for n in names:
            p = os.path.join(cur_path, n)
            # Sin lista de extensiones (modo "cualquiera") entra todo:
            # endswith(()) es SIEMPRE False, asi que sin este caso no se
            # veria ni un fichero.
            if (not n.startswith('.') and os.path.isfile(p)
                    and (not BROWSE_EXTS or n.lower().endswith(BROWSE_EXTS))):
                items.append([K_FILE, n, False])
    apply_filter()

GITEMS = []          # (titulo, ruta_imagen, payload)

def load_manifest():
    global GITEMS
    GITEMS = []
    with open(ARG4, encoding='utf-8') as f:
        for l in f:
            l = l.rstrip('\n')
            if not l.strip():
                continue
            parts = l.split('|')
            while len(parts) < 4:
                parts.append('')
            # lista y no tupla: el favorito se cambia en el sitio al pulsar R1
            GITEMS.append([parts[0], parts[1], parts[2], parts[3]])

def grid_apply_filter():
    global view, sel, scroll
    if FILTER.strip():
        f = FILTER.lower()
        view = [i for i, it in enumerate(GITEMS) if _match(it[0], f)]
    else:
        view = list(range(len(GITEMS)))
    sel = 0
    scroll = 0

def colocar_en_preseleccion():
    # Abrir la lista SOBRE el juego indicado. Se usa al marcar un favorito:
    # sin esto, la lista volveria a empezar por arriba y habria que buscar
    # otra vez donde estabas.
    global sel, scroll
    if not PRESEL or not view:
        return
    for i, idx in enumerate(view):
        nombre = GITEMS[idx][0] if MODE == 'grid' else items[idx][1]
        if nombre == PRESEL:
            sel = i
            vis = max(1, VIS_FULL if not kb_open else VIS_KB)
            scroll = max(0, sel - vis // 2)
            return

def load_request_data():
    # Carga lo que necesite el modo actual (opciones, carpeta o manifiesto)
    global FILTER, sel, scroll, kb_open, kb_r, kb_c
    FILTER = ''
    sel = scroll = 0
    kb_open = False
    kb_r = kb_c = 0
    if MODE in ('progress', 'text', 'canvas'):
        return
    if MODE == 'browse':
        load_dir(ARG4 if os.path.isdir(ARG4) else os.path.expanduser('~'))
    elif MODE == 'grid':
        load_manifest()
        grid_apply_filter()
        colocar_en_preseleccion()
    else:
        load_options()
        colocar_en_preseleccion()

def init_video():
    # pygame.init() NO lanza excepcion si solo falla el video: devuelve el
    # numero de subsistemas fallidos y sigue, y luego revienta el primer uso
    # ("video system not initialized"). Hay que inicializar el video aparte
    # y probar los drivers uno a uno.
    for drv in DRIVER_ORDER:
        if drv:
            os.environ['SDL_VIDEODRIVER'] = drv
        else:
            os.environ.pop('SDL_VIDEODRIVER', None)
        try:
            pygame.display.quit()
        except Exception:
            pass
        try:
            pygame.display.init()
            sys.stderr.write('menu_pygame: video OK con driver %s\n' % (drv or 'auto'))
            return True
        except Exception as e:
            sys.stderr.write('menu_pygame: driver %s no vale (%s)\n' % (drv or 'auto', e))
    return False

pygame.init()          # el resto de subsistemas (no falla aunque el video si)
if not init_video():
    sys.stderr.write('menu_pygame: sin video utilizable; se usaran menus de texto\n')
    sys.exit(2)
pygame.key.set_repeat(400, 120)

# --- hilo evdev: unico camino del mando (funciona sin foco de ventana) ---
import struct, threading, select as _select

EV_KEY_RAW, EV_ABS_RAW = 1, 3
IE_FMT = 'llHHi'
IE_SZ = struct.calcsize(IE_FMT)
# A/Start=Enter | B=Esc | X=Espacio | Y=Tab (teclado de busqueda)
# L1=F1 (ficha del juego) | R1=F2 (marcar favorito)
RAW_BTN = {304: pygame.K_RETURN, 315: pygame.K_RETURN,
           305: pygame.K_ESCAPE, 307: pygame.K_SPACE,
           308: pygame.K_TAB,
           310: pygame.K_F1, 311: pygame.K_F2}
SELECT_BTN = 314          # BTN_SELECT: con A pulsa pantalla completa
# Peticion de "volver al menu principal": la pone el hilo que lee el mando y
# la atiende el bucle principal. De modulo porque son dos funciones
# distintas, y una lista para poder mutarla desde el hilo sin declararla
# global en cada sitio.
home_req = [False]
# Crucetas que reportan BOTONES (Anbernic/Decktroid...) en vez de hat:
DPAD_BTN = {544: pygame.K_UP, 545: pygame.K_DOWN,
            546: pygame.K_LEFT, 547: pygame.K_RIGHT}

def parse_input_chunk(data):
    out = []
    for off in range(0, len(data) - IE_SZ + 1, IE_SZ):
        _, _, t, c, v = struct.unpack_from(IE_FMT, data, off)
        out.append((t, c, v))
    return out

BAD_DEV = ('accel', 'gyro', 'imu', 'motion', 'sensor')
def find_raw_pads():
    # Solo mandos de verdad: fuera acelerometros/giroscopos que Batocera y los
    # handhelds exponen como joystick (movian el menu al inclinar la consola)
    # UN mando puede exponer VARIOS nodos: el controlador xpad crea uno por
    # interfaz ("Microsoft X-Box 360 pad" y "...pad 0"), y el DualSense saca
    # ademas sus sensores. Si se leen todos, cada pulsacion llega DOS veces y
    # los menus saltan de dos en dos.
    #
    # Se agrupan por aparato fisico (la linea "P: Phys=") y de cada grupo se
    # deja UN nodo, el primero (el principal).
    pads = []
    vistos = set()
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
                # "P: Phys=usb-0000:00:14.0-3/input0" -> "usb-0000:00:14.0-3"
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
        clave = phys or ev          # sin phys, cada nodo va por su cuenta
        if clave in vistos:
            continue
        vistos.add(clave)
        pads.append('/dev/input/' + ev)
    return pads

DEV = os.environ.get('WP_DEV') == '1'
CAPT_DIR = os.environ.get('WP_CAPT_DIR', '')

REC = {'hasta': 0.0, 'dir': '', 'n': 0, 'ultimo': 0.0, 'comprobado': 0.0}

def grabar_fotograma():
    # Graba los menus DESDE DENTRO, guardando fotogramas.
    #
    # Hace falta porque ffmpeg, que lee la pantalla desde fuera, saca video
    # NEGRO: la ventana de pygame se dibuja con aceleracion y su contenido no
    # llega a la ventana raiz de las X. Desde aqui sale exacto, igual que las
    # capturas con F12.
    #
    # Se activa dejando un fichero .rec con la marca de tiempo final, asi que
    # no hace falta reiniciar el proceso de menus.
    if not DEV or screen is None:
        return
    ahora = time.time()
    if ahora - REC['comprobado'] > 1.0:
        REC['comprobado'] = ahora
        marca = os.path.join(CAPT_DIR or '.', '.rec')
        try:
            if os.path.isfile(marca):
                with open(marca) as fh:
                    hasta, destino = fh.read().split('\n')[:2]
                if float(hasta) > ahora and REC['dir'] != destino:
                    REC.update({'hasta': float(hasta), 'dir': destino, 'n': 0})
                    os.makedirs(destino, exist_ok=True)
                    sys.stderr.write('menu_pygame: grabando menus en %s\n' % destino)
        except Exception:
            pass
    if not REC['dir'] or ahora > REC['hasta']:
        if REC['dir'] and ahora > REC['hasta']:
            sys.stderr.write('menu_pygame: grabacion terminada (%d fotogramas)\n'
                             % REC['n'])
            REC['dir'] = ''
        return
    if ahora - REC['ultimo'] < 0.1:      # 10 por segundo: suficiente y ligero
        return
    REC['ultimo'] = ahora
    try:
        pygame.image.save(screen, os.path.join(REC['dir'], 'f%05d.png' % REC['n']))
        REC['n'] += 1
    except Exception:
        pass

def captura():
    # Guarda la pantalla actual del menu. Se hace desde pygame, asi que sale
    # exacta y sin bordes de ventana ni raton, que es lo que hace falta para
    # el manual y la web.
    if not (DEV and CAPT_DIR) or screen is None:
        return
    try:
        os.makedirs(CAPT_DIR, exist_ok=True)
        nombre = time.strftime('wproton_%Y%m%d_%H%M%S')
        ruta = os.path.join(CAPT_DIR, nombre + '.png')
        n = 2
        while os.path.exists(ruta):
            ruta = os.path.join(CAPT_DIR, '%s_%d.png' % (nombre, n)); n += 1
        pygame.image.save(screen, ruta)
        sys.stderr.write('menu_pygame: captura -> %s\n' % ruta)
    except Exception as e:
        sys.stderr.write('menu_pygame: no se pudo capturar (%s)\n' % e)

def eventos():
    # pygame.event.get() a prueba de cambios de mandos.
    #
    # Cuando Steam se cierra y se vuelve a abrir, crea y destruye sus mandos
    # virtuales. pygame recibe entonces avisos de "mando desconectado" de un
    # joystick que no tiene fichado y revienta DENTRO de event.get() con un
    # "KeyError: 0", que sale como SystemError y se lleva por delante el menu
    # entero. Aqui se absorbe: se reinicia el subsistema de joystick y se
    # sigue, en vez de perder la ventana.
    try:
        return pygame.event.get()
    except (SystemError, KeyError, Exception) as e:
        sys.stderr.write('menu_pygame: cambio de mandos durante la lectura '
                         '(%s); se reinicia el subsistema\n' % e)
        try:
            pygame.event.clear()
        except Exception:
            pass
        try:
            pygame.joystick.quit()
            pygame.joystick.init()
        except Exception:
            pass
        return []

def post_key(k):
    try:
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=k))
    except Exception:
        pass

AXIS_KEYS = {17: (pygame.K_UP, pygame.K_DOWN),      # dpad vertical
             16: (pygame.K_LEFT, pygame.K_RIGHT),   # dpad horizontal
             1:  (pygame.K_UP, pygame.K_DOWN),      # stick izq vertical
             0:  (pygame.K_LEFT, pygame.K_RIGHT)}   # stick izq horizontal

_noaccess = set()

def evdev_thread():
    fds, held, ax = {}, {}, {}
    sel_held = [False]
    sel_combo = [False]     # ¿se uso Select como modificador?
    sel_desde = [0.0]       # cuando se pulso, para distinguir corta de larga
    last_scan = 0.0
    REP_FIRST, REP_NEXT = 0.40, 0.15
    TH_ON, TH_OFF = 18000, 12000
    sys.stderr.write('menu_pygame: fallback evdev ACTIVO (leyendo /dev/input)\n')
    while True:
        now = time.time()
        if now - last_scan > 2:
            last_scan = now
            for p in find_raw_pads():
                if p not in fds:
                    try:
                        fds[p] = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
                        sys.stderr.write('menu_pygame: mando via evdev: %s\n' % p)
                    except OSError as e:
                        # avisar UNA vez por dispositivo: el reintento cada 2s
                        # llenaba el log con cientos de lineas identicas
                        if p not in _noaccess:
                            _noaccess.add(p)
                            sys.stderr.write('menu_pygame: sin acceso a %s (%s)\n' % (p, e))
        try:
            r, _, _ = _select.select(list(fds.values()), [], [], 0.05 if held else 0.5)
        except OSError:
            r = []
        for fd in r:
            try:
                data = os.read(fd, IE_SZ * 64)
            except OSError:
                for p, f in list(fds.items()):
                    if f == fd:
                        try: os.close(f)
                        except OSError: pass
                        del fds[p]
                continue
            for t, c, v in parse_input_chunk(data):
                if t == EV_KEY_RAW and c in DPAD_BTN:
                    k = DPAD_BTN[c]
                    if v == 1:
                        post_key(k); held[k] = time.time() + REP_FIRST
                    else:
                        held.pop(k, None)
                elif t == EV_KEY_RAW and c == SELECT_BTN:
                    # SELECT SOLO = volver al menu principal.
                    #
                    # Select es MODIFICADOR (Select+A pantalla completa,
                    # Select+X lista/rejilla), asi que no se puede actuar al
                    # pulsarlo: hay que esperar a soltarlo y ver si por medio
                    # se uso alguna combinacion.
                    #
                    # Y es una pulsacion CORTA: mantenerlo es lo que usa el
                    # guardian para cerrar el juego, y eso no se toca.
                    if v != 0:
                        sel_held[0] = True
                        sel_combo[0] = False
                        sel_desde[0] = time.time()
                    else:
                        sel_held[0] = False
                        if not sel_combo[0] \
                           and (time.time() - sel_desde[0]) < 0.6:
                            # UNA BANDERA, NO UNA TECLA.
                            #
                            # El primer intento simulaba una pulsacion (F12),
                            # que ya era la captura de pantalla y se comia el
                            # evento. Cambiarla a F9 tapaba ESE choque, pero
                            # el problema de fondo seguia: el Select del mando
                            # no tiene por que depender de una tecla del
                            # teclado, ni pulsar esa tecla en un teclado real
                            # deberia volver al menu principal.
                            #
                            # Con una bandera son cosas independientes y no
                            # hay tecla que se pueda pisar mañana.
                            home_req[0] = True
                elif t == EV_KEY_RAW and c in RAW_BTN and v == 1:
                    if c == 304 and sel_held[0]:
                        sel_combo[0] = True
                        post_key(pygame.K_F11)      # Select + A: pantalla completa
                    elif c == 307 and sel_held[0]:
                        # Select + X: cambiar entre lista y rejilla.
                        #
                        # Antes era L2, pero en la mayoria de mandos L2 y R2
                        # NO son botones: son ejes analogicos (ABS_Z/ABS_RZ),
                        # asi que su codigo de boton no llega nunca.
                        sel_combo[0] = True
                        post_key(pygame.K_F3)
                    else:
                        post_key(RAW_BTN[c])
                elif t == EV_ABS_RAW and c in (16, 17):
                    neg, pos = AXIS_KEYS[c]
                    for n in (neg, pos):
                        held.pop(n, None)
                    if v != 0:
                        k = pos if v > 0 else neg
                        post_key(k); held[k] = time.time() + REP_FIRST
                elif t == EV_ABS_RAW and c in (0, 1):
                    st = ax.get((fd, c), 0)
                    new = st
                    if st == 0 and abs(v) > TH_ON: new = 1 if v > 0 else -1
                    elif st != 0 and abs(v) < TH_OFF: new = 0
                    if new != st:
                        ax[(fd, c)] = new
                        neg, pos = AXIS_KEYS[c]
                        for n in (neg, pos):
                            held.pop(n, None)
                        if new != 0:
                            k = pos if new > 0 else neg
                            post_key(k); held[k] = time.time() + REP_FIRST
        now = time.time()
        for k, t_ in list(held.items()):
            if now >= t_:
                post_key(k); held[k] = now + REP_NEXT

# El hilo del mando siempre activo: con el servidor hay UN solo proceso, asi
# que no hay dos lectores compitiendo por /dev/input (que era el motivo de
# desactivarlo en el antiguo lienzo, que era un proceso aparte).
if sys.argv[1] != 'canvas':
    threading.Thread(target=evdev_thread, daemon=True).start()

W, H = 960, 680
def _open_window():
    if FULLSCREEN:
        return pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    return pygame.display.set_mode((W, H))
# Los modos que NO dibujan no deben abrir ventana.
#
# El vigilante del mando solo lee /dev/input y el generador de imagenes
# trabaja en memoria, pero ambos abrian una ventana a pantalla completa que
# nunca se dibujaba: negra. La del vigilante ademas sobrevive a la partida,
# asi que al cerrar WProton se quedaba la pantalla en negro.
SIN_VENTANA = len(sys.argv) > 1 and sys.argv[1] in ('guardia', 'logo')
screen = None
if SIN_VENTANA:
    sys.stderr.write('menu_pygame: modo "%s": sin ventana\n' % sys.argv[1])
else:
    try:
        screen = _open_window()
    except Exception as e:
        sys.stderr.write('menu_pygame: no se pudo abrir la ventana (%s)\n' % e)
        if FULLSCREEN:                      # reintentar en ventana
            FULLSCREEN = False
            screen = _open_window()
        else:
            raise
    if FULLSCREEN:
        W, H = screen.get_size()
    pygame.display.set_caption('WProton')
    sys.stderr.write('menu_pygame: video driver = %s | ventana %dx%d | fullscreen=%s\n'
                     % (pygame.display.get_driver(), W, H, FULLSCREEN))

_last_frame = [time.time()]

def frame_watchdog():
    # En Wayland, flip() espera la confirmacion del compositor. Si gamescope
    # deja de mandarla (la ventana no llega a mostrarse), el proceso se queda
    # colgado PARA SIEMPRE y parece que WProton "no carga". Este hilo vigila
    # que sigan pintandose fotogramas; si se para, salimos con codigo 3 para
    # que WProton reintente con X11.
    def _vigila():
        n = 0
        while True:
            time.sleep(1.0)
            n += 1
            if n % 5 == 0:
                # rastro periodico: si esto aparece, el menu SI se esta
                # dibujando y el problema es que no llega a verse
                sys.stderr.write('menu_pygame: dibujando (ultimo fotograma hace %.1fs)\n'
                                 % (time.time() - _last_frame[0]))
            parado = time.time() - _last_frame[0]
            if parado > 6.0:
                sys.stderr.write('menu_pygame: %s lleva %.0fs sin dibujar; '
                                 'se reintentara con otro driver\n'
                                 % (pygame.display.get_driver(), parado))
                os._exit(3)
    threading.Thread(target=_vigila, daemon=True).start()

# OJO: solo para los modos CON VENTANA.
#
# El vigilante mata el proceso si pasan 6 segundos sin dibujar un fotograma,
# para reintentar con otro driver cuando la ventana se queda en negro. Pero
# los modos "guardia" (vigilar el mando durante la partida) y "logo" (generar
# las imagenes) NO DIBUJAN NADA: a los 6 segundos los daba por colgados y los
# mataba. Por eso el cierre con el mando dejaba de funcionar nada mas empezar
# a jugar.
if len(sys.argv) > 1 and sys.argv[1] not in ('guardia', 'logo'):
    frame_watchdog()

if IS_GAMESCOPE_SESS:
    try:
        pygame.event.set_grab(False)
    except Exception:
        pass

def apply_layout():
    global W, H, VIS_FULL, VIS_KB, GCOLS, LIST_X, LIST_Y, LIST_W, LIST_H, SIDE_X, SIDE_W
    W, H = screen.get_size()
    make_bg()
    make_scan()
    if PANEL_UI and MODE == 'grid':
        # en rejilla no hay panel lateral: todo el ancho para las carátulas
        LIST_X, LIST_Y = 20, HEAD + 16
        LIST_H = H - LIST_Y - 76
        LIST_W = W - 40
        SIDE_W, SIDE_X = 0, 0
    elif PANEL_UI:
        # Interfaz de dos paneles: lista a la izquierda, detalles a la derecha
        foot = 62
        LIST_X, LIST_Y = 20, HEAD + 16
        LIST_H = H - LIST_Y - foot - 14
        if MODE in ('list', 'check', 'browse'):
            SIDE_W = max(240, int(W * 0.34))
            SIDE_X = W - SIDE_W - 20
            LIST_W = SIDE_X - LIST_X - 16
        else:
            SIDE_W, SIDE_X = 0, 0
            LIST_W = W - 40
    else:
        LIST_X, LIST_Y = 16, TOP
        LIST_W, LIST_H = W - 32, H - TOP - 60
    VIS_FULL = max(1, LIST_H // ROW)
    VIS_KB = max(1, (LIST_H - KB_H) // ROW)
    grid_metrics()

def toggle_fullscreen():
    global screen, FULLSCREEN, scroll
    FULLSCREEN = not FULLSCREEN
    try:
        screen = _open_window()
    except Exception:
        FULLSCREEN = not FULLSCREEN
        screen = _open_window()
    try:
        if FULLSCREEN:
            # vuelve a pantalla completa: se borra la preferencia de ventana
            if os.path.isfile(WIN_MARK):
                os.remove(WIN_MARK)
        else:
            open(WIN_MARK, 'w').close()
    except Exception:
        pass
    apply_layout()
    scroll = 0
    sys.stderr.write('menu_pygame: pantalla completa = %s\n' % FULLSCREEN)
clock = pygame.time.Clock()
# Escala de letra: 1.0 normal, 1.25 grande, 1.5 muy grande (WP_FONT_SCALE).
# Pensado sobre todo para consolas portatiles, donde 24 px se leen mal.
try:
    FSCALE = float(os.environ.get('WP_FONT_SCALE', '1') or '1')
except ValueError:
    FSCALE = 1.0
FSCALE = max(0.8, min(2.0, FSCALE))
def FS(px):
    return max(14, int(px * FSCALE))
f_tit = pygame.font.Font(None, FS(34))
f_it  = pygame.font.Font(None, FS(30))
f_sm  = pygame.font.Font(None, FS(24))
f_kb  = pygame.font.Font(None, FS(28))

# ---------------------------------------------------------------------------
# TEMAS: "clasico" (el de siempre, sobrio) y "moderno" (paneles y acento neon).
# Se elige con WP_THEME; para añadir uno nuevo basta con copiar un bloque y
# cambiar los colores: el resto del helper se adapta solo.
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
    # Arcade synthwave: rejilla en perspectiva, escaneado CRT, marcador de
    # seleccion y esquinas de HUD. Nada minimalista, a proposito.
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
}
# Accion secundaria: con WP_ACTION_X=1, la X devuelve la seleccion marcada
# para que quien llame abra la configuración en vez de jugar.
SERVER_MODE = False
ACTION_X = os.environ.get('WP_ACTION_X') == '1'
LANG = os.environ.get('WP_LANG', 'es')
# El helper lee el MISMO lang/<codigo>.json que el script: así los textos
# propios (SELECCION, chips, teclado) se traducen a cualquier idioma nuevo
# sin tocar el codigo.
_LANGMAP = {}
if LANG != 'es':
    try:
        import json as _json
        with open(os.path.join(os.path.dirname(BASE), 'lang', LANG + '.json'),
                  encoding='utf-8') as _fh:
            _LANGMAP = {k: v for k, v in _json.load(_fh).items()
                        if isinstance(v, str) and v and k != '__version__'}
    except Exception:
        _LANGMAP = {}

def L(es, en=None):
    # busca en el json; si no esta, usa el ingles de respaldo (si se paso)
    if LANG == 'es':
        return es
    if es in _LANGMAP:
        return _LANGMAP[es]
    return en if en is not None else es
THEME_NAME = os.environ.get('WP_THEME', 'moderno')
if THEME_NAME not in THEMES:
    THEME_NAME = 'moderno'
TH = THEMES[THEME_NAME]

BG   = TH['bg']
FG   = TH['fg']
HIBG = TH['sel_bg']
DIM  = TH['dim']
ACC  = TH['acc']
DIRC = TH['dir']
KBBG = TH['kb_bg']
WARN = TH['warn']
RAD  = TH['radius']

BGSURF = None
SCANSURF = None
def make_scan():
    # Velo de lineas de escaneo (CRT): se dibuja una vez y se superpone
    global SCANSURF
    if not TH.get('scan'):
        SCANSURF = None
        return
    try:
        surf = pygame.Surface((W, H), pygame.SRCALPHA)
    except Exception:
        SCANSURF = None
        return
    for y in range(0, H, 3):
        pygame.draw.rect(surf, (0, 0, 0, 46), (0, y, W, 1))
    SCANSURF = surf

def make_bg():
    # Fondo: liso en clasico, degradado vertical suave en moderno
    global BGSURF
    surf = pygame.Surface((W, H))
    if TH.get('gridbg'):
        # Cielo degradado + horizonte con rejilla en fuga (synthwave)
        c1, c2 = TH['bg2'], TH['bg']
        hz = int(H * 0.42)
        for i in range(hz):
            f = i / float(max(1, hz - 1))
            col = tuple(int(c1[k] + (c2[k] - c1[k]) * f) for k in range(3))
            pygame.draw.rect(surf, col, (0, i, W, 1))
        pygame.draw.rect(surf, TH['bg'], (0, hz, W, H - hz))
        pygame.draw.rect(surf, TH['acc'], (0, hz - 2, W, 2))
        gcol = (TH['border'][0], TH['border'][1], TH['border'][2])
        vp = W // 2
        for k in range(-14, 15):          # verticales que convergen
            pygame.draw.line(surf, gcol, (vp + k * 46, hz), (vp + k * 300, H), 1)
        yy, step = hz + 6, 6              # horizontales cada vez más separadas
        while yy < H:
            pygame.draw.line(surf, gcol, (0, yy), (W, yy), 1)
            step = int(step * 1.42) + 1
            yy += step
    elif TH['bg'] == TH['bg2']:
        surf.fill(TH['bg'])
    else:
        c1, c2 = TH['bg'], TH['bg2']
        steps = 48
        bh = H // steps + 1
        for i in range(steps):
            f = i / float(steps - 1)
            col = tuple(int(c1[k] + (c2[k] - c1[k]) * f) for k in range(3))
            pygame.draw.rect(surf, col, (0, i * bh, W, bh))
    BGSURF = surf

def draw_panel(rect):
    if TH['panel'] is None:
        return
    x, y, w, h = rect
    pygame.draw.rect(screen, TH['panel'], rect, border_radius=RAD)
    if TH.get('brackets'):
        # Marco de HUD: solo las esquinas, en color de acento
        c, L, t = ACC, 26, 3
        for (cx, cy, dx, dy) in ((x, y, 1, 1), (x + w, y, -1, 1),
                                 (x, y + h, 1, -1), (x + w, y + h, -1, -1)):
            pygame.draw.rect(screen, c, (min(cx, cx + dx * L), cy - (t if dy < 0 else 0), L, t))
            pygame.draw.rect(screen, c, (cx - (t if dx < 0 else 0), min(cy, cy + dy * L), t, L))
        pygame.draw.rect(screen, TH['border'], rect, 1)
    else:
        pygame.draw.rect(screen, TH['border'], rect, 1, border_radius=RAD)

def hbar(rect, c1, c2):
    # Barra con degradado horizontal (cabecera y seleccion del tema moderno)
    x, y, w, h = rect
    if w <= 0:
        return
    steps = 26
    sw = max(1, w // steps + 1)
    for i in range(steps):
        f = i / float(steps - 1)
        col = tuple(int(c1[k] + (c2[k] - c1[k]) * f) for k in range(3))
        pygame.draw.rect(screen, col, (x + i * sw, y, sw, h))

def vbar(rect, c1, c2):
    # Degradado vertical: da relieve de boton a las filas
    x, y, w, h = rect
    if h <= 0 or w <= 0:
        return
    steps = 12
    sh = max(1, h // steps + 1)
    for i in range(steps):
        f = i / float(steps - 1)
        col = tuple(int(c1[k] + (c2[k] - c1[k]) * f) for k in range(3))
        pygame.draw.rect(screen, col, (x, y + i * sh, w, sh))

def notch_points(x, y, w, h, n=15):
    # Cantos cortados en diagonal (arriba-derecha y abajo-izquierda)
    return [(x, y), (x + w - n, y), (x + w, y + n),
            (x + w, y + h), (x + n, y + h), (x, y + h - n)]

def draw_button_notch(rect, active):
    # Moderno: cápsula achaflanada, relleno plano y pestana de acento
    x, y, w, h = rect
    pts = notch_points(x, y, w, h)
    fill = TH['card'] if not active else tuple(min(255, int(c * 0.34) + 18) for c in ACC)
    try:
        pygame.draw.polygon(screen, fill, pts)
        pygame.draw.polygon(screen, ACC if active else TH['border'], pts, 2 if active else 1)
    except Exception:
        pygame.draw.rect(screen, fill, rect)
    # pestana lateral: fina si esta en reposo, gruesa y luminosa al elegir
    pygame.draw.rect(screen, ACC if active else TH['border'],
                     (x, y + (0 if active else 8), 6 if active else 3,
                      h - (0 if active else 16)))
    if active:
        pygame.draw.rect(screen, TH.get('acc2', ACC), (x + w - 15, y, 15, 3))

def draw_button(rect, active):
    # Fila con aspecto de boton: relieve, borde y brillo superior
    if TH.get('shape') == 'notch':
        draw_button_notch(rect, active)
        return
    x, y, w, h = rect
    if active:
        base = tuple(min(255, int(c * 0.42)) for c in ACC)
        vbar((x, y, w, h), base, TH['panel'])
        pygame.draw.rect(screen, ACC, (x, y, w, h), 2, border_radius=RAD)
        pygame.draw.rect(screen, ACC, (x + 2, y + 4, 5, h - 8), border_radius=2)
    else:
        c1 = tuple(min(255, c + 14) for c in TH['card'])
        vbar((x, y, w, h), c1, TH['card'])
        pygame.draw.rect(screen, TH['border'], (x, y, w, h), 1, border_radius=RAD)
    # brillo sutil en el borde superior
    hl = tuple(min(255, c + (46 if active else 22)) for c in TH['card'])
    pygame.draw.rect(screen, hl, (x + 3, y + 1, w - 6, 1))

def draw_chip(x, y, key, text, font):
    # "Pastilla" de ayuda: [A] elegir
    kw = rtext(font, key, TH['bg'])
    tw = rtext(font, text, TH['dim'])
    bw = kw.get_width() + 16
    pygame.draw.rect(screen, ACC, (x, y, bw, 24), border_radius=(0 if ARCADE else 8))
    if ARCADE:
        pygame.draw.rect(screen, TH['acc2'], (x, y, bw, 24), 1)
    screen.blit(kw, (x + 8, y + 3))
    screen.blit(tw, (x + bw + 8, y + 3))
    return x + bw + 16 + tw.get_width()

def draw_header():
    # Cabecera de marca a todo lo ancho, con acento y contador
    hh = HEAD - 6
    pygame.draw.rect(screen, TH['panel'], (0, 0, W, hh))
    hbar((0, hh - 3, W, 3), ACC, TH.get('acc2', ACC))
    if ARCADE:
        # sombra de un color y encima la marca a dos colores
        screen.blit(marca_surface(f_tit, TH['acc2']), (27, 19))
        brand = marca_surface(f_tit)
        screen.blit(brand, (24, 16))
    else:
        brand = marca_surface(f_tit)
        screen.blit(brand, (24, 16))
    bx = 24 + brand.get_width() + 16
    pygame.draw.rect(screen, TH['border'], (bx - 8, 14, 2, hh - 34))
    for i, tl in enumerate(TITLE_LINES):
        screen.blit(f_it.render(fit_label(tl, f_it, W - bx - 150), True, FG),
                    (bx, 16 + i * 26))
    if view:
        badge = f_sm.render('%d/%d' % (sel + 1, len(view)), True, TH['bg'])
        bwd = badge.get_width() + 18
        pygame.draw.rect(screen, ACC, (W - bwd - 20, 18, bwd, 24), border_radius=12)
        screen.blit(badge, (W - bwd - 11, 21))

_forma_cache = {}

def es_ancha(path):
    # ¿La caratula es mas ancha que alta? Se recuerda para no abrir el
    # fichero en cada fotograma.
    if not path:
        return False
    if path not in _forma_cache:
        try:
            img = pygame.image.load(path)
            w, h = img.get_size()
            forma = (w > h)
        except Exception:
            forma = False
        # CON TOPE, como las demas caches de este fichero.
        #
        # Guardaba una entrada por caratula vista y no se vaciaba nunca. En una
        # sesion larga, paseando por una biblioteca grande, eso crece sin
        # parar. Las otras caches (COVER_CACHE, _rcache, _imgcache) ya tenian
        # su limite; estas dos se quedaron sin el.
        if len(_forma_cache) > 300:
            _forma_cache.clear()
        _forma_cache[path] = forma
    return _forma_cache[path]

def cover_surface(ruta, ancho):
    # Carátula escalada, guardada en memoria: sin esto se recargaria del disco
    # 60 veces por segundo al mover la seleccion.
    if not ruta or not os.path.isfile(ruta):
        return None
    clave = (ruta, ancho)
    if clave in COVER_CACHE:
        return COVER_CACHE[clave]
    try:
        img = pygame.image.load(ruta)
        w0, h0 = img.get_size()
        if w0 <= 0 or h0 <= 0:
            return None
        alto = int(ancho * h0 / w0)
        img = pygame.transform.smoothscale(img, (ancho, alto))
    except Exception:
        img = None
    if len(COVER_CACHE) > 40:
        COVER_CACHE.clear()
    COVER_CACHE[clave] = img
    return img

def caches_resumen():
    """Cuantas entradas tiene cada cache. Para el diagnostico.

    Se pidio reducir la memoria del servidor de menus y lo primero era saber
    cuanto de los ~200 MiB son caches nuestras y cuanto es el suelo de pygame
    (superficie de pantalla, fuentes, SDL). Suponerlo habria sido otra ronda
    perdida.
    """
    return 'covers=%d img=%d fit=%d texto=%d forma=%d' % (
        len(COVER_CACHE), len(_imgcache), len(_fitcache),
        len(_rcache), len(_forma_cache))


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
# Ayuda del panel derecho
#
# El panel "SELECCION" repetia el texto de la fila y ya esta, o sea que no
# aportaba nada. Aqui se explica QUE HACE cada opcion, que es lo que cuesta
# adivinar cuando buscas algo y no sabes por donde anda.
#
# Se casa por PREFIJO porque muchas opciones llevan un valor detras
# ("Prefijo: propio del juego", "Runner: GE-Proton11-5"). Gana el prefijo mas
# largo que case, para poder afinar casos concretos sin romper los generales.
#
# OJO: esta tabla vive aqui y los menus se escriben en wproton.sh, asi que
# pueden desincronizarse. Hay una prueba que comprueba que cada prefijo de
# aqui existe de verdad como opcion en el script.
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


def draw_side_panel():
    # Panel derecho: detalle de lo seleccionado. En la lista de juegos muestra
    # ademas la CARATULA y los datos del juego, para que la lista no sea solo
    # una columna de nombres.
    if SIDE_W <= 0:
        return
    rect = (SIDE_X, LIST_Y, SIDE_W, LIST_H)
    draw_panel(rect)
    px, py = SIDE_X + 16, LIST_Y + 14
    screen.blit(f_sm.render(L('SELECCION', 'SELECTION'), True, TH.get('acc2', ACC)), (px, py))
    py += 26
    pygame.draw.rect(screen, TH['border'], (px, py, SIDE_W - 32, 1))
    py += 14
    if view:
        txt = items[view[sel]][1] if MODE != 'grid' else GITEMS[view[sel]][0]
        datos = LIST_INFO.get(txt)
        # el nombre del fichero no aporta nada en el panel
        titulo_panel = (datos or {}).get('nombre') or txt
        for _ext in ('.wsquashfs', '.squashfs', '.dwarfs'):
            if titulo_panel.lower().endswith(_ext):
                titulo_panel = titulo_panel[:-len(_ext)]
                break
        # Carátula: ocupa como mucho la mitad del alto del panel, para que
        # siempre quede sitio para el nombre y los datos.
        if datos and MODE == 'list':
            # Un poco mas grande que antes (170): con caratulas horizontales
            # se quedaba pequeña y no se leia el titulo.
            # Ancho maximo segun la forma de la caratula.
            #
            # Las verticales se limitan a 240 px: mas grandes se comen el
            # panel y no dejan sitio a los datos del juego. Las panoramicas y
            # las 4:3 son mucho mas bajas para el mismo ancho, asi que pueden
            # ocupar el panel entero y se ven bastante mejor.
            _ancho_max = SIDE_W - 16
            if not es_ancha(datos.get('cov')):
                _ancho_max = min(SIDE_W - 24, 240)
            cov = cover_surface(datos.get('cov'), _ancho_max)
            if cov is not None:
                ch = cov.get_height()
                # el tope de alto solo estorba a las verticales
                _alto_max = int(LIST_H * (0.45 if es_ancha(datos.get('cov')) else 0.55))
                if ch > _alto_max:
                    cov = cover_surface(datos.get('cov'),
                                        int(_ancho_max * _alto_max / ch))
                    ch = cov.get_height() if cov is not None else 0
                if cov is not None:
                    cx = SIDE_X + (SIDE_W - cov.get_width()) // 2
                    pygame.draw.rect(screen, TH['border'],
                                     (cx - 2, py - 2, cov.get_width() + 4, ch + 4), 1)
                    screen.blit(cov, (cx, py))
                    py += ch + 14
        _ayuda = ayuda_de(titulo_panel) if not datos else None
        # con ayuda debajo, el titulo se recorta a 3 lineas para dejarle sitio
        for ln in wrap_title(titulo_panel, f_it, SIDE_W - 34,
                             3 if (datos or _ayuda) else 6):
            screen.blit(rtext(f_it, ln, FG), (px, py))
            py += 28
        if _ayuda:
            py += 10
            for ln in wrap_title(_ayuda, f_sm, SIDE_W - 34, 10):
                if py > LIST_Y + LIST_H - 24:
                    break
                screen.blit(rtext(f_sm, ln, DIM), (px, py))
                py += 20
        if datos and MODE == 'list':
            py += 6
            filas = []
            # SIEMPRE las mismas filas, en el mismo orden, aunque el dato no
            # este. Antes solo salian las que tenian valor, asi que cada juego
            # enseñaba unas cuantas distintas y el panel bailaba: la nota, por
            # ejemplo, solo la traen los juegos con puntuacion de Metacritic,
            # y parecia que faltaba informacion en unos y en otros no.
            SIN = L('—')
            filas.append((L('Año', 'Year'), datos.get('ano') or SIN))
            filas.append((L('Desarrollo', 'Developer'), datos.get('dev') or SIN))
            _edi = datos.get('edi')
            if _edi and _edi == datos.get('dev'):
                _edi = ''          # no repetir la misma empresa dos veces
            filas.append((L('Edición', 'Publisher'), _edi or SIN))
            filas.append((L('Género', 'Genre'), datos.get('gen') or SIN))
            filas.append((L('Nota', 'Score'),
                          ('%s/100' % datos['nota']) if datos.get('nota') else SIN))
            filas.append((L('Duración', 'Length'), datos.get('dur') or SIN))
            _veces = datos.get('veces') or '0'
            filas.append((L('Jugado', 'Played'),
                          L('%s veces', '%s times') % _veces if _veces != '0'
                          else L('nunca', 'never')))
            filas.append((L('Tiempo', 'Time'), fmt_horas(datos.get('segs')) or SIN))
            if datos.get('completado') == '1':
                filas.append((L('Estado', 'Status'), L('COMPLETADO', 'COMPLETED')))
            for etiqueta, valor in filas:
                if py > LIST_Y + LIST_H - 26:
                    break
                se = rtext(f_sm, etiqueta, DIM)
                screen.blit(se, (px, py))
                # el valor va a la derecha; si no cabe, se recorta con puntos
                hueco = SIDE_W - 32 - se.get_width() - 10
                v = str(valor)
                sv = rtext(f_sm, v, TH.get('acc2', ACC))
                while sv.get_width() > hueco and len(v) > 4:
                    v = v[:-2]
                    sv = rtext(f_sm, v + '...', TH.get('acc2', ACC))
                screen.blit(sv, (SIDE_X + SIDE_W - 16 - sv.get_width(), py))
                py += 22
            # La sinopsis, con lo que quede de panel. Va la ultima porque es
            # lo unico que puede ocupar mucho y lo que menos se necesita de un
            # vistazo.
            _sin = datos.get('sinopsis')
            if _sin and py < LIST_Y + LIST_H - 40:
                py += 8
                pygame.draw.rect(screen, TH['border'], (px, py, SIDE_W - 32, 1))
                py += 10
                for ln in wrap_title(_sin, f_sm, SIDE_W - 34, 12):
                    if py > LIST_Y + LIST_H - 22:
                        break
                    screen.blit(rtext(f_sm, ln, DIM), (px, py))
                    py += 19
    else:
        screen.blit(f_it.render(L('(vacio)', '(empty)'), True, DIM), (px, py))
        py += 28
    if MODE == 'browse':
        py += 8
        screen.blit(f_sm.render(L('CARPETA', 'FOLDER'), True, TH.get('acc2', ACC)), (px, py))
        py += 22
        for ln in wrap_title(cur_path, f_sm, SIDE_W - 34, 4):
            screen.blit(rtext(f_sm, ln, DIM), (px, py))
            py += 20
    if FILTER:
        py += 10
        screen.blit(f_sm.render('BUSCANDO: %s' % FILTER, True, WARN), (px, py))
        py += 20
        # Si la busqueda no deja ver nada, hay que decirlo Y decir como
        # quitarla. Una pantalla vacia con un filtro puesto parece que no hay
        # ficheros, y no que estan escondidos.
        if not view:
            for _ln in wrap_title('Nada coincide con esa busqueda. '
                                  'Pulsa B para quitarla.', f_sm, SIDE_W - 34, 3):
                screen.blit(rtext(f_sm, _ln, WARN), (px, py))
                py += 20

def draw_footer(chips):
    fy = H - 46
    pygame.draw.rect(screen, TH['panel'], (0, fy - 8, W, 54))
    hbar((0, fy - 10, W, 2), TH.get('acc2', ACC), ACC)
    x = 24
    for k, t in chips:
        x = draw_chip(x, fy + 6, k, t, f_sm)
        if x > W - 160:
            break

def draw_selection(rect):
    # clasico: barra plana | moderno: tarjeta | arcade: barra con marcador
    x, y, w, h = rect
    if TH.get('marker'):
        hbar((x, y, w, h), TH['sel_bg'], TH['bg'])
        pulse = 0.55 + 0.45 * abs(((time.time() * 1.6) % 2.0) - 1.0)
        col = tuple(int(c * pulse) for c in ACC)
        pygame.draw.rect(screen, col, (x, y, w, h), 2)
        pygame.draw.rect(screen, ACC, (x, y, 6, h))
        tri = [(x + 14, y + h // 2), (x + 4, y + 8), (x + 4, y + h - 8)]
        try:
            pygame.draw.polygon(screen, ACC, tri)
        except Exception:
            pass
        return
    if TH['pill']:
        hbar((x, y, w, h), TH['sel_bg'], TH['panel'])
        pygame.draw.rect(screen, ACC, (x, y, w, h), 1, border_radius=RAD)
        pygame.draw.rect(screen, ACC, (x + 2, y + 5, 5, h - 10), border_radius=3)
    else:
        pygame.draw.rect(screen, TH['sel_bg'], (x, y, w, h), border_radius=RAD)

_rcache = {}
def rtext(font, txt, color):
    # font.render cacheado: mismo texto+color+fuente -> misma superficie
    k = (id(font), txt, color)
    surf = _rcache.get(k)
    if surf is None:
        surf = font.render(txt, True, color)
        # TOPE BAJADO DE 900 A 300.
        #
        # Medido en la Deck: con 857 entradas la memoria del servidor sube de
        # 207 a 226 MiB, o sea unos 22 KiB por linea renderizada. Bajando el
        # tope se recorta la mayor parte de ese crecimiento.
        #
        # Se pierde algo de cache y habra que redibujar mas texto, pero eso es
        # justo lo que esta cache hace rapido: preparar un menu tarda 0-3 ms
        # segun el registro, asi que hay margen de sobra.
        if len(_rcache) > 300:
            _rcache.clear()
        _rcache[k] = surf
    return surf

def wrap_title(text, font, maxw, maxlines=6):
    # Respeta los saltos de linea y ajusta al ancho; las rutas largas se
    # parten por caracteres (antes se cortaba el titulo y se perdia la pregunta)
    out = []
    for para in text.split('\n'):
        para = para.rstrip()
        if not para:
            out.append('')
            continue
        words, line = para.split(' '), ''
        for wd in words:
            probe = (line + ' ' + wd).strip()
            if rtext(font, probe, FG).get_width() <= maxw:
                line = probe
                continue
            if line:
                out.append(line)
                line = ''
            while rtext(font, wd, FG).get_width() > maxw:
                cut = len(wd)
                while cut > 1 and rtext(font, wd[:cut], FG).get_width() > maxw:
                    cut -= 1
                out.append(wd[:cut])
                wd = wd[cut:]
            line = wd
        if line:
            out.append(line)
    if len(out) > maxlines:
        out = out[:maxlines - 1] + ['\u2026']
    return out or ['']

# Valores que dependen del TITULO y del MODO: se recalculan en cada peticion
TITLE_LINES = ['']
T_FONT = None
T_LH = 30
HEAD = 70
ROW = 40
PANEL_UI = False
ARCADE = False
TOP = HEAD
LIST_X, LIST_Y, LIST_W, LIST_H = 16, TOP, 900, 480
SIDE_X, SIDE_W = 0, 0
VIS_FULL = 10
KB_H = 200
VIS_KB = 6

def compute_layout():
    # Recalcula todo lo que depende del titulo y del modo de esta peticion
    global TITLE_LINES, T_FONT, T_LH, HEAD, ROW, PANEL_UI, ARCADE, TOP
    global LIST_X, LIST_Y, LIST_W, LIST_H, SIDE_X, SIDE_W, VIS_FULL, VIS_KB
    T_FONT = f_tit if len(TITLE) < 60 else f_it
    TITLE_LINES = wrap_title(TITLE, T_FONT, 912)
    T_LH = FS(34) if T_FONT is f_tit else FS(30)
    HEAD = int(22 * FSCALE) + len(TITLE_LINES) * T_LH + 14
    ROW = max(TH['row'], int(TH['row'] * FSCALE))
    PANEL_UI = TH.get('layout') in ('panel', 'arcade')
    ARCADE = TH.get('layout') == 'arcade'
    TOP = (HEAD + 30) if MODE == 'browse' else HEAD
    LIST_X, LIST_Y = 16, TOP
    VIS_FULL = max(1, (H - TOP - 60) // ROW)
    VIS_KB = max(1, (H - TOP - 60 - KB_H) // ROW)
    apply_layout()

# --- teclado virtual (rejilla navegable con el dpad) ---
KB_ROWS = ['ABCDEFGHIJ',
           'KLMNOPQRST',
           'UVWXYZ0123',
           '456789 .-_']
KB_ACTIONS = ['BORRAR', 'LIMPIAR', 'LISTO'] if LANG != 'en' else ['DELETE', 'CLEAR', 'DONE']

def kb_cols(r):
    return len(KB_ACTIONS) if r == len(KB_ROWS) else len(KB_ROWS[r])

def shorten(p, n=82):
    return p if len(p) <= n else '\u2026' + p[-(n - 1):]

def write_out(text):
    with open(OUTFILE, 'w', encoding='utf-8') as f:
        f.write(text)

def _mark_clean_exit():
    # marca de "cierre ordenado": si falta, es que el proceso murio de golpe
    try:
        with open(OUTFILE + '.done', 'w') as _fh:
            _fh.write('ok')
    except Exception:
        pass

class SessionEnd(Exception):
    # Fin de UNA peticion. En modo servidor no se cierra la ventana: se
    # vuelve al reposo esperando la siguiente.
    def __init__(self, code):
        Exception.__init__(self, code)
        self.code = code

def safe_quit(code):
    # el texto ya esta escrito: pase lo que pase al cerrar, el llamador
    # recibe el codigo correcto
    _mark_clean_exit()
    if SERVER_MODE:
        raise SessionEnd(code)
    try:
        pygame.quit()
    except Exception:
        pass
    sys.exit(code)

def vis():
    return VIS_KB if kb_open else VIS_FULL

def pagina(d):
    """Salta una pantalla entera SIN mover la fila donde esta el puntero.

    move() recoloca el desplazamiento a partir de la seleccion, asi que
    usarlo para saltar dejaba el puntero pegado al borde de la pantalla. Aqui
    se mueven la seleccion Y el desplazamiento juntos: si estabas en la
    tercera fila, sigues en la tercera fila de la pagina siguiente.

    En los extremos no se da la vuelta: se llega al principio o al final y el
    puntero se queda donde pueda, que es lo que uno espera al pasar paginas.
    """
    global sel, scroll
    if not view:
        return
    n = len(view)
    v = vis()
    fila = sel - scroll                     # en que fila de la pantalla estoy
    salto = d * _pagina()
    nuevo_sel = max(0, min(n - 1, sel + salto))
    if nuevo_sel == sel:                    # ya estabamos en el extremo
        sel = 0 if d < 0 else n - 1
    else:
        sel = nuevo_sel
    # El desplazamiento se recoloca para dejar el puntero en la MISMA fila,
    # y despues se ajusta a los limites de la lista.
    scroll = max(0, min(max(0, n - v), sel - fila))
    if sel < scroll:
        scroll = sel
    elif sel >= scroll + v:
        scroll = sel - v + 1


def _pagina():
    """Cuantas filas salta una 'pagina'.

    Las que caben en pantalla menos una, para que quede una de referencia y
    no se pierda el hilo al saltar. Con el teclado de busqueda abierto caben
    menos, y hay que usar ese numero.
    """
    vis = VIS_KB if kb_open else VIS_FULL
    return max(1, vis - 1)


def move(d):
    global sel, scroll
    if not view:
        return
    sel = (sel + d) % len(view)
    if sel < scroll:
        scroll = sel
    if sel >= scroll + vis():
        scroll = sel - vis() + 1

def toggle():
    if MODE == 'check' and view:
        it = items[view[sel]]
        it[2] = not it[2]

# Rejilla adaptativa: en pantallas de portatil/consola (Steam Deck, Legion Go)
# menos columnas y carátulas MAS GRANDES; en monitores grandes, más columnas.
# WP_GRID_COLS fuerza un numero concreto de columnas (0 = automático).
GCOLS = 5
GCW, GCH = 176, 268
GIMG_W, GIMG_H = 150, 225

# Proporcion de la caratula: alto = ancho * ASPECTO.
#   1.5  -> vertical, 2:3, la clasica de las tiendas
#   0.47 -> panoramica, tipo cabecera de Steam (920x430)
#   0.75 -> 4:3, para colecciones de caratulas cuadradas (640x480)
# Cuanto mas ancha, menos caben por fila pero mas grandes se ven.
ASPECTOS = {'1': 0.47, 'wide': 0.47, '43': 0.75, 'vertical': 1.5, '': 1.5}
ASPECTO = ASPECTOS.get(os.environ.get('WP_GRID_BANNER', ''), 1.5)

def set_aspecto(valor):
    # La proporcion viaja en CADA peticion, no solo al arrancar.
    #
    # Antes se leia una sola vez, al iniciar el proceso de menus. Como ese
    # proceso es persistente, cambiar de vista dejaba las casillas con la
    # forma anterior: las caratulas verticales salian en recuadros anchos.
    # Asi no depende de reiniciar nada.
    global ASPECTO
    nuevo = ASPECTOS.get(valor or '', 1.5)
    if nuevo != ASPECTO:
        ASPECTO = nuevo
        _imgcache.clear()      # las caratulas escaladas ya no valen
_imgcache = {}

def grid_metrics():
    # Tamaño de carátula según la pantalla. La regla que manda es la ALTURA:
    # la caratura debe caber en su fila con holgura (2 filas en monitores,
    # 1 fila grande en consolas portatiles). Antes solo se repartia el ancho
    # y en un monitor de sobremesa salian gigantes.
    global GCOLS, GCW, GCH, GIMG_W, GIMG_H
    # Se reserva un margen a la derecha para el indicador de desplazamiento.
    # Sin el, las caratulas anchas de la ultima columna se metian debajo de la
    # barra y parecia que se salian de la pantalla.
    avail_w = (LIST_W if PANEL_UI else (W - 40)) - 18
    avail_h = max(120, LIST_H - 16)
    forced = 0
    try:
        forced = int(os.environ.get('WP_GRID_COLS', '0'))
    except ValueError:
        forced = 0
    if forced > 0:
        rows = 1 if avail_h < 620 else 2
    elif avail_h < 620:          # Steam Deck, Legion Go, ventana baja
        rows = 1
    else:                        # monitor: dos filas de carátulas
        rows = 2
    # altura por fila (incluye el hueco del titulo): así las filas CABEN
    h_max = int(avail_h / rows) - 48
    w_from_h = int(h_max / ASPECTO)
    # ancho maximo razonable por carátula según el tamaño de pantalla
    w_cap = 190 if W <= 1400 else (210 if W <= 1920 else 240)
    if ASPECTO < 1:          # horizontales: mas anchas, caben menos por fila
        w_cap = int(w_cap * 2.1)
    if forced > 0:
        # columnas fijadas por el usuario: el tamaño de la carátula se calcula
        # para que QUEPAN esas columnas (antes se mantenía el tamaño y con
        # muchas columnas se salían de la pantalla)
        GCOLS = forced
        GCW = max(80, avail_w // forced)
        GIMG_W = max(90, GCW - 26)
        # y que la fila siga cabiendo de alto
        if int(GIMG_W * ASPECTO) + 48 > int(avail_h / rows):
            GIMG_W = max(90, int((int(avail_h / rows) - 48) / ASPECTO))
        GIMG_H = int(GIMG_W * ASPECTO)
        GCH = GIMG_H + 48
    else:
        GIMG_W = max(120, min(w_from_h, w_cap))
        GIMG_H = int(GIMG_W * ASPECTO)
        GCW = GIMG_W + 26
        GCH = GIMG_H + 48
        GCOLS = max(3, min(9, avail_w // GCW))
    _imgcache.clear()          # las imagenes se reescalan al nuevo tamaño

def grid_rows_vis():
    area = H - TOP - 60 - (KB_H if kb_open else 0)
    return max(1, area // GCH)

def grid_move(dx, dy):
    global sel, scroll
    if not view:
        return
    n = len(view)
    if dy == 0:
        sel = (sel + dx) % n
    else:
        s2 = sel + dy * GCOLS
        if 0 <= s2 < n:
            sel = s2
        elif dy > 0 and (sel // GCOLS) < ((n - 1) // GCOLS):
            sel = n - 1          # bajar a una fila incompleta: último juego
        # en los bordes verticales: quieto (el horizontal si envuelve)
    row = sel // GCOLS
    first = scroll // GCOLS
    vis_r = grid_rows_vis()
    if row < first:
        scroll = row * GCOLS
    elif row >= first + vis_r:
        scroll = (row - vis_r + 1) * GCOLS

def row_segments(label, base_color):
    # "Prefijo: compartido" -> etiqueta en color de acento, valor en blanco.
    # "MangoHud: ON" -> ON en verde, OFF apagado.
    if not TH.get('labelcolor') or ':' not in label:
        return [(label, base_color)]
    k, _, v = label.partition(':')
    # "arcade - synthwave: ..." no es etiqueta+valor, es una descripcion
    if ' - ' in k or len(k) > 36:
        return [(label, base_color)]
    # Unos dos puntos DENTRO de un parentesis no separan etiqueta y valor:
    # son parte del texto, como la proporcion "(2:3)". Sin esto, "Solo
    # verticales (2:3)" se pintaba como si "Solo verticales (2" fuera la
    # etiqueta, y los numeros salian de otro color.
    if k.count('(') > k.count(')'):
        return [(label, base_color)]
    segs = [(k + ':', TH.get('acc2', ACC))]
    v = v.strip()
    if v:
        low = v.lower()
        if low in ('on', 'si'):
            segs.append((' ' + v, TH.get('ok', ACC)))
        elif low in ('off', 'no'):
            segs.append((' ' + v, DIM))
        else:
            segs.append((' ' + v, base_color))
    return segs

def draw_segments(segs, font, x, y, maxw, active):
    # Pinta varios trozos de texto con colores distintos, con marquesina si
    # el conjunto no cabe (solo en la fila seleccionada) y recorte estricto.
    surfs = [(rtext(font, t, c), t, c) for t, c in segs if t]
    total = sum(sf.get_width() for sf, _, _ in surfs)
    if total <= maxw:
        cx = x
        for sf, _, _ in surfs:
            screen.blit(sf, (cx, y))
            cx += sf.get_width()
        return
    if not active:
        cx, rest = x, maxw
        for sf, t, c in surfs:
            wsf = sf.get_width()
            if wsf <= rest:
                screen.blit(sf, (cx, y)); cx += wsf; rest -= wsf
            else:
                screen.blit(rtext(font, fit_label(t, font, rest), c), (cx, y))
                break
        return
    over = total - maxw
    period = 2.2 + over / 70.0
    tt = (time.time() % (period * 2)) / period
    f = tt if tt <= 1.0 else 2.0 - tt
    f = max(0.0, min(1.0, (f - 0.14) / 0.72))
    old = None
    try:
        old = screen.get_clip()
        screen.set_clip((x, y - 2, maxw, ROW))
    except Exception:
        pass
    cx = x - int(over * f)
    for sf, _, _ in surfs:
        screen.blit(sf, (cx, y))
        cx += sf.get_width()
    try:
        screen.set_clip(old)
    except Exception:
        pass

# LOS DOS COLORES DE LA MARCA NO DEPENDEN DEL TEMA.
#
# "PROTON" se pintaba con el acento del tema activo, asi que la palabra
# cambiaba de color en cada uno. El morado y el cian de moderno son ya la
# seña de la marca, y una marca que cambia de color no es una marca. El tema
# sigue mandando en todo lo demas -incluida la sombra del arcade, que es
# suya-, pero estas dos letras se quedan quietas.
MORADO_W = (150, 90, 230)      # el morado de la W
CIAN_PROTON = (56, 214, 224)   # el cian de moderno, para "PROTON"

def marca_surface(fuente, color=None):
    # "WPROTON" con la W en morado y el resto en el color de acento. Se
    # devuelve como una sola imagen para poder centrarla y medirla como
    # antes. Con "color" se fuerza un unico color (sombra del tema arcade).
    c_w = color if color else MORADO_W
    c_r = color if color else CIAN_PROTON
    sw = fuente.render('W', True, c_w)
    sr = fuente.render('PROTON', True, c_r)
    try:
        sup = pygame.Surface((sw.get_width() + sr.get_width(),
                              max(sw.get_height(), sr.get_height())),
                             pygame.SRCALPHA)
        sup.blit(sw, (0, 0))
        sup.blit(sr, (sw.get_width(), 0))
        return sup
    except Exception:
        return fuente.render('WPROTON', True, c_r)

def draw_estrella(cx, cy, r, color):
    # Estrella de cinco puntas dibujada a mano: el simbolo tipografico no
    # existe en la fuente por defecto, y un asterisco quedaba pobre.
    import math
    pts = []
    for i in range(10):
        ang = math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rad * math.cos(ang), cy - rad * math.sin(ang)))
    try:
        pygame.draw.polygon(screen, color, pts)
    except Exception:
        pass

def draw_row_text(text, font, color, x, y, maxw, active):
    # Si el texto no cabe: en la fila seleccionada se desplaza (marquesina),
    # en las demás se recorta. Antes se salia de la tarjeta e invadia el panel.
    surf = rtext(font, text, color)
    w = surf.get_width()
    if w <= maxw:
        screen.blit(surf, (x, y))
        return
    if not active:
        screen.blit(rtext(font, fit_label(text, font, maxw), color), (x, y))
        return
    over = w - maxw
    period = 2.2 + over / 70.0          # cuanto más larga, más despacio
    tt = (time.time() % (period * 2)) / period
    f = tt if tt <= 1.0 else 2.0 - tt   # ida y vuelta
    f = max(0.0, min(1.0, (f - 0.14) / 0.72))   # pausa en los extremos
    old = None
    try:
        old = screen.get_clip()
        screen.set_clip((x, y - 2, maxw, ROW))
    except Exception:
        pass
    screen.blit(surf, (x - int(over * f), y))
    try:
        screen.set_clip(old)
    except Exception:
        pass

_fitcache = {}
def fit_label(txt, font, maxw):
    # Recorta midiendo el ancho renderizado (por caracteres se solapaban)
    k = (txt, maxw)
    if k in _fitcache:
        return _fitcache[k]
    # CON TOPE. Guardaba una entrada por CADA etiqueta distinta de CADA menu, y
    # no se vaciaba nunca: en una sesion larga son miles, y son las etiquetas
    # enteras, no un identificador. Las demas caches del fichero ya tenian su
    # limite.
    if len(_fitcache) > 900:
        _fitcache.clear()
    if rtext(font, txt, FG).get_width() <= maxw:
        _fitcache[k] = txt
        return txt
    t = txt
    while t and rtext(font, t + '\u2026', FG).get_width() > maxw:
        t = t[:-1]
    t = (t.rstrip() + '\u2026') if t else '\u2026'
    _fitcache[k] = t
    return t

def grid_img(path):
    # La caratula se ajusta a la casilla SIN DEFORMARLA.
    #
    # Antes se estiraba hasta llenarla, asi que en la vista de caratulas
    # anchas una vertical salia achatada y horrible. Ahora se escala hasta
    # que quepa entera y se centra sobre el fondo de la casilla; asi una
    # vertical en una casilla ancha se ve bien, solo con aire a los lados.
    clave = (path, GIMG_W, GIMG_H)
    if clave in _imgcache:
        return _imgcache[clave]
    # CON TOPE DE TAMAÑO, no solo vaciandose al cambiar el tema.
    #
    # Guardaba una superficie escalada por cada caratula vista y solo se
    # vaciaba al cambiar de tema o de tamaño de casilla. Con una biblioteca
    # grande son cientos de superficies vivas a la vez.
    if len(_imgcache) > 120:
        _imgcache.clear()
    if not path or not os.path.isfile(path):
        _imgcache[clave] = None
        return None
    try:
        img = pygame.image.load(path).convert_alpha()
        w0, h0 = img.get_size()
        if w0 <= 0 or h0 <= 0:
            raise ValueError('imagen vacia')
        escala = min(GIMG_W / w0, GIMG_H / h0)
        an, al = max(1, int(w0 * escala)), max(1, int(h0 * escala))
        peq = pygame.transform.smoothscale(img, (an, al))
        if an == GIMG_W and al == GIMG_H:
            _imgcache[clave] = peq
        else:
            lienzo = pygame.Surface((GIMG_W, GIMG_H), pygame.SRCALPHA)
            lienzo.fill(TH.get('card', (20, 26, 44)))
            lienzo.blit(peq, ((GIMG_W - an) // 2, (GIMG_H - al) // 2))
            _imgcache[clave] = lienzo
    except Exception:
        _imgcache[clave] = None
    return _imgcache[clave]

def draw_grid():
    gx0 = LIST_X + max(0, (LIST_W - GCOLS * GCW) // 2) + (GCW - GIMG_W) // 2
    vis_r = grid_rows_vis()
    first = scroll
    for i in range(first, min(first + vis_r * GCOLS, len(view))):
        col = (i - first) % GCOLS
        rowi = (i - first) // GCOLS
        x = gx0 + col * GCW
        y = LIST_Y + 8 + rowi * GCH
        _cell = (x - 6, y - 6, GIMG_W + 12, GCH - 18)
        if TH['panel'] is not None:
            pygame.draw.rect(screen, TH['card'], _cell, border_radius=RAD)
        if i == sel and not kb_open:
            draw_selection(_cell)
        title, ipath, _pay = GITEMS[view[i]][:3]
        is_fav = len(GITEMS[view[i]]) > 3 and GITEMS[view[i]][3] == '1' 
        img = grid_img(ipath)
        if img:
            screen.blit(img, (x, y))
        else:
            pygame.draw.rect(screen, TH['card'], (x, y, GIMG_W, GIMG_H), border_radius=RAD)
            pygame.draw.rect(screen, TH['border'], (x, y, GIMG_W, GIMG_H), 1, border_radius=RAD)
            line, yy = '', y + 16
            for wd in title.split() + ['']:
                t2 = (line + ' ' + wd).strip()
                if wd and f_sm.render(t2, True, FG).get_width() < GIMG_W - 12:
                    line = t2
                    continue
                if line and yy < y + GIMG_H - 20:
                    screen.blit(f_sm.render(fit_label(line, f_sm, GIMG_W - 12), True, FG), (x + 6, yy))
                    yy += 22
                line = wd
        if is_fav:
            # cinta diagonal en la esquina superior derecha de la carátula
            rb = max(26, GIMG_W // 5)
            try:
                pygame.draw.polygon(screen, TH.get('acc2', ACC),
                                    [(x + GIMG_W - rb, y), (x + GIMG_W, y),
                                     (x + GIMG_W, y + rb)])
                pygame.draw.line(screen, FG, (x + GIMG_W - rb, y),
                                 (x + GIMG_W, y + rb), 2)
            except Exception:
                pygame.draw.rect(screen, TH.get('acc2', ACC),
                                 (x + GIMG_W - rb, y, rb, 8))
        draw_row_text(title, f_sm, FG if i == sel else DIM,
                      x, y + GIMG_H + 8, GIMG_W, i == sel)

def action_sobre_juego(accion):
    # Devuelve "WPACT:<accion>|<lo elegido>" y cierra el menu. WProton hace lo
    # suyo y vuelve a abrir la lista donde estaba.
    #   CONFIG -> configurar (X)      INFO -> ficha (L1)      FAV -> favorito (R1)
    global running, done
    if not view:
        return
    if MODE == 'grid':
        payload = GITEMS[view[sel]][2]
    else:
        payload = items[view[sel]][1]
    write_out('WPACT:%s|%s' % (accion, payload))
    running = False; done = True

def action_x():
    action_sobre_juego('CONFIG')

def marcar_favorito():
    # Cambia el favorito en el acto (sin cerrar el menu) y lo apunta para que
    # WProton lo guarde en el perfil cuando el menu termine.
    if not view:
        return
    if MODE == 'grid':
        # En la rejilla el favorito vive en GITEMS (es lo que dibuja la cinta
        # en la caratula), no en LIST_INFO: hay que cambiarlo ahi para que se
        # vea al instante.
        fila = GITEMS[view[sel]]
        nombre = fila[0]
        while len(fila) < 4:
            fila.append('0')
        fila[3] = '0' if str(fila[3]) == '1' else '1'
    else:
        nombre = items[view[sel]][1]
        datos = LIST_INFO.get(nombre)
        if datos is None:
            datos = {'fav': '0'}
            LIST_INFO[nombre] = datos
        datos['fav'] = '0' if datos.get('fav') == '1' else '1'
    if not FAV_FILE:
        return
    try:
        # se apunta cada pulsacion: WProton alterna una vez por cada una
        with open(FAV_FILE, 'a', encoding='utf-8') as fh:
            fh.write(nombre + '\n')
    except Exception:
        pass

def on_enter():
    global running, done
    if MODE == 'grid':
        if not view:
            return
        write_out(GITEMS[view[sel]][2])
        running = False; done = True
        return
    if not view:
        return
    kind, txt, _ = items[view[sel]]
    if MODE == 'check':
        write_out('|'.join(t for k, t, on in items if on))
        running = False; done = True
    elif MODE == 'browse':
        if kind == K_HDR:
            write_out(cur_path); running = False; done = True
        elif kind == K_UP2:
            load_dir(os.path.dirname(cur_path))
        elif kind == K_CANCEL:
            running = False
        elif kind == K_DIR:
            load_dir(os.path.join(cur_path, txt[:-1]))
        else:
            write_out(os.path.join(cur_path, txt)); running = False; done = True
    else:
        write_out(txt); running = False; done = True

def on_escape():
    global running, FILTER
    if FILTER:
        FILTER = ''
        _refilter()
        return
    if MODE == 'browse':
        parent = os.path.dirname(cur_path)
        if parent != cur_path:
            load_dir(parent)
        else:
            # Ya estamos en la raiz: no hay donde subir, asi que B cierra el
            # navegador. Antes no hacia nada y daba la sensacion de que se
            # habia quedado colgado.
            running = False
    else:
        running = False

def _refilter():
    if MODE == 'grid':
        grid_apply_filter()
    else:
        apply_filter()

def filter_add(ch, origen='?'):
    # Se deja constancia de CADA letra que entra en la busqueda y de donde
    # viene. Hubo un caso de un filtro que aparecia solo ("ij") y escondia los
    # ficheros; sin esto no habia forma de saber si lo escribia el usuario, el
    # teclado en pantalla o el propio mando.
    global FILTER
    FILTER += ch
    sys.stderr.write('menu_pygame: busqueda += %r (%s) -> %r\n'
                     % (ch, origen, FILTER))
    _refilter()

def filter_back():
    global FILTER
    if FILTER:
        FILTER = FILTER[:-1]
        _refilter()

def kb_press():
    global kb_open
    if kb_r == len(KB_ROWS):
        act = KB_ACTIONS[kb_c]
        if act in ('BORRAR', 'DELETE'):
            filter_back()
        elif act in ('LIMPIAR', 'CLEAR'):
            global FILTER
            FILTER = ''
            _refilter()
        else:                       # LISTO
            kb_open = False
    else:
        filter_add(KB_ROWS[kb_r][kb_c].lower(), 'teclado en pantalla')

def run_session():
    # Ejecuta UNA peticion (un menu, un teclado, una barra de progreso)
    # y devuelve su codigo de salida. En modo servidor se llama muchas
    # veces sobre la MISMA ventana; en modo suelto, una sola vez.
    global MODE, TITLE, OUTFILE, ARG4, BROWSE_KIND, items
    global view, cur_path, sel, scroll, FILTER, kb_open
    global kb_r, kb_c, GITEMS, running, done, screen
    global FULLSCREEN, TITLE_LINES, T_FONT, T_LH, HEAD, ROW
    global PANEL_UI, ARCADE, TOP, LIST_X, LIST_Y, LIST_W
    global LIST_H, SIDE_X, SIDE_W, VIS_FULL, VIS_KB
    # estado del teclado virtual: sus funciones internas lo declaran global,
    # asi que run_session tiene que declararlo tambien o quedaria como local
    global TXT, shift, tr_r, tr_c

    if MODE == 'ver':
        # Visor de un fichero de texto, con scroll de verdad.
        #
        # El registro se enseñaba con zenity (una ventana de escritorio que en
        # el modo Juego ni se ve) o, si no habia, metiendo 60 lineas como
        # opciones de un menu: se cortaban por la derecha y no habia forma de
        # leer una linea larga entera.
        #
        # ARG4 = fichero a mostrar
        try:
            with open(ARG4, encoding='utf-8', errors='replace') as fh:
                crudo = fh.read().split('\n')
        except OSError as e:
            crudo = ['No se pudo abrir el fichero:', str(e)]
        # Se parten las lineas largas al ancho de la pantalla: es la unica
        # forma de leerlas enteras sin scroll horizontal, que con el mando
        # seria un suplicio.
        ancho = W - FS(40)
        lineas = []
        for l in crudo:
            l = l.rstrip()
            if not l:
                lineas.append('')
                continue
            lineas.extend(wrap_title(l, f_sm, ancho, 40) or [''])
        if not lineas:
            lineas = ['(vacio)']
        alto_l = f_sm.get_height() + FS(3)
        visibles = max(4, (H - HEAD - FS(70)) // alto_l)
        # se abre AL FINAL: lo que acaba de pasar es lo que interesa
        pos = max(0, len(lineas) - visibles)
        clockV = pygame.time.Clock()
        while True:
            for ev in eventos():
                if ev.type == pygame.QUIT:
                    safe_quit(1)
                if ev.type != pygame.KEYDOWN:
                    continue
                k = ev.key
                if k in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                    safe_quit(0)
                elif k in (pygame.K_RETURN, pygame.K_SPACE):
                    safe_quit(0)
                elif k == pygame.K_UP:
                    pos = max(0, pos - 1)
                elif k == pygame.K_DOWN:
                    pos = min(max(0, len(lineas) - visibles), pos + 1)
                elif k == pygame.K_PAGEUP:
                    pos = max(0, pos - visibles)
                elif k == pygame.K_PAGEDOWN:
                    pos = min(max(0, len(lineas) - visibles), pos + visibles)
                elif k == pygame.K_HOME:
                    pos = 0
                elif k == pygame.K_END:
                    pos = max(0, len(lineas) - visibles)
            if BGSURF is not None:
                screen.blit(BGSURF, (0, 0))
            else:
                screen.fill(TH['bg'])
            draw_header()
            y = HEAD + FS(10)
            for l in lineas[pos:pos + visibles]:
                col = FG
                # un poco de color para lo que importa
                if '[!]' in l or 'ERROR' in l or 'AVISO' in l or 'WARN' in l:
                    col = TH.get('acc2', ACC)
                elif l.lstrip().startswith('[+]'):
                    col = ACC
                elif l.lstrip().startswith('['):
                    col = DIM
                screen.blit(rtext(f_sm, l, col), (FS(20), y))
                y += alto_l
            # cuanto queda, y como moverse
            total = max(1, len(lineas))
            pie = L('%d-%d de %d   |   arriba/abajo, L1/R1 pagina, B salir') % (
                pos + 1, min(pos + visibles, total), total)
            sf = rtext(f_sm, pie, DIM)
            screen.blit(sf, ((W - sf.get_width()) // 2, H - sf.get_height() - FS(14)))
            if SCANSURF is not None:
                screen.blit(SCANSURF, (0, 0))
            pygame.display.flip()
            grabar_fotograma()
            clockV.tick(30)

    if MODE == 'canvas':
        # Fondo persistente para el MODO JUEGO de SteamOS.
        #
        # El problema: cada menu abria y cerraba su ventana. Al salir de un juego,
        # gamescope se quedaba sin ninguna superficie nuestra y no sabia a quien
        # devolver el foco: el menu siguiente nacia detras y parecia que WProton
        # no volvia. Con esta ventana SIEMPRE viva, el compositor siempre tiene a
        # donde volver, y los menus se dibujan encima de ella.
        #
        # Se cierra sola cuando el fichero de estado dice STOP (o desaparece).
        clockC = pygame.time.Clock()
        status = ''
        misses = 0
        while True:
            for ev in eventos():
                if ev.type == pygame.QUIT:
                    safe_quit(0)
            try:
                with open(ARG4, encoding='utf-8') as fh:
                    status = fh.readline().strip()
                misses = 0
            except Exception:
                misses += 1
                if misses > 40:            # el fichero ya no esta: nos vamos
                    safe_quit(0)
            if status.startswith('STOP'):
                safe_quit(0)
            screen.blit(BGSURF, (0, 0))
            if PANEL_UI:
                draw_header()
            # marca centrada
            big = pygame.font.Font(None, max(48, W // 14))
            # Composicion vertical a partir de la ALTURA REAL de la marca: antes
            # se usaban distancias fijas y con la letra grande el texto de estado
            # se montaba encima de "WPROTON".
            brand = marca_surface(big)
            try:
                bh = brand.get_height()
            except Exception:
                bh = FS(96)
            by = H // 2 - bh
            screen.blit(brand, ((W - brand.get_width()) // 2, by))
            _y = by + bh + FS(28)          # el estado empieza DEBAJO de la marca
            if status:
                for _ln in wrap_title(status, f_it, W - 120, 3):
                    sf = rtext(f_it, _ln, FG)
                    screen.blit(sf, ((W - sf.get_width()) // 2, _y))
                    _y += FS(34)
            # punto animado, para que se vea que sigue vivo
            _p = int(time.time() * 2) % 4
            dots = rtext(f_sm, '.' * _p, DIM)
            screen.blit(dots, ((W - dots.get_width()) // 2, _y + FS(16)))
            if SCANSURF is not None:
                screen.blit(SCANSURF, (0, 0))
            pygame.display.flip()
            grabar_fotograma()
            _last_frame[0] = time.time()
            clockC.tick(15)          # muy poco consumo: no compite con el juego

    if MODE == 'progress':
        # Ventana de espera: lee "pct|texto" del fichero de estado hasta DONE
        bar_pct, bar_txt = 0, L('Preparando...', 'Preparing...')
        clock2 = pygame.time.Clock()
        while True:
            for ev in eventos():
                if ev.type == pygame.QUIT:
                    pygame.quit(); sys.exit(0)
            try:
                with open(ARG4, encoding='utf-8') as fh:
                    raw = fh.readline().rstrip('\n')
                if raw.startswith('DONE'):
                    break
                p, _, t = raw.partition('|')
                bar_pct = max(0, min(100, int(p or 0)))
                bar_txt = t or bar_txt
            except Exception:
                pass
            screen.blit(BGSURF, (0, 0))
            for _i, _tl in enumerate(TITLE_LINES):
                screen.blit(rtext(T_FONT, _tl, FG), (24, 22 + _i * T_LH))
            pygame.draw.line(screen, (60, 64, 74), (24, HEAD - 8), (W - 24, HEAD - 8), 1)
            screen.blit(f_it.render(fit_label(bar_txt, f_it, W - 60), True, FG), (30, HEAD + 24))
            bx, by, bw, bh = 30, HEAD + 74, W - 60, 26
            pygame.draw.rect(screen, TH['card'], (bx, by, bw, bh), border_radius=RAD)
            if TH['panel'] is not None:
                pygame.draw.rect(screen, TH['border'], (bx, by, bw, bh), 1, border_radius=RAD)
            if bar_pct > 0:
                pygame.draw.rect(screen, ACC if TH['glow'] else HIBG,
                                 (bx, by, int(bw * bar_pct / 100.0), bh), border_radius=RAD)
            else:
                t0 = (time.time() * 220) % (bw * 2)
                xx = t0 if t0 < bw else (bw * 2 - t0)
                pygame.draw.rect(screen, ACC if TH['glow'] else HIBG,
                                 (bx + max(0, min(bw - 140, xx - 70)), by, 140, bh), border_radius=RAD)
            if bar_pct:
                screen.blit(f_sm.render('%d%%' % bar_pct, True, DIM), (bx, by + bh + 8))
            screen.blit(f_sm.render(L('Espera, esto puede tardar...', 'Please wait, this may take a while...'), True, DIM), (24, H - 40))
            if SCANSURF is not None:
                screen.blit(SCANSURF, (0, 0))
            pygame.display.flip()
            grabar_fotograma()
            _last_frame[0] = time.time()
            clock2.tick(30)
        pygame.quit()
        sys.exit(0)

    if MODE == 'text':
        # Editor de una linea con teclado en pantalla: para argumentos, DLL
        # overrides, notas... Se maneja con el mando (o el teclado real).
        # El valor de partida. Nunca el nombre del fichero de salida: si no
        # hay valor, se empieza en blanco.
        TXT = ARG4 if (len(sys.argv) > 4 and ARG4 != OUTFILE) else ''
        TROWS = ['1234567890-=',
                 'qwertyuiop[]',
                 'asdfghjkl;\'',
                 'zxcvbnm,./\\',
                 ' _:"|+*@#$%&']
        TACT = [L('MAYUS', 'SHIFT'), L('BORRAR', 'DELETE'),
                L('LIMPIAR', 'CLEAR'), L('ACEPTAR', 'ACCEPT'), L('CANCELAR', 'CANCEL')]
        tr_r, tr_c, shift = 0, 0, False
        clockT = pygame.time.Clock()
        t_open2 = time.time()

        def tcols(r):
            return len(TACT) if r == len(TROWS) else len(TROWS[r])

        def col_al_entrar(fila, col):
            """En que columna cae el puntero al llegar a una fila.

            En la fila de acciones se va a ACEPTAR, no a la columna que
            tuvieras. Antes se conservaba la columna y, viniendo de la derecha
            del teclado, caia en CANCELAR: justo lo contrario de lo que uno
            quiere despues de escribir algo.
            """
            if fila == len(TROWS):
                for k, a in enumerate(TACT):
                    if a in ('ACEPTAR', 'ACCEPT'):
                        return k
            return min(col, tcols(fila) - 1)

        def t_press():
            global TXT, shift, tr_r, tr_c
            if tr_r == len(TROWS):
                act = TACT[tr_c]
                if act in ('MAYUS', 'SHIFT'):
                    shift = not shift
                elif act in ('BORRAR', 'DELETE'):
                    TXT = TXT[:-1]
                elif act in ('LIMPIAR', 'CLEAR'):
                    TXT = ''
                elif act in ('ACEPTAR', 'ACCEPT'):
                    return 'ok'
                else:
                    return 'cancel'
            else:
                ch = TROWS[tr_r][tr_c]
                TXT += ch.upper() if shift else ch
            return None

        while True:
            for ev in eventos():
                if ev.type == pygame.QUIT:
                    safe_quit(1)
                if ev.type != pygame.KEYDOWN:
                    continue
                if time.time() - t_open2 < 0.35:
                    continue
                if ev.key == pygame.K_UP:
                    tr_r = (tr_r - 1) % (len(TROWS) + 1)
                    tr_c = col_al_entrar(tr_r, tr_c)
                elif ev.key == pygame.K_DOWN:
                    tr_r = (tr_r + 1) % (len(TROWS) + 1)
                    tr_c = col_al_entrar(tr_r, tr_c)
                elif ev.key == pygame.K_LEFT:
                    tr_c = (tr_c - 1) % tcols(tr_r)
                elif ev.key == pygame.K_RIGHT:
                    tr_c = (tr_c + 1) % tcols(tr_r)
                elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    r = t_press()
                    if r == 'ok':
                        write_out(TXT); safe_quit(0)
                    if r == 'cancel':
                        safe_quit(1)
                elif ev.key == pygame.K_SPACE:      # X del mando: borrar
                    TXT = TXT[:-1]
                elif ev.key == pygame.K_BACKSPACE:
                    TXT = TXT[:-1]
                elif ev.key == pygame.K_TAB:        # Y: aceptar rapido
                    write_out(TXT); safe_quit(0)
                elif ev.key == pygame.K_ESCAPE:
                    safe_quit(1)
                else:
                    ch = getattr(ev, 'unicode', '')
                    if ch and ch.isprintable():
                        TXT += ch

            screen.blit(BGSURF, (0, 0))
            if PANEL_UI:
                draw_header()
            else:
                for _i, _tl in enumerate(TITLE_LINES):
                    screen.blit(rtext(T_FONT, _tl, FG), (24, 22 + _i * T_LH))
                pygame.draw.line(screen, TH['border'], (24, HEAD - 8), (W - 24, HEAD - 8), 1)
            # caja de texto
            bx, by, bw, bh = 30, HEAD + 20, W - 60, 54
            pygame.draw.rect(screen, TH['card'], (bx, by, bw, bh), border_radius=RAD)
            pygame.draw.rect(screen, ACC, (bx, by, bw, bh), 2, border_radius=RAD)
            cursor = '_' if int(time.time() * 2) % 2 == 0 else ' '
            shown = TXT
            while f_it.render(shown + cursor, True, FG).get_width() > bw - 24 and shown:
                shown = shown[1:]
            screen.blit(f_it.render(shown + cursor, True, FG), (bx + 12, by + 14))
            # teclado
            ky0 = by + bh + 26
            cw = (W - 80) // 12
            for r, row in enumerate(TROWS):
                for c, ch in enumerate(row):
                    x = 40 + c * cw
                    y = ky0 + r * 44
                    if r == tr_r and c == tr_c:
                        draw_selection((x - 8, y - 6, cw - 6, 38))
                    lab = ch.upper() if shift else ch
                    if ch == ' ':
                        lab = L('ESP', 'SPC')
                    screen.blit(f_it.render(lab, True, FG), (x, y))
            aw = (W - 80) // len(TACT)
            for c, act in enumerate(TACT):
                x = 40 + c * aw
                y = ky0 + len(TROWS) * 44
                if tr_r == len(TROWS) and c == tr_c:
                    draw_selection((x - 8, y - 6, aw - 14, 38))
                col = ACC if act in ('ACEPTAR', 'ACCEPT') else (
                      WARN if act in ('MAYUS', 'SHIFT') and shift else FG)
                screen.blit(f_it.render(act, True, col), (x, y))
            hint2 = L('Dpad: moverse   A: pulsar   X: borrar   Y: aceptar   B: cancelar',
                      'Dpad: move   A: press   X: delete   Y: accept   B: cancel')
            if PANEL_UI:
                draw_footer([('A', L('pulsar', 'press')), ('X', L('borrar', 'delete')),
                             ('Y', L('aceptar', 'accept')), ('B', L('cancelar', 'cancel'))])
            else:
                screen.blit(f_sm.render(hint2, True, DIM), (24, H - 40))
            if SCANSURF is not None:
                screen.blit(SCANSURF, (0, 0))
            pygame.display.flip()
            grabar_fotograma()
            _last_frame[0] = time.time()
            clockT.tick(30)

    running, done = True, False
    GRACE = 0.35
    t_open = time.time()
    def ready():
        return time.time() - t_open >= GRACE

    _last_key = [None, 0.0]
    DEBOUNCE = 0.08
    # Se limpia al empezar la sesion: en modo servidor el proceso no muere
    # entre menu y menu, y una peticion suelta -pulsar Select justo mientras
    # se dibuja el siguiente- cerraria el menu recien abierto.
    home_req[0] = False
    while running:
        # ¿Se pidio volver al menu principal? Se mira aqui, antes de los
        # eventos: no depende de ninguna tecla y funciona en cualquier modo.
        if home_req[0]:
            home_req[0] = False
            write_out('WPACT:HOME|')
            running = False
            done = True
            break
        for ev in eventos():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                if DEV and ev.key == pygame.K_F12:
                    captura()
                    continue
                t_now = time.time()
                if ev.key == _last_key[0] and (t_now - _last_key[1]) < DEBOUNCE:
                    continue
                _last_key[0], _last_key[1] = ev.key, t_now
                if ev.key == pygame.K_F11:
                    toggle_fullscreen()
                    continue
                if kb_open:
                    # --- navegacion del teclado virtual ---
                    if ev.key == pygame.K_UP:
                        kb_r = (kb_r - 1) % (len(KB_ROWS) + 1)
                        kb_c = min(kb_c, kb_cols(kb_r) - 1)
                    elif ev.key == pygame.K_DOWN:
                        kb_r = (kb_r + 1) % (len(KB_ROWS) + 1)
                        kb_c = min(kb_c, kb_cols(kb_r) - 1)
                    elif ev.key == pygame.K_LEFT:
                        kb_c = (kb_c - 1) % kb_cols(kb_r)
                    elif ev.key == pygame.K_RIGHT:
                        kb_c = (kb_c + 1) % kb_cols(kb_r)
                    elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        if ready(): kb_press()
                    elif ev.key == pygame.K_SPACE:
                        if ready(): filter_back()          # X = borrar
                    elif ev.key in (pygame.K_ESCAPE, pygame.K_TAB):
                        if ready(): kb_open = False        # B / Y = cerrar
                    elif ev.key == pygame.K_BACKSPACE:
                        filter_back()
                    else:
                        ch = getattr(ev, 'unicode', '')
                        if ch and ch.isprintable():
                            filter_add(ch, 'tecla %s' % pygame.key.name(ev.key))
                else:
                    if ev.key == pygame.K_ESCAPE:
                        if ready(): on_escape()
                    elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        if ready(): on_enter()
                    elif ev.key == pygame.K_UP:
                        if MODE == 'grid': grid_move(0, -1)
                        else: move(-1)
                    elif ev.key == pygame.K_DOWN:
                        if MODE == 'grid': grid_move(0, 1)
                        else: move(1)
                    elif ev.key == pygame.K_LEFT:
                        # En la rejilla, moverse de columna. En la LISTA,
                        # izquierda y derecha no hacian nada: se usan para
                        # saltar una pantalla entera, que con bibliotecas de
                        # cientos de juegos ahorra muchisimo desplazamiento.
                        if MODE == 'grid': grid_move(-1, 0)
                        else: pagina(-1)
                    elif ev.key == pygame.K_RIGHT:
                        if MODE == 'grid': grid_move(1, 0)
                        else: pagina(1)
                    elif ev.key == pygame.K_TAB:
                        # Y del mando (o Tab): abrir teclado de busqueda
                        if ready() and MODE != 'check':
                            kb_open = True
                            kb_r, kb_c = 0, 0
                            scroll = max(0, min(scroll, max(0, len(view) - VIS_KB)))
                    elif ev.key == pygame.K_BACKSPACE:
                        filter_back()
                    elif ev.key == pygame.K_F1:
                        # L1: ficha del juego, sin pasar por configuracion
                        if ready() and ACTION_X and MODE in ('list', 'grid'):
                            action_sobre_juego('INFO')
                    elif ev.key == pygame.K_F3:
                        # L2: cambiar entre lista y rejilla. Se cierra el menu
                        # y WProton lo reabre en la otra vista; con el servidor
                        # de menus, el cambio se ve al momento.
                        if ready() and ACTION_X and MODE in ('list', 'grid'):
                            action_sobre_juego('VISTA')
                    elif ev.key == pygame.K_F2:
                        # R1: marcar o quitar favorito AQUI MISMO. Antes se
                        # cerraba el menu, lo aplicaba WProton y se volvia a
                        # abrir: funcionaba, pero se notaba el parpadeo. Ahora
                        # el cambio se ve al instante y se apunta en un fichero
                        # que WProton aplica al salir del menu.
                        if ready() and ACTION_X and MODE in ('list', 'grid'):
                            marcar_favorito()
                    elif ev.key == pygame.K_SPACE:
                        if ready():
                            if MODE == 'check':
                                toggle()
                            elif ACTION_X and MODE in ('list', 'grid'):
                                action_x()
                            else:
                                on_enter()
                    else:
                        # TYPE-AHEAD con teclado real: filtra al escribir
                        if MODE != 'check':
                            ch = getattr(ev, 'unicode', '')
                            if ch and ch.isprintable():
                                filter_add(ch, 'type-ahead %s'
                                           % pygame.key.name(ev.key))

        screen.blit(BGSURF, (0, 0))
        if PANEL_UI:
            draw_header()
            draw_panel((LIST_X - 6, LIST_Y, LIST_W + 12, LIST_H))
            draw_side_panel()
        else:
            for _i, _tl in enumerate(TITLE_LINES):
                screen.blit(rtext(T_FONT, _tl, FG), (24, 22 + _i * T_LH))
            if MODE == 'browse':
                screen.blit(f_sm.render(shorten(cur_path), True, DIM), (24, HEAD - 8))
                _ry = HEAD + 20
            else:
                _ry = HEAD - 8
            pygame.draw.line(screen, TH['border'], (24, _ry), (W - 24, _ry), 1)

        if MODE == 'grid':
            draw_grid()
        for i in ([] if MODE == 'grid' else range(scroll, min(scroll + vis(), len(view)))):
            y = LIST_Y + 8 + (i - scroll) * ROW
            _rect = (LIST_X, y - 4, LIST_W, ROW - 6)
            if TH.get('btn'):
                draw_button(_rect, i == sel and not kb_open)
                if i == sel and not kb_open and TH.get('marker'):
                    try:
                        pygame.draw.polygon(screen, ACC,
                            [(LIST_X + 20, y + ROW // 2 - 4), (LIST_X + 10, y + 2),
                             (LIST_X + 10, y + ROW - 14)])
                    except Exception:
                        pass
            else:
                if PANEL_UI and i != sel:
                    pygame.draw.rect(screen, TH['card'], _rect, border_radius=RAD)
                if i == sel and not kb_open:
                    draw_selection(_rect)
            kind, txt, on = items[view[i]]
            favorito_aqui = False
            if MODE == 'check':
                label = ('[x] ' if on else '[  ] ') + txt
                color = ACC if on else FG
            elif kind == K_DIR:
                label, color = txt, DIRC
            elif kind in HEADER_KINDS:
                label, color = txt, (ACC if kind == K_HDR else DIM)
            else:
                label, color = txt, FG
                # Marca de favorito en la propia lista: al pulsar R1 se ve al
                # momento cual esta marcado, sin tener que mirar el panel.
                if MODE == 'list' and LIST_INFO.get(txt, {}).get('fav') == '1':
                    favorito_aqui = True
            _tx = LIST_X + (18 if PANEL_UI else 14)
            if TH.get('numbered'):
                _tx += 46
                screen.blit(f_sm.render('%02d' % (i + 1), True, ACC if i == sel else TH['border']),
                            (LIST_X + 28, y + 12))
            _ty = y + (6 if PANEL_UI else 0)
            _tw = LIST_X + LIST_W - _tx - 18     # ancho util hasta el borde
            if TH.get('shadow'):
                draw_row_text(label, f_it, (0, 0, 0), _tx + 2, _ty + 2, _tw, i == sel)
            if favorito_aqui:
                # Estrella a la DERECHA de la fila: delante quedaba pegada al
                # nombre y descuadrada. Se reserva su hueco para que el texto
                # largo no la pise.
                _tw -= FS(26)
                draw_estrella(LIST_X + LIST_W - FS(24), y + ROW // 2,
                              FS(8), TH.get('acc2', ACC))
            if kind in HEADER_KINDS or MODE == 'check':
                draw_row_text(label, f_it, color, _tx, _ty, _tw, i == sel)
            else:
                draw_segments(row_segments(label, color), f_it, _tx, _ty, _tw, i == sel)
        if not view and FILTER:
            screen.blit(f_it.render("(sin coincidencias para '%s')" % FILTER, True, WARN),
                        (LIST_X + 14, LIST_Y + 14))

        # Barra lateral: avisa de que hay más opciones de las que caben en pantalla
        _total = len(view)
        _vis = (grid_rows_vis() * GCOLS) if MODE == 'grid' else vis()
        if _total > _vis:
            _tr_x = (LIST_X + LIST_W + 2) if PANEL_UI else (W - 14)
            _tr_y = LIST_Y + 8
            _tr_h = LIST_H - 16
            pygame.draw.rect(screen, TH['card'], (_tr_x, _tr_y, 6, _tr_h), border_radius=3)
            _kh = max(28, int(_tr_h * _vis / float(_total)))
            _maxoff = max(1, _total - _vis)
            _ky = _tr_y + int((_tr_h - _kh) * min(1.0, scroll / float(_maxoff)))
            pygame.draw.rect(screen, ACC if TH['glow'] else (120, 130, 150),
                             (_tr_x, _ky, 6, _kh), border_radius=3)
        if view and not PANEL_UI:
            pos = f_sm.render('%d/%d' % (sel + 1, len(view)), True, DIM)
            screen.blit(pos, (W - 24 - pos.get_width(), max(4, HEAD - 30)))
        if (FILTER or kb_open) and not PANEL_UI:
            ft = f_sm.render('Buscar: %s_' % FILTER, True, WARN)
            screen.blit(ft, (W - 24 - ft.get_width(), max(24, HEAD - 30)))

        if kb_open:
            ky0 = H - KB_H - 44
            pygame.draw.rect(screen, KBBG, (12, ky0 - 8, W - 24, KB_H + 8), border_radius=RAD)
            if TH['panel'] is not None:
                pygame.draw.rect(screen, TH['border'], (12, ky0 - 8, W - 24, KB_H + 8), 1, border_radius=RAD)
            cw = (W - 60) // 10
            for r, row in enumerate(KB_ROWS):
                for c, ch in enumerate(row):
                    x = 30 + c * cw
                    y = ky0 + r * 36
                    if r == kb_r and c == kb_c:
                        draw_selection((x - 6, y - 4, cw - 6, 32))
                    lab = 'ESP' if ch == ' ' else ch
                    screen.blit(f_kb.render(lab, True, FG), (x, y))
            aw = (W - 60) // len(KB_ACTIONS)
            for c, act in enumerate(KB_ACTIONS):
                x = 30 + c * aw
                y = ky0 + len(KB_ROWS) * 36
                if kb_r == len(KB_ROWS) and c == kb_c:
                    draw_selection((x - 6, y - 4, aw - 12, 32))
                screen.blit(f_kb.render(act, True, ACC if act == 'LISTO' else FG), (x, y))

        if kb_open:
            hint = 'Dpad: moverse   A: pulsar   X: borrar   B/Y: cerrar teclado'
        elif MODE == 'check':
            hint = 'X/Espacio: marcar   A/Enter: aceptar   B/Esc: cancelar'
        elif MODE == 'browse':
            hint = 'A: entrar/elegir   B: subir   Y: buscar   (o escribe para filtrar)'
        elif MODE == 'grid':
            hint = ('A: jugar  X: configurar  L1: ficha  R1: favorito  B: volver' if ACTION_X
                    else 'Dpad: moverse   A: jugar   B: volver   Y: buscar   Select+A/F11: pantalla')
        else:
            hint = 'A: elegir   B: volver   Y: buscar   Select+A/F11: pantalla completa'
        if PANEL_UI:
            if kb_open:
                _chips = [('Dpad', L('moverse', 'move')), ('A', L('pulsar', 'press')),
                          ('X', L('borrar', 'delete')), ('B/Y', L('cerrar', 'close'))]
            elif MODE == 'check':
                _chips = [('X', L('marcar', 'toggle')), ('A', L('aceptar', 'accept')),
                          ('B', L('cancelar', 'cancel'))]
            elif MODE == 'browse':
                _chips = [('A', L('entrar', 'enter')), ('B', L('subir', 'up')),
                          ('Y', L('buscar', 'search')), ('Sel+A', L('pantalla', 'screen'))]
            elif MODE == 'grid':
                _chips = [('A', L('jugar', 'play')), ('X', L('config', 'config')),
                          ('Y', L('buscar', 'search')), ('L1', L('ficha', 'info')),
                          ('R1', L('favorito', 'favourite')),
                          ('Sel+X', L('vista', 'view')),
                          ('B', L('volver', 'back'))] if ACTION_X else \
                         [('Dpad', L('moverse', 'move')), ('A', L('jugar', 'play')),
                          ('B', L('volver', 'back')), ('Y', L('buscar', 'search'))]
            else:
                _chips = [('A', L('jugar', 'play')), ('X', L('config', 'config')),
                          ('Y', L('buscar', 'search')), ('L1', L('ficha', 'info')),
                          ('R1', L('favorito', 'favourite')),
                          ('Sel+X', L('vista', 'view')),
                          ('B', L('volver', 'back'))] if ACTION_X else \
                         [('A', L('elegir', 'choose')), ('B', L('volver', 'back')),
                          ('Y', L('buscar', 'search')), ('Sel+A', L('pantalla', 'screen'))]
            draw_footer(_chips)
        else:
            screen.blit(f_sm.render(hint, True, DIM), (24, H - 40))
        if SCANSURF is not None:
            screen.blit(SCANSURF, (0, 0))
        try:
            pygame.display.flip()
            grabar_fotograma()
            _last_frame[0] = time.time()
        except Exception as _e:
            # El servidor X de gamescope puede desaparecer al cerrarse un juego
            # ("XIO: fatal IO error"). Salimos con codigo 2 para que WProton
            # reabra el menu, en vez de morir con un traceback.
            sys.stderr.write('menu_pygame: se perdio la pantalla (%s)\n' % _e)
            safe_quit(2)
        clock.tick(60)

    _mark_clean_exit()
    return 0 if done else 1


# ---------------------------------------------------------------------------
# PUNTO DE ENTRADA
#
#   menu_pygame.py <modo> <titulo> <salida> [arg4] [tipo]   -> una peticion
#   menu_pygame.py server <carpeta>                         -> servidor
#
# En modo SERVIDOR el proceso (y su ventana) NO se cierran entre menus: se
# queda en reposo esperando la siguiente peticion. Eso quita el parpadeo al
# cambiar de menu y, en el modo Juego de SteamOS, evita que el compositor se
# quede sin ninguna ventana nuestra al salir de un juego.
#
# Protocolo, deliberadamente simple (ficheros, sin dependencias):
#   <carpeta>/req      peticion: una linea por campo
#   <carpeta>/req.ready  marca de "peticion lista"
#   <carpeta>/resp     codigo de salida de la sesion
#   <carpeta>/stop     si aparece, el servidor termina
# ---------------------------------------------------------------------------

_IDLE_PASOS = 10          # tamaños pre-renderizados de cada letra
_idle_letras = None
_idle_key = None
_idle_alto = 0
_idle_ancho = 0


def draw_idle(status=''):
    # Pantalla de reposo entre peticiones: la ventana sigue viva.
    # Se vacia la cola de eventos para que las pulsaciones hechas mientras
    # no habia menu no se apliquen de golpe al abrir el siguiente.
    try:
        pygame.event.clear()
    except Exception:
        pass
    if BGSURF is not None:
        screen.blit(BGSURF, (0, 0))
    else:
        screen.fill(TH['bg'])
    # LA MARCA SE PREPARA UNA VEZ, NO QUINCE VECES POR SEGUNDO.
    #
    # Esto creaba una fuente nueva y volvia a componer "WPROTON" en CADA
    # fotograma del reposo. Crear una fuente no es barato, y el reposo corre a
    # 15 fps: eran 15 fuentes por segundo para dibujar siempre lo mismo.
    #
    # Guardada, la animacion de abajo sale practicamente gratis: solo cambia la
    # transparencia de una imagen que ya esta hecha.
    global _idle_letras, _idle_key, _idle_alto, _idle_ancho
    clave = (W, H, TH.get('bg'), ACC)
    if _idle_letras is None or _idle_key != clave:
        # CADA LETRA POR SEPARADO, Y EN DOS TONOS.
        #
        # Se preparan una sola vez: siete letras en su color y siete
        # encendidas. Catorce imagenes pequeñas que despues solo se colocan.
        # Mover algo ya dibujado es barato; recomponer texto en cada fotograma
        # no lo seria.
        # CADA LETRA EN VARIOS TAMAÑOS, HECHOS DE UNA VEZ.
        #
        # El zoom se pidio en lugar del salto. Escalar en cada fotograma seria
        # trabajo de verdad -siete escalados quince veces por segundo-, asi que
        # se preparan los tamaños de antemano y por fotograma solo se ELIGE
        # cual toca y se coloca. Sigue sin dibujarse nada nuevo.
        #
        # Diez pasos entre el tamaño normal y un 35% mas: con menos se ve a
        # saltos, y con muchos mas solo se gasta memoria.
        _base_px = max(48, W // 14)
        _idle_letras = []
        for _i, _c in enumerate('WPROTON'):
            _col = MORADO_W if _i == 0 else CIAN_PROTON
            _pasos = []
            for _k in range(_IDLE_PASOS):
                _esc = 1.0 + 0.35 * (_k / float(_IDLE_PASOS - 1))
                _fk = pygame.font.Font(None, max(8, int(_base_px * _esc)))
                # UN SOLO TONO. Antes se guardaba tambien una version clara
                # para encender la letra que crecia, y se quito: distraia del
                # movimiento y son la mitad de imagenes.
                _pasos.append(_fk.render(_c, True, _col))
            _idle_letras.append(_pasos)
        # El ANCHO Y EL ALTO son los del tamaño normal: la palabra ocupa
        # siempre lo mismo aunque una letra este agrandada, o el texto entero
        # se moveria a cada fotograma.
        _idle_ancho = sum(_p[0].get_width() for _p in _idle_letras)
        _idle_alto = max(_p[0].get_height() for _p in _idle_letras)
        _idle_key = clave
    bh = _idle_alto
    by = H // 2 - bh

    # LA ANIMACION: una onda de zoom que recorre las letras.
    #
    # Cada letra se agranda y vuelve a su tamaño por turnos. Los tamaños estan
    # hechos de antemano, asi que por fotograma solo se elige cual toca y se
    # coloca: no se escala ni se dibuja texto nuevo.
    #
    # SIN ENCENDER LA LETRA. Se probo iluminar la que crecia y distraia del
    # movimiento, que es lo que se queria ver.
    #
    # Ciclo de 2,6 s con una pausa al final. Empezo en 1,8 y resulto algo
    # rapido: la onda pasaba antes de que la vista la siguiera.
    # EL RITMO: separacion entre letras y cuanto dura el paso por cada una.
    #
    # Antes iba apelotonado -hasta CUATRO letras moviendose a la vez- y ademas
    # el recorrido terminaba en el 112% del ciclo: la onda se solapaba con su
    # propio reinicio y la ultima letra se quedaba a medias.
    #
    # Con 1/10 de separacion y una ventana de 0,22 se mueven DOS letras como
    # mucho, la onda acaba en el 82% y queda un 18% de pausa antes de volver a
    # empezar. Asi se distingue el paso de una letra a la siguiente.
    _ahora = time.time()
    _x = (W - _idle_ancho) // 2
    for _i, _pasos in enumerate(_idle_letras):
        _u = ((_ahora % 2.6) / 2.6 - _i / (len(_idle_letras) + 3.0)) / 0.22
        _lift = math.sin(_u * math.pi) if 0 < _u < 1 else 0.0
        _k = int(round(_lift * (_IDLE_PASOS - 1)))
        _sn = _pasos[max(0, min(_IDLE_PASOS - 1, _k))]
        _w0 = _pasos[0].get_width()
        _h0 = _pasos[0].get_height()
        # Crece desde su CENTRO: si creciera desde la esquina, la letra se
        # iria hacia abajo y a la derecha en vez de agrandarse en su sitio.
        screen.blit(_sn, (_x - (_sn.get_width() - _w0) // 2,
                          by - (_sn.get_height() - _h0) // 2))
        _x += _w0

    if status:
        sf = rtext(f_it, status, FG)
        screen.blit(sf, ((W - sf.get_width()) // 2, by + bh + FS(24)))
        # Y tres puntos que van apareciendo, para que se vea que sigue vivo.
        # El texto se cachea por contenido, asi que son tres cadenas distintas
        # y no un render nuevo cada vez.
        try:
            n_pts = int(time.time() * 2) % 4
            if n_pts:
                pf = rtext(f_it, '.' * n_pts, FG)
                screen.blit(pf, ((W + sf.get_width()) // 2 + FS(6),
                                 by + bh + FS(24)))
        except Exception:
            pass
    if SCANSURF is not None:
        screen.blit(SCANSURF, (0, 0))
    try:
        pygame.display.flip()
        grabar_fotograma()
        _last_frame[0] = time.time()
    except Exception:
        pass

def serve(dirpath):
    global SERVER_MODE
    SERVER_MODE = True
    # El fondo (BGSURF) se construye al calcular la disposicion. En modo
    # servidor la primera pantalla es el reposo, ANTES de cualquier peticion,
    # asi que hay que prepararlo aqui o no habria nada que dibujar.
    set_request('list', '', '')
    compute_layout()
    req = os.path.join(dirpath, 'req')
    ready = os.path.join(dirpath, 'req.ready')
    resp = os.path.join(dirpath, 'resp')
    stop = os.path.join(dirpath, 'stop')
    idle = pygame.time.Clock()
    sys.stderr.write('menu_pygame: servidor de menus en %s\n' % dirpath)
    status = ''
    while True:
        if os.path.isfile(stop):
            try:
                os.remove(stop)
            except Exception:
                pass
            break
        if os.path.isfile(ready):
            try:
                with open(req, encoding='utf-8') as fh:
                    campos = fh.read().split('\n')
            except Exception:
                campos = []
            try:
                os.remove(ready)
            except Exception:
                pass
            while len(campos) < 10:
                campos.append('')
            # Los campos vienen con los saltos de linea escapados como \n:
            # el protocolo es una linea por campo y los titulos tienen varias.
            def _desescapa(v):
                out = []
                i = 0
                while i < len(v):
                    if v[i] == '\\' and i + 1 < len(v):
                        if v[i + 1] == 'n':
                            out.append('\n'); i += 2; continue
                        if v[i + 1] == '\\':
                            out.append('\\'); i += 2; continue
                    out.append(v[i]); i += 1
                return ''.join(out)
            campos = [_desescapa(c) for c in campos[:10]]
            (modo, titulo, salida, arg4, kind, ax,
             manif, presel, favf, aspec) = campos
            if modo == 'idle':
                # sin menu: solo actualizar el texto del reposo
                status = titulo
            elif modo:
                # OJO con "arg4 or None": una cadena VACIA es falsa, asi que
                # se convertia en None y ARG4 acababa siendo la ruta del
                # fichero temporal. En el editor de texto eso salia escrito en
                # el campo: habia que borrar "/tmp/tmp.XXXX" a mano antes de
                # poder escribir. Se distingue "vacio" de "no hay".
                set_request(modo, titulo, salida,
                            arg4 if arg4 != '' else None,
                            kind or 'file', ax == '1', manif or None,
                            presel or None, favf or None, aspec or None)
                # CUANTO TARDA EN APARECER EL MENU.
                #
                # Es el numero que faltaba. Los tiempos que medi­a WProton
                # incluyen la espera del usuario, asi que no dicen nada sobre
                # si una transicion es lenta. Este mide desde que llega la
                # peticion hasta que el menu esta listo para dibujarse, que es
                # lo unico que podemos mejorar.
                #
                # Se escribe en la salida de errores, que va al registro de
                # WProton, y solo con DIAG_TIEMPOS=1: en el uso normal seria
                # una linea por menu y solo ensucia.
                _t_prep = time.time()
                load_request_data()
                compute_layout()
                if os.environ.get('DIAG_TIEMPOS') == '1':
                    sys.stderr.write(
                        'menu_pygame: preparado en %d ms | %s\n'
                        % ((time.time() - _t_prep) * 1000, caches_resumen()))
                    sys.stderr.flush()
                try:
                    rc = run_session()
                except SessionEnd as e:
                    rc = e.code
                except SystemExit as e:
                    rc = e.code if isinstance(e.code, int) else 0
                except Exception as e:
                    sys.stderr.write('menu_pygame: fallo en la peticion (%s)\n' % e)
                    rc = 2
                try:
                    with open(resp, 'w', encoding='utf-8') as fh:
                        fh.write(str(rc))
                except Exception:
                    pass
                # El texto de "cargando" ya cumplio su funcion: si no se
                # borra, se queda fijo en la pantalla de reposo mostrando el
                # ultimo mensaje aunque la tarea acabara hace rato.
                status = ''
                # limpiar el estado visible entre menus
                pygame.event.clear()
            continue
        try:
            draw_idle(status)
        except Exception as e:
            # un fallo dibujando el reposo no puede tumbar el servidor:
            # se anota y se sigue, que el usuario aun tiene sus menus
            sys.stderr.write('menu_pygame: reposo: %s\n' % e)
            time.sleep(1.0)
        idle.tick(15)
    sys.stderr.write('menu_pygame: servidor detenido\n')
    try:
        pygame.quit()
    except Exception:
        pass
    sys.exit(0)

def dibujar_logo(sup, ancho, alto, con_lema=True):
    # Logotipo de WProton: la W en morado y el resto en el color de acento.
    # Se dibuja en vez de traer un PNG para que el script siga siendo UN solo
    # fichero: las imagenes de Steam se generan aqui mismo.
    fondo_a = (14, 18, 30)
    fondo_b = (26, 32, 54)
    # fondo con degradado vertical suave
    for y in range(alto):
        t = y / max(1, alto - 1)
        col = tuple(int(fondo_a[i] + (fondo_b[i] - fondo_a[i]) * t) for i in range(3))
        pygame.draw.line(sup, col, (0, y), (ancho, y))
    # tamaño de letra proporcional al ancho
    cuerpo = max(16, int(ancho * 0.17))
    f = pygame.font.Font(None, cuerpo)
    marca = marca_surface(f)
    total = marca.get_width()
    x = (ancho - total) // 2
    y = (alto - marca.get_height()) // 2
    sup.blit(marca, (x, y))
    # subrayado en dos tramos, uno por color, bajo cada parte de la palabra
    lw = max(2, alto // 90)
    y2 = y + marca.get_height() + max(4, alto // 40)
    corte = x + f.size('W')[0]
    pygame.draw.line(sup, MORADO_W, (x, y2), (corte, y2), lw)
    pygame.draw.line(sup, CIAN_PROTON, (corte, y2), (x + total, y2), lw)
    if con_lema and alto > 220:
        f2 = pygame.font.Font(None, max(12, int(cuerpo * 0.26)))
        lema = f2.render('Juegos de Windows en Linux', True, DIM)
        sup.blit(lema, ((ancho - lema.get_width()) // 2, y2 + max(8, alto // 30)))
    return sup

def generar_imagenes(destino):
    # Genera las imagenes que Steam usa en su biblioteca. Cada una tiene su
    # proporcion: si se pone una cuadrada, Steam la deforma.
    medidas = (('p', 600, 900),          # vertical (rejilla de la biblioteca)
               ('header', 920, 430),     # apaisada
               ('hero', 1920, 620),      # cabecera grande
               ('logo', 640, 360),       # logotipo sobre la cabecera
               ('icono', 256, 256))      # icono del acceso directo
    os.makedirs(destino, exist_ok=True)
    hechas = []
    for nombre, an, al in medidas:
        ruta_previa = os.path.join(destino, 'wproton_%s.png' % nombre)
        if os.path.exists(ruta_previa) and os.path.getsize(ruta_previa) > 0:
            continue          # ya hay una imagen buena: no se pisa
        try:
            sup = pygame.Surface((an, al))
            dibujar_logo(sup, an, al, con_lema=(nombre != 'logo'))
            ruta = os.path.join(destino, 'wproton_%s.png' % nombre)
            pygame.image.save(sup, ruta)
            hechas.append(ruta)
        except Exception as e:
            sys.stderr.write('logo: fallo generando %s (%s)\n' % (nombre, e))
    for r in hechas:
        print(r)
    return 0 if hechas else 1

def ocultar_cursor():
    # Esconde el puntero del raton mientras se juega.
    #
    # Al arrancar un juego se queda el puntero en medio de la pantalla hasta
    # que lo mueves. Con la extension XFixes de las X se puede ocultar para
    # toda la pantalla, y se restaura solo cuando este proceso termina, que es
    # justo cuando acaba la partida.
    #
    # Se usa ctypes: nada que instalar. Si algo falla, se deja como estaba.
    if os.environ.get('WP_OCULTAR_CURSOR') == '0':
        return None
    if not os.environ.get('DISPLAY'):
        return None
    try:
        import ctypes, ctypes.util
        x11 = ctypes.CDLL(ctypes.util.find_library('X11') or 'libX11.so.6')
        fixes = ctypes.CDLL(ctypes.util.find_library('Xfixes') or 'libXfixes.so.3')
        x11.XOpenDisplay.restype = ctypes.c_void_p
        dpy = x11.XOpenDisplay(None)
        if not dpy:
            sys.stderr.write('menu_pygame: no se pudo abrir la pantalla para '
                             'ocultar el cursor\n')
            return None
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        raiz = x11.XDefaultRootWindow(ctypes.c_void_p(dpy))
        fixes.XFixesHideCursor.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        fixes.XFixesHideCursor(ctypes.c_void_p(dpy), raiz)
        # Ademas se aparta el puntero a la esquina inferior derecha. XFixes
        # solo lo oculta mientras esta conexion siga abierta, y algunos juegos
        # vuelven a mostrarlo por su cuenta; apartado, al menos no molesta en
        # medio de la pantalla.
        try:
            x11.XWarpPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                         ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                                         ctypes.c_uint, ctypes.c_uint,
                                         ctypes.c_int, ctypes.c_int]
            x11.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
            x11.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
            an = x11.XDisplayWidth(ctypes.c_void_p(dpy), 0)
            al = x11.XDisplayHeight(ctypes.c_void_p(dpy), 0)
            x11.XWarpPointer(ctypes.c_void_p(dpy), 0, raiz, 0, 0, 0, 0,
                             int(an) - 1, int(al) - 1)
        except Exception:
            pass
        x11.XFlush(ctypes.c_void_p(dpy))
        sys.stderr.write('menu_pygame: cursor oculto en %s (si el juego corre en '
                         'otra pantalla, p.ej. gamescope anidado, no le afecta)\n'
                         % os.environ.get('DISPLAY'))
        # se devuelve la conexion: mientras siga abierta, el cursor sigue
        # oculto. Al morir este proceso, las X lo restauran solas.
        return (x11, dpy)
    except Exception as e:
        sys.stderr.write('menu_pygame: no se pudo ocultar el cursor (%s)\n' % e)
        return None

def reloj_salida(desde, pulsado, soltado, ahora, segundos):
    """Decide si toca cerrar el juego. Devuelve (nuevo_desde, cerrar).

    ESTA LOGICA VIVE APARTE PARA PODER PROBARLA. El fallo que arregla no se
    veia leyendo el bucle: solo aparece con una secuencia de pulsaciones y
    soltadas a un ritmo concreto, y eso hay que EJECUTARLO para verlo.

    - desde    cuando empezo la pulsacion que se esta midiendo (None si no hay)
    - pulsado  si la combinacion esta pulsada AHORA
    - soltado  si ha llegado una SOLTADA desde la ultima vez que se pregunto
    - ahora    el reloj
    - segundos cuanto hay que mantener

    LA SOLTADA MANDA SOBRE EL ESTADO. El guardian mira el estado cada 50 ms;
    si entre dos miradas cabe una soltada Y la siguiente pulsacion, el boton
    parece seguir pulsado y el reloj no se reiniciaba: varias pulsaciones
    cortas se sumaban como una larga y el juego se cerraba solo.

    CUANTO PASABA, MEDIDO. Depende MUCHO de "segundos": cuanto mas corto, mas
    facil es que ninguna mirada caiga en un hueco.

        segundos=5, pulsar 0,30 s / soltar 0,02 s ->  0,1% de las tandas
        segundos=2, pulsar 0,10 s / soltar 0,02 s ->  0,8%
        segundos=2, pulsar 0,30 s / soltar 0,02 s -> 37%

    El registro de un tester con PAD_EXIT_SEGUNDOS=2 mostraba catorce
    pulsaciones seguidas de 0,1 s. Con ese ajuste esto no era "a veces": era
    una de cada tres. Con la soltada atendida como evento, cero.
    """
    if soltado:
        desde = None
    if not pulsado:
        return (None, False)
    if desde is None:
        return (ahora, False)
    return (desde, ahora - desde >= segundos)


def guardia(marca, segundos=5.0, combo='select'):
    # Vigila los mandos DURANTE la partida esperando la combinacion de salida.
    #
    # Combinaciones (ajuste PAD_EXIT_COMBO):
    #   select  - mantener Select 5 segundos (por defecto). Un solo boton,
    #             sencillo de explicar y que nadie mantiene tanto sin querer.
    #   l3r3    - los dos sticks a la vez
    #   start   - Select + Start (OJO: en el escritorio de SteamOS, mantener
    #             Start cambia el mando de modo)
    #
    # Solo LEE los dispositivos (no necesita uinput) y no interfiere con el
    # juego: varios procesos pueden leer el mismo mando.
    import struct
    FMT = 'llHHi'
    SZ = struct.calcsize(FMT)
    SELECT, START, L3, R3 = 314, 315, 317, 318
    if combo == 'l3r3':
        REQ, nombre_combo = (L3, R3), 'L3+R3'
    elif combo == 'start':
        REQ, nombre_combo = (SELECT, START), 'Select+Start'
    else:
        REQ, nombre_combo = (SELECT,), 'Select'
    # Los botones se cuentan POR DISPOSITIVO, no en un monton comun.
    #
    # Un mismo mando puede aparecer como varios dispositivos, y ademas Steam
    # crea mandos virtuales con los botones remapeados. Si se juntaban todos,
    # bastaba con que UNO mandara el codigo de Select para que la combinacion
    # se cumpliera: pulsar L1 podia cerrar el juego. Ahora la combinacion
    # tiene que venir entera del MISMO dispositivo.
    fds = {}
    pulsados = {}          # dispositivo -> botones pulsados en el
    desde = None
    avisado = set()
    ultimo_escaneo = 0.0
    sys.stderr.write('menu_pygame: guardia activo (%s durante %.0fs para cerrar)\n'
                     % (nombre_combo, segundos))
    # El cursor se oculta aqui y se restaura solo al terminar este proceso,
    # que es cuando acaba la partida.
    # El cursor es lo MENOS importante del guardia: si algo va mal ahi, no
    # puede llevarse por delante el cierre del juego.
    try:
        _cursor = ocultar_cursor()
    except Exception as e:
        sys.stderr.write('menu_pygame: fallo ocultando el cursor (%s)\n' % e)
        _cursor = None
    _t0 = time.time()
    _vistos = [0]
    _btn_log = [0]      # botones ya apuntados (NO lecturas)
    _desde = {}         # boton de la combinacion -> cuando se pulso
    _soltado_req = [False]   # ha llegado una soltada de la combinacion
    while True:
        ahora = time.time()
        if ahora - ultimo_escaneo > 3:
            ultimo_escaneo = ahora
            for p in find_raw_pads():
                if p not in fds:
                    try:
                        fds[p] = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
                        sys.stderr.write('menu_pygame: guardia vigilando %s\n' % p)
                    except OSError as e:
                        if p not in avisado:
                            avisado.add(p)
                            sys.stderr.write('menu_pygame: guardia no puede leer %s (%s)\n'
                                             % (p, e))
        if not fds:
            if 'sin_mandos' not in avisado:
                avisado.add('sin_mandos')
                sys.stderr.write('menu_pygame: guardia SIN MANDOS que leer: '
                                 'el cierre con el mando no funcionara\n')
            time.sleep(1.0)
            continue
        for p, fd in list(fds.items()):
            # SE VACIA LA COLA ENTERA, NO 32 EVENTOS.
            #
            # Antes se leian como mucho 32 eventos por vuelta (SZ*32) y se
            # dormia 50 ms: 640 eventos por segundo como mucho. Los dos
            # sticks de un mando pueden pasar de eso mientras se juega, y
            # entonces la cola crece.
            #
            # HONESTIDAD SOBRE ESTE CAMBIO: se hizo buscando por que pulsar
            # Select varias veces cerraba el juego, y NO se ha demostrado que
            # sea la causa. Simulando el retraso de la cola, la soltada se
            # recupera en una decima de segundo, muy lejos de los 5 que hacen
            # falta para cerrar. Se deja porque leer de par en par es
            # correcto igualmente y evita que el nucleo tenga que tirar
            # eventos, pero la causa del fallo sigue sin estar probada.
            datos = b''
            try:
                while True:
                    _trozo = os.read(fd, SZ * 256)
                    if not _trozo:
                        break
                    datos += _trozo
                    if len(_trozo) < SZ * 256:
                        break
            except (BlockingIOError, OSError):
                pass
            if not datos:
                continue
            _vistos[0] += 1
            aqui = pulsados.setdefault(p, set())
            for i in range(0, len(datos) - SZ + 1, SZ):
                _s, _us, t, c, v = struct.unpack(FMT, datos[i:i+SZ])
                # SI EL NUCLEO HA TIRADO EVENTOS, lo que creemos saber de este
                # mando ya no vale: puede faltar justo una soltada. Se olvida
                # lo pulsado y se empieza de cero, que es mucho mejor que
                # cerrar el juego por un boton que nadie esta tocando.
                if t == 0 and c == 3:      # EV_SYN / SYN_DROPPED
                    aqui.clear()
                    _desde.clear()
                    sys.stderr.write('menu_pygame: guardia: el nucleo tiro '
                                     'eventos de %s; se olvida lo pulsado\n' % p)
                    continue
                if t != 1:            # EV_KEY
                    continue
                if v == 1:
                    aqui.add(c)
                    # Los primeros BOTONES se apuntan con su codigo, para ver
                    # si llegan y si son los que espera la combinacion.
                    #
                    # OJO: antes esto miraba _vistos, que cuenta LECTURAS, no
                    # botones. Los ejes de los sticks generan lecturas sin
                    # parar, asi que se comian el cupo de 12 antes de que
                    # nadie pulsara nada y no se registraba ni un boton. En
                    # los registros de un tester no habia ni una linea.
                    if _btn_log[0] < 12:
                        _btn_log[0] += 1
                        sys.stderr.write('menu_pygame: guardia: boton %d en %s '
                                         '(la combinacion espera %s)\n'
                                         % (c, p, list(REQ)))
                    if c in REQ:
                        # SI YA ESTABA PULSADO, NO SE REINICIA EL RELOJ, pero
                        # se apunta: dos pulsaciones seguidas sin soltada por
                        # medio son la firma de una soltada perdida, que es lo
                        # que hay que poder ver en el registro.
                        if c in _desde:
                            sys.stderr.write('menu_pygame: guardia: %d PULSADO '
                                             'otra vez SIN soltada previa '
                                             '(llevaba %.1fs)\n'
                                             % (c, time.time() - _desde[c]))
                        else:
                            _desde[c] = time.time()
                            sys.stderr.write('menu_pygame: guardia: %d PULSADO '
                                             '(hay que mantenerlo %.0fs)\n'
                                             % (c, segundos))
                elif v == 0:
                    aqui.discard(c)
                    # Cuanto se mantuvo. Si sale "soltado a los 4.6s" cuando
                    # hacen falta 5, el problema es el tiempo y no el codigo.
                    if c in REQ:
                        # AQUI ESTABA EL FALLO.
                        #
                        # El reloj de "mantenido" se reiniciaba mirando el
                        # ESTADO cada 50 ms. Si entre dos miradas cabia una
                        # soltada Y la siguiente pulsacion, al mirar el boton
                        # estaba pulsado y el reloj NO se reiniciaba: varias
                        # pulsaciones cortas se sumaban como una larga y el
                        # juego se cerraba solo.
                        #
                        # Medido con el ritmo que sale al aporrear el boton
                        # -pulsar 0,30 s y soltar 0,02 s-: pasaba el 0,8% de
                        # las tandas. De ahi el "a veces" del tester.
                        #
                        # La soltada es un EVENTO y se atiende como tal: en
                        # cuanto llega, el reloj a cero. No importa lo que
                        # parezca el estado despues.
                        _soltado_req[0] = True
                        if c in _desde:
                            sys.stderr.write('menu_pygame: guardia: %d soltado a '
                                             'los %.1fs\n' % (c, time.time() - _desde[c]))
                            del _desde[c]
        # Si a los 60 segundos no ha llegado NI UN evento, es que no se puede
        # leer el mando (permisos), no que el usuario no pulse nada.
        if _vistos[0] == 0 and 'mudo' not in avisado and time.time() - _t0 > 60:
            avisado.add('mudo')
            sys.stderr.write('menu_pygame: guardia: 60s sin recibir NADA de %d '
                             'dispositivo(s). Revisa los permisos de '
                             '/dev/input (Runners y herramientas -> Arreglar '
                             'permisos del mando)\n' % len(fds))
        # combinacion de cierre: entera en UN dispositivo
        cual = None
        for p, aqui in pulsados.items():
            if all(b in aqui for b in REQ):
                cual = p
                break
        desde, _cerrar = reloj_salida(desde, cual is not None,
                                      _soltado_req[0], time.time(), segundos)
        _soltado_req[0] = False
        # Aqui hubo un parche de "boton encallado" -descartar una pulsacion
        # que durase mas de cuatro veces el tiempo de salida-. Se ha quitado
        # al encontrar la causa de verdad: tapaba el sintoma y ademas habria
        # impedido cerrar el juego a quien mantuviera Select un rato largo,
        # que es justo lo que hay que hacer.
        if _cerrar:
            try:
                with open(marca, 'w') as fh:
                    fh.write('salir\n')
            except Exception:
                pass
            sys.stderr.write('menu_pygame: %s mantenido en %s -> cerrar el juego\n'
                             % (nombre_combo, cual))
            return 0
        if cual is None:
            # Diagnostico: si se mantiene algo mucho rato y NO es la
            # combinacion, se apunta su codigo. Asi, si en algun mando los
            # botones no son los estandar, el registro lo dice.
            for p, aqui in pulsados.items():
                if aqui and 'mantiene_%s' % p not in avisado:
                    avisado.add('mantiene_%s' % p)
                    sys.stderr.write('menu_pygame: guardia: %s mantiene %s '
                                     '(la combinacion espera %s)\n'
                                     % (p, sorted(aqui), list(REQ)))
        time.sleep(0.05)

if sys.argv[1] == 'guardia':
    sys.exit(guardia(sys.argv[2],
                     float(sys.argv[3]) if len(sys.argv) > 3 else 5.0,
                     sys.argv[4] if len(sys.argv) > 4 else 'select'))

if sys.argv[1] == 'logo':
    sys.exit(generar_imagenes(sys.argv[2]))

if sys.argv[1] == 'server':
    serve(sys.argv[2])
else:
    set_request(sys.argv[1], sys.argv[2], sys.argv[3],
                sys.argv[4] if len(sys.argv) > 4 else None,
                sys.argv[5] if len(sys.argv) > 5 else 'file',
                os.environ.get('WP_ACTION_X') == '1',
                os.environ.get('WP_LIST_INFO') or None,
                os.environ.get('WP_PRESEL') or None,
                os.environ.get('WP_FAV_FILE') or None,
                os.environ.get('WP_GRID_BANNER') or None)
    load_request_data()
    compute_layout()
    rc = run_session()
    pygame.quit()
    sys.exit(rc)
