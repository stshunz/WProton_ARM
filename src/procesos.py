# -*- coding: utf-8 -*-
# WProton - arbol de procesos
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
#   el heredoc PYDESC de descendientes_nuestros()
#
# PARA QUE SIRVE
#
# Al cerrar un juego hay que saber que procesos siguen vivos por debajo de
# WProton: el juego puede dejar hijos sueltos -lanzadores, servicios del DRM,
# procesos de Wine- y desmontar el squashfs con alguno todavia abierto deja el
# punto de montaje ocupado.
#
# SE LEE /proc, YA NO SE LLAMA A "ps"
# -----------------------------------
# La version anterior lanzaba "ps -eo pid=,ppid=,comm=" y parseaba su salida.
# Ese "-eo" con "=" para quitar cabeceras es sintaxis de procps; el ps de
# busybox no la lleva igual. No he podido comprobar que hace el de Batocera,
# asi que NO digo que alli fallara; lo que si es seguro es que leyendo /proc
# la pregunta desaparece, y ademas se ahorra lanzar un proceso justo cuando se
# esta intentando ver cuales quedan vivos.
#
# EL NOMBRE SE SACA CON CUIDADO. En /proc/<pid>/stat el nombre va entre
# parentesis y PUEDE LLEVAR PARENTESIS DENTRO: hay juegos cuyo ejecutable se
# llama "Game (2011)". Partir por el primer ")" daria un ppid equivocado, y
# entonces el proceso parece colgar de otro sitio y no se espera. Por eso se
# busca el ULTIMO ")".
# ----------------------------------------------------------------------------

import os
import sys

VERSION = "1"

# Procesos que lanzamos NOSOTROS para diagnosticar: esperarlos seria
# esperarnos a nosotros mismos.
NUESTROS = ("sh", "dash", "sleep", "ps", "awk", "grep")

# Tope de saltos al subir por el arbol. Con un ciclo en los ppid -no deberia
# pasar, pero un proceso reasignado a init durante la lectura lo puede
# simular- esto evita quedarse dando vueltas.
MAX_SALTOS = 40


def _leer_stat(pid):
    """(ppid, nombre) de un proceso, o None si ya no esta."""
    try:
        with open("/proc/%d/stat" % pid, encoding="utf-8", errors="replace") as fh:
            linea = fh.read()
    except (OSError, ValueError):
        return None
    # El nombre va entre el primer "(" y el ULTIMO ")": puede llevar
    # parentesis dentro.
    ini = linea.find("(")
    fin = linea.rfind(")")
    if ini < 0 or fin < ini:
        return None
    nombre = linea[ini + 1:fin]
    resto = linea[fin + 2:].split()
    if len(resto) < 2:
        return None
    try:
        ppid = int(resto[1])
    except ValueError:
        return None
    return ppid, nombre


def tabla():
    """{pid: (ppid, nombre)} de todo lo que hay ahora mismo."""
    salida = {}
    try:
        entradas = os.listdir("/proc")
    except OSError:
        return salida
    for e in entradas:
        if not e.isdigit():
            continue
        pid = int(e)
        datos = _leer_stat(pid)
        if datos:
            salida[pid] = datos
    return salida


def descendientes(raiz, procesos=None, yo=None):
    """Los procesos que cuelgan de 'raiz'. Lista de (pid, nombre), ordenada.

    No se incluye ni la propia raiz ni el proceso que pregunta.
    """
    procesos = tabla() if procesos is None else procesos
    yo = os.getpid() if yo is None else yo
    salida = []
    for pid, (_ppid, nombre) in procesos.items():
        if pid in (raiz, yo):
            continue
        # Un hilo del nucleo no es un proceso que podamos esperar.
        if nombre.startswith("["):
            continue
        if nombre in NUESTROS:
            continue
        actual, saltos = pid, 0
        while actual > 1 and saltos < MAX_SALTOS:
            siguiente = procesos.get(actual, (0, ""))[0]
            if siguiente == actual:      # se apunta a si mismo: ciclo
                break
            actual = siguiente
            saltos += 1
            if actual == raiz:
                salida.append((pid, nombre))
                break
    salida.sort()
    return salida


# ----------------------------------------------------------------------------
# COMPROBACION INTERNA
#
# El arbol se pasa como argumento para poder probar formas que en una maquina
# de verdad no se pueden montar a voluntad.
# ----------------------------------------------------------------------------

def comprobar():
    fallos = []

    def esperar(que, visto, esperado):
        if visto != esperado:
            fallos.append("%s: salio %r y se esperaba %r" % (que, visto, esperado))

    # 100 es la raiz; 200 y 201 cuelgan de el, 300 no.
    arbol = {
        100: (1, "wproton"),
        200: (100, "juego.exe"),
        201: (200, "hijo.exe"),
        300: (1, "otracosa"),
        400: (100, "sleep"),          # lo lanzamos nosotros
        500: (100, "[kworker]"),      # hilo del nucleo
        600: (100, "yo-mismo"),
    }
    esperar("arbol basico", descendientes(100, arbol, yo=600),
            [(200, "juego.exe"), (201, "hijo.exe")])
    esperar("nada cuelga de 300", descendientes(300, arbol, yo=600), [])

    # Un ciclo en los ppid no debe colgar la lectura.
    ciclo = {10: (11, "a"), 11: (10, "b"), 12: (1, "c"), 100: (1, "raiz")}
    descendientes(100, ciclo, yo=1)      # basta con que termine

    # Un proceso que se apunta a si mismo tampoco.
    descendientes(100, {7: (7, "raro"), 100: (1, "raiz")}, yo=1)

    # El nombre con parentesis dentro: lo que rompe partir por el primer ")".
    linea = "4242 (Game (2011).exe) S 100 4242 4242 0 -1 4194304 1 2 3\n"
    ini, fin = linea.find("("), linea.rfind(")")
    nombre = linea[ini + 1:fin]
    ppid = int(linea[fin + 2:].split()[1])
    esperar("nombre con parentesis", nombre, "Game (2011).exe")
    esperar("ppid con parentesis en el nombre", ppid, 100)

    # Sobre la maquina de verdad: el proceso actual tiene que salir en la
    # tabla, y su padre tiene que estar bien.
    t = tabla()
    yo = os.getpid()
    if yo not in t:
        fallos.append("el proceso actual no aparece en la tabla de /proc")
    elif t[yo][0] != os.getppid():
        fallos.append("el ppid leido de /proc no coincide: %r vs %r"
                      % (t[yo][0], os.getppid()))
    if len(t) < 2:
        fallos.append("la tabla de /proc sale casi vacia (%d procesos)" % len(t))

    return fallos


# ----------------------------------------------------------------------------
# LINEA DE ORDENES
# ----------------------------------------------------------------------------

def main(argv):
    if len(argv) < 2:
        sys.stderr.write(
            "uso: procesos.py <orden> [...]\n"
            "  hijos <pid>    los procesos que cuelgan de ese: \"pid nombre\"\n"
            "  comprobar      auto-diagnostico\n")
        return 2
    orden = argv[1]

    if orden == "comprobar":
        fallos = comprobar()
        if fallos:
            sys.stderr.write("procesos.py: %d fallo(s)\n" % len(fallos))
            for f in fallos:
                sys.stderr.write("  - %s\n" % f)
            return 1
        print("procesos.py: todo correcto")
        return 0

    if orden == "hijos":
        if len(argv) < 3:
            return 2
        try:
            raiz = int(argv[2])
        except ValueError:
            sys.stderr.write("procesos.py: %r no es un pid\n" % argv[2])
            return 2
        for pid, nombre in descendientes(raiz):
            print("%d %s" % (pid, nombre))
        return 0

    sys.stderr.write("procesos.py: orden desconocida %r\n" % orden)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
