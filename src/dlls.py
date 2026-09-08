# -*- coding: utf-8 -*-
# WProton - overrides de DLL de Wine (WINEDLLOVERRIDES)
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
#   dll_over_lista()      -> desglosar()
#   merge_overrides()     -> fusionar()
#   dll_informe()         -> informe()
#   (la parte de listar)  -> listar_carpeta()
#
# TRES FALLOS DE merge_overrides QUE SE ARREGLAN
# ----------------------------------------------
# merge_overrides comprobaba si el override ya estaba con una comparacion de
# SUBCADENA: case "$DLL_OVERRIDES" in *"$1"*). Eso falla de tres maneras, y
# las tres se han reproducido:
#
#   A) dgVoodoo2 y OptiScaler piden VARIAS DLL de una vez ("d3d9=n,b;ddraw=n,b").
#      Si una de ellas ya estaba, la cadena entera no casa y se añade completa:
#
#        antes: d3d9=n,b        + d3d9=n,b;ddraw=n,b
#        queda: d3d9=n,b;d3d9=n,b;ddraw=n,b
#
#   B) No se detectaban los conflictos. Con "d3d9=b" puesto a mano y OptiScaler
#      pidiendo "d3d9=n,b", quedaba "d3d9=b;d3d9=n,b": Wine se queda con la
#      ultima, asi que la eleccion del usuario se anulaba sin decir nada.
#
#   C) Una DLL cuyo nombre es subcadena de otra ya presente NO se añadia nunca:
#      con "xinput1_3=n,b" puesto, pedir "input1_3=n,b" no hacia nada, porque
#      el texto ya aparecia dentro.
#
# Aqui la comparacion es POR NOMBRE DE DLL, que es la unidad que entiende
# Wine, y los conflictos se devuelven para poder avisar de ellos.
# ----------------------------------------------------------------------------

import os
import re
import sys

VERSION = "1"

# Modos que entiende Wine: n(ative), b(uiltin), d(isabled), en el orden que se
# quiera y separados por comas. No se validan: si alguien pone algo raro es
# cosa suya y Wine ya se queja, pero no queremos perder lo que escribio.


def desglosar(cadena):
    """Desmenuza WINEDLLOVERRIDES en una lista de (nombre, modo).

    Wine deja agrupar varias en una sola asignacion ("d3d9,ddraw=n,b"), que es
    como lo dejan dgVoodoo2 y OptiScaler. Aqui se separan para poder tratarlas
    una a una; juntar() las vuelve a unir.

    Se conserva el orden de aparicion, y si una DLL sale dos veces gana la
    ULTIMA, que es con la que se queda Wine.
    """
    vistos = {}
    orden = []
    for trozo in (cadena or "").split(";"):
        trozo = trozo.replace(" ", "").replace("\t", "")
        if not trozo or "=" not in trozo:
            continue
        nombres, modo = trozo.split("=", 1)
        for n in nombres.split(","):
            if not n:
                continue
            clave = n.lower()
            if clave not in vistos:
                orden.append(clave)
            vistos[clave] = (n, modo)
    return [vistos[c] for c in orden]


def juntar(pares):
    """La cadena WINEDLLOVERRIDES a partir de una lista de (nombre, modo).

    Se escribe una entrada por DLL en vez de agrupar por modo. Es un poco mas
    larga, pero al leerla se ve de un vistazo que le toca a cada una, y sobre
    todo se puede quitar una sola sin tocar las demas.
    """
    return ";".join("%s=%s" % (n, m) for n, m in pares)


def fusionar(actual, nuevo):
    """Anade unos overrides a otros SIN duplicar. Devuelve (cadena, conflictos).

    'nuevo' manda cuando la misma DLL esta en los dos, que es lo que ya pasaba
    de hecho (Wine se queda con la ultima de la cadena). La diferencia es que
    ahora queda UNA sola entrada y el cambio se puede contar: cada conflicto
    vuelve como (nombre, modo_antiguo, modo_nuevo) para que quien llame avise.
    """
    base = desglosar(actual)
    anadir = desglosar(nuevo)
    porclave = {n.lower(): (n, m) for n, m in base}
    orden = [n.lower() for n, _ in base]
    conflictos = []
    for n, m in anadir:
        c = n.lower()
        if c in porclave:
            viejo = porclave[c][1]
            if viejo != m:
                conflictos.append((porclave[c][0], viejo, m))
            porclave[c] = (porclave[c][0], m)
        else:
            porclave[c] = (n, m)
            orden.append(c)
    return juntar([porclave[c] for c in orden]), conflictos


def quitar(cadena, nombre):
    """Quita una DLL de la cadena, dejando las demas intactas.

    Quien tenga "dxgi=n,b;mscoree=d" y quite mscoree se queda con su
    "dxgi=n,b".
    """
    objetivo = (nombre or "").lower()
    return juntar([(n, m) for n, m in desglosar(cadena)
                   if n.lower() != objetivo])


def listar_carpeta(carpeta):
    """Las DLL que hay junto al ejecutable del juego, sin extension.

    Son las candidatas de verdad: si alguien ha dejado ahi un dinput8.dll es
    porque quiere que se cargue, y sin el override Wine usa la suya y el mod
    no arranca.
    """
    try:
        ficheros = os.listdir(carpeta)
    except OSError:
        return []
    nombres = {}
    for f in ficheros:
        if not os.path.isfile(os.path.join(carpeta, f)):
            continue
        raiz, ext = os.path.splitext(f)
        if ext.lower() == ".dll" and raiz:
            nombres.setdefault(raiz.lower(), raiz)
    return [nombres[c] for c in sorted(nombres)]


# ----------------------------------------------------------------------------
# INFORME: despues de jugar, decir si cada DLL forzada se cargo DE VERDAD.
# Necesita el +loaddll de Wine (DIAG_DLL=1).
# ----------------------------------------------------------------------------

# LO QUE DECIDE ES LA ULTIMA PALABRA DE LA LINEA, no la ruta. Wine lo dice el
# solito:
#     Loaded L"C:\\Games\\Juego\\d3d9.dll"        at 7BB60000: native
#     Loaded L"C:\\windows\\system32\\dinput8.dll" at 79530000: builtin
#
# Una version anterior miraba si la ruta llevaba "system32" y daba el override
# por fallido. Estaba mal por partida doble: una DLL nativa puede vivir EN
# system32 -es donde la deja winetricks- y ademas una misma DLL se carga
# varias veces (procesos de 32 y de 64 bits).
_CARGA = re.compile(r'Loaded\s+L"([^"]*)".*?:\s*(\w+)\s*$', re.IGNORECASE)


def informe(ruta_log, cadena):
    """Lineas de texto explicando que paso con cada override.

    Devuelve una lista de cadenas, ya listas para enseñar. Sin log o sin
    overrides devuelve lista vacia.
    """
    pares = desglosar(cadena)
    if not pares:
        return []
    try:
        with open(ruta_log, encoding="utf-8", errors="replace") as fh:
            lineas = [l for l in fh if "loaddll" in l.lower() or "Loaded L\"" in l]
    except OSError:
        return []

    cargas = {}
    for l in lineas:
        m = _CARGA.search(l.strip())
        if not m:
            continue
        ruta, modo = m.group(1), m.group(2).lower()
        base = ruta.replace("\\", "/").rsplit("/", 1)[-1]
        if base.lower().endswith(".dll"):
            base = base[:-4]
        cargas.setdefault(base.lower(), []).append((ruta, modo))

    salida = []
    for nombre, _modo in pares:
        vistas = cargas.get(nombre.lower(), [])
        if not vistas:
            salida.append("  %s: no se cargo nunca (el juego no la pidio)" % nombre)
            continue
        nativas = [r for r, m in vistas if m == "native"]
        if nativas:
            salida.append("  %s: NATIVA -> el override se aplico  [%s]"
                          % (nombre, nativas[0]))
        else:
            salida.append("  %s: solo la de Wine (builtin) -> el override NO se aplico"
                          % nombre)
    return salida


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

    # desglosar deshace los grupos
    esperar("desglosar agrupado",
            desglosar("d3d9,ddraw=n,b"), [("d3d9", "n,b"), ("ddraw", "n,b")])
    esperar("desglosar con espacios",
            desglosar(" d3d9 = n,b ; dxgi=b "), [("d3d9", "n,b"), ("dxgi", "b")])
    esperar("desglosar basura", desglosar("sin_igual;;=x;"), [])
    esperar("desglosar repetida gana la ultima",
            desglosar("d3d9=b;d3d9=n,b"), [("d3d9", "n,b")])

    # LOS TRES FALLOS DE merge_overrides
    # A) un grupo cuando una de las suyas ya estaba
    r, c = fusionar("d3d9=n,b", "d3d9=n,b;ddraw=n,b")
    esperar("A: sin duplicar", r, "d3d9=n,b;ddraw=n,b")
    if c:
        fallos.append("A: no deberia haber conflicto y hay %r" % (c,))
    # B) conflicto de modo: gana el nuevo pero se avisa
    r, c = fusionar("d3d9=b", "d3d9=n,b")
    esperar("B: una sola entrada", r, "d3d9=n,b")
    if c != [("d3d9", "b", "n,b")]:
        fallos.append("B: el conflicto no se reporta: %r" % (c,))
    # C) nombre que es subcadena de otro
    r, _ = fusionar("xinput1_3=n,b", "input1_3=n,b")
    esperar("C: subcadena", r, "xinput1_3=n,b;input1_3=n,b")

    # fusionar sobre vacio y con vacio
    esperar("fusionar desde vacio", fusionar("", "d3d9=n,b")[0], "d3d9=n,b")
    esperar("fusionar nada", fusionar("d3d9=n,b", "")[0], "d3d9=n,b")

    # quitar deja lo demas
    esperar("quitar mscoree",
            quitar("dxgi=n,b;mscoree=d", "mscoree"), "dxgi=n,b")
    esperar("quitar sin distinguir mayusculas",
            quitar("DXGI=n,b;MSCOREE=d", "mscoree"), "DXGI=n,b")
    esperar("quitar lo que no esta",
            quitar("dxgi=n,b", "d3d9"), "dxgi=n,b")
    esperar("quitar de un grupo",
            quitar("d3d9,mscoree=n,b", "mscoree"), "d3d9=n,b")

    # listar_carpeta
    d = tempfile.mkdtemp(prefix="wp-dlls-")
    for f in ("dinput8.dll", "D3D9.DLL", "juego.exe", "leeme.txt"):
        with open(os.path.join(d, f), "w") as fh:
            fh.write("x")
    esperar("listar_carpeta", listar_carpeta(d), ["D3D9", "dinput8"])
    esperar("listar_carpeta inexistente", listar_carpeta(d + "/no"), [])

    # informe
    log = os.path.join(d, "log")
    with open(log, "w", encoding="utf-8") as fh:
        fh.write('trace:loaddll:Loaded L"C:\\\\Juego\\\\d3d9.dll" at 7BB60000: native\n')
        fh.write('trace:loaddll:Loaded L"C:\\\\windows\\\\system32\\\\dinput8.dll" at 79530000: builtin\n')
        fh.write('trace:loaddll:Loaded L"C:\\\\Juego\\\\d3d9.dll" at 7BB60000: native\n')
    r = informe(log, "d3d9=n,b;dinput8=n,b;ddraw=n,b")
    if len(r) != 3:
        fallos.append("informe: %d lineas en vez de 3" % len(r))
    else:
        if "NATIVA" not in r[0]:
            fallos.append("informe: no detecta la nativa: %r" % r[0])
        if "NO se aplico" not in r[1]:
            fallos.append("informe: no detecta la builtin: %r" % r[1])
        if "no se cargo nunca" not in r[2]:
            fallos.append("informe: no detecta la ausente: %r" % r[2])
    # una nativa que vive EN system32 sigue siendo nativa
    with open(log, "w", encoding="utf-8") as fh:
        fh.write('Loaded L"C:\\\\windows\\\\system32\\\\d3d9.dll" at 1: native\n')
    r = informe(log, "d3d9=n,b")
    if "NATIVA" not in r[0]:
        fallos.append("informe: una nativa en system32 se da por fallida: %r" % r[0])

    shutil.rmtree(d, ignore_errors=True)
    return fallos


# ----------------------------------------------------------------------------
# LINEA DE ORDENES
# ----------------------------------------------------------------------------

def main(argv):
    if len(argv) < 2:
        sys.stderr.write(
            "uso: dlls.py <orden> [...]\n"
            "  desglosar <cadena>            una linea por DLL\n"
            "  fusionar  <actual> <nuevo>    une sin duplicar (avisos por stderr)\n"
            "  quitar    <cadena> <nombre>   quita una DLL\n"
            "  listar    <carpeta>           las DLL junto al ejecutable\n"
            "  informe   <log> <cadena>      que paso con cada override\n"
            "  comprobar                     auto-diagnostico\n")
        return 2
    orden = argv[1]

    if orden == "comprobar":
        fallos = comprobar()
        if fallos:
            sys.stderr.write("dlls.py: %d fallo(s)\n" % len(fallos))
            for f in fallos:
                sys.stderr.write("  - %s\n" % f)
            return 1
        print("dlls.py: todo correcto")
        return 0

    if orden == "desglosar":
        for n, m in desglosar(argv[2] if len(argv) > 2 else ""):
            print("%s=%s" % (n, m))
        return 0

    if orden == "fusionar":
        if len(argv) < 4:
            sys.stderr.write("dlls.py fusionar: faltan <actual> <nuevo>\n")
            return 2
        r, c = fusionar(argv[2], argv[3])
        for nombre, viejo, nuevo in c:
            # Por stderr para que bash pueda mandarlo al registro sin que se
            # mezcle con la cadena resultante.
            sys.stderr.write("aviso: %s pasa de '%s' a '%s'\n" % (nombre, viejo, nuevo))
        sys.stdout.write(r)
        return 0

    if orden == "quitar":
        if len(argv) < 4:
            return 2
        sys.stdout.write(quitar(argv[2], argv[3]))
        return 0

    if orden == "listar":
        if len(argv) < 3:
            return 2
        for n in listar_carpeta(argv[2]):
            print(n)
        return 0

    if orden == "informe":
        if len(argv) < 4:
            return 2
        for l in informe(argv[2], argv[3]):
            print(l)
        return 0

    sys.stderr.write("dlls.py: orden desconocida %r\n" % orden)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
