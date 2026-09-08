# -*- coding: utf-8 -*-
# WProton - utilidades de disco (tamaños, espacio, huerfanos, listados)
#
# Copyright (C) 2026  stshunz y colaboradores
#
# Este programa es software libre: puedes redistribuirlo y/o modificarlo bajo
# los terminos de la Licencia Publica General GNU (GPL), version 3 o
# posterior, publicada por la Free Software Foundation.
#
# Se distribuye SIN NINGUNA GARANTIA. Ver <https://www.gnu.org/licenses/>.
# ----------------------------------------------------------------------------
# QUE SUSTITUYE
#
#   human_size()       -> tam_humano()
#   fmt_playtime()     -> fmt_tiempo()
#   dir_bytes()        -> bytes_de()
#   free_bytes()       -> bytes_libres()
#   orphan_scan()      -> huerfanos()
#   disk_games_list()  -> lista_juegos()
#   (la cabecera de verify_squashfs) -> magia()
#
# EL FALLO GORDO QUE SE ARREGLA
# -----------------------------
# orphan_scan daba por huerfano el overlay y el prefijo de cualquier juego EN
# CARPETA cuyo nombre llevara un espacio. Y esa lista va derecha a un "rm -rf"
# con el mensaje "elementos de juegos que ya no tienes": o sea que se borraban
# las partidas guardadas y el prefijo de un juego que el usuario tenia
# perfectamente instalado.
#
# El motivo: el identificador cambia los espacios por guiones bajos, asi que
# la carpeta "My Game" tiene el gid "My_Game". La comprobacion era
#
#     [ -e "$GAMES_PATH/$gid" ] && continue
#
# que busca literalmente "My_Game" dentro de games/. Ahi no hay nada -la
# carpeta se llama "My Game"- asi que daba el juego por desaparecido. Solo se
# salvaban los juegos cuyo nombre no tuviera ningun espacio.
#
# Aqui se calcula el gid de CADA entrada real de games/ (archivos y carpetas)
# con la misma regla que game_id, y se compara gid contra gid. Un juego que
# esta, esta, se llame como se llame.
#
# Y DE PASO, EL RECORRIDO
# -----------------------
# orphan_scan lanzaba un "find" completo sobre GAMES_PATH POR CADA candidato.
# Con 141 juegos y unos cuantos prefijos eso son decenas de recorridos del
# arbol entero para responder algo que se sabe con uno solo. Aqui se recorre
# una vez, se guardan los gid en un conjunto y lo demas son consultas.
#
# SIN HERRAMIENTAS EXTERNAS
# -------------------------
# Esto no llama a "du -sb" ni a "df -PB1". Las banderas -b y -B1 son de las
# coreutils de GNU y no estan en las de busybox; no he podido comprobar cual
# lleva Batocera, asi que no digo que alli fallara. Lo que si es seguro es
# que a partir de ahora da igual: os.statvfs y os.stat estan siempre.
# ----------------------------------------------------------------------------

import os
import sys

VERSION = "1"

_EXT_IMAGEN = (".wsquashfs", ".squashfs", ".dwarfs")

# Carpetas de PREFIX_DIR y OVERLAY_BASE que nunca son de un juego concreto.
_NO_SON_JUEGO = ("default", "__wptools__")


# ----------------------------------------------------------------------------
# FORMATO
# ----------------------------------------------------------------------------

def tam_humano(b):
    """Bytes -> "1.2 GB" / "340 MB". Los mismos cortes que hacia el awk."""
    try:
        b = int(b)
    except (TypeError, ValueError):
        b = 0
    if b >= 1073741824:
        return "%.1f GB" % (b / 1073741824.0)
    if b >= 1048576:
        return "%.0f MB" % (b / 1048576.0)
    if b >= 1024:
        return "%.0f KB" % (b / 1024.0)
    return "%d B" % b


def fmt_tiempo(segundos):
    """Segundos -> "3 h 12 min" / "45 min" / "<1 min"."""
    try:
        t = int(segundos)
    except (TypeError, ValueError):
        t = 0
    if t < 0:
        t = 0
    h, m = t // 3600, (t % 3600) // 60
    if h > 0:
        return "%d h %d min" % (h, m)
    if m > 0:
        return "%d min" % m
    return "<1 min"


# ----------------------------------------------------------------------------
# TAMAÑOS
# ----------------------------------------------------------------------------

def bytes_de(ruta):
    """Bytes que ocupa un fichero o una carpeta entera.

    Se cuenta el tamaño aparente, como hacia "du -sb", y un inodo que aparece
    varias veces (enlaces duros) se cuenta UNA sola: los overlays de WProton
    estan llenos de enlaces duros y contarlos varias veces inflaba el informe.
    """
    try:
        st = os.lstat(ruta)
    except OSError:
        return 0
    if not os.path.isdir(ruta):
        return st.st_size
    vistos = set()
    total = st.st_size
    for actual, dirs, ficheros in os.walk(ruta, followlinks=False):
        for nombre in dirs + ficheros:
            completa = os.path.join(actual, nombre)
            try:
                s = os.lstat(completa)
            except OSError:
                continue
            if s.st_nlink > 1:
                clave = (s.st_dev, s.st_ino)
                if clave in vistos:
                    continue
                vistos.add(clave)
            total += s.st_size
    return total


def bytes_libres(ruta):
    """Bytes libres en el sistema de ficheros de esa ruta.

    Si la ruta no existe todavia -es el caso normal: se pregunta ANTES de
    crear la carpeta destino- se sube hasta el primer padre que exista.
    """
    d = ruta or "/"
    while d and not os.path.isdir(d):
        padre = os.path.dirname(d)
        if padre == d:
            break
        d = padre
    try:
        st = os.statvfs(d or "/")
    except OSError:
        return -1
    # f_bavail: bloques libres para quien no es root, que es lo que df pone
    # en la columna "Available" y lo que de verdad se puede usar.
    return st.f_bavail * st.f_frsize


# ----------------------------------------------------------------------------
# IDENTIFICADOR DE JUEGO
# ----------------------------------------------------------------------------

def gid_de(ruta):
    """El identificador de un juego. MISMA REGLA que game_id() en bash.

    Si esto y game_id() dejan de coincidir, los perfiles, los overlays y los
    prefijos dejan de encontrarse entre si. La regla es:
      - el nombre sin la carpeta
      - se le quita la ultima extension SOLO si no es un directorio
      - los espacios y las barras pasan a guion bajo
    """
    nombre = os.path.basename(ruta.rstrip("/")) if ruta else ""
    if not os.path.isdir(ruta):
        nombre = os.path.splitext(nombre)[0] if "." in nombre else nombre
    return nombre.replace(" ", "_").replace("/", "_")


def entradas_juego(games_path, hondura=3):
    """Todo lo que en games/ es un juego: imagenes y carpetas.

    Se devuelve una lista de rutas. Las carpetas cuentan como juego: son los
    "juegos en carpeta", y olvidarlas es justo lo que hacia que sus prefijos
    salieran como huerfanos.
    """
    salida = []
    if not os.path.isdir(games_path):
        return salida
    base = os.path.abspath(games_path)
    for actual, dirs, ficheros in os.walk(base):
        nivel = 0 if actual == base else os.path.relpath(actual, base).count(os.sep) + 1
        if nivel >= hondura:
            dirs[:] = []
        for f in sorted(ficheros):
            if os.path.splitext(f)[1].lower() in _EXT_IMAGEN:
                salida.append(os.path.join(actual, f))
        if nivel == 0:
            for d in sorted(dirs):
                salida.append(os.path.join(actual, d))
    return salida


def gids_vivos(games_path):
    """El conjunto de identificadores de los juegos que siguen estando.

    Se recorre games/ UNA vez. orphan_scan lo recorria entero por cada
    candidato a huerfano.
    """
    return {gid_de(r) for r in entradas_juego(games_path)}


# ----------------------------------------------------------------------------
# HUERFANOS
# ----------------------------------------------------------------------------

def huerfanos(games_path, overlay_base, prefix_dir, profile_dir):
    """Overlays y prefijos de juegos que ya no estan.

    Devuelve una lista de (tipo, ruta, bytes) con tipo "overlay" o "prefijo".
    Lo que salga de aqui se le ofrece al usuario para BORRAR, asi que ante la
    duda no se incluye: es mucho peor tirar el overlay de un juego que se
    tiene -ahi viven las partidas guardadas- que dejar sin listar una carpeta
    que sobra.
    """
    vivos = gids_vivos(games_path)
    salida = []
    for base, tipo in ((overlay_base, "overlay"), (prefix_dir, "prefijo")):
        if not base or not os.path.isdir(base):
            continue
        for nombre in sorted(os.listdir(base)):
            d = os.path.join(base, nombre)
            if not os.path.isdir(d):
                continue
            if nombre in _NO_SON_JUEGO or nombre.startswith("."):
                continue
            if nombre in vivos:
                continue
            # un perfil vivo tambien cuenta: el juego puede estar
            # temporalmente en otra unidad
            if profile_dir and os.path.isfile(
                    os.path.join(profile_dir, nombre + ".conf")):
                continue
            salida.append((tipo, d + os.sep, bytes_de(d)))
    return salida


def lista_juegos(games_path, overlay_base, prefix_dir):
    """Tamaño por juego (imagen + overlay + prefijo propio), de mayor a menor.

    Devuelve una lista de (bytes, etiqueta).
    """
    filas = []
    for ruta in entradas_juego(games_path):
        g = gid_de(ruta)
        total = bytes_de(ruta)
        total += bytes_de(os.path.join(overlay_base, g)) if overlay_base else 0
        if prefix_dir and os.path.isdir(os.path.join(prefix_dir, g)):
            total += bytes_de(os.path.join(prefix_dir, g))
        filas.append((total, os.path.basename(ruta.rstrip("/"))))
    filas.sort(key=lambda f: (-f[0], f[1].lower()))
    return filas


def sha256(ruta):
    """La huella SHA-256 de un fichero, o "" si no se puede leer.

    Se lee a trozos de 1 MiB: estas huellas se sacan de ficheros .wsquashfs
    que pueden pasar de los 50 GB, y cargarlos enteros en memoria no es una
    opcion.
    """
    import hashlib
    h = hashlib.sha256()
    try:
        with open(ruta, "rb") as fh:
            for trozo in iter(lambda: fh.read(1 << 20), b""):
                h.update(trozo)
    except OSError:
        return ""
    return h.hexdigest()


# ----------------------------------------------------------------------------
# CABECERA DE LAS IMAGENES
# ----------------------------------------------------------------------------

def magia(ruta):
    """Que tipo de imagen es, por su cabecera: squashfs, dwarfs o "".

    Antes esto se hacia con head -c 6 dentro de una sustitucion de ordenes, y
    bash avisa por consola cada vez que se traga un byte nulo -que los hay,
    porque es una cabecera binaria-. Leyendo los bytes en Python no hay tal.
    """
    try:
        with open(ruta, "rb") as fh:
            cab = fh.read(6)
    except OSError:
        return ""
    if cab[:4] in (b"hsqs", b"sqsh"):
        return "squashfs"
    if cab[:6] == b"DWARFS":
        return "dwarfs"
    return ""


# ----------------------------------------------------------------------------
# COMPROBACION INTERNA
# ----------------------------------------------------------------------------

def comprobar():
    import shutil
    import tempfile
    fallos = []

    def esperar(que, visto, esperado):
        if visto != esperado:
            fallos.append("%s: salio %r y se esperaba %r" % (que, visto, esperado))

    esperar("tam_humano GB", tam_humano(2 * 1073741824), "2.0 GB")
    esperar("tam_humano MB", tam_humano(340 * 1048576), "340 MB")
    esperar("tam_humano B", tam_humano(512), "512 B")
    esperar("tam_humano basura", tam_humano("no soy un numero"), "0 B")
    esperar("fmt_tiempo horas", fmt_tiempo(3 * 3600 + 12 * 60), "3 h 12 min")
    esperar("fmt_tiempo min", fmt_tiempo(45 * 60), "45 min")
    esperar("fmt_tiempo poco", fmt_tiempo(5), "<1 min")
    esperar("fmt_tiempo basura", fmt_tiempo(None), "<1 min")

    # gid_de tiene que coincidir con game_id() de bash
    esperar("gid imagen", gid_de("/g/Otomedius.pc.wsquashfs"), "Otomedius.pc")
    esperar("gid con espacios", gid_de("/g/My Game.wsquashfs"), "My_Game")

    raiz = tempfile.mkdtemp(prefix="wp-disco-")
    games = os.path.join(raiz, "games")
    overlay = os.path.join(raiz, "overlay")
    prefix = os.path.join(raiz, "prefix")
    perfiles = os.path.join(raiz, "profiles")
    for d in (games, overlay, prefix, perfiles):
        os.makedirs(d)

    # un juego EN CARPETA con espacio en el nombre
    os.makedirs(os.path.join(games, "My Game"))
    with open(os.path.join(games, "My Game", "juego.exe"), "wb") as fh:
        fh.write(b"x" * 100)
    os.makedirs(os.path.join(overlay, "My_Game"))
    os.makedirs(os.path.join(prefix, "My_Game"))
    # una imagen normal
    with open(os.path.join(games, "Otro.wsquashfs"), "wb") as fh:
        fh.write(b"hsqs" + b"\x00" * 200)
    os.makedirs(os.path.join(overlay, "Otro"))
    # un huerfano de verdad
    os.makedirs(os.path.join(overlay, "JuegoBorrado"))
    # carpetas que nunca son de un juego
    os.makedirs(os.path.join(prefix, "default"))
    os.makedirs(os.path.join(prefix, "__wptools__"))

    esperar("gid_de sobre carpeta", gid_de(os.path.join(games, "My Game")), "My_Game")
    vivos = gids_vivos(games)
    if "My_Game" not in vivos:
        fallos.append("un juego en carpeta con espacios no cuenta como vivo: %r" % vivos)
    if "Otro" not in vivos:
        fallos.append("una imagen no cuenta como viva: %r" % vivos)

    h = huerfanos(games, overlay, prefix, perfiles)
    rutas = sorted(os.path.basename(r.rstrip(os.sep)) for _t, r, _b in h)
    # EL FALLO GORDO: My_Game NO puede salir aqui.
    if "My_Game" in rutas:
        fallos.append("un juego en carpeta con espacios sigue saliendo como huerfano")
    esperar("huerfanos", rutas, ["JuegoBorrado"])

    # un perfil vivo protege la carpeta
    os.makedirs(os.path.join(overlay, "ConPerfil"))
    with open(os.path.join(perfiles, "ConPerfil.conf"), "w") as fh:
        fh.write("x")
    rutas = sorted(os.path.basename(r.rstrip(os.sep)) for _t, r, _b in
                   huerfanos(games, overlay, prefix, perfiles))
    if "ConPerfil" in rutas:
        fallos.append("una carpeta con perfil vivo sale como huerfana")

    # tamaños
    if bytes_de(os.path.join(games, "My Game")) < 100:
        fallos.append("bytes_de no suma el contenido de la carpeta")
    if bytes_de(os.path.join(raiz, "no-existe")) != 0:
        fallos.append("bytes_de de algo que no existe no da 0")
    if bytes_libres(raiz) <= 0:
        fallos.append("bytes_libres no devuelve nada util")
    if bytes_libres(os.path.join(raiz, "aun", "no", "existe")) <= 0:
        fallos.append("bytes_libres no sube al padre que existe")

    # listado ordenado de mayor a menor
    filas = lista_juegos(games, overlay, prefix)
    if len(filas) != 2:
        fallos.append("lista_juegos: %d filas en vez de 2" % len(filas))
    if filas and filas != sorted(filas, key=lambda f: (-f[0], f[1].lower())):
        fallos.append("lista_juegos no viene ordenada")

    # sha256
    import hashlib
    ph = os.path.join(raiz, "h.bin")
    with open(ph, "wb") as fh:
        fh.write(b"abc" * 100000)
    esperar("sha256", sha256(ph),
            hashlib.sha256(b"abc" * 100000).hexdigest())
    esperar("sha256 inexistente", sha256(os.path.join(raiz, "nada")), "")

    # cabeceras
    esperar("magia squashfs", magia(os.path.join(games, "Otro.wsquashfs")), "squashfs")
    with open(os.path.join(raiz, "d.dwarfs"), "wb") as fh:
        fh.write(b"DWARFS\x00\x00")
    esperar("magia dwarfs", magia(os.path.join(raiz, "d.dwarfs")), "dwarfs")
    with open(os.path.join(raiz, "malo.bin"), "wb") as fh:
        fh.write(b"no soy una imagen")
    esperar("magia desconocida", magia(os.path.join(raiz, "malo.bin")), "")
    esperar("magia inexistente", magia(os.path.join(raiz, "nada")), "")

    shutil.rmtree(raiz, ignore_errors=True)
    return fallos


# ----------------------------------------------------------------------------
# LINEA DE ORDENES
# ----------------------------------------------------------------------------

def main(argv):
    if len(argv) < 2:
        sys.stderr.write(
            "uso: disco.py <orden> [...]\n"
            "  humano   <bytes>                        \"1.2 GB\"\n"
            "  tiempo   <segundos>                     \"3 h 12 min\"\n"
            "  bytes    <ruta>                         tamaño de fichero o carpeta\n"
            "  libres   <ruta>                         bytes libres\n"
            "  gid      <ruta>                         identificador del juego\n"
            "  huerfanos <games> <overlay> <prefix> <profiles>\n"
            "  juegos   <games> <overlay> <prefix>     tamaño por juego\n"
            "  magia    <fichero>                      squashfs | dwarfs | vacio\n"
            "  sha256   <fichero>                      huella del fichero\n"
            "  comprobar                               auto-diagnostico\n")
        return 2
    orden = argv[1]

    if orden == "comprobar":
        fallos = comprobar()
        if fallos:
            sys.stderr.write("disco.py: %d fallo(s)\n" % len(fallos))
            for f in fallos:
                sys.stderr.write("  - %s\n" % f)
            return 1
        print("disco.py: todo correcto")
        return 0

    if orden == "humano":
        sys.stdout.write(tam_humano(argv[2] if len(argv) > 2 else 0))
        return 0
    if orden == "tiempo":
        sys.stdout.write(fmt_tiempo(argv[2] if len(argv) > 2 else 0))
        return 0

    if len(argv) < 3:
        sys.stderr.write("disco.py %s: falta la ruta\n" % orden)
        return 2

    if orden == "bytes":
        sys.stdout.write("%d" % bytes_de(argv[2]))
        return 0
    if orden == "libres":
        n = bytes_libres(argv[2])
        if n < 0:
            return 1
        sys.stdout.write("%d" % n)
        return 0
    if orden == "gid":
        sys.stdout.write(gid_de(argv[2]))
        return 0
    if orden == "sha256":
        h = sha256(argv[2])
        if not h:
            return 1
        sys.stdout.write(h)
        return 0

    if orden == "magia":
        m = magia(argv[2])
        if not m:
            return 1
        sys.stdout.write(m)
        return 0
    if orden == "huerfanos":
        if len(argv) < 6:
            sys.stderr.write("disco.py huerfanos: faltan carpetas\n")
            return 2
        for tipo, ruta, tam in huerfanos(argv[2], argv[3], argv[4], argv[5]):
            print("%s|%s|%d" % (tipo, ruta, tam))
        return 0
    if orden == "juegos":
        if len(argv) < 5:
            sys.stderr.write("disco.py juegos: faltan carpetas\n")
            return 2
        for tam, nombre in lista_juegos(argv[2], argv[3], argv[4]):
            print("%015d\t%s (%s)" % (tam, nombre, tam_humano(tam)))
        return 0

    sys.stderr.write("disco.py: orden desconocida %r\n" % orden)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
