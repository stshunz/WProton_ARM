# -*- coding: utf-8 -*-
# WProton - perfiles XML de TeknoParrot
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
#   el heredoc EOFTKP  de teknoparrot_rutas()            -> arreglar_rutas()
#   el heredoc EOFTKPR de teknoparrot_devolver_rutas()   -> devolver_rutas()
#
# QUE HACE
#
# Los perfiles de TeknoParrot (UserProfiles/*.xml) llevan la ruta del juego en
# <GamePath>, escrita para el ordenador de quien los hizo. Aqui se reescriben
# para que apunten a donde esta el juego AHORA. Y antes de tocar nada se
# guarda una copia intacta (.wproton_original), porque un juego en carpeta es
# una carpeta de verdad: sin la copia le estariamos reescribiendo a Batocera
# el XML que alli funciona.
#
# La logica es la MISMA que estaba dentro del heredoc, con sus casos ganados a
# base de golpes: la busqueda tolerante de F-Zero, la ruta relativa de Street
# Fighter y la ruta en C: de Aliens Armageddon. Cada uno tiene ahora su prueba
# en comprobar(), que es lo que antes no se podia hacer: metido en un literal
# de bash, este codigo solo se podia probar montando un juego de verdad.
#
# DOS FALLOS QUE SE ARREGLAN AL PORTAR
# ------------------------------------
#
# 1. EL INDICE DEPENDIA DEL ORDEN DEL SISTEMA DE FICHEROS.
#
#    Se recorre el juego con os.walk y se guarda cada nombre con setdefault,
#    o sea que GANA EL PRIMERO QUE APAREZCA. Y os.walk devuelve orden de
#    readdir, que cambia entre sistemas de ficheros. Con dos ficheros del
#    mismo nombre -un lanzador en la raiz y el juego de verdad mas adentro- el
#    perfil podia quedar apuntando a uno o a otro segun se leyera el juego
#    como carpeta o montado desde el squashfs. Ahora el recorrido va ordenado
#    y ademas gana el MENOS HONDO, que es el criterio que ya se queria.
#
# 2. AL DEVOLVER LAS RUTAS SE TRUNCABA EL PERFIL.
#
#    devolver_rutas abria el XML en modo escritura y escribia encima. Si
#    fallaba a medias, el perfil se quedaba cortado y TeknoParrot ya no
#    arrancaba el juego. Ahora se escribe en un temporal y se mueve.
# ----------------------------------------------------------------------------

import os
import re
import sys
import tempfile

VERSION = "1"

CAMPOS = ("GamePath", "GamePath2")

# El indice se para a los 60.000 ficheros. Recorrer el juego entero es
# instantaneo en un disco normal, pero sobre un squashfs comprimido leido de
# un USB puede tardar de verdad, y el usuario solo ve "Preparando el entorno
# de Windows" sin saber que pasa. Con 60.000 hay de sobra: lo que se busca es
# una ISO o un ejecutable, no algo enterrado entre cien mil ficheros.
MAX_FICHEROS = 60000


# ----------------------------------------------------------------------------
# RUTAS
# ----------------------------------------------------------------------------

def a_windows(ruta, raiz, letra="", base_unidad=""):
    """La ruta como la ve Wine.

    Con unidad propia (D:) sale corta y relativa a la carpeta del juego, que
    es lo que estos programas esperan y lo que llevaban los perfiles de
    Batocera. Sin ella se usa Z:, la raiz del sistema: funciona, pero da
    rutas larguisimas con la carpeta personal por medio.
    """
    p = os.path.abspath(ruta)
    letra = (letra or "").strip().upper()
    if letra:
        base = os.path.abspath(base_unidad or raiz)
        if p == base:
            return letra + ":\\"
        if p.startswith(base + os.sep):
            return letra + ":\\" + p[len(base) + 1:].replace("/", "\\")
    return "Z:" + p.replace("/", "\\")


def _laxo(nombre):
    """El nombre sin espacios ni signos, para comparar con tolerancia.

    El perfil y el fichero no siempre coinciden al caracter. Un caso real:

      el perfil dice   F-Zero AX (Triforce) (Rev E) [JAP][SBGG].iso
      el fichero es    F-Zero AX (Triforce) (Rev E) [JAP] [SBGG].iso

    Un espacio de diferencia, y la busqueda exacta no lo encontraba. Quien
    empaqueto el juego renombro el fichero y no toco el perfil, o al reves:
    pasa constantemente.
    """
    return re.sub(r"[^a-z0-9.]", "", nombre.lower())


def indexar(raiz):
    """Indice de los ficheros del juego. Devuelve (exacto, laxo, cortado).

    Se recorre UNA vez: con juegos grandes, buscar por cada perfil seria
    lentisimo.

    EL RECORRIDO VA ORDENADO Y GANA EL MENOS HONDO. Antes era orden de
    readdir con "el primero que aparezca", asi que con dos ficheros del mismo
    nombre el resultado cambiaba entre sistemas de ficheros: el mismo juego
    podia quedar apuntando a un sitio leido como carpeta y a otro leido desde
    el squashfs.
    """
    exacto, laxo = {}, {}
    vistos = 0
    cortado = False
    encontrados = []
    for base, dirs, ficheros in os.walk(raiz):
        dirs.sort()
        if os.path.basename(base).lower() == "userprofiles":
            dirs[:] = []
            continue
        for f in sorted(ficheros):
            encontrados.append((base, f))
            vistos += 1
        if vistos > MAX_FICHEROS:
            cortado = True
            break
    # menos hondo primero, y a igual hondura por orden alfabetico
    encontrados.sort(key=lambda t: (t[0].count(os.sep), t[0], t[1]))
    for base, f in encontrados:
        completa = os.path.join(base, f)
        exacto.setdefault(f.lower(), completa)
        laxo.setdefault(_laxo(f), completa)
    return exacto, laxo, (cortado, vistos)


def perfiles_de(raiz):
    """Los XML de UserProfiles, sin contar las copias intactas.

    Una copia .wproton_original NO es un perfil: procesarla guardaria una
    copia de la copia y se lian los nombres.
    """
    salida = []
    for base, dirs, ficheros in os.walk(raiz):
        dirs.sort()
        if os.path.basename(base).lower() != "userprofiles":
            continue
        for f in sorted(ficheros):
            if f.lower().endswith(".xml") and not f.endswith(".wproton_original"):
                salida.append(os.path.join(base, f))
    return salida


def _escribir(ruta, texto):
    """Escritura atomica: temporal al lado y os.replace encima."""
    carpeta = os.path.dirname(os.path.abspath(ruta)) or "."
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=carpeta, prefix=".tkp-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(texto)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, ruta)
        return True
    except OSError:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise


def _resolver_tal_cual(actual, raiz):
    """Si la ruta del perfil YA apunta a un fichero que existe, esa ruta.

    PRIMERO LA RUTA TAL CUAL. Un perfil traia ".\\game\\...\\StreetFighterV.exe",
    una ruta RELATIVA que ya era correcta. Quedarse solo con el nombre del
    fichero hacia que, habiendo dos con ese nombre -un lanzador y el juego de
    verdad-, se cogiera el que no era: la ruta buena estaba delante y se
    tiraba.

    UNA RUTA EN C: SE RESUELVE CONTRA drive_c, NO CONTRA LA RAIZ. El XML de
    Aliens Armageddon dice "C:\\game\\game.exe". Quitandole solo los "./"
    quedaba "C:/game/game.exe" y se buscaba en "<paquete>/C:/game/game.exe",
    que no existe nunca; entonces se caia en la busqueda por nombre, y
    "game.exe" es tan generico que podia apuntar a cualquier cosa. Y esa ruta
    ES correcta: paquete_drive_c_enlazar pone en el C: del prefijo lo que el
    paquete trae en su drive_c.
    """
    rel = actual.replace("\\", "/")
    raiz_rel = raiz
    m = re.match(r"^([A-Za-z]):/(.*)$", rel)
    if m:
        if m.group(1).lower() == "c":
            raiz_rel = os.path.join(raiz, "drive_c")
            rel = m.group(2)
        else:
            # Otra letra: es de un prefijo de Windows de verdad y aqui no
            # significa nada. Se busca por nombre.
            return ""
    else:
        rel = rel.lstrip("./")
    if not rel:
        return ""
    cand = os.path.join(raiz_rel, rel)
    if os.path.isfile(cand):
        return cand
    # Tambien desde la raiz: hay paquetes sin drive_c que ponen las carpetas
    # arriba.
    alt = os.path.join(raiz, rel)
    return alt if os.path.isfile(alt) else ""


def arreglar_perfil(perfil, raiz, exacto, laxo, letra="", base_unidad=""):
    """Reescribe un XML. Devuelve una lista de sucesos "TIPO|a|b"."""
    sucesos = []

    # EL ORIGINAL SE GUARDA Y NUNCA SE PIERDE.
    #
    # Con un .wsquashfs esto va sobre la superposicion y el archivo no se
    # toca. Pero un juego en CARPETA es una carpeta de verdad: le estariamos
    # reescribiendo su XML en su sitio, y ese es el que funciona en Batocera.
    # Asi que la primera vez se guarda una copia intacta y a partir de
    # entonces SIEMPRE se parte de ella: el fichero se puede recuperar, y la
    # ruta no se va acumulando de una sesion a otra.
    original = perfil + ".wproton_original"
    try:
        if not os.path.exists(original):
            with open(perfil, encoding="utf-8", errors="replace") as fh:
                intacto = fh.read()
            _escribir(original, intacto)
            sucesos.append("COPIA|%s|%s" % (os.path.basename(perfil),
                                            os.path.basename(original)))
    except OSError as e:
        # Sin poder guardar la copia NO se toca el perfil: mejor que el juego
        # no arranque a dejar sin recuperacion el que funciona en Batocera.
        sucesos.append("NOCOPIA|%s|%s" % (os.path.basename(perfil), e))
        return sucesos

    try:
        with open(original, encoding="utf-8", errors="replace") as fh:
            texto = fh.read()
    except OSError:
        return sucesos

    texto2 = texto
    tocado = False
    faltan = []

    # El nombre que el perfil quiere, por si <GamePath> viene vacio: estos
    # perfiles llegan como PLANTILLA, con la ruta en blanco y el fichero en
    # <ExecutableName>. El .bat que hacia esto a mano copiaba una version ya
    # rellena por cada sitio donde pudiera estar el juego; aqui se rellena con
    # la ruta real, que vale para cualquier sitio.
    m_exe = re.search(r"<ExecutableName>(.*?)</ExecutableName>", texto2, re.S)
    nombre_exe = m_exe.group(1).strip() if m_exe else ""

    for campo in CAMPOS:
        patron = r"<%s>(.*?)</%s>" % (campo, campo)
        # DE ATRAS ADELANTE: asi las posiciones de las coincidencias
        # anteriores siguen valiendo aunque cambie la longitud del texto.
        for m in reversed(list(re.finditer(patron, texto2, re.S))):
            # 'nombre' se declara SIEMPRE: si la ruta no existe y el campo no
            # es GamePath, se llegaba abajo sin haberlo definido y esto moria
            # con NameError. Lo caza la prueba de Street Fighter.
            nombre = ""
            actual = m.group(1).strip()
            if actual:
                # Solo lo que PARECE una ruta: hay campos con parametros
                # sueltos ("-t") y esos no se tocan.
                if "\\" not in actual and "/" not in actual:
                    continue
                cand = _resolver_tal_cual(actual, raiz)
                if cand:
                    nv = a_windows(cand, raiz, letra, base_unidad)
                    if actual != nv:
                        texto2 = texto2[:m.start(1)] + nv + texto2[m.end(1):]
                        tocado = True
                    continue
                nombre = re.split(r"[\\/]", actual)[-1]
            elif campo == "GamePath" and nombre_exe:
                nombre = re.split(r"[\\/]", nombre_exe)[-1]
            else:
                continue
            if not nombre:
                continue
            real = exacto.get(nombre.lower())
            if not real:
                # Segunda pasada, tolerante: sobra o falta un espacio, un
                # guion... El fichero esta, solo que escrito de otra forma.
                real = laxo.get(_laxo(nombre))
                if real:
                    sucesos.append("LAXO|%s|%s" % (os.path.basename(perfil),
                                                   os.path.basename(real)))
            if not real:
                faltan.append(nombre)
                continue
            nueva = a_windows(real, raiz, letra, base_unidad)
            if actual == nueva:
                continue
            texto2 = texto2[:m.start(1)] + nueva + texto2[m.end(1):]
            tocado = True

    for n in faltan:
        sucesos.append("FALTA|%s|%s" % (os.path.basename(perfil), n))
    if not tocado:
        sucesos.append("NADA|%s|%s" % (os.path.basename(perfil),
                                       nombre_exe or "sin ruta ni ExecutableName"))
        return sucesos

    try:
        _escribir(perfil, texto2)
        # SE DEVUELVE LA RUTA QUE HA QUEDADO, no solo el nombre del fichero:
        # con el nombre a secas hay que abrir el XML a mano para comprobar si
        # la ruta escrita es la buena.
        puestas = re.findall(r"<GamePath>(.*?)</GamePath>", texto2, re.S)
        sucesos.append("OK|%s|%s" % (os.path.basename(perfil),
                                     puestas[0].strip() if puestas else nombre))
    except OSError as e:
        sucesos.append("ERROR|%s|%s" % (os.path.basename(perfil), e))
    return sucesos


def arreglar_rutas(raiz, letra="", base_unidad=""):
    """Recorre el juego y arregla todos sus perfiles. Devuelve los sucesos."""
    perfiles = perfiles_de(raiz)
    if not perfiles:
        return []
    exacto, laxo, (cortado, vistos) = indexar(raiz)
    sucesos = []
    if cortado:
        sucesos.append("MUCHOS|%d|se dejo de mirar (juego muy grande)" % vistos)
    for p in perfiles:
        sucesos.extend(arreglar_perfil(p, raiz, exacto, laxo, letra, base_unidad))
    return sucesos


def devolver_rutas(original, perfil):
    """Repone en el perfil las rutas que tenia el original.

    Se sustituyen en el mismo orden en que aparecen. Antes esto abria el XML
    en modo escritura y escribia encima: si fallaba a medias, el perfil se
    quedaba cortado y TeknoParrot ya no arrancaba el juego. Ahora es atomico.
    """
    try:
        with open(original, encoding="utf-8", errors="replace") as fh:
            texto_orig = fh.read()
        with open(perfil, encoding="utf-8", errors="replace") as fh:
            actual = fh.read()
    except OSError:
        return False

    nuevo = actual
    for campo in CAMPOS:
        patron = r"<%s>(.*?)</%s>" % (campo, campo)
        viejos = re.findall(patron, texto_orig, re.S)
        if not viejos:
            continue
        it = iter(viejos)

        def _rep(m, campo=campo, it=it):
            try:
                return "<%s>%s</%s>" % (campo, next(it), campo)
            except StopIteration:
                return m.group(0)

        nuevo = re.sub(patron, _rep, nuevo, flags=re.S)

    if nuevo == actual:
        return True
    try:
        _escribir(perfil, nuevo)
    except OSError:
        return False
    return True


# ----------------------------------------------------------------------------
# COMPROBACION INTERNA
#
# Cada caso de aqui abajo es un juego real que dio problemas. Metido en un
# literal de bash este codigo solo se podia probar montando el juego entero.
# ----------------------------------------------------------------------------

def comprobar():
    import shutil
    fallos = []
    raiz_tmp = tempfile.mkdtemp(prefix="wp-tkp-")

    def juego(nombre, ficheros, xml):
        d = os.path.join(raiz_tmp, nombre)
        for f in ficheros:
            p = os.path.join(d, f)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("x")
        up = os.path.join(d, "UserProfiles")
        os.makedirs(up, exist_ok=True)
        with open(os.path.join(up, "perfil.xml"), "w", encoding="utf-8") as fh:
            fh.write(xml)
        return d, os.path.join(up, "perfil.xml")

    def ruta_puesta(p):
        with open(p, encoding="utf-8") as fh:
            m = re.search(r"<GamePath>(.*?)</GamePath>", fh.read(), re.S)
        return m.group(1).strip() if m else ""

    # 1. F-ZERO: el nombre del perfil y el del fichero difieren en un espacio.
    d, p = juego("fzero",
                 ["roms/F-Zero AX (Triforce) (Rev E) [JAP] [SBGG].iso"],
                 "<X><GamePath>D:\\F-Zero AX (Triforce) (Rev E) [JAP][SBGG].iso"
                 "</GamePath></X>")
    s = arreglar_rutas(d, "D", d)
    if not any(x.startswith("LAXO|") for x in s):
        fallos.append("F-Zero: la busqueda tolerante no entra: %s" % s)
    if "roms" not in ruta_puesta(p):
        fallos.append("F-Zero: no se apunto al fichero real: %r" % ruta_puesta(p))

    # 2. STREET FIGHTER: ruta relativa YA correcta, y hay un homonimo mas
    #    arriba que no es el juego.
    d, p = juego("sf",
                 ["StreetFighterV.exe", "game/bin/StreetFighterV.exe"],
                 "<X><GamePath>.\\game\\bin\\StreetFighterV.exe</GamePath>"
                 "<GamePath2>-t</GamePath2></X>")
    arreglar_rutas(d, "D", d)
    if "bin" not in ruta_puesta(p):
        fallos.append("Street Fighter: se perdio la ruta relativa buena: %r"
                      % ruta_puesta(p))
    with open(p, encoding="utf-8") as fh:
        if "<GamePath2>-t</GamePath2>" not in fh.read():
            fallos.append("Street Fighter: se toco un campo que no es una ruta")

    # 3. ALIENS ARMAGEDDON: ruta en C:, que es el drive_c del paquete.
    d, p = juego("aliens", ["drive_c/game/game.exe", "otro/game.exe"],
                 "<X><GamePath>C:\\game\\game.exe</GamePath></X>")
    arreglar_rutas(d, "D", d)
    r = ruta_puesta(p)
    if "drive_c" not in r.replace("\\", "/"):
        fallos.append("Aliens: C: no se resolvio contra drive_c: %r" % r)

    # 4. PLANTILLA: GamePath vacio, el nombre esta en ExecutableName.
    d, p = juego("plantilla", ["roms/juego.iso"],
                 "<X><GamePath></GamePath>"
                 "<ExecutableName>juego.iso</ExecutableName></X>")
    arreglar_rutas(d, "D", d)
    if "juego.iso" not in ruta_puesta(p):
        fallos.append("Plantilla: no se relleno desde ExecutableName: %r"
                      % ruta_puesta(p))

    # 5. LA COPIA INTACTA se crea una vez y siempre se parte de ella.
    d, p = juego("copia", ["roms/x.iso"],
                 "<X><GamePath>Q:\\viejo\\x.iso</GamePath></X>")
    arreglar_rutas(d, "D", d)
    orig = p + ".wproton_original"
    if not os.path.isfile(orig):
        fallos.append("no se guardo la copia intacta")
    else:
        with open(orig, encoding="utf-8") as fh:
            if "Q:\\viejo" not in fh.read():
                fallos.append("la copia intacta no conserva la ruta original")
    primera = ruta_puesta(p)
    arreglar_rutas(d, "D", d)          # segunda pasada
    if ruta_puesta(p) != primera:
        fallos.append("la segunda pasada cambia el resultado (se acumula)")

    # 6. DEVOLVER las rutas del original.
    if not devolver_rutas(orig, p):
        fallos.append("devolver_rutas fallo")
    elif "Q:\\viejo" not in ruta_puesta(p):
        fallos.append("devolver_rutas no repuso la ruta: %r" % ruta_puesta(p))

    # 7. a_windows con y sin unidad
    if a_windows("/j/x/y.iso", "/j/x", "D", "/j/x") != "D:\\y.iso":
        fallos.append("a_windows con unidad: %r"
                      % a_windows("/j/x/y.iso", "/j/x", "D", "/j/x"))
    if a_windows("/j/x/y.iso", "/j/x") != "Z:\\j\\x\\y.iso":
        fallos.append("a_windows sin unidad: %r" % a_windows("/j/x/y.iso", "/j/x"))
    if a_windows("/j/x", "/j/x", "D", "/j/x") != "D:\\":
        fallos.append("a_windows sobre la propia raiz")

    # 8. FALTA: el fichero no esta en ningun sitio.
    d, p = juego("falta", ["otro.txt"],
                 "<X><GamePath>D:\\no_existe.iso</GamePath></X>")
    s = arreglar_rutas(d, "D", d)
    if not any(x.startswith("FALTA|") for x in s):
        fallos.append("no se avisa de un fichero que falta: %s" % s)

    # 9. UserProfiles NO entra en el indice: un XML no es el juego.
    d, p = juego("indice", ["roms/a.iso"], "<X><GamePath></GamePath></X>")
    exacto, _laxo_i, _ = indexar(d)
    if any("UserProfiles" in v for v in exacto.values()):
        fallos.append("el indice incluye UserProfiles")

    # 10. El indice tiene que ser ESTABLE y quedarse con el menos hondo.
    d = os.path.join(raiz_tmp, "hondo")
    for f in ("juego.exe", "a/b/c/juego.exe", "z/juego.exe"):
        pp = os.path.join(d, f)
        os.makedirs(os.path.dirname(pp), exist_ok=True)
        open(pp, "w").write("x")
    e1, _l1, _ = indexar(d)
    e2, _l2, _ = indexar(d)
    if e1 != e2:
        fallos.append("el indice no es estable entre pasadas")
    if os.path.dirname(e1["juego.exe"]).rstrip(os.sep) != d.rstrip(os.sep):
        fallos.append("el indice no se queda con el menos hondo: %r"
                      % e1["juego.exe"])

    shutil.rmtree(raiz_tmp, ignore_errors=True)
    return fallos


# ----------------------------------------------------------------------------
# LINEA DE ORDENES
# ----------------------------------------------------------------------------

def main(argv):
    if len(argv) < 2:
        sys.stderr.write(
            "uso: teknoparrot.py <orden> [...]\n"
            "  rutas    <raiz> [letra] [base]   arregla los perfiles; sucesos por stdout\n"
            "  devolver <original> <perfil>     repone las rutas del original\n"
            "  comprobar                        auto-diagnostico\n")
        return 2
    orden = argv[1]

    if orden == "comprobar":
        fallos = comprobar()
        if fallos:
            sys.stderr.write("teknoparrot.py: %d fallo(s)\n" % len(fallos))
            for f in fallos:
                sys.stderr.write("  - %s\n" % f)
            return 1
        print("teknoparrot.py: todo correcto")
        return 0

    if orden == "rutas":
        if len(argv) < 3:
            return 2
        for s in arreglar_rutas(argv[2],
                                argv[3] if len(argv) > 3 else "",
                                argv[4] if len(argv) > 4 else ""):
            print(s)
        return 0

    if orden == "devolver":
        if len(argv) < 4:
            return 2
        return 0 if devolver_rutas(argv[2], argv[3]) else 1

    sys.stderr.write("teknoparrot.py: orden desconocida %r\n" % orden)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
