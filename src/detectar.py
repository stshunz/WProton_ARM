# -*- coding: utf-8 -*-
# WProton - deteccion del ejecutable de un juego
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
#   _fexe()               -> descartado() / filtrar()
#   scan_exes()           -> escanear()
#   parse_autorun()       -> leer_autorun()
#   autorun_args_de()     -> args_autorun()
#   find_exe_por_autorun()-> exe_por_autorun()
#   find_game_exe()       -> buscar_exe()
#   protondb_separar()    -> protondb_separar()
#   args_etiqueta()       -> etiqueta_args()
#
# La heuristica es la MISMA y en el mismo orden. Lo que cambia es que ahora se
# puede probar: hay un arbol de juego de mentira en comprobar() y cada paso de
# la heuristica tiene su caso. Antes esto solo se podia probar montando un
# wsquashfs de verdad.
#
# TRES FALLOS QUE SE ARREGLAN AL PORTAR
# -------------------------------------
#
# 1. EL FILTRO MIRABA LA RUTA ENTERA, NO EL NOMBRE DEL FICHERO.
#
#    _fexe era un "grep -iv" sobre lineas que son rutas completas, asi que un
#    juego perfectamente normal desaparecia si alguna CARPETA de su ruta
#    contenia una de las palabras de la lista:
#
#      /juegos/PhysX Racing/game.exe        -> descartado por "physx"
#      /juegos/Uninstall Tools/miJuego.exe  -> descartado por "unins"
#      /juegos/ReShade Collection/juego.exe -> descartado por "reshade"
#
#    Los tres son juegos buenos y WProton no los veia. Aqui el filtro se
#    aplica al NOMBRE DEL FICHERO, que es lo que siempre se quiso mirar. Las
#    exclusiones por carpeta (system32, syswow64, windows) siguen siendo por
#    ruta, aparte, porque ahi si importa la ruta.
#
# 2. LA LINEA DE PROTONDB SE PARTIA CON GLOBBING.
#
#    protondb_separar hacia "for tok in $linea" sin comillas: bash parte por
#    espacios Y expande comodines. Pegar "-windowed *" de ProtonDB metia los
#    nombres de los ficheros del directorio actual como argumentos del juego.
#    Aqui se parte con shlex, que es exactamente la regla de comillas del
#    shell y no expande nada.
#
# 3. EL NOMBRE DE UNITY SE SACABA CON "sed 's/[_.]Data$//i'".
#
#    La bandera "i" del comando s/// es una extension de GNU sed. En Batocera
#    el sed es el de busybox y no esta garantizada. No lo he podido comprobar
#    en un Batocera de verdad, asi que no afirmo que fallara alli; lo que si
#    es seguro es que aqui ya no depende de que sed sea uno u otro.
#
# UNA DIFERENCIA DE COMPORTAMIENTO, A PROPOSITO
# ---------------------------------------------
# "find" no promete ningun orden, asi que cuando habia varios candidatos el
# que salia dependia del orden del sistema de ficheros: el mismo juego podia
# arrancar por un .exe distinto en dos maquinas. Aqui los candidatos se
# ordenan siempre igual (por profundidad y luego alfabeticamente). Puede que
# en algun juego salga otro .exe del que salia antes; a cambio, sale SIEMPRE
# el mismo y un fallo se puede reproducir.
# ----------------------------------------------------------------------------

import os
import re
import shlex
import sys

VERSION = "1"

# ----------------------------------------------------------------------------
# EL FILTRO: herramientas, instaladores y utilidades que no son el juego.
# Las mismas palabras que tenia _fexe, en el mismo orden. Se comparan contra
# el NOMBRE del fichero, sin distinguir mayusculas.
# ----------------------------------------------------------------------------

_PALABRAS_FILTRO = [
    r'dgvoodoocpl', r'dxwnd', r'reshade', r'enbhost', r'enbinjector',
    r'winecfg', r'wineboot', r'winedbg', r'winepath',
    r'regedit', r'iexplore', r'explorer\.exe',
    r'msiexec', r'rundll32', r'regsvr32', r'regasm', r'regsvcs',
    r'notepad', r'wordpad', r'mspaint', r'wmplayer',
    r'dxdiag', r'msconfig', r'taskmgr', r'conhost', r'cmd\.exe',
    r'wscript', r'cscript', r'mshta', r'control\.exe',
    r'winver', r'mmc\.exe', r'werfault', r'drwatson', r'dwwin',
    r'unitycrashandler', r'unityplayer',
    r'ue4prereq', r'ue5prereq', r'epicwebhelper',
    r'vcredist', r'vc_redist', r'dxsetup', r'dotnetfx',
    r'oalinst', r'physx', r'msvcr', r'msvcp',
    r'modorganizer', r'xivlauncher', r'openxr', r'fpsmon',
    r'setup\.exe$', r'unins', r'install\.exe$',
    r'redist\.exe$', r'prerequisite', r'crashreport', r'bugsplat',
    r'scriptinterpreter', r'goggame', r'galaxycommunication',
]

_FILTRO = re.compile("|".join(_PALABRAS_FILTRO), re.IGNORECASE)

# Carpetas de Windows que nunca contienen el juego. Estas SI van por ruta.
_CARPETAS_VETADAS = ("/system32/", "/syswow64/")


def descartado(ruta):
    """True si este fichero es una herramienta y no el juego."""
    return bool(_FILTRO.search(os.path.basename(ruta)))


def filtrar(rutas):
    """Quita de una lista lo que no es el juego, conservando el orden."""
    return [r for r in rutas if not descartado(r)]


# ----------------------------------------------------------------------------
# RECORRIDO DEL ARBOL
# ----------------------------------------------------------------------------

def _hondura(raiz, ruta):
    return os.path.relpath(ruta, raiz).count(os.sep)


def _recorrer(raiz, exts, maxdepth=None, vetar_windows_raiz=True):
    """Ficheros bajo 'raiz' con una de esas extensiones.

    Se devuelve ORDENADO por profundidad y luego por ruta, para que dos
    maquinas con el mismo juego elijan el mismo ejecutable.
    """
    salidas = []
    raiz = os.path.abspath(raiz)
    veto_raiz = os.path.join(raiz, "windows") + os.sep
    for actual, dirs, ficheros in os.walk(raiz, followlinks=False):
        dirs.sort()
        if maxdepth is not None and _hondura(raiz, actual) >= maxdepth:
            dirs[:] = []
        bajo = (actual + os.sep).lower()
        if any(v in bajo for v in _CARPETAS_VETADAS):
            continue
        if vetar_windows_raiz and bajo.startswith(veto_raiz.lower()):
            continue
        for f in sorted(ficheros):
            if os.path.splitext(f)[1].lower() in exts:
                salidas.append(os.path.join(actual, f))
    salidas.sort(key=lambda r: (_hondura(raiz, r), r.lower()))
    return salidas


def escanear(raiz):
    """La lista que se ofrece al elegir el ejecutable a mano (scan_exes).

    Ademas de .exe se incluyen .bat y .cmd: algunos juegos -sobre todo ports
    y titulos antiguos- arrancan con un script por lotes que prepara
    variables o elige la version correcta antes de llamar al ejecutable.
    """
    todo = _recorrer(raiz, {".exe", ".bat", ".cmd"})
    return filtrar(r for r in todo
                   if os.path.basename(r).lower() != "autorun.cmd")


# ----------------------------------------------------------------------------
# AUTORUN.CMD (formato Batocera, con CRLF y a veces en UTF-16)
# ----------------------------------------------------------------------------

def _texto_autorun(ruta):
    """El contenido del autorun.cmd, venga como venga.

    Antes esto dependia de que la orden 'file' estuviera instalada y dijera
    "UTF-16". Cuando no lo decia -y hay autorun en UTF-16 que no detecta- se
    leia con los bytes nulos dentro. Aqui se mira el BOM, y si no hay BOM se
    mira si el fichero esta lleno de bytes nulos, que es la firma de UTF-16
    con texto ASCII dentro.
    """
    try:
        with open(ruta, "rb") as fh:
            crudo = fh.read()
    except OSError:
        return ""
    if crudo.startswith(b"\xff\xfe") or crudo.startswith(b"\xfe\xff"):
        try:
            return crudo.decode("utf-16")
        except (UnicodeDecodeError, ValueError):
            pass
    if crudo.count(b"\x00") > len(crudo) // 4:
        for cod in ("utf-16-le", "utf-16-be"):
            try:
                return crudo.decode(cod)
            except (UnicodeDecodeError, ValueError):
                continue
    return crudo.replace(b"\x00", b"").decode("utf-8", "replace")


_CLAVE = {}
for _c in ("DIR", "CMD", "ENV", "LANG", "SAVEDIR"):
    # SE ADMITEN ESPACIOS ALREDEDOR DEL "=" Y AL PRINCIPIO DE LA LINEA.
    #
    # El patron de antes era "^CLAVE=", que no casa con 'DIR = SysStart/Game'
    # ni con una linea sangrada. Como no se sacaba nada, el ejecutable se
    # elegia por heuristica y acertaba solo de casualidad -cuando el .exe
    # bueno estaba en la raiz-.
    _CLAVE[_c] = re.compile(r"^[ \t]*%s[ \t]*=(.*)$" % _c, re.IGNORECASE)


def leer_autorun(ruta):
    """Devuelve un dict con dir, cmd, cmd_base, args, env, lang, savedir."""
    r = {"dir": "", "cmd": "", "cmd_base": "", "args": "",
         "env": "", "lang": "", "savedir": False}
    if not os.path.isfile(ruta):
        return r
    texto = _texto_autorun(ruta).replace("\r", "")
    # Las barras invertidas de Windows pasan a barras normales, como antes.
    texto = texto.replace("\\", "/")

    def valor(clave):
        for linea in texto.split("\n"):
            m = _CLAVE[clave].match(linea)
            if m:
                return m.group(1).strip()
        return ""

    r["savedir"] = bool(valor("SAVEDIR"))
    d = valor("DIR").strip()
    if len(d) >= 2 and d[0] == '"' and d[-1] == '"':
        d = d[1:-1]
    if d.startswith("./"):
        d = d[2:]
    r["dir"] = d

    bruto = valor("CMD")
    # CMD puede llevar comillas y argumentos: CMD="Rayman Origins.exe" --full
    if bruto.startswith('"'):
        cierre = bruto.find('"', 1)
        if cierre > 0:
            r["cmd"] = bruto[1:cierre]
            r["args"] = bruto[cierre + 1:].strip()
        else:
            r["cmd"] = bruto[1:]
    elif bruto:
        partes = bruto.split(" ", 1)
        r["cmd"] = partes[0]
        r["args"] = partes[1].strip() if len(partes) > 1 else ""
    r["cmd_base"] = os.path.basename(r["cmd"]) if r["cmd"] else ""
    r["env"] = valor("ENV")
    r["lang"] = valor("LANG")
    return r


def autorun_de(raiz):
    """El autorun.cmd de este juego: primero en la raiz, luego mas adentro."""
    if not os.path.isdir(raiz):
        return ""
    arriba = os.path.join(raiz, "autorun.cmd")
    for f in sorted(os.listdir(raiz)):
        if f.lower() == "autorun.cmd":
            arriba = os.path.join(raiz, f)
            if os.path.isfile(arriba):
                return arriba
    for actual, dirs, ficheros in os.walk(raiz):
        dirs.sort()
        for f in sorted(ficheros):
            if f.lower() == "autorun.cmd":
                return os.path.join(actual, f)
    return ""


def args_autorun(raiz):
    """Los argumentos que trae el autorun.cmd. Cadena vacia si no hay.

    No es raro que ahi este lo que de verdad hace funcionar el juego:
      CMD="hl2.exe" -game portal -novid -language spanish
    Sin esos argumentos arranca Half-Life 2 en ingles en vez de Portal en
    español.
    """
    a = autorun_de(raiz)
    if not a:
        return ""
    return leer_autorun(a)["args"]


def _buscar_por_nombre(raiz, nombre, dentro_de=""):
    """El primer fichero que se llame asi, opcionalmente bajo cierta carpeta.

    'dentro_de' se compara como TEXTO dentro de la ruta, no como patron: el
    DIR del autorun puede traer corchetes o parentesis (los nombres de los
    volcados de arcade estan llenos), y de patron eso no casaria con nada.
    """
    nombre = nombre.lower()
    dentro = dentro_de.strip("/").lower()
    encontrados = []
    for actual, dirs, ficheros in os.walk(raiz):
        dirs.sort()
        for f in sorted(ficheros):
            if f.lower() != nombre:
                continue
            ruta = os.path.join(actual, f)
            if dentro and dentro not in ruta.replace(os.sep, "/").lower():
                continue
            encontrados.append(ruta)
    encontrados.sort(key=lambda r: (_hondura(raiz, r), r.lower()))
    return encontrados[0] if encontrados else ""


def exe_por_autorun(raiz):
    """El ejecutable que dice el autorun.cmd de ESTA carpeta (solo la raiz)."""
    if not os.path.isdir(raiz):
        return ""
    arriba = ""
    for f in sorted(os.listdir(raiz)):
        if f.lower() == "autorun.cmd" and os.path.isfile(os.path.join(raiz, f)):
            arriba = os.path.join(raiz, f)
            break
    if not arriba:
        return ""
    a = leer_autorun(arriba)
    if not a["cmd_base"]:
        return ""
    return _buscar_por_nombre(raiz, a["cmd_base"], a["dir"])


# ----------------------------------------------------------------------------
# LA HEURISTICA, en el mismo orden de fiabilidad que tenia find_game_exe
# ----------------------------------------------------------------------------

def buscar_exe(raiz):
    """El ejecutable del juego, o cadena vacia si no se encuentra ninguno."""
    raiz = os.path.abspath(raiz)
    if not os.path.isdir(raiz):
        return ""

    # 0) EL AUTORUN.CMD MANDA, igual que al lanzar.
    #
    # Antes el asistente NO lo miraba y find_exe (lo que se usa AL LANZAR) si.
    # O sea que el asistente sugeria un .exe distinto del que se iba a
    # ejecutar; al aceptar la sugerencia se guardaba en el perfil y entonces
    # el autorun ya no se consultaba nunca. Asi se perdian los juegos que
    # arrancan por un .bat (TeknoParrot y compania).
    a = autorun_de(raiz)
    if a:
        datos = leer_autorun(a)
        if datos["cmd_base"]:
            hit = _buscar_por_nombre(raiz, datos["cmd_base"], datos["dir"])
            if hit:
                return hit

    exes = _recorrer(raiz, {".exe"})

    # 1) Binarios de motor (Unreal y similares)
    motor = [r for r in exes
             if re.search(r"/(Binaries/)?Win(64|32)/", r.replace(os.sep, "/"),
                          re.IGNORECASE)]
    motor = filtrar(motor)
    if motor:
        return motor[0]

    # 2) exe en la raiz
    superficie = filtrar(r for r in exes if _hondura(raiz, r) == 0)
    if superficie:
        return superficie[0]

    # 3) prefijos con drive_c
    drive_c = os.path.join(raiz, "drive_c")
    if os.path.isdir(drive_c):
        # LAS CARPETAS DE WINDOWS SE VETABAN MAL.
        #
        # El original excluia "$ROOT/windows/*" mientras buscaba dentro de
        # "$ROOT/drive_c": esa exclusion no casaba nunca, porque windows
        # cuelga de drive_c, no de la raiz. Solo salvaban el resultado los
        # vetos de system32 y syswow64. Aqui se veta la carpeta windows del
        # prefijo, que es lo que se queria.
        dentro = _recorrer(drive_c, {".exe"})
        veto = ("/programdata/", "/common files/",
                "/" + os.path.relpath(drive_c, raiz).lower() + "/windows/")
        dentro = [r for r in dentro
                  if not any(v in ("/" + os.path.relpath(r, raiz).lower())
                             for v in veto)]
        dentro = filtrar(dentro)
        if dentro:
            return dentro[0]

    # 4) Unity: <Nombre>_Data junto a <Nombre>.exe
    for actual, dirs, _f in os.walk(raiz):
        dirs.sort()
        if _hondura(raiz, actual) >= 5:
            dirs[:] = []
            continue
        for d in dirs:
            bajo = d.lower()
            if bajo.endswith("_data") or bajo.endswith(".data"):
                nombre = d[:-5]          # quita "_Data" o ".Data"
                cand = os.path.join(actual, nombre + ".exe")
                if os.path.isfile(cand):
                    return cand
                # sin distinguir mayusculas, como hacia el sed con su "i"
                for f2 in sorted(os.listdir(actual)):
                    if f2.lower() == (nombre + ".exe").lower():
                        return os.path.join(actual, f2)

    # 5) barrido general
    general = filtrar(exes)
    if general:
        return general[0]

    # 6) sin ningun .exe utilizable: puede ser un juego que arranca por .bat
    #
    # Ordenado por PROFUNDIDAD, para no coger "utilidades/limpiar.bat" antes
    # que el "jugar.bat" de la raiz.
    lotes = _recorrer(raiz, {".bat", ".cmd"})
    lotes = filtrar(r for r in lotes
                    if os.path.basename(r).lower() != "autorun.cmd")
    return lotes[0] if lotes else ""


# ----------------------------------------------------------------------------
# PROTONDB
# ----------------------------------------------------------------------------

def protondb_separar(linea):
    """Parte una linea de ProtonDB en (variables, argumentos).

    En ProtonDB las opciones se dan como se escriben en Steam:

        PROTON_ENABLE_WAYLAND=1 %command% -vulkan

    Eso son dos cosas: una VARIABLE DE ENTORNO y un ARGUMENTO del juego.
    Nuestro campo "Argumentos" es solo para lo segundo, asi que pegar la
    linea entera hacia que el juego recibiera "PROTON_ENABLE_WAYLAND=1" como
    si fuera un argumento suyo.

    SE PARTE CON shlex Y NO CON EL SHELL. El original hacia "for tok in
    $linea" sin comillas, y eso no solo parte por espacios: tambien expande
    comodines. Pegar "-windowed *" metia los ficheros del directorio actual
    como argumentos del juego. shlex aplica las reglas de comillas del shell
    sin expandir nada.
    """
    linea = (linea or "").replace("%command%", " ")
    try:
        piezas = shlex.split(linea)
    except ValueError:
        # comillas sin cerrar: se parte por espacios, que es lo unico
        # razonable que queda, pero sin expandir comodines
        piezas = linea.split()
    variables, argumentos = [], []
    for pieza in piezas:
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", pieza):
            variables.append(pieza)
        else:
            argumentos.append(pieza)
    return " ".join(variables), " ".join(argumentos)


def etiqueta_args(raiz, override=""):
    """Lo que pone la fila "Argumentos:" en el menu.

    Ponia "ninguno" cuando no habias escrito nada tuyo, pero el juego SI
    llevaba los de su autorun.cmd. Con Portal eso son "-game portal -novid
    -language spanish": decir "ninguno" es mentir, y ademas invita a escribir
    algo que los borraria.
    """
    if override:
        return override
    a = args_autorun(raiz) if raiz and os.path.isdir(raiz) else ""
    return ("%s   (del autorun.cmd)" % a) if a else "ninguno"


# ----------------------------------------------------------------------------
# COMPROBACION INTERNA
#
# Se monta un arbol de juego de mentira y se comprueba cada paso de la
# heuristica. Antes esto solo se podia probar montando un wsquashfs de
# verdad, asi que en la practica no se probaba.
# ----------------------------------------------------------------------------

def _crear(base, *rutas):
    for r in rutas:
        completa = os.path.join(base, r)
        os.makedirs(os.path.dirname(completa), exist_ok=True)
        with open(completa, "w", encoding="utf-8") as fh:
            fh.write("x")


def comprobar():
    import shutil
    import tempfile
    fallos = []
    raiz = tempfile.mkdtemp(prefix="wp-detectar-")

    def caso(nombre, arbol, esperado, autorun=None):
        d = os.path.join(raiz, nombre)
        os.makedirs(d, exist_ok=True)
        _crear(d, *arbol)
        if autorun is not None:
            with open(os.path.join(d, "autorun.cmd"), "wb") as fh:
                fh.write(autorun)
        visto = buscar_exe(d)
        visto = os.path.relpath(visto, d) if visto else ""
        if visto.replace(os.sep, "/") != esperado:
            fallos.append("%s: se esperaba %r y salio %r" % (nombre, esperado, visto))

    # paso 0: manda el autorun
    caso("autorun", ["launcher.exe", "bin/juego.exe"], "bin/juego.exe",
         autorun=b'DIR = bin\r\nCMD = "juego.exe" -novid\r\n')
    # paso 0 en UTF-16, que es como los trae Batocera
    caso("autorun16", ["launcher.exe", "bin/real.exe"], "bin/real.exe",
         autorun='DIR=bin\r\nCMD="real.exe"\r\n'.encode("utf-16"))
    # paso 1: motor Unreal
    caso("unreal", ["algo/Binaries/Win64/Juego.exe", "hondo/otro.exe"],
         "algo/Binaries/Win64/Juego.exe")
    # paso 2: exe en la raiz
    caso("raiz", ["Juego.exe", "sub/otro.exe"], "Juego.exe")
    # paso 4: Unity
    caso("unity", ["datos/MiJuego_Data/x.dat", "datos/MiJuego.exe"],
         "datos/MiJuego.exe")
    # paso 6: solo un .bat, y gana el menos hondo
    caso("lotes", ["util/limpiar.bat", "jugar.bat"], "jugar.bat")
    # el filtro descarta instaladores pero NO el juego
    caso("filtro", ["setup.exe", "vcredist.exe", "unins000.exe", "ElJuego.exe"],
         "ElJuego.exe")

    # EL FALLO QUE SE ARREGLA: carpetas con nombre de la lista negra.
    for carpeta in ("PhysX Racing", "Uninstall Tools", "ReShade Collection"):
        d = os.path.join(raiz, "carpeta_" + carpeta.split()[0])
        _crear(d, os.path.join(carpeta, "ElJuego.exe"))
        if not buscar_exe(d):
            fallos.append("un juego dentro de %r sigue sin verse" % carpeta)

    # protondb: variables aparte de argumentos, y sin expandir comodines
    v, a = protondb_separar("PROTON_ENABLE_WAYLAND=1 %command% -vulkan")
    if v != "PROTON_ENABLE_WAYLAND=1" or a != "-vulkan":
        fallos.append("protondb_separar: %r / %r" % (v, a))
    antes = os.getcwd()
    os.chdir(raiz)
    v, a = protondb_separar("-windowed *")
    os.chdir(antes)
    if a != "-windowed *":
        fallos.append("protondb_separar expande comodines: %r" % a)
    v, a = protondb_separar('MANGOHUD=1 %command% -opt "a b"')
    if a != "-opt a b" or v != "MANGOHUD=1":
        fallos.append("protondb_separar y las comillas: %r / %r" % (v, a))

    # autorun: argumentos y claves con espacios alrededor del =
    d = os.path.join(raiz, "args")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "autorun.cmd"), "w", encoding="utf-8") as fh:
        fh.write('  DIR = bin\r\n  CMD = "hl2.exe" -game portal -novid\r\n')
    if args_autorun(d) != "-game portal -novid":
        fallos.append("args_autorun: %r" % args_autorun(d))
    if etiqueta_args(d) != "-game portal -novid   (del autorun.cmd)":
        fallos.append("etiqueta_args: %r" % etiqueta_args(d))
    if etiqueta_args(d, "-mio") != "-mio":
        fallos.append("etiqueta_args ignora el override")

    # el resultado tiene que ser el mismo en dos pasadas seguidas
    d = os.path.join(raiz, "estable")
    _crear(d, "a/uno.exe", "b/dos.exe", "c/tres.exe")
    if buscar_exe(d) != buscar_exe(d):
        fallos.append("buscar_exe no es estable entre pasadas")

    shutil.rmtree(raiz, ignore_errors=True)
    return fallos


# ----------------------------------------------------------------------------
# LINEA DE ORDENES
# ----------------------------------------------------------------------------

def main(argv):
    if len(argv) < 2:
        sys.stderr.write(
            "uso: detectar.py <orden> [...]\n"
            "  exe        <raiz>              el ejecutable del juego\n"
            "  escanear   <raiz>              lista para elegir a mano\n"
            "  filtrar                        filtro de tuberia (rutas por stdin)\n"
            "  autorun    <raiz>              claves del autorun.cmd\n"
            "  autorun-fichero <fichero>      idem, dando el fichero\n"
            "  args       <raiz>              argumentos del autorun.cmd\n"
            "  exe-autorun <raiz>             el exe que dice el autorun\n"
            "  protondb   <linea>             variables<TAB>argumentos\n"
            "  etiqueta   <raiz> [override]   texto de la fila Argumentos\n"
            "  comprobar                      auto-diagnostico\n")
        return 2
    orden = argv[1]

    if orden == "comprobar":
        fallos = comprobar()
        if fallos:
            sys.stderr.write("detectar.py: %d fallo(s)\n" % len(fallos))
            for f in fallos:
                sys.stderr.write("  - %s\n" % f)
            return 1
        print("detectar.py: todo correcto")
        return 0

    if orden == "filtrar":
        # Filtro de tuberia: rutas por la entrada, las buenas por la salida.
        # Lo usa el codigo de instaladores GOG, que arma su propia lista de
        # candidatos y solo necesita quitarle las herramientas.
        for linea in sys.stdin.read().split("\n"):
            if linea and not descartado(linea):
                print(linea)
        return 0

    if orden == "autorun-fichero":
        # parse_autorun() recibe el FICHERO, no la carpeta: tiene un llamador
        # en write_autorun que ya lo tiene localizado.
        if len(argv) < 3:
            return 2
        d = leer_autorun(argv[2])
        for k in ("dir", "cmd", "cmd_base", "args", "env", "lang"):
            print("%s\t%s" % (k, d[k]))
        return 0

    if orden == "protondb":
        v, a = protondb_separar(argv[2] if len(argv) > 2 else "")
        sys.stdout.write("%s\t%s" % (v, a))
        return 0

    if len(argv) < 3:
        sys.stderr.write("detectar.py %s: falta <raiz>\n" % orden)
        return 2
    raiz = argv[2]

    if orden == "exe":
        r = buscar_exe(raiz)
        if not r:
            return 1
        sys.stdout.write(r)
        return 0
    if orden == "escanear":
        for r in escanear(raiz):
            print(r)
        return 0
    if orden == "autorun":
        a = autorun_de(raiz)
        if not a:
            return 1
        d = leer_autorun(a)
        for k in ("dir", "cmd", "cmd_base", "args", "env", "lang"):
            print("%s\t%s" % (k, d[k]))
        return 0
    if orden == "args":
        a = args_autorun(raiz)
        if not a:
            return 1
        sys.stdout.write(a)
        return 0
    if orden == "exe-autorun":
        r = exe_por_autorun(raiz)
        if not r:
            return 1
        sys.stdout.write(r)
        return 0
    if orden == "etiqueta":
        sys.stdout.write(etiqueta_args(raiz, argv[3] if len(argv) > 3 else ""))
        return 0

    sys.stderr.write("detectar.py: orden desconocida %r\n" % orden)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
