# -*- coding: utf-8 -*-
# WProton - formato de los ficheros .keys (mapeo de mando a teclado)
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
#   keys_texto_hay() / keys_teclado_hay()   -> buscar_accion()
#   keys_texto_poner() / keys_teclado_poner()-> poner_accion()
#   keys_raton_leer() / keys_raton_poner()  -> raton_leer() / raton_poner()
#   keys_sustituye_al_mando()               -> sustituye_al_mando()
#   keys_ejemplo_crear()                    -> ejemplo()
#   el heredoc PYESC de keys_editor()       -> componer()
#
# ESTO YA ERA PYTHON
# ------------------
# Las siete funciones de arriba estaban escritas en Python, pero DENTRO de
# comillas simples de bash: "$PY_BIN" -c 'import json,sys ...'. Son 8 de los
# 16 bloques incrustados que hay en el script. Metido ahi, ese codigo:
#
#   - no lo mira ningun linter ni el py_compile del build;
#   - no se puede probar sin montar el script entero;
#   - no puede llevar una comilla simple, que en bash cierra el literal;
#   - y se repite: "leer el .keys tolerando que este roto" estaba escrito seis
#     veces, con seis capturas de excepciones distintas.
#
# Sacarlo a un fichero no es cambiar de lenguaje: es dejar de esconderlo.
#
# TRES FALLOS QUE SE ARREGLAN
# ---------------------------
#
# 1. UN .keys CON ALGO QUE NO SEA UN OBJETO ROMPIA EL GUARDADO.
#
#    El heredoc de keys_editor hacia a.get('trigger') sobre cada elemento de
#    actions_player1, y capturaba (OSError, ValueError, IndexError). Si un
#    elemento era una cadena -un .keys escrito a mano, o de otra herramienta-
#    salta AttributeError, que NO esta en esa lista: el guardado moria y el
#    usuario perdia toda la sesion de edicion. Aqui todo lo que no sea un
#    objeto se ignora y se sigue.
#
# 2. UN "trigger" QUE FUERA CADENA SE ENSEÑABA LETRA A LETRA.
#
#    keys_texto_hay hacia "+".join(a.get("trigger") or []). Con un trigger en
#    lista eso da "hotkey+y", que es lo que se queria; con un trigger que sea
#    una sola cadena, join recorre sus LETRAS y al usuario le aparecia
#    "h+o+t+k+e+y". Los .keys de Batocera usan las dos formas.
#
# 3. EL .keys SE ESCRIBIA TRUNCANDO EL ORIGINAL.
#
#    json.dump(d, open(f,"w")) abre en modo escritura -o sea, vacia el
#    fichero- y va escribiendo. Si algo falla a mitad, el .keys se queda
#    cortado y ya no es JSON valido: el mapeador no lo carga y el mando deja
#    de responder en ese juego. Aqui se escribe en un temporal de la misma
#    carpeta y se mueve encima, que es atomico.
#
# LO QUE NO CAMBIA
# ----------------
# El formato del fichero es el mismo y el mapeador no se toca. Un .keys escrito
# por este modulo lo lee el mapeador de siempre, y al reves.
# ----------------------------------------------------------------------------

import json
import os
import sys
import tempfile

VERSION = "1"

# La salida de emergencia. Va siempre la primera y no se duplica.
FIJA = {"trigger": ["hotkey", "start"], "type": "key",
        "target": ["KEY_LEFTALT", "KEY_F4"]}

# Valores de partida de la seccion "mouse", los mismos que tenia keys_raton_poner.
RATON_DEFECTO = {"axis": "joystick2", "click_left": "r2", "speed": 900}

EJEMPLO = {
    "_comentario": "Ejemplo de WProton. Copialo junto a un juego como <juego>.wsquashfs.keys",
    "_aviso": "Solo COMBINACIONES: si mapeas botones sueltos, el juego recibira la pulsacion del mando Y la tecla.",
    "actions_player1": [
        {"trigger": ["hotkey", "y"], "target": ["KEY_LEFTALT", "KEY_TAB"]},
        {"trigger": ["l3", "r3"], "target": ["KEY_LEFTALT", "KEY_F4"]},
    ],
}


# ----------------------------------------------------------------------------
# LECTURA Y ESCRITURA
# ----------------------------------------------------------------------------

def leer(ruta):
    """El contenido de un .keys. Devuelve {} si no se puede leer.

    UN .keys ROTO NUNCA DEBE PARAR NADA. Puede venir de Batocera, de otra
    herramienta o de un editor de texto; si no se entiende se trata como
    vacio y el juego arranca igual, sin mapeo, que es mucho mejor que no
    arrancar.
    """
    try:
        with open(ruta, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def acciones(datos):
    """La lista actions_player1, quedandose SOLO con los objetos.

    Aqui es donde se filtra lo que hacia saltar AttributeError al guardar: un
    elemento que no sea un objeto no se puede consultar, asi que se ignora.
    """
    lista = datos.get("actions_player1") if isinstance(datos, dict) else None
    if not isinstance(lista, list):
        return []
    return [a for a in lista if isinstance(a, dict)]


def guardar(ruta, datos, sangrado=None):
    """Escribe un .keys de forma atomica: temporal al lado y os.replace encima.

    Si algo falla -disco lleno, se apaga la Deck- el fichero de antes sigue
    entero. Con json.dump(d, open(f,"w")) se quedaba cortado y el mapeador ya
    no lo cargaba: el mando dejaba de responder en ese juego.
    """
    carpeta = os.path.dirname(os.path.abspath(ruta)) or "."
    tmp = None
    try:
        os.makedirs(carpeta, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=carpeta, prefix=".keys-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=sangrado)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, ruta)
        tmp = None
        return True
    except (OSError, TypeError, ValueError) as e:
        sys.stderr.write("teclas: no se pudo guardar %s: %s\n" % (ruta, e))
        return False
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


# ----------------------------------------------------------------------------
# COMBINACIONES CON DESTINO ESPECIAL (texto rapido, teclado en pantalla)
# ----------------------------------------------------------------------------

def etiqueta_trigger(trigger):
    """El disparo, tal como se le enseña al usuario: "hotkey+y".

    ACEPTA LAS DOS FORMAS. En un .keys el trigger puede ser una lista
    (["hotkey","y"]) o una sola cadena ("hotkey"), y Batocera usa ambas. El
    codigo de antes hacia "+".join(trigger) sin mirar: con una cadena, join
    recorre sus LETRAS y al usuario le salia "h+o+t+k+e+y".
    """
    if isinstance(trigger, str):
        return trigger or "?"
    if isinstance(trigger, (list, tuple)):
        partes = [str(t) for t in trigger if t not in (None, "")]
        return "+".join(partes) if partes else "?"
    return "?"


def buscar_accion(ruta, destino):
    """El disparo asignado a ese destino especial, o "" si no hay ninguno."""
    for a in acciones(leer(ruta)):
        if a.get("target") == destino:
            return etiqueta_trigger(a.get("trigger"))
    return ""


def poner_accion(ruta, destino, trigger):
    """Pone o quita la accion de ese destino.

    'trigger' es el JSON del disparo (["hotkey","y"]); vacio la quita. Las
    demas acciones se conservan intactas.
    """
    datos = leer(ruta)
    if not datos:
        datos = {"actions_player1": []}
    lista = [a for a in acciones(datos) if a.get("target") != destino]
    if trigger:
        try:
            t = json.loads(trigger) if isinstance(trigger, str) else trigger
        except ValueError:
            sys.stderr.write("teclas: disparo mal formado: %r\n" % (trigger,))
            return False
        lista.append({"trigger": t, "type": "key", "target": destino})
    datos["actions_player1"] = lista
    return guardar(ruta, datos)


# ----------------------------------------------------------------------------
# RATON
# ----------------------------------------------------------------------------

def raton_leer(ruta, campo):
    """Un campo de la seccion del raton, como texto. "" si no esta."""
    d = leer(ruta)
    v = d.get(campo, "") if isinstance(d, dict) else ""
    return "" if v is None else str(v)


def raton_poner(ruta, campo, valor):
    """Cambia UN campo del raton, dejando los demas.

    Los numeros se guardan como numero. SE ADMITE EL SIGNO MENOS: antes se
    usaba v.isdigit(), que dice que no a "-5", asi que un valor negativo se
    guardaba como texto y el mapeador se encontraba una cadena donde esperaba
    un numero.
    """
    d = leer(ruta)
    if not d:
        d = dict(RATON_DEFECTO)
    texto = str(valor)
    try:
        d[campo] = int(texto)
    except ValueError:
        d[campo] = texto
    return guardar(ruta, d)


# ----------------------------------------------------------------------------
# ¿ESTE .keys SUSTITUYE AL MANDO?
# ----------------------------------------------------------------------------

_MOV = ("l2", "r2")


def sustituye_al_mando(ruta):
    """True si el .keys mapea el movimiento, o sea si el juego va por teclado.

    LA CRUCETA SOLA NO CUENTA. Hay .keys que mapean SOLO la cruceta para
    AÑADIRLA a un juego que ya funciona con el stick; capturar el mando ahi es
    lo contrario de lo que se quiere, porque le quita el stick, que era lo
    unico que le iba.

    EL RATON TAMPOCO. Un stick puesto como raton no sustituye al mando: es lo
    que hace falta para los menus de algunos juegos. Contarlo como movimiento
    -por empezar por "joystick"- capturaba el mando y dejaba al juego sin el.

    Sustituir al mando es mapear los STICKS o los gatillos: ahi el juego esta
    pensado para el teclado.
    """
    for a in acciones(leer(ruta)):
        t = a.get("trigger")
        if isinstance(t, list):          # las combinaciones no cuentan
            continue
        if str(a.get("type", "")).lower() == "mouse":
            continue
        t = str(t or "")
        if t.startswith("joystick") or t in _MOV:
            return True
    return False


# ----------------------------------------------------------------------------
# COMPOSICION DEL .keys FINAL (lo que hacia el heredoc PYESC)
# ----------------------------------------------------------------------------

def componer(destino, fichero_teclas, fichero_combos="", fichero_raton=""):
    """Arma el .keys final a partir de los tres temporales del editor.

    - fichero_teclas: lineas "disparo|tecla", una por asignacion simple
    - fichero_combos: un .keys con las combinaciones y teclas compuestas, que
      el editor no toca y devuelve tal cual
    - fichero_raton:  el JSON de la seccion "mouse", si se pidio

    La salida de emergencia (hotkey+start -> Alt+F4) va siempre la primera y
    no se duplica.
    """
    lista = [dict(FIJA)]

    if fichero_combos:
        for a in acciones(leer(fichero_combos)):
            if a.get("trigger") != FIJA["trigger"]:
                lista.append(a)

    if fichero_teclas:
        try:
            with open(fichero_teclas, encoding="utf-8") as fh:
                for linea in fh:
                    linea = linea.strip()
                    if not linea or "|" not in linea:
                        continue
                    disparo, tecla = linea.split("|", 1)
                    lista.append({"trigger": disparo, "type": "key",
                                  "target": tecla})
        except OSError:
            pass

    salida = {"actions_player1": lista}

    if fichero_raton:
        try:
            with open(fichero_raton, encoding="utf-8") as fh:
                texto = fh.read().strip()
            if texto:
                salida["mouse"] = json.loads(texto)
        except (OSError, ValueError):
            pass

    return guardar(destino, salida, sangrado=2)


def contar_combos(ruta):
    """Cuantas combinaciones lleva dentro un temporal.

    El temporal arranca con {"actions_player1": []}, asi que NUNCA esta vacio
    como fichero: hay que contar lo que lleva dentro o el editor rechaza el
    guardado por "no has asignado ninguna tecla" y se pierde el trabajo.
    """
    return len(acciones(leer(ruta)))


# ----------------------------------------------------------------------------
# NOMBRES LEGIBLES Y RESUMEN (lo que hacia el heredoc PYKEYS de keys_resumen)
# ----------------------------------------------------------------------------

BOTONES = {
    "a": "A", "b": "B", "x": "X", "y": "Y",
    "up": "Cruceta arriba", "down": "Cruceta abajo",
    "left": "Cruceta izq.", "right": "Cruceta der.",
    "pageup": "L1", "pagedown": "R1", "l1": "L1", "r1": "R1",
    "l2": "L2", "r2": "R2", "l3": "L3", "r3": "R3",
    "start": "Start", "select": "Select", "hotkey": "Hotkey",
    "joystick1up": "Stick izq. arriba", "joystick1down": "Stick izq. abajo",
    "joystick1left": "Stick izq. izq.", "joystick1right": "Stick izq. der.",
    "joystick2up": "Stick der. arriba", "joystick2down": "Stick der. abajo",
    "joystick2left": "Stick der. izq.", "joystick2right": "Stick der. der.",
}

TECLAS = {
    "LEFTALT": "Alt", "RIGHTALT": "AltGr",
    "LEFTCTRL": "Ctrl", "RIGHTCTRL": "Ctrl der.",
    "LEFTSHIFT": "Mayus", "RIGHTSHIFT": "Mayus der.",
    "LEFTMETA": "Windows", "ENTER": "Enter", "KPENTER": "Enter (num)",
    "SPACE": "Espacio", "ESC": "Escape", "TAB": "Tabulador",
    "BACKSPACE": "Retroceso", "DELETE": "Supr", "INSERT": "Insert",
    "HOME": "Inicio", "END": "Fin", "PAGEUP": "Av.Pag", "PAGEDOWN": "Re.Pag",
    "UP": "Flecha arriba", "DOWN": "Flecha abajo",
    "LEFT": "Flecha izq.", "RIGHT": "Flecha der.",
}

_RATON_BTN = {"BTN_LEFT": "clic izquierdo", "BTN_RIGHT": "clic derecho",
              "BTN_MIDDLE": "clic central"}

# Los botones de la cara del mando. Si un .keys los usa, el estilo (Xbox o
# Batocera) cambia que tecla sale al pulsar, y hay que preguntarlo.
CARA = ("a", "b", "x", "y")


def _lista(v):
    """El campo puede venir como texto suelto o como lista."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return [str(v)]


def nombre_boton(n):
    return BOTONES.get(str(n).lower(), str(n))


def nombre_tecla(n):
    n = str(n)
    if n == "TECLADO_VIRTUAL":
        return "abrir el teclado en pantalla"
    if n == "ESCRIBIR_TEXTO":
        return "escribir el texto guardado"
    if n in _RATON_BTN:
        return _RATON_BTN[n]
    corto = n[4:] if n.startswith("KEY_") else n
    if corto in TECLAS:
        return TECLAS[corto]
    if len(corto) == 1:
        return corto
    if corto.startswith("F") and corto[1:].isdigit():
        return corto
    return corto.capitalize() if corto.isalpha() else n


def usa_botones_cara(ruta):
    """True si el .keys mapea A, B, X o Y.

    Con esos botones el estilo (Xbox o Batocera) cambia que tecla sale al
    pulsar, asi que hay que preguntarle al usuario cual quiere. Si el fichero
    no se puede leer se devuelve True: mejor preguntar de mas que aplicar un
    estilo que no toca.
    """
    datos = leer(ruta)
    if not datos:
        return True                      # ilegible: mejor preguntar
    for a in acciones(datos):
        for t in _lista(a.get("trigger")):
            if str(t or "").lower() in CARA:
                return True
    return False


def resumen(ruta):
    """Las filas legibles del .keys. Devuelve (filas, roto).

    'roto' distingue un fichero ILEGIBLE de uno vacio: no es lo mismo, y
    confundirlos haria creer al usuario que no tiene nada asignado cuando en
    realidad lo esta perdiendo.
    """
    try:
        with open(ruta, encoding="utf-8") as fh:
            datos = json.load(fh)
        if not isinstance(datos, dict):
            raise ValueError("no es un objeto")
    except (OSError, ValueError):
        return [], True

    filas = []
    raton = datos.get("mouse") or {}
    if isinstance(raton, dict) and raton:
        ejes = {"joystick1": "Stick izquierdo", "joystick2": "Stick derecho"}
        eje = raton.get("axis", "joystick2")
        filas.append("%-26s ->  %s" % (ejes.get(eje, eje),
                     "mover el raton (velocidad %s)" % raton.get("speed", 900)))
        filas.append("%-26s ->  %s" % (nombre_boton(raton.get("click_left", "r2")),
                                       "clic del raton"))

    # LAS ACCIONES INCOMPLETAS SE ENSEÑAN, no se saltan en silencio.
    #
    # Un .keys real traia una accion sin "target". El visor la ignoraba sin
    # decir nada, asi que el fichero parecia correcto... y el mapeador moria
    # al arrancar, dejando el juego sin NINGUN boton. Verlo aqui ahorra el
    # viaje de lanzar el juego para descubrirlo.
    lista = datos.get("actions_player1")
    for a in (lista if isinstance(lista, list) else []):
        if not isinstance(a, dict):
            continue
        origen = " + ".join(nombre_boton(x) for x in _lista(a.get("trigger")))
        destino = " + ".join(nombre_tecla(x) for x in _lista(a.get("target")))
        if origen and destino:
            filas.append("%-26s ->  %s" % (origen, destino))
        elif str(a.get("type", "")).lower() == "mouse":
            # El raton no lleva "target": el destino va implicito en el tipo.
            filas.append("%-26s ->  %s" % (origen or "(sin boton)",
                                           "mover el raton"))
        else:
            filas.append("%-26s ->  %s" % (origen or "(sin boton)",
                                           "(SIN TECLA: linea incompleta)"))
    return filas, False


def descomponer(ruta, fichero_teclas, fichero_combos, fichero_raton):
    """Parte un .keys en los tres temporales que edita keys_editor.

    - fichero_teclas: lineas "disparo|tecla" de las asignaciones simples
    - fichero_combos: las combinaciones y teclas compuestas, TAL CUAL
    - fichero_raton:  la seccion "mouse", si la hay

    Lo que no se puede editar en la lista SE CONSERVA: antes se perdia sin
    avisar en cuanto se tocaba cualquier otra asignacion.
    """
    def uno(v):
        if isinstance(v, str):
            return v
        if isinstance(v, (list, tuple)) and len(v) == 1 and isinstance(v[0], str):
            return v[0]
        return None

    datos = leer(ruta)
    if not datos:
        return False

    raton = datos.get("mouse") or {}
    if isinstance(raton, dict) and raton and fichero_raton:
        guardar(fichero_raton, raton)

    editables, conservar = [], []
    for a in acciones(datos):
        disparo, tecla = uno(a.get("trigger")), uno(a.get("target"))
        if disparo is not None and tecla is not None:
            editables.append("%s|%s" % (disparo, tecla))
        else:
            conservar.append(a)

    try:
        with open(fichero_teclas, "w", encoding="utf-8") as fh:
            fh.write("\n".join(editables) + ("\n" if editables else ""))
    except OSError as e:
        sys.stderr.write("teclas: no se pudo escribir %s: %s\n" % (fichero_teclas, e))
        return False
    return guardar(fichero_combos, {"actions_player1": conservar}, sangrado=2)


# ----------------------------------------------------------------------------
# COMPROBACION INTERNA
# ----------------------------------------------------------------------------

def comprobar():
    import contextlib
    import io
    import shutil
    fallos = []
    raiz = tempfile.mkdtemp(prefix="wp-teclas-")

    def esperar(que, visto, esperado):
        if visto != esperado:
            fallos.append("%s: salio %r y se esperaba %r" % (que, visto, esperado))

    def escribir(nombre, texto):
        p = os.path.join(raiz, nombre)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(texto)
        return p

    # FALLO 1: un elemento que no es objeto no puede romper nada
    malo = escribir("malo.keys",
                    '{"actions_player1":["basura",{"trigger":["l3","r3"],"target":["KEY_LEFTALT"]}]}')
    esperar("se ignora la basura", len(acciones(leer(malo))), 1)
    dest = os.path.join(raiz, "salida.keys")
    if not componer(dest, "", malo, ""):
        fallos.append("componer muere con un .keys que trae basura")
    else:
        esperar("componer conserva la buena", len(acciones(leer(dest))), 2)

    # FALLO 2: un trigger que es cadena no se enseña letra a letra
    uno = escribir("uno.keys",
                   '{"actions_player1":[{"trigger":"hotkey","target":"ESCRIBIR_TEXTO"}]}')
    esperar("trigger cadena", buscar_accion(uno, "ESCRIBIR_TEXTO"), "hotkey")
    dos = escribir("dos.keys",
                   '{"actions_player1":[{"trigger":["hotkey","y"],"target":"ESCRIBIR_TEXTO"}]}')
    esperar("trigger lista", buscar_accion(dos, "ESCRIBIR_TEXTO"), "hotkey+y")
    esperar("trigger vacio", etiqueta_trigger([]), "?")
    esperar("sin la accion", buscar_accion(dos, "TECLADO_VIRTUAL"), "")

    # FALLO 3: el guardado no deja el fichero a medias
    v = escribir("vivo.keys", '{"actions_player1":[],"mouse":{"speed":900}}')
    antes = open(v, encoding="utf-8").read()
    # Estos dos fallan A PROPOSITO. Se silencia su queja para que la salida
    # del diagnostico no parezca que algo va mal cuando va bien.
    with contextlib.redirect_stderr(io.StringIO()):
        fallo_esperado = guardar(v, {"no": set()})   # un set no es JSON
    if fallo_esperado:
        fallos.append("guardar acepta algo que no es JSON")
    if open(v, encoding="utf-8").read() != antes:
        fallos.append("un guardado fallido se lleva por delante el fichero")

    # poner y quitar conservan lo demas
    p = escribir("p.keys",
                 '{"actions_player1":[{"trigger":["a"],"target":"OTRA"}],"mouse":{"speed":1}}')
    poner_accion(p, "TECLADO_VIRTUAL", '["hotkey","x"]')
    esperar("poner", buscar_accion(p, "TECLADO_VIRTUAL"), "hotkey+x")
    esperar("conserva las demas", len(acciones(leer(p))), 2)
    esperar("conserva mouse", leer(p).get("mouse"), {"speed": 1})
    poner_accion(p, "TECLADO_VIRTUAL", "")
    esperar("quitar", buscar_accion(p, "TECLADO_VIRTUAL"), "")
    esperar("sigue la otra", len(acciones(leer(p))), 1)
    with contextlib.redirect_stderr(io.StringIO()):
        fallo_esperado = poner_accion(p, "X", "esto no es json")
    if fallo_esperado:
        fallos.append("poner_accion acepta un disparo mal formado")

    # raton
    r = os.path.join(raiz, "r.keys")
    raton_poner(r, "speed", "1200")
    esperar("raton numero", leer(r).get("speed"), 1200)
    raton_poner(r, "axis", "joystick1")
    esperar("raton texto", leer(r).get("axis"), "joystick1")
    esperar("raton conserva", leer(r).get("speed"), 1200)
    raton_poner(r, "ajuste", "-5")
    esperar("raton negativo es numero", leer(r).get("ajuste"), -5)
    esperar("raton_leer", raton_leer(r, "speed"), "1200")
    esperar("raton_leer ausente", raton_leer(r, "nada"), "")

    # sustituye_al_mando
    casos = [
        ('{"actions_player1":[{"trigger":"joystick1up","target":"KEY_W"}]}', True),
        ('{"actions_player1":[{"trigger":"up","target":"KEY_W"}]}', False),
        ('{"actions_player1":[{"trigger":"joystick2","type":"mouse","target":"x"}]}', False),
        ('{"actions_player1":[{"trigger":["l3","r3"],"target":"x"}]}', False),
        ('{"actions_player1":[{"trigger":"r2","target":"KEY_SPACE"}]}', True),
        ('{"actions_player1":["basura"]}', False),
    ]
    for i, (texto, esp) in enumerate(casos):
        f = escribir("s%d.keys" % i, texto)
        if sustituye_al_mando(f) != esp:
            fallos.append("sustituye_al_mando caso %d: %r" % (i, texto))
    if sustituye_al_mando(os.path.join(raiz, "no-existe")):
        fallos.append("sustituye_al_mando dice que si con un fichero que no esta")

    # componer con los tres temporales
    tteclas = escribir("t.txt", "a|KEY_A\nb|KEY_B\nlinea mala\n\n")
    traton = escribir("m.json", '{"axis":"joystick2","speed":900}')
    d2 = os.path.join(raiz, "final.keys")
    if not componer(d2, tteclas, malo, traton):
        fallos.append("componer fallo con los tres temporales")
    else:
        got = leer(d2)
        esperar("componer: la fija va primera",
                acciones(got)[0].get("trigger"), FIJA["trigger"])
        esperar("componer: total", len(acciones(got)), 4)   # fija + 1 combo + 2 teclas
        esperar("componer: mouse", got.get("mouse"), {"axis": "joystick2", "speed": 900})
    # la fija no se duplica
    solofija = escribir("f.keys", json.dumps({"actions_player1": [FIJA]}))
    d3 = os.path.join(raiz, "f2.keys")
    componer(d3, "", solofija, "")
    esperar("la fija no se duplica", len(acciones(leer(d3))), 1)

    # nombres legibles
    esperar("boton", nombre_boton("pagedown"), "R1")
    esperar("boton L1", nombre_boton("pageup"), "L1")
    esperar("boton raro", nombre_boton("zzz"), "zzz")
    esperar("tecla", nombre_tecla("KEY_LEFTALT"), "Alt")
    esperar("tecla letra", nombre_tecla("KEY_A"), "A")
    esperar("tecla F", nombre_tecla("KEY_F4"), "F4")
    esperar("tecla especial", nombre_tecla("TECLADO_VIRTUAL"),
            "abrir el teclado en pantalla")
    esperar("boton de raton", nombre_tecla("BTN_LEFT"), "clic izquierdo")

    # usa_botones_cara
    ca = escribir("ca.keys", '{"actions_player1":[{"trigger":"a","target":"KEY_Z"}]}')
    if not usa_botones_cara(ca):
        fallos.append("no detecta los botones de la cara")
    nc = escribir("nc.keys", '{"actions_player1":[{"trigger":"l3","target":"KEY_Z"}]}')
    if usa_botones_cara(nc):
        fallos.append("dice que usa botones de la cara cuando no")
    if not usa_botones_cara(os.path.join(raiz, "no-existe")):
        fallos.append("con un fichero ilegible deberia preguntar (True)")

    # resumen
    rf = escribir("res.keys", json.dumps({
        "mouse": {"axis": "joystick2", "click_left": "r2", "speed": 900},
        "actions_player1": [
            {"trigger": ["hotkey", "y"], "target": ["KEY_LEFTALT", "KEY_TAB"]},
            {"trigger": "a", "target": "KEY_SPACE"},
            {"trigger": "b"},                       # incompleta a proposito
            "basura",
        ]}))
    filas, roto = resumen(rf)
    if roto:
        fallos.append("resumen da por roto un fichero valido")
    else:
        texto = "\n".join(filas)
        if "Hotkey + Y" not in texto:
            fallos.append("resumen no traduce la combinacion: %r" % texto)
        if "Stick derecho" not in texto:
            fallos.append("resumen no describe el raton: %r" % texto)
        if "SIN TECLA" not in texto:
            fallos.append("resumen se salta la accion incompleta: %r" % texto)
    _f, roto = resumen(escribir("rot.keys", "no soy json"))
    if not roto:
        fallos.append("resumen no distingue un .keys roto de uno vacio")

    # descomponer conserva lo que no se puede editar
    dd = escribir("desc.keys", json.dumps({
        "mouse": {"speed": 700},
        "actions_player1": [
            {"trigger": "a", "target": "KEY_A"},
            {"trigger": ["l3", "r3"], "target": ["KEY_LEFTALT", "KEY_F4"]},
        ]}))
    t1 = os.path.join(raiz, "d_t.txt")
    t2 = os.path.join(raiz, "d_c.keys")
    t3 = os.path.join(raiz, "d_r.json")
    if not descomponer(dd, t1, t2, t3):
        fallos.append("descomponer fallo")
    else:
        esperar("descomponer editables",
                open(t1, encoding="utf-8").read().strip(), "a|KEY_A")
        esperar("descomponer conserva la combinacion", len(acciones(leer(t2))), 1)
        esperar("descomponer saca el raton", leer(t3).get("speed"), 700)

    esperar("contar_combos", contar_combos(malo), 1)
    esperar("contar_combos vacio", contar_combos(os.path.join(raiz, "nada")), 0)
    esperar("leer roto", leer(escribir("x.keys", "esto no es json")), {})
    esperar("leer lista", leer(escribir("y.keys", "[1,2]")), {})

    shutil.rmtree(raiz, ignore_errors=True)
    return fallos


# ----------------------------------------------------------------------------
# LINEA DE ORDENES
# ----------------------------------------------------------------------------

def main(argv):
    if len(argv) < 2:
        sys.stderr.write(
            "uso: teclas.py <orden> [...]\n"
            "  buscar   <fichero> <destino>            el disparo asignado\n"
            "  poner    <fichero> <destino> [trigger]  pone o quita (vacio quita)\n"
            "  raton-leer  <fichero> <campo>\n"
            "  raton-poner <fichero> <campo> <valor>\n"
            "  sustituye <fichero>                     rc 0 si mapea el movimiento\n"
            "  resumen  <fichero>                      las asignaciones, legibles\n"
            "  cara     <fichero>                      rc 0 si usa A/B/X/Y\n"
            "  descomponer <fichero> <teclas> <combos> <raton>\n"
            "  componer <destino> <teclas> [combos] [raton]\n"
            "  combos   <fichero>                      cuantas combinaciones lleva\n"
            "  ejemplo  <fichero>                      escribe el .keys de ejemplo\n"
            "  comprobar                               auto-diagnostico\n")
        return 2
    orden = argv[1]

    if orden == "comprobar":
        fallos = comprobar()
        if fallos:
            sys.stderr.write("teclas.py: %d fallo(s)\n" % len(fallos))
            for f in fallos:
                sys.stderr.write("  - %s\n" % f)
            return 1
        print("teclas.py: todo correcto")
        return 0

    if len(argv) < 3:
        sys.stderr.write("teclas.py %s: falta el fichero\n" % orden)
        return 2
    fichero = argv[2]

    if orden == "buscar":
        if len(argv) < 4:
            return 2
        r = buscar_accion(fichero, argv[3])
        if not r:
            return 1
        sys.stdout.write(r)
        return 0

    if orden == "poner":
        if len(argv) < 4:
            return 2
        return 0 if poner_accion(fichero, argv[3],
                                 argv[4] if len(argv) > 4 else "") else 1

    if orden == "raton-leer":
        if len(argv) < 4:
            return 2
        sys.stdout.write(raton_leer(fichero, argv[3]))
        return 0

    if orden == "raton-poner":
        if len(argv) < 5:
            return 2
        return 0 if raton_poner(fichero, argv[3], argv[4]) else 1

    if orden == "resumen":
        filas, roto = resumen(fichero)
        if roto:
            sys.stdout.write("!ROTO\n")
            return 1
        if not filas:
            return 1
        sys.stdout.write("\n".join(filas) + "\n")
        return 0

    if orden == "cara":
        return 0 if usa_botones_cara(fichero) else 1

    if orden == "descomponer":
        if len(argv) < 6:
            sys.stderr.write("teclas.py descomponer: faltan los tres temporales\n")
            return 2
        return 0 if descomponer(fichero, argv[3], argv[4], argv[5]) else 1

    if orden == "sustituye":
        return 0 if sustituye_al_mando(fichero) else 1

    if orden == "combos":
        sys.stdout.write("%d" % contar_combos(fichero))
        return 0

    if orden == "ejemplo":
        return 0 if guardar(fichero, EJEMPLO, sangrado=2) else 1

    if orden == "componer":
        if len(argv) < 4:
            sys.stderr.write("teclas.py componer: faltan <destino> <teclas>\n")
            return 2
        return 0 if componer(fichero, argv[3],
                             argv[4] if len(argv) > 4 else "",
                             argv[5] if len(argv) > 5 else "") else 1

    sys.stderr.write("teclas.py: orden desconocida %r\n" % orden)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
