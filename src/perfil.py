# -*- coding: utf-8 -*-
# WProton - perfiles por juego (profiles/<gid>.conf)
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
# A profile_defaults(), load_profile(), write_full_profile(),
# overrides_sin_mscoree() y perfiles_limpiar_mscoree() del script grande.
#
# POR QUE
#
#   1. EL PERFIL SE LEIA CON '. "$conf"'.
#
#      Eso no es leer un fichero de configuracion: es EJECUTARLO. Un .conf con
#      NOTAS="$(cualquier-cosa)" corre esa orden al cargar el juego. Mientras
#      los .conf los escribiera solo WProton daba igual, pero con perfiles de
#      la comunidad (el campo COMUNIDAD_VISTO) el .conf pasa a venir de fuera.
#      Aqui se PARSEA, no se ejecuta: no hay forma de que un perfil corra nada.
#
#   2. write_full_profile NO ESCAPABA LOS VALORES.
#
#      El heredoc ponia NOTAS="$NOTAS" tal cual. Si NOTAS trae una comilla
#      doble -y los campos donde se pegan lineas de ProtonDB la traen a
#      menudo: ARGS_OVERRIDE, DLL_OVERRIDES, ENV_EXTRA- el fichero quedaba
#      roto y al recargarlo el valor se perdia EN SILENCIO. Aqui se escapa
#      siempre, y el parser ademas sabe recomponer los ficheros que ya
#      quedaron mal.
#
#   3. EL ESQUEMA ESTABA ESCRITO TRES VECES.
#
#      Una en profile_defaults, otra en el heredoc de write_full_profile y
#      otra en cada menu que lee el campo. Hoy las 52 coinciden, pero eso hay
#      que mantenerlo a mano y a la larga siempre se escapa una. Aqui el
#      esquema es UNA tabla y todo lo demas sale de ella.
#
#   4. SE ESCRIBIA CON 'cat >', QUE TRUNCA ANTES DE ESCRIBIR.
#
#      Si algo falla a mitad -disco lleno, se corta la corriente en la Deck-,
#      el perfil se queda a medias y con el se van las horas jugadas, los
#      favoritos y los ajustes del mando. Aqui se escribe en un temporal y se
#      mueve encima, que es una operacion atomica.
#
# COMPATIBILIDAD
#
# El formato del fichero NO cambia. Sigue siendo el mismo .conf de siempre,
# con los mismos campos en el mismo orden, y se puede seguir editando a mano.
# Un perfil escrito por este modulo lo lee el WProton viejo y al reves.
# ----------------------------------------------------------------------------

import os
import re
import shlex
import sys
import tempfile

VERSION = "1"

# ----------------------------------------------------------------------------
# EL ESQUEMA: la unica definicion de que campos hay, en que orden y con que
# valor por defecto. El orden es el mismo del heredoc antiguo, a proposito:
# asi un perfil reescrito por este modulo no sale con las lineas cambiadas de
# sitio y se puede comparar con 'diff' contra los de antes.
#
#   tipo:
#     "texto"  -> cadena libre, se escribe siempre entre comillas
#     "entero" -> numero, se escribe sin comillas
#     "opcion" -> uno de una lista cerrada; si llega otro se avisa y se deja
#                 el valor por defecto (nunca se rompe la carga por esto)
# ----------------------------------------------------------------------------

ESQUEMA = [
    # (nombre,            tipo,     defecto,          opciones validas)
    ("GAMEID",            "texto",  "umu-default",    None),
    ("STORE",             "texto",  "none",           None),
    ("RUNNER",            "texto",  "",               None),
    ("EXE_OVERRIDE",      "texto",  "",               None),
    ("ARGS_OVERRIDE",     "texto",  "",               None),
    ("PREFIX_MODE",       "opcion", "shared",         ("shared", "own", "bundled", "teknoparrot")),
    ("PREFIX_ORIGEN",     "opcion", "nuevo",          ("nuevo", "bundled")),
    ("UNIDAD_JUEGO",      "texto",  "",               None),
    ("UNIDAD_CD",         "entero", 0,                None),
    ("UNIDAD_DESTINO",    "opcion", "juego",          ("juego", "datos")),
    ("JUEGO_EN_C",        "entero", 0,                None),
    ("DEPS_JUEGO",        "entero", 0,                None),
    ("EXE_ACOMPANA",      "texto",  "",               None),
    ("ACOMPANA_ESPERA",   "entero", 3,                None),
    ("INSTALAR_UNA_VEZ",  "texto",  "",               None),
    ("MANGOHUD",          "entero", 0,                None),
    ("PAD_SDL",           "opcion", "auto",           ("auto", "1", "0")),
    ("PAD_SONY",          "opcion", "auto",           ("auto", "1", "0")),
    ("KEYS_ESTILO",       "opcion", "xbox",           ("xbox", "nintendo")),
    ("TECLADO_POS",       "opcion", "abajo",          ("abajo", "arriba", "centro")),
    ("KEYS_EXCLUSIVO",    "opcion", "auto",           ("auto", "1", "0")),
    # MANDO_VIRTUAL crece con cada mando que se añade, asi que va como texto
    # libre: una lista cerrada aqui obligaria a tocar dos sitios cada vez.
    ("MANDO_VIRTUAL",     "texto",  "0",              None),
    ("TEXTO_RAPIDO",      "texto",  "",               None),
    ("TEXTO_ENTER",       "entero", 0,                None),
    ("PAD_STEAMFIX",      "entero", 0,                None),
    ("NESTED_GAMESCOPE",  "entero", 0,                None),
    ("NTSYNC",            "entero", 0,                None),
    ("FAVORITO",          "entero", 0,                None),
    ("COMPLETADO",        "entero", 0,                None),
    ("NOTAS",             "texto",  "",               None),
    ("PLAY_COUNT",        "entero", 0,                None),
    ("PLAY_SECONDS",      "entero", 0,                None),
    ("LAST_PLAYED",       "texto",  "",               None),
    ("SAVE_PATHS",        "texto",  "",               None),
    # USE_BATOCERA no tiene un defecto fijo: depende de si estamos EN Batocera.
    # El valor real llega en la variable de entorno WP_IS_BATOCERA, igual que
    # el $IS_BATOCERA del script.
    ("USE_BATOCERA",      "entero", 0,                None),
    ("GAMEMODE",          "entero", 1,                None),
    ("FSYNC",             "entero", 1,                None),
    ("ESYNC",             "entero", 1,                None),
    ("DXVK_ASYNC",        "entero", 1,                None),
    ("WAYLAND",           "entero", 0,                None),
    ("ENV_EXTRA",         "texto",  "",               None),
    ("HDR",               "entero", 0,                None),
    ("WINED3D",           "entero", 0,                None),
    ("FSR",               "entero", 0,                None),
    ("LAA",               "entero", 0,                None),
    ("GAMESCOPE",         "texto",  "",               None),
    ("DLL_OVERRIDES",     "texto",  "",               None),
    ("MONO_PEDIR",        "entero", 0,                None),
    ("COMUNIDAD_VISTO",   "entero", 0,                None),
    ("REDIST_JUEGO",      "texto",  "",               None),
    ("GAME_LANG",         "texto",  "es_ES.UTF-8",    None),
    ("EXTRA_ENV",         "texto",  "",               None),
]

ORDEN = [c[0] for c in ESQUEMA]
CAMPOS = {c[0]: {"tipo": c[1], "defecto": c[2], "opciones": c[3]} for c in ESQUEMA}


def defectos():
    """Los valores por defecto, ya resueltos los que dependen del sistema."""
    d = {n: CAMPOS[n]["defecto"] for n in ORDEN}
    # Igual que USE_BATOCERA="$IS_BATOCERA" en profile_defaults.
    if os.environ.get("WP_IS_BATOCERA", "0") == "1":
        d["USE_BATOCERA"] = 1
    return d


# ----------------------------------------------------------------------------
# LECTURA
# ----------------------------------------------------------------------------

_ASIGNACION = re.compile(r"^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)

# Dentro de comillas dobles, bash solo trata como escape estos cuatro. Un
# \n ahi es una barra y una ene, no un salto de linea, y hay que respetarlo o
# los DLL_OVERRIDES con rutas de Windows saldrian cambiados.
_ESCAPABLES = '"\\$`'


def _leer_valor(s, i):
    """Lee un valor de asignacion desde s[i:] al estilo de bash.

    Devuelve (valor, indice_siguiente). Concatena trozos pegados igual que
    hace bash: 'a"b c"d' es un solo valor, "ab cd".

    ESO ES LO QUE RECUPERA LOS PERFILES YA ROTOS. Un NOTAS="usar "GE 9-27""
    escrito por la version antigua se lee aqui como 'usar GE 9-27' en vez de
    perderse. No es lo que el usuario escribio -las comillas ya no estan- pero
    es su texto, y antes se quedaba en nada.
    """
    partes = []
    n = len(s)
    while i < n:
        c = s[i]
        if c == '"':
            i += 1
            trozo = []
            while i < n and s[i] != '"':
                if s[i] == "\\" and i + 1 < n and s[i + 1] in _ESCAPABLES:
                    trozo.append(s[i + 1])
                    i += 2
                elif s[i] == "\\" and i + 1 < n and s[i + 1] == "\n":
                    i += 2          # continuacion de linea: se traga
                else:
                    trozo.append(s[i])
                    i += 1
            i += 1                  # la comilla de cierre (o el fin del texto)
            partes.append("".join(trozo))
        elif c == "'":
            i += 1
            trozo = []
            while i < n and s[i] != "'":
                trozo.append(s[i])
                i += 1
            i += 1
            partes.append("".join(trozo))
        elif c == "\n":
            break
        elif c == "\\" and i + 1 < n:
            partes.append(s[i + 1])
            i += 2
        else:
            partes.append(c)
            i += 1
    return "".join(partes), i


def _normalizar(nombre, bruto, avisos):
    """Convierte el texto leido al tipo del campo, sin fallar nunca."""
    info = CAMPOS[nombre]
    if info["tipo"] == "entero":
        try:
            return int(str(bruto).strip() or 0)
        except ValueError:
            avisos.append("%s=%r no es un numero; se usa %r"
                          % (nombre, bruto, info["defecto"]))
            return info["defecto"]
    valor = str(bruto)
    if info["tipo"] == "opcion" and info["opciones"] and valor not in info["opciones"]:
        avisos.append("%s=%r no es un valor conocido (%s); se usa %r"
                      % (nombre, valor, "|".join(info["opciones"]), info["defecto"]))
        return info["defecto"]
    return valor


def cargar(ruta):
    """Lee un .conf. Devuelve (valores, extras, avisos).

    valores  - los 52 campos del esquema, siempre completos
    extras   - campos que estan en el fichero y no en el esquema. Se conservan
               y se vuelven a escribir tal cual: son perfiles de una version
               MAS NUEVA, y perderlos al guardar seria peor que ignorarlos.
    avisos   - lo que no cuadraba. No se imprimen aqui: los recoge quien llame,
               que es el que sabe si hay que mandarlos al log o a la pantalla.
    """
    valores = defectos()
    extras = {}
    avisos = []
    if not os.path.isfile(ruta):
        return valores, extras, avisos

    try:
        with open(ruta, encoding="utf-8", errors="replace") as fh:
            texto = fh.read()
    except OSError as e:
        avisos.append("no se pudo leer %s: %s" % (ruta, e))
        return valores, extras, avisos

    i = 0
    n = len(texto)
    while i < n:
        fin = texto.find("\n", i)
        if fin < 0:
            fin = n
        linea = texto[i:fin]
        desnuda = linea.strip()
        if not desnuda or desnuda.startswith("#"):
            i = fin + 1
            continue
        m = _ASIGNACION.match(texto[i:])
        if not m:
            i = fin + 1
            continue
        nombre = m.group(1)
        # El valor puede seguir en las lineas de abajo si abre comillas y no
        # las cierra, asi que se lee sobre el texto entero y no sobre la linea.
        inicio_valor = i + m.start(2)
        bruto, siguiente = _leer_valor(texto, inicio_valor)
        if nombre in CAMPOS:
            valores[nombre] = _normalizar(nombre, bruto, avisos)
        else:
            extras[nombre] = bruto
        i = siguiente
        # colocarse al principio de la linea siguiente
        salto = texto.find("\n", i - 1 if i > 0 else 0)
        if i <= (salto if salto >= 0 else n):
            i = (salto + 1) if salto >= 0 else n

    # Lo que hacia load_profile al terminar: quitar mscoree en memoria.
    if valores["DLL_OVERRIDES"]:
        limpio = sin_mscoree(valores["DLL_OVERRIDES"])
        if limpio != valores["DLL_OVERRIDES"]:
            valores["DLL_OVERRIDES"] = limpio
    return valores, extras, avisos


# ----------------------------------------------------------------------------
# ESCRITURA
# ----------------------------------------------------------------------------

def _entrecomillar(valor):
    """Un valor listo para meter entre comillas dobles en el .conf."""
    s = str(valor)
    for c in ("\\", '"', "$", "`"):
        s = s.replace(c, "\\" + c)
    return '"%s"' % s


def volcar(valores, extras=None, gid=""):
    """El texto completo del .conf, en el orden del esquema."""
    lineas = ["# Perfil WProton para: %s  (editable a mano o via ./wproton.sh --config)" % gid]
    for nombre in ORDEN:
        valor = valores.get(nombre, CAMPOS[nombre]["defecto"])
        if CAMPOS[nombre]["tipo"] == "entero":
            try:
                lineas.append("%s=%d" % (nombre, int(valor)))
            except (TypeError, ValueError):
                lineas.append("%s=%d" % (nombre, CAMPOS[nombre]["defecto"]))
        else:
            lineas.append("%s=%s" % (nombre, _entrecomillar(valor)))
    for nombre in sorted(extras or {}):
        lineas.append("%s=%s" % (nombre, _entrecomillar(extras[nombre])))
    return "\n".join(lineas) + "\n"


def guardar(ruta, valores, extras=None, gid=""):
    """Escribe el .conf de forma atomica: temporal en la MISMA carpeta y
    os.replace encima. Si algo falla, el perfil de antes sigue entero."""
    carpeta = os.path.dirname(os.path.abspath(ruta)) or "."
    os.makedirs(carpeta, exist_ok=True)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=carpeta, prefix=".perfil-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(volcar(valores, extras, gid))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, ruta)
        tmp = None
        return True
    except OSError as e:
        sys.stderr.write("perfil: no se pudo guardar %s: %s\n" % (ruta, e))
        return False
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


# ----------------------------------------------------------------------------
# MSCOREE (lo que hacian overrides_sin_mscoree y perfiles_limpiar_mscoree)
# ----------------------------------------------------------------------------

def sin_mscoree(lista):
    """Quita la entrada mscoree de unos DLL overrides, dejando las demas.

    LA LOGICA DE VERDAD ESTA EN dlls.py, que es quien entiende el formato de
    WINEDLLOVERRIDES (grupos "d3d9,ddraw=n,b", mayusculas, espacios). Aqui
    solo se delega, para no tener dos ideas distintas de lo que es una
    entrada.

    Si dlls.py no esta -no deberia pasar: el build escribe los dos en la
    misma carpeta- se devuelve la cadena tal cual. Esto es una limpieza de
    perfiles antiguos, no algo que rompa nada si no se hace: el barrido
    volvera a intentarlo, y load_profile la ignora igual.
    """
    if not lista:
        return ""
    try:
        aqui = os.path.dirname(os.path.abspath(__file__))
        if aqui not in sys.path:
            sys.path.insert(0, aqui)
        import dlls
    except ImportError:
        return str(lista)
    return dlls.quitar(lista, "mscoree")


def limpiar_mscoree(carpeta):
    """Barrido de una vez sobre todos los .conf. Devuelve cuantos se tocaron.

    Igual que antes solo se toca el perfil que lo tenga de verdad, pero ahora
    se reescribe entero y sin riesgo: la escritura es atomica y el resto de
    campos vuelven a salir del propio fichero, no de un awk.
    """
    n = 0
    try:
        nombres = sorted(os.listdir(carpeta))
    except OSError:
        return 0
    for nombre in nombres:
        if not nombre.endswith(".conf"):
            continue
        ruta = os.path.join(carpeta, nombre)
        valores, extras, _ = cargar(ruta)
        # cargar() ya lo quita en memoria: se compara con lo que hay en disco.
        try:
            with open(ruta, encoding="utf-8", errors="replace") as fh:
                if "mscoree" not in fh.read().lower():
                    continue
        except OSError:
            continue
        if guardar(ruta, valores, extras, nombre[:-5]):
            n += 1
    return n


# ----------------------------------------------------------------------------
# COMPROBACION INTERNA
#
# Va aqui dentro y no en un documento aparte para que se pueda ejecutar en
# cualquier maquina donde falle algo, sin tener que pedirle a nadie que
# escriba ordenes sueltas en una terminal.
# ----------------------------------------------------------------------------

def comprobar(carpeta=None):
    fallos = []
    tmpd2 = tempfile.mkdtemp(prefix="wp-perfil-cli-")
    import shutil as _sh
    import subprocess

    # 1. Ida y vuelta con los valores mas hostiles que se pueden escribir.
    hostiles = {
        "NOTAS": 'usar "GE 9-27" y $HOME `id` \\ fin',
        "ARGS_OVERRIDE": '-dxlevel 90 -w 1280 -novid "con espacios"',
        "DLL_OVERRIDES": "d3d9=n,b;dxgi=n,b",
        "ENV_EXTRA": 'WINEDLLOVERRIDES="d3d11=n" MANGOHUD=1',
        "TEXTO_RAPIDO": "linea uno\nlinea dos",
        "UNIDAD_JUEGO": "e f",
        "PLAY_SECONDS": 516,
    }
    v = defectos()
    v.update(hostiles)
    texto = volcar(v, {"CAMPO_DEL_FUTURO": 'valor "raro"'}, "prueba")
    tmpd = tempfile.mkdtemp(prefix="wp-perfil-")
    ruta = os.path.join(tmpd, "prueba.conf")
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write(texto)
    leido, extras, avisos = cargar(ruta)
    for k, esperado in hostiles.items():
        if leido.get(k) != esperado:
            fallos.append("ida y vuelta de %s: se guardo %r y se leyo %r"
                          % (k, esperado, leido.get(k)))
    if extras.get("CAMPO_DEL_FUTURO") != 'valor "raro"':
        fallos.append("los campos desconocidos no se conservan: %r" % extras)
    if avisos:
        fallos.append("avisos inesperados en la ida y vuelta: %s" % avisos)

    # 2. Un perfil malicioso no debe ejecutar nada ni colar el resultado.
    malo = os.path.join(tmpd, "malo.conf")
    with open(malo, "w", encoding="utf-8") as fh:
        fh.write('NOTAS="$(id -un)"\nGAMESCOPE="`hostname`"\n')
    lm, _, _ = cargar(malo)
    if lm["NOTAS"] != "$(id -un)" or lm["GAMESCOPE"] != "`hostname`":
        fallos.append("un .conf con ordenes dentro no se lee literal: %r / %r"
                      % (lm["NOTAS"], lm["GAMESCOPE"]))

    # 3. Un perfil ya roto por la version antigua debe recuperarse.
    roto = os.path.join(tmpd, "roto.conf")
    with open(roto, "w", encoding="utf-8") as fh:
        fh.write('NOTAS="usar "GE 9-27""\nFAVORITO=1\n')
    lr, _, _ = cargar(roto)
    if "GE 9-27" not in lr["NOTAS"]:
        fallos.append("no se recupera un NOTAS roto: %r" % lr["NOTAS"])
    if lr["FAVORITO"] != 1:
        fallos.append("una linea rota se lleva por delante la siguiente")

    # 4. Valores fuera de la lista: se avisa, no se revienta.
    raro = os.path.join(tmpd, "raro.conf")
    with open(raro, "w", encoding="utf-8") as fh:
        fh.write('PREFIX_MODE="inventado"\nPLAY_COUNT="no soy un numero"\n')
    lx, _, ax = cargar(raro)
    if lx["PREFIX_MODE"] != "shared" or lx["PLAY_COUNT"] != 0:
        fallos.append("los valores invalidos no caen al defecto")
    if len(ax) != 2:
        fallos.append("faltan avisos para los valores invalidos: %s" % ax)

    # 5. Las asignaciones para bash tienen que llegar a bash INTACTAS.
    #
    # No vale mirar si la cadena "parece" segura: la primera version de esta
    # comprobacion buscaba comillas invertidas en la salida y daba un fallo
    # que no era tal (shlex.quote usa comillas SIMPLES, y ahi una comilla
    # invertida no hace nada). La unica forma de saberlo es evaluarla con
    # bash de verdad y comparar lo que sale.
    bash = _sh.which("bash")
    if bash:
        # Los separadores son bytes de control (\x01 y \x02) y no saltos de
        # linea: TEXTO_RAPIDO puede tener saltos dentro, y partiendo por
        # lineas un valor de dos renglones se leeria a medias.
        guion = como_shell(v, {}) + "\n".join(
            'printf "%%s\\001%%s\\002" %s "$%s"' % (shlex.quote(k), k)
            for k in hostiles
        )
        try:
            res = subprocess.run([bash, "-c", guion], capture_output=True,
                                 text=True, timeout=20)
            visto = {}
            for registro in res.stdout.split("\x02"):
                if "\x01" in registro:
                    k, val = registro.split("\x01", 1)
                    visto[k] = val
            for k, esperado in hostiles.items():
                if visto.get(k) != str(esperado):
                    fallos.append("bash recibe %s como %r y no %r"
                                  % (k, visto.get(k), str(esperado)))
        except (OSError, subprocess.SubprocessError) as e:
            fallos.append("no se pudo comprobar con bash: %s" % e)

    # 6. Si nos dan la carpeta real, se leen todos los perfiles de verdad.
    if carpeta and os.path.isdir(carpeta):
        for nombre in sorted(os.listdir(carpeta)):
            if not nombre.endswith(".conf"):
                continue
            _, _, av = cargar(os.path.join(carpeta, nombre))
            for a in av:
                fallos.append("%s: %s" % (nombre, a))

    # metas: la vista de biblioteca sale del mismo parser que todo lo demas
    mv = defectos(); mv.update({"FAVORITO": 1, "LAST_PLAYED": "2026-09-08 14:30",
                                "PLAY_SECONDS": 516})
    with open(os.path.join(tmpd2, "unjuego.conf"), "w", encoding="utf-8") as fh:
        fh.write(volcar(mv, {}, "unjuego"))
    fila = [f for f in metas(tmpd2) if f[0] == "unjuego"]
    if fila != [("unjuego", 1, "2026-09-08 14:30", 516)]:
        fallos.append("metas: %r" % fila)

    # 7. CADA ORDEN DEL CLI, EJECUTADA DE VERDAD.
    #
    # Esta comprobacion existe por un fallo concreto: una edicion se llevo por
    # delante la linea "def _ruta_de(...)" y su cuerpo quedo colgando dentro
    # de la funcion de arriba como codigo muerto. Eso es Python VALIDO: el
    # modulo compilaba, "python -m py_compile" pasaba, y el fallo solo salia
    # al llamar a guardar. Compilar no es funcionar; hay que llamarlo.
    guiones = os.path.abspath(__file__)
    pruebas = [
        (["cargar", tmpd2, "prueba"], 0),
        (["ver", tmpd2, "prueba"], 0),
        (["ver", tmpd2, "prueba", "FAVORITO"], 0),
        (["poner", tmpd2, "prueba", "FAVORITO=1"], 0),
        (["mscoree", tmpd2], 0),
        (["metas", tmpd2], 0),
        (["defectos-bash"], 0),
    ]
    for args, esperado in pruebas:
        try:
            r = subprocess.run([sys.executable, guiones] + args,
                               capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            fallos.append("la orden %r no se pudo ejecutar: %s" % (args[0], e))
            continue
        if r.returncode != esperado:
            fallos.append("la orden %r devolvio %d (se esperaba %d): %s"
                          % (args[0], r.returncode, esperado,
                             r.stderr.strip().splitlines()[-1:] or ""))
    # y 'guardar', que lee de la entrada estandar
    try:
        r = subprocess.run([sys.executable, guiones, "guardar", tmpd2, "prueba"],
                           input="NOTAS=probado\nFAVORITO=1\n",
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            fallos.append("la orden 'guardar' devolvio %d: %s"
                          % (r.returncode, r.stderr.strip()))
        else:
            vg, _, _ = cargar(os.path.join(tmpd2, "prueba.conf"))
            if vg["NOTAS"] != "probado" or vg["FAVORITO"] != 1:
                fallos.append("'guardar' no dejo los valores puestos: %r" % vg["NOTAS"])
    except (OSError, subprocess.SubprocessError) as e:
        fallos.append("la orden 'guardar' no se pudo ejecutar: %s" % e)

    import shutil
    shutil.rmtree(tmpd, ignore_errors=True)
    shutil.rmtree(tmpd2, ignore_errors=True)
    return fallos


# ----------------------------------------------------------------------------
# INTERFAZ DE LINEA DE ORDENES (la que usa el shim de bash)
# ----------------------------------------------------------------------------

def como_shell(valores, extras=None):
    """Las asignaciones listas para 'eval' en bash.

    Se entrecomillan con shlex.quote, que es exactamente lo que hace falta
    para que bash reciba el texto literal por raro que sea. El 'eval' del shim
    es seguro porque lo que evalua lo generamos aqui, no el fichero.
    """
    fuera = []
    for nombre in ORDEN:
        fuera.append("%s=%s" % (nombre, shlex.quote(str(valores[nombre]))))
    for nombre in sorted(extras or {}):
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", nombre):
            fuera.append("%s=%s" % (nombre, shlex.quote(str(extras[nombre]))))
    return "\n".join(fuera) + "\n"


def defectos_bash():
    """La funcion profile_defaults() de bash, generada desde el esquema.

    POR QUE SE GENERA Y NO SE ESCRIBE A MANO
    ----------------------------------------
    WProton tiene que poder cargar un perfil ANTES de tener python: en el
    primer arranque, si el sistema no trae python3, el portable todavia no se
    ha descargado y PY_BIN esta vacio. Sin esto, un juego lanzado por linea de
    ordenes en esa ventana se quedaria sin perfil.

    Pero copiar los 52 valores a bash a mano seria volver justo al problema
    que este modulo resuelve: dos listas que hay que mantener iguales y que
    con el tiempo dejan de estarlo. Asi que la lista de bash la escribe el
    build a partir de ESTA tabla, y no puede desincronizarse.
    """
    lineas = [
        "# GENERADO POR perfil.py: no editar a mano, se reescribe en cada build.",
        "WP_CAMPOS_PERFIL='%s'" % " ".join(ORDEN),
        "profile_defaults() {",
    ]
    for nombre in ORDEN:
        info = CAMPOS[nombre]
        if nombre == "USE_BATOCERA":
            lineas.append('    USE_BATOCERA="${IS_BATOCERA:-0}"')
            continue
        if info["tipo"] == "entero":
            lineas.append("    %s=%d" % (nombre, info["defecto"]))
        else:
            lineas.append("    %s=%s" % (nombre, _entrecomillar(info["defecto"])))
    lineas.append("}")
    return "\n".join(lineas) + "\n"


def metas(carpeta):
    """Para la vista de biblioteca: gid, favorito, ultima vez y tiempo jugado.

    ESTO LO HACIA UN PARSER PROPIO, el tercero. La biblioteca leia los .conf
    con su propio bucle de "si la linea empieza por FAVORITO=, quitale las
    comillas", que no entiende los escapes ni los valores de varias lineas.
    Mientras solo mire numeros y fechas da igual, pero era una tercera idea de
    lo que es un fichero de perfil conviviendo con esta y con la de bash: la
    clase de sitio donde un cambio de formato se olvida.

    Se lee todo en UNA sola llamada -no un proceso por juego- porque esto
    corre en cada pasada de la biblioteca y con 141 juegos se nota.
    """
    filas = []
    try:
        nombres = sorted(os.listdir(carpeta))
    except OSError:
        return filas
    for nombre in nombres:
        if not nombre.endswith(".conf"):
            continue
        v, _e, _a = cargar(os.path.join(carpeta, nombre))
        filas.append((nombre[:-5], v["FAVORITO"], v["LAST_PLAYED"],
                      v["PLAY_SECONDS"]))
    return filas


def _ruta_de(carpeta, gid):
    return os.path.join(carpeta, "%s.conf" % gid)


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(
            "uso: perfil.py <orden> [...]\n"
            "  cargar   <carpeta> <gid>              asignaciones para bash\n"
            "  guardar  <carpeta> <gid>              lee CAMPO=valor de la entrada\n"
            "  poner    <carpeta> <gid> CAMPO=valor  cambia campos sueltos\n"
            "  ver      <carpeta> <gid> [CAMPO]      imprime un campo o todos\n"
            "  mscoree  <carpeta>                    barrido de limpieza\n"
            "  metas    <carpeta>                    gid<TAB>fav|ultima|segundos\n"
            "  defectos-bash                         profile_defaults() para el build\n"
            "  comprobar [carpeta]                   auto-diagnostico\n")
        return 2

    orden = argv[1]

    if orden == "comprobar":
        fallos = comprobar(argv[2] if len(argv) > 2 else None)
        if fallos:
            sys.stderr.write("perfil.py: %d fallo(s)\n" % len(fallos))
            for f in fallos:
                sys.stderr.write("  - %s\n" % f)
            return 1
        print("perfil.py: todo correcto (%d campos)" % len(ORDEN))
        return 0

    if orden == "metas":
        if len(argv) < 3:
            return 2
        for gid, fav, last, secs in metas(argv[2]):
            print("%s\t%s|%s|%s" % (gid, fav, last, secs))
        return 0

    if orden == "defectos-bash":
        sys.stdout.write(defectos_bash())
        return 0

    if orden == "mscoree":
        n = limpiar_mscoree(argv[2])
        if n:
            sys.stderr.write("Perfiles limpiados de mscoree: %d\n" % n)
        return 0

    if len(argv) < 4:
        sys.stderr.write("perfil.py %s: faltan <carpeta> <gid>\n" % orden)
        return 2
    carpeta, gid = argv[2], argv[3]
    ruta = _ruta_de(carpeta, gid)

    if orden == "cargar":
        valores, extras, avisos = cargar(ruta)
        for a in avisos:
            sys.stderr.write("perfil %s: %s\n" % (gid, a))
        sys.stdout.write(como_shell(valores, extras))
        return 0

    if orden == "ver":
        valores, extras, _ = cargar(ruta)
        if len(argv) > 4:
            campo = argv[4]
            if campo in valores:
                print(valores[campo])
            elif campo in extras:
                print(extras[campo])
            else:
                sys.stderr.write("perfil: no existe el campo %s\n" % campo)
                return 1
            return 0
        sys.stdout.write(volcar(valores, extras, gid))
        return 0

    if orden in ("guardar", "poner"):
        valores, extras, _ = cargar(ruta)
        if orden == "guardar":
            # Los valores llegan por la entrada estandar, uno por linea, para
            # no pasar por la linea de ordenes: hay campos con saltos de linea
            # y con comillas, y ahi se estropearian.
            fuente = sys.stdin.read().splitlines()
        else:
            fuente = argv[4:]
        avisos = []
        for par in fuente:
            if "=" not in par:
                continue
            nombre, bruto = par.split("=", 1)
            nombre = nombre.strip()
            if nombre in CAMPOS:
                valores[nombre] = _normalizar(nombre, bruto, avisos)
            elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", nombre):
                extras[nombre] = bruto
        for a in avisos:
            sys.stderr.write("perfil %s: %s\n" % (gid, a))
        return 0 if guardar(ruta, valores, extras, gid) else 1

    sys.stderr.write("perfil.py: orden desconocida %r\n" % orden)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
