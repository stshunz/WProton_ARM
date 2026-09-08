# -*- coding: utf-8 -*-
# WProton - fichas de juego (Steam, HowLongToBeat) e identificadores
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
#   el PYAPPID de steam_appid_de()  -> appid_acceso_directo()
#   el PYAPPID de ficha_appid()     -> appid_de_steam()
#   el PYHLTB  de hltb_duracion()   -> duracion()
#   el PYFICHA de ficha_campo()     -> campo()
#   urlencode_py()                  -> la orden "urlencode"
#
# Eran cuatro literales de bash sueltos que compartian la misma idea -pedir
# algo por red o leer un JSON y sacar un dato- sin compartir una linea de
# codigo. Aqui estan juntos y con pruebas.
#
# UN FALLO QUE SE ARREGLA
# -----------------------
# Los cuatro capturaban "except Exception" y salian con codigo 1 sin decir
# nada (y bash ademas les mandaba el stderr a /dev/null). Asi, "no encuentro
# el juego", "no hay internet" y "el JSON venia mal" eran EXACTAMENTE lo
# mismo desde fuera: la ficha se quedaba vacia y no habia forma de saber por
# que. Ahora cada fallo dice lo que es por stderr, que en bash va al registro.
# ----------------------------------------------------------------------------

import json
import os
import re
import sys
import urllib.parse
import urllib.request
import zlib

VERSION = "1"

TIEMPO_ESPERA = 15
AGENTE = "WProton"


def _clave(x):
    """El nombre sin lo que cambia entre bases de datos, para comparar."""
    x = (x or "").lower()
    for c in " ._-:'!,":
        x = x.replace(c, "")
    return x


# ----------------------------------------------------------------------------
# IDENTIFICADORES
# ----------------------------------------------------------------------------

def appid_acceso_directo(exe, nombre):
    """El identificador que Steam da a un acceso directo que no es suyo.

    Es el CRC32 de la ruta mas el nombre, con el bit alto puesto. Steam lo
    calcula asi y hay que dar el mismo numero o la caratula no aparece.
    """
    crc = zlib.crc32(("%s%s" % (exe, nombre)).encode("utf-8"))
    return (crc | 0x80000000) & 0xFFFFFFFF


def appid_de_steam(nombre):
    """Busca el juego en Steam. Devuelve (appid, nombre) o lanza LookupError.

    Se prefiere la coincidencia EXACTA -comparando sin espacios ni signos- y
    solo si no la hay se acepta una que empiece igual. Sin eso, buscar
    "Portal" devolvia "Portal 2".
    """
    url = ("https://steamcommunity.com/actions/SearchApps/"
           + urllib.parse.quote(nombre))
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    try:
        datos = json.load(urllib.request.urlopen(req, timeout=TIEMPO_ESPERA))
    except Exception as e:
        # Se distingue de "no lo encuentro": esto es un fallo de red o de
        # formato, y la diferencia es lo unico que permite saber si hay que
        # reintentar o cambiar el nombre.
        raise IOError("no se pudo consultar Steam (%s)" % e)
    if not datos:
        raise LookupError('Steam no conoce "%s"' % nombre)

    k = _clave(nombre)
    exacto = parecido = None
    for d in datos:
        if not isinstance(d, dict):
            continue
        n, a = d.get("name", ""), d.get("appid", "")
        if not n or not a:
            continue
        kn = _clave(n)
        if kn == k:
            exacto = (a, n)
            break
        if parecido is None and (kn.startswith(k) or k.startswith(kn)):
            parecido = (a, n)
    elegido = exacto or parecido
    if not elegido:
        raise LookupError('ningun resultado de Steam coincide con "%s"' % nombre)
    return elegido


# ----------------------------------------------------------------------------
# DURACION (HowLongToBeat)
# ----------------------------------------------------------------------------

PARECIDO_MINIMO = 0.7


def duracion(nombre):
    """(historia, completarlo) en horas, o None si no se sabe.

    Por debajo de 0.7 de parecido no es el mismo juego: mas vale callar que
    poner en la ficha la duracion de otro.
    """
    try:
        from howlongtobeatpy import HowLongToBeat
    except ImportError:
        raise IOError("falta el modulo howlongtobeatpy")
    try:
        res = HowLongToBeat().search(nombre, similarity_case_sensitive=False)
    except Exception as e:
        raise IOError("no se pudo consultar HowLongToBeat (%s)" % e)
    if not res:
        raise LookupError('HowLongToBeat no conoce "%s"' % nombre)
    mejor = max(res, key=lambda e: e.similarity)
    if mejor.similarity < PARECIDO_MINIMO:
        raise LookupError('lo mas parecido a "%s" es "%s", demasiado distinto'
                          % (nombre, getattr(mejor, "game_name", "?")))
    hist = getattr(mejor, "main_story", None) or 0
    todo = getattr(mejor, "completionist", None) or 0
    if not hist and not todo:
        raise LookupError('HowLongToBeat no da duracion para "%s"' % nombre)
    return hist, todo


# ----------------------------------------------------------------------------
# LECTURA DE UN CAMPO DE LA FICHA DE STEAM
# ----------------------------------------------------------------------------

def campo(fichero, ruta):
    """Saca un campo de la respuesta de Steam. 'ruta' va con puntos.

    La respuesta viene envuelta en el appid: {"620": {"data": {...}}}. Los
    indices numericos entran en listas: "genres.0.description".
    """
    try:
        with open(fichero, encoding="utf-8") as fh:
            d = json.load(fh)
    except OSError as e:
        raise IOError("no se pudo leer la ficha (%s)" % e)
    except ValueError as e:
        raise IOError("la ficha no es JSON valido (%s)" % e)

    try:
        d = list(d.values())[0].get("data", {})
    except (AttributeError, IndexError, TypeError):
        raise LookupError("la ficha no trae datos")

    for parte in ruta.split("."):
        if d is None:
            raise LookupError("no hay '%s' en la ficha" % ruta)
        try:
            if isinstance(d, list):
                d = d[int(parte)]
            elif isinstance(d, dict):
                d = d.get(parte)
            else:
                raise LookupError("no hay '%s' en la ficha" % ruta)
        except (ValueError, IndexError, KeyError):
            raise LookupError("no hay '%s' en la ficha" % ruta)
    if d is None:
        raise LookupError("no hay '%s' en la ficha" % ruta)

    if isinstance(d, list):
        # Solo los cuatro primeros: son generos o etiquetas y la ficha no da
        # para mas.
        return ", ".join(
            (x.get("description", "") if isinstance(x, dict) else str(x))
            for x in d[:4])
    return str(d)


# ----------------------------------------------------------------------------
# RAWG: para los juegos que no estan en Steam
# ----------------------------------------------------------------------------

def rawg(nombre, clave):
    """Busca el juego en RAWG. Devuelve un dict con nombre, nota, ano y gen.

    SE GUARDA APARTE del .info.json de Steam, no mezclado: asi se sabe de
    donde vino cada dato, y al volver a bajar la ficha de Steam no se pierde
    lo de RAWG sin que nadie se entere.

    LA VERSION ANTERIOR TRAIA CODIGO MUERTO. Abria el .info.json de Steam en
    una variable "previo" y definia una funcion "dato()" para -segun su
    comentario- que "lo de Steam mandara y RAWG solo rellenara huecos". Ni la
    variable se leia nunca ni la funcion se llamaba: era de un diseño que se
    habia revertido justo por lo que dice el parrafo de arriba. Lo unico que
    conseguia era abrir y parsear un JSON en balde en cada consulta.
    """
    url = ("https://api.rawg.io/api/games?key=%s&search=%s"
           "&page_size=5&search_precise=true"
           % (urllib.parse.quote(clave), urllib.parse.quote(nombre)))
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            datos = json.load(r)
    except Exception as e:
        raise IOError("no se pudo consultar RAWG (%s)" % e)

    return elegir_rawg(datos, nombre)


def elegir_rawg(datos, nombre=""):
    """Saca el mejor resultado de una respuesta de RAWG. Aparte, para poder
    probarlo sin red."""
    res = datos.get("results") if isinstance(datos, dict) else None
    if not res:
        raise LookupError('RAWG no conoce "%s"' % nombre)
    # El primero que traiga nota; si ninguno la trae, el primero a secas.
    elegido = next((g for g in res if isinstance(g, dict) and g.get("metacritic")),
                   None)
    if elegido is None:
        elegido = next((g for g in res if isinstance(g, dict)), None)
    if elegido is None:
        raise LookupError('RAWG no devolvio nada util para "%s"' % nombre)
    return {
        "nombre": elegido.get("name", "") or "",
        "nota": str(elegido.get("metacritic") or ""),
        "ano": (elegido.get("released") or "")[:4],
        "gen": ", ".join(g.get("name", "")
                         for g in (elegido.get("genres") or [])[:2]
                         if isinstance(g, dict)),
    }


# ----------------------------------------------------------------------------
# COMPROBACION INTERNA
#
# Nada de aqui toca la red: lo que se prueba es el filtro de resultados, la
# navegacion por el JSON y que cada fallo se distinga del otro. Lo que se va a
# internet se prueba con datos ya descargados.
# ----------------------------------------------------------------------------

def comprobar():
    import shutil
    import tempfile
    fallos = []
    raiz = tempfile.mkdtemp(prefix="wp-ficha-")

    def esperar(que, visto, esperado):
        if visto != esperado:
            fallos.append("%s: salio %r y se esperaba %r" % (que, visto, esperado))

    # appid de acceso directo: estable y con el bit alto puesto
    a1 = appid_acceso_directo("/j/x.exe", "Mi Juego")
    esperar("appid estable", appid_acceso_directo("/j/x.exe", "Mi Juego"), a1)
    if not a1 & 0x80000000:
        fallos.append("appid sin el bit alto: %r" % a1)
    if a1 == appid_acceso_directo("/j/y.exe", "Mi Juego"):
        fallos.append("el appid no depende del ejecutable")

    # el filtro de resultados de Steam, sin red
    def elegir(nombre, datos):
        k = _clave(nombre)
        exacto = parecido = None
        for d in datos:
            n, a = d.get("name", ""), d.get("appid", "")
            if not n or not a:
                continue
            kn = _clave(n)
            if kn == k:
                exacto = (a, n); break
            if parecido is None and (kn.startswith(k) or k.startswith(kn)):
                parecido = (a, n)
        return exacto or parecido

    datos = [{"appid": "620", "name": "Portal 2"},
             {"appid": "400", "name": "Portal"}]
    esperar("gana la coincidencia exacta", elegir("Portal", datos), ("400", "Portal"))
    esperar("signos y espacios dan igual",
            elegir("portal-2", datos), ("620", "Portal 2"))
    esperar("sin coincidencia", elegir("Zzz", datos), None)
    esperar("resultado incompleto se salta",
            elegir("X", [{"name": "X"}, {"appid": "9", "name": "X"}]), ("9", "X"))

    # campo(): navegacion por el JSON
    f = os.path.join(raiz, "ficha.json")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump({"620": {"data": {
            "name": "Portal 2",
            "release_date": {"date": "19 Apr, 2011"},
            "genres": [{"description": "Puzzle"}, {"description": "Accion"},
                       {"description": "A"}, {"description": "B"},
                       {"description": "NO SALE"}],
            "vacio": None,
        }}}, fh)
    esperar("campo simple", campo(f, "name"), "Portal 2")
    esperar("campo anidado", campo(f, "release_date.date"), "19 Apr, 2011")
    esperar("lista de generos", campo(f, "genres"), "Puzzle, Accion, A, B")
    esperar("indice en lista", campo(f, "genres.1.description"), "Accion")
    for ruta in ("no_existe", "name.mas", "genres.99", "vacio"):
        try:
            campo(f, ruta)
            fallos.append("campo(%r) deberia fallar" % ruta)
        except LookupError:
            pass
        except IOError:
            fallos.append("campo(%r) da error de lectura en vez de 'no esta'" % ruta)

    # RAWG: eleccion del resultado, sin red
    r = elegir_rawg({"results": [
        {"name": "Sin nota", "released": "1999-01-01"},
        {"name": "Con nota", "metacritic": 87, "released": "2011-04-19",
         "genres": [{"name": "Puzzle"}, {"name": "Accion"}, {"name": "NO SALE"}]},
    ]})
    esperar("rawg gana el que trae nota", r["nombre"], "Con nota")
    esperar("rawg nota", r["nota"], "87")
    esperar("rawg ano", r["ano"], "2011")
    esperar("rawg dos generos", r["gen"], "Puzzle, Accion")
    r = elegir_rawg({"results": [{"name": "Unico"}]})
    esperar("rawg sin nota coge el primero", r["nombre"], "Unico")
    esperar("rawg sin nota deja el campo vacio", r["nota"], "")
    esperar("rawg sin fecha", r["ano"], "")
    for vacio in ({"results": []}, {}, {"results": None}):
        try:
            elegir_rawg(vacio, "X")
            fallos.append("elegir_rawg(%r) deberia fallar" % vacio)
        except LookupError:
            pass

    # LOS FALLOS SE DISTINGUEN: leer mal no es lo mismo que no encontrar
    with open(os.path.join(raiz, "roto.json"), "w", encoding="utf-8") as fh:
        fh.write("no soy json")
    try:
        campo(os.path.join(raiz, "roto.json"), "name")
        fallos.append("un JSON roto no da error")
    except IOError:
        pass
    except LookupError:
        fallos.append("un JSON roto se confunde con 'no esta el campo'")
    try:
        campo(os.path.join(raiz, "no-existe.json"), "name")
        fallos.append("un fichero que no esta no da error")
    except IOError:
        pass

    shutil.rmtree(raiz, ignore_errors=True)
    return fallos


# ----------------------------------------------------------------------------
# LINEA DE ORDENES
# ----------------------------------------------------------------------------

def main(argv):
    if len(argv) < 2:
        sys.stderr.write(
            "uso: ficha.py <orden> [...]\n"
            "  appid-acceso <exe> <nombre>   identificador de acceso directo\n"
            "  appid        <nombre>         appid|nombre desde Steam\n"
            "  duracion     <nombre>         historia|completarlo (horas)\n"
            "  campo        <fichero> <ruta> un campo de la ficha\n"
            "  rawg  <nombre> <clave> <salida>  ficha de RAWG a un JSON\n"
            "  urlencode    <texto>          texto listo para una URL\n"
            "  comprobar                     auto-diagnostico\n")
        return 2
    orden = argv[1]

    if orden == "comprobar":
        fallos = comprobar()
        if fallos:
            sys.stderr.write("ficha.py: %d fallo(s)\n" % len(fallos))
            for f in fallos:
                sys.stderr.write("  - %s\n" % f)
            return 1
        print("ficha.py: todo correcto")
        return 0

    if len(argv) < 3:
        sys.stderr.write("ficha.py %s: faltan argumentos\n" % orden)
        return 2

    if orden == "urlencode":
        sys.stdout.write(urllib.parse.quote(argv[2]))
        return 0

    if orden == "appid-acceso":
        if len(argv) < 4:
            return 2
        sys.stdout.write("%d" % appid_acceso_directo(argv[2], argv[3]))
        return 0

    # Estas tres pueden fallar de dos maneras distintas y hay que poder
    # contarlas: 1 = no se encontro, 2 = no se pudo consultar o leer.
    try:
        if orden == "appid":
            a, n = appid_de_steam(argv[2])
            sys.stdout.write("%s|%s" % (a, n))
            return 0
        if orden == "duracion":
            h, t = duracion(argv[2])
            sys.stdout.write("%s|%s" % (h, t))
            return 0
        if orden == "rawg":
            if len(argv) < 5:
                sys.stderr.write("ficha.py rawg: faltan <nombre> <clave> <salida>\n")
                return 2
            d = rawg(argv[2], argv[3])
            with open(argv[4], "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False)
            sys.stderr.write("[rawg] %s -> nota %s\n"
                             % (d["nombre"], d["nota"] or "sin nota"))
            return 0
        if orden == "campo":
            if len(argv) < 4:
                return 2
            sys.stdout.write(campo(argv[2], argv[3]))
            return 0
    except LookupError as e:
        sys.stderr.write("ficha: %s\n" % e)
        return 1
    except IOError as e:
        sys.stderr.write("ficha: %s\n" % e)
        return 2

    sys.stderr.write("ficha.py: orden desconocida %r\n" % orden)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
