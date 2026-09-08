# -*- coding: utf-8 -*-
"""Mando virtual: presenta al juego un mando distinto del que tienes.

QUE PROBLEMA RESUELVE

Hay juegos que solo leen una parte del mando. El caso que lo motivo: un juego
que solo hace caso al stick izquierdo, asi que la cruceta no sirve para nada.
Con un .keys se puede convertir la cruceta en teclas, pero muchos juegos, al
detectar un mando activo, DEJAN DE LEER EL TECLADO: no llega ni una cosa ni la
otra.

La solucion es no traducir a teclado sino a MANDO: se crea un mando virtual
-un Xbox 360 normal y corriente- y se le copia todo lo del mando fisico, pero
haciendo que la cruceta mueva tambien el stick izquierdo. El juego ve un solo
mando, perfectamente normal, en el que la cruceta funciona.

COMO CONVIVE CON EL RESTO

Esto NO toca el mapeador de teclas: son cosas distintas y pueden usarse a la
vez o por separado. El mapeador convierte el mando en TECLAS; esto convierte
un mando en OTRO MANDO.

El mando fisico se captura (grab) para que el juego no vea los dos a la vez y
se le dupliquen los controles.

USO

    mando_virtual.py <modo> [dispositivo]

        modo         cruceta_stick | copia
        dispositivo  /dev/input/eventN (si no, se busca solo)

Se para con SIGTERM, y al hacerlo suelta el mando fisico.
"""

import errno
import os
import signal
import sys
import time

try:
    import evdev
    from evdev import ecodes
except ImportError:
    sys.stderr.write("mando_virtual: falta python-evdev\n")
    sys.exit(2)


# QUE MANDO FINGIMOS.
#
# Por defecto un Xbox 360, que es el que todos los juegos entienden sin
# configurar nada. Pero hay juegos que se portan mejor con uno de Sony -o que
# simplemente enseñan los botones correctos-, asi que tambien se puede fingir
# un DualShock 4.
#
# Lo que decide como te ve un juego NO es el nombre, sino el par
# vendor/product: es lo que miran SDL y Wine para saber que mando es y que
# iconos dibujar. Por eso se cambian los tres numeros y no solo el texto.
MANDOS = {
    "xbox": ("Microsoft X-Box 360 pad", 0x045E, 0x028E, 0x0114),
    "ds4":  ("Sony Interactive Entertainment Wireless Controller",
             0x054C, 0x09CC, 0x8111),
}
NOMBRE_VIRTUAL = MANDOS["xbox"][0]
VENDOR, PRODUCT, VERSION = MANDOS["xbox"][1:]

# Todos los nombres que puede tener el mando virtual. Hace falta para no
# leernos a nosotros mismos: si lo hicieramos, cada evento volveria a entrar y
# se formaria un bucle.
NOMBRES_VIRTUALES = tuple(v[0] for v in MANDOS.values())

# UN MANDO COMPLETO, no solo lo imprescindible.
#
# Se declara todo lo que un mando moderno puede tener, aunque el fisico no lo
# traiga: declarar de mas no molesta -el juego simplemente nunca recibe ese
# boton- y declarar de MENOS si, porque lo que no esta declarado el kernel lo
# descarta EN SILENCIO. Ese fallo ya nos mordio con los clics del raton.
BOTONES = [
    # Cara
    ecodes.BTN_SOUTH, ecodes.BTN_EAST, ecodes.BTN_NORTH, ecodes.BTN_WEST,
    # Hombros y gatillos como boton (hay juegos que leen esto en vez del eje)
    ecodes.BTN_TL, ecodes.BTN_TR, ecodes.BTN_TL2, ecodes.BTN_TR2,
    # Centrales
    ecodes.BTN_SELECT, ecodes.BTN_START, ecodes.BTN_MODE,
    # Sticks pulsables
    ecodes.BTN_THUMBL, ecodes.BTN_THUMBR,
    # LA CRUCETA COMO BOTONES.
    #
    # Es la que mas cambia de un mando a otro: unos la mandan como eje
    # (ABS_HAT0) y otros como botones. La Steam Deck y las Anbernic la mandan
    # como BOTONES, y ahi ese eje es el TOUCHPAD. Sin declararla asi, esta
    # opcion no funcionaria justo en la Deck.
    ecodes.BTN_DPAD_UP, ecodes.BTN_DPAD_DOWN,
    ecodes.BTN_DPAD_LEFT, ecodes.BTN_DPAD_RIGHT,
    # Paletas traseras y botones extra (la Deck tiene cuatro)
    ecodes.BTN_TRIGGER_HAPPY1, ecodes.BTN_TRIGGER_HAPPY2,
    ecodes.BTN_TRIGGER_HAPPY3, ecodes.BTN_TRIGGER_HAPPY4,
]

# La cruceta cuando llega como BOTON: a que direccion del eje corresponde.
# El primer valor es el eje y el segundo lo que vale al pulsarlo.
DPAD_BOTON = {
    ecodes.BTN_DPAD_UP:    (ecodes.ABS_HAT0Y, -1),
    ecodes.BTN_DPAD_DOWN:  (ecodes.ABS_HAT0Y, 1),
    ecodes.BTN_DPAD_LEFT:  (ecodes.ABS_HAT0X, -1),
    ecodes.BTN_DPAD_RIGHT: (ecodes.ABS_HAT0X, 1),
}

# Rango de los sticks de un Xbox 360. Se declara explicito para que el juego
# calibre igual que con uno de verdad.
EJE_MIN, EJE_MAX = -32768, 32767
GAT_MIN, GAT_MAX = 0, 255

EJES = [
    (ecodes.ABS_X,     (EJE_MIN, EJE_MAX, 16, 128)),
    (ecodes.ABS_Y,     (EJE_MIN, EJE_MAX, 16, 128)),
    (ecodes.ABS_RX,    (EJE_MIN, EJE_MAX, 16, 128)),
    (ecodes.ABS_RY,    (EJE_MIN, EJE_MAX, 16, 128)),
    (ecodes.ABS_Z,     (GAT_MIN, GAT_MAX, 0, 0)),
    (ecodes.ABS_RZ,    (GAT_MIN, GAT_MAX, 0, 0)),
    (ecodes.ABS_HAT0X, (-1, 1, 0, 0)),
    (ecodes.ABS_HAT0Y, (-1, 1, 0, 0)),
]


# UN MANDO DE LOS DE ANTES, para juegos de DirectInput.
#
# De emular DirectInput ya se encarga Wine: cualquier mando de Linux aparece
# ahi. El problema de los juegos viejos es otro: ven un mando DEMASIADO
# moderno y se lian.
#
#   - Los GATILLOS como eje no existian entonces. Un juego de los 90 ve un eje
#     que en reposo esta en un extremo y cree que lo estas empujando: se
#     acelera solo, o el menu se va corriendo hacia un lado.
#   - Muchos solo miran los cuatro primeros ejes.
#   - Y algunos no manejan mas de diez o doce botones.
#
# Este perfil declara lo que tenia un mando de aquella epoca: dos sticks, la
# cruceta como POV, y los gatillos COMO BOTONES, que es lo que eran.
BOTONES_CLASICO = [
    ecodes.BTN_SOUTH, ecodes.BTN_EAST, ecodes.BTN_NORTH, ecodes.BTN_WEST,
    ecodes.BTN_TL, ecodes.BTN_TR, ecodes.BTN_TL2, ecodes.BTN_TR2,
    ecodes.BTN_SELECT, ecodes.BTN_START,
    ecodes.BTN_THUMBL, ecodes.BTN_THUMBR,
]

EJES_CLASICO = [
    (ecodes.ABS_X,     (EJE_MIN, EJE_MAX, 16, 128)),
    (ecodes.ABS_Y,     (EJE_MIN, EJE_MAX, 16, 128)),
    (ecodes.ABS_RX,    (EJE_MIN, EJE_MAX, 16, 128)),
    (ecodes.ABS_RY,    (EJE_MIN, EJE_MAX, 16, 128)),
    (ecodes.ABS_HAT0X, (-1, 1, 0, 0)),
    (ecodes.ABS_HAT0Y, (-1, 1, 0, 0)),
]

# A partir de que punto un gatillo cuenta como pulsado, cuando se convierte en
# boton. La mitad del recorrido: ni un roce ni hay que hundirlo del todo.
GATILLO_UMBRAL = (GAT_MAX - GAT_MIN) // 2


def capacidades(clasico=False):
    """Lo que el mando virtual dice saber hacer."""
    botones = BOTONES_CLASICO if clasico else BOTONES
    ejes = EJES_CLASICO if clasico else EJES
    abs_caps = []
    for codigo, (mn, mx, fuzz, flat) in ejes:
        abs_caps.append((codigo, evdev.AbsInfo(value=0, min=mn, max=mx,
                                               fuzz=fuzz, flat=flat,
                                               resolution=0)))
    return {ecodes.EV_KEY: botones, ecodes.EV_ABS: abs_caps}


# EL MODO ESCRITORIO DE STEAM, TRADUCIDO DE VUELTA A MANDO.
#
# Steam trae dos "modos de accion". En el de ESCRITORIO los botones no mandan
# botones de mando: mandan TECLADO Y RATON. Es lo que llaman "modo lagarto", y
# la tabla por defecto esta documentada:
#
#     A -> Enter        Y -> Espacio      Cruceta -> flechas
#     B -> Escape       R2 -> clic izq.   L2 -> clic der.
#
# Un juego que espere un mando no recibe NADA, aunque el mando se vea
# perfectamente. Se cambia manteniendo Start, pero eso hay que saberlo: aqui
# se traduce de vuelta y ya.
#
# (La X abre el teclado en pantalla, que es una accion interna de Steam y no
# manda ninguna tecla: esa no se puede recuperar.)
TECLA_A_BOTON = {
    ecodes.KEY_ENTER:      ecodes.BTN_SOUTH,
    ecodes.KEY_KPENTER:    ecodes.BTN_SOUTH,
    ecodes.KEY_ESC:        ecodes.BTN_EAST,
    ecodes.KEY_SPACE:      ecodes.BTN_NORTH,
    ecodes.KEY_TAB:        ecodes.BTN_SELECT,
}

# Las flechas van a la cruceta: eje y boton, como todo lo demas.
TECLA_A_CRUCETA = {
    ecodes.KEY_UP:    (ecodes.ABS_HAT0Y, -1, ecodes.BTN_DPAD_UP),
    ecodes.KEY_DOWN:  (ecodes.ABS_HAT0Y, 1,  ecodes.BTN_DPAD_DOWN),
    ecodes.KEY_LEFT:  (ecodes.ABS_HAT0X, -1, ecodes.BTN_DPAD_LEFT),
    ecodes.KEY_RIGHT: (ecodes.ABS_HAT0X, 1,  ecodes.BTN_DPAD_RIGHT),
}

# Los clics son los gatillos.
RATON_A_BOTON = {
    ecodes.BTN_LEFT:  (ecodes.ABS_RZ, ecodes.BTN_TR2),
    ecodes.BTN_RIGHT: (ecodes.ABS_Z,  ecodes.BTN_TL2),
}

VENDOR_STEAM = 0x28DE


def es_teclado_de_steam(dev):
    """¿Es el teclado VIRTUAL que crea Steam, y no el del usuario?

    Esto importa mucho: para traducir el modo escritorio hay que leer -y
    capturar- un teclado. Capturar el teclado DE VERDAD dejaria al usuario sin
    poder escribir, asi que solo se toca si es de Steam.

    Se mira el fabricante, 0x28DE, que es el unico dato fiable.
    """
    try:
        if dev.info.vendor != VENDOR_STEAM:
            return False
        caps = dev.capabilities()
    except (OSError, IOError):
        return False
    teclas = caps.get(ecodes.EV_KEY) or []
    # Un teclado tiene letras; un mando no.
    return ecodes.KEY_A in teclas or ecodes.KEY_ENTER in teclas


def es_mando(dev):
    """¿Este dispositivo es un mando y no un teclado o un raton?

    Se mira que tenga botones DE MANDO y ejes: un teclado tiene teclas pero no
    ejes, y un raton tiene ejes relativos, no absolutos.
    """
    try:
        caps = dev.capabilities()
    except (OSError, IOError):
        return False
    teclas = caps.get(ecodes.EV_KEY) or []
    ejes = [e[0] if isinstance(e, tuple) else e
            for e in (caps.get(ecodes.EV_ABS) or [])]
    tiene_boton = (ecodes.BTN_SOUTH in teclas or ecodes.BTN_A in teclas
                   or ecodes.BTN_GAMEPAD in teclas)
    # Un mando cuya cruceta son BOTONES puede no tener ABS_HAT0, y uno de
    # cruceta sin sticks puede no tener ABS_X. Vale cualquiera de las tres
    # señales: exigir una concreta dejaria fuera mandos que si lo son.
    tiene_eje = (ecodes.ABS_X in ejes or ecodes.ABS_HAT0X in ejes
                 or ecodes.BTN_DPAD_UP in teclas)
    return tiene_boton and tiene_eje


def buscar_mando():
    """El primer mando legible del sistema, saltando el nuestro.

    Saltar el virtual es importante: si nos leyeramos a nosotros mismos, cada
    evento volveria a entrar y se formaria un bucle.
    """
    for ruta in sorted(evdev.list_devices()):
        try:
            dev = evdev.InputDevice(ruta)
        except (OSError, IOError):
            continue
        if dev.name in NOMBRES_VIRTUALES:
            dev.close()
            continue
        if es_mando(dev):
            return dev
        dev.close()
    return None


def cruceta_a_stick(valor_hat, eje_actual):
    """El valor de stick que corresponde a una cruceta pulsada.

    La cruceta es -1, 0 o 1. El stick va de -32768 a 32767. Se manda el
    extremo, que es lo que hace un jugador al empujar el stick del todo.

    Si el stick FISICO ya esta movido, manda el stick: quien lo esta usando
    no quiere que la cruceta le corrija la direccion.
    """
    if abs(eje_actual) > 8000:
        return eje_actual
    if valor_hat < 0:
        return EJE_MIN
    if valor_hat > 0:
        return EJE_MAX
    return 0


def traducir_escritorio(virtual, teclados):
    """Lee los teclados virtuales de Steam y emite MANDO. Nunca vuelve.

    Se usa selectors en vez de un read_loop por dispositivo porque Steam crea
    varios -teclado y raton van separados- y hay que atenderlos a la vez.
    """
    import selectors

    sel = selectors.DefaultSelector()
    for d in teclados:
        sel.register(d, selectors.EVENT_READ)

    while True:
        for clave, _ in sel.select():
            for ev in clave.fileobj.read():
                if ev.type != ecodes.EV_KEY:
                    continue
                valor = 1 if ev.value else 0

                if ev.code in TECLA_A_BOTON:
                    virtual.write(ecodes.EV_KEY, TECLA_A_BOTON[ev.code], valor)
                    virtual.syn()
                    continue

                if ev.code in TECLA_A_CRUCETA:
                    eje, direccion, boton = TECLA_A_CRUCETA[ev.code]
                    virtual.write(ecodes.EV_ABS, eje,
                                  direccion if valor else 0)
                    virtual.write(ecodes.EV_KEY, boton, valor)
                    virtual.syn()
                    continue

                if ev.code in RATON_A_BOTON:
                    # Los clics son los gatillos: se manda el eje al maximo y
                    # el boton, porque unos juegos leen uno y otros el otro.
                    eje, boton = RATON_A_BOTON[ev.code]
                    virtual.write(ecodes.EV_ABS, eje, GAT_MAX if valor else 0)
                    virtual.write(ecodes.EV_KEY, boton, valor)
                    virtual.syn()


def main():
    modo = sys.argv[1] if len(sys.argv) > 1 else "cruceta_stick"
    # El modo clasico lleva sufijo, para poder combinarlo:
    #   cruceta_stick            mando moderno, cruceta al stick
    #   clasico                  mando de los de antes, tal cual
    #   clasico_cruceta_stick    de los de antes y ademas cruceta al stick
    clasico = modo.startswith("clasico")
    cruceta_al_stick = modo.endswith("cruceta_stick")
    # Que mando fingir. "ds4" en cualquier parte del modo: asi se combina con
    # lo demas sin inventar una lista de modos por cada cruce. Cualquier otra
    # cosa -"xbox", "cruceta_stick", "clasico"...- es un Xbox, que es el que
    # todos los juegos entienden.
    tipo = "ds4" if "ds4" in modo else "xbox"
    nombre, vendor, product, version = MANDOS[tipo]
    ruta = sys.argv[2] if len(sys.argv) > 2 else ""

    # MODO ESCRITORIO: se leen los teclados virtuales de Steam, no un mando.
    if modo.startswith("escritorio"):
        teclados = []
        for r in sorted(evdev.list_devices()):
            try:
                d = evdev.InputDevice(r)
            except (OSError, IOError):
                continue
            if es_teclado_de_steam(d):
                teclados.append(d)
            else:
                d.close()
        if not teclados:
            sys.stderr.write("mando_virtual: no hay teclado virtual de Steam;"
                             " el modo escritorio no aplica aqui\n")
            return 1
        try:
            virtual = evdev.UInput(capacidades(False), name=NOMBRE_VIRTUAL,
                                   vendor=VENDOR, product=PRODUCT,
                                   version=VERSION)
        except (OSError, IOError) as e:
            sys.stderr.write("mando_virtual: no se pudo crear (%s)\n" % e)
            return 1
        # Se capturan para que el juego no reciba ADEMAS las teclas: si no,
        # cada boton contaria dos veces (una como tecla y otra como boton).
        for d in teclados:
            try:
                d.grab()
            except (OSError, IOError):
                pass

        def soltar_esc(*_):
            for dd in teclados:
                try:
                    dd.ungrab()
                except (OSError, IOError):
                    pass
            try:
                virtual.close()
            except Exception:
                pass
            print("[mando] traductor del modo escritorio retirado", flush=True)
            sys.exit(0)

        signal.signal(signal.SIGTERM, soltar_esc)
        signal.signal(signal.SIGINT, soltar_esc)
        print("[mando] Modo escritorio de Steam -> mando (%d dispositivo(s))"
              % len(teclados), flush=True)
        try:
            traducir_escritorio(virtual, teclados)
        except (OSError, IOError) as e:
            sys.stderr.write("mando_virtual: se perdio el teclado (%s)\n" % e)
        soltar_esc()

    if ruta:
        try:
            fisico = evdev.InputDevice(ruta)
        except (OSError, IOError) as e:
            sys.stderr.write("mando_virtual: no se puede abrir %s (%s)\n"
                             % (ruta, e))
            return 1
    else:
        fisico = buscar_mando()
    if fisico is None:
        sys.stderr.write("mando_virtual: no hay ningun mando que leer\n")
        return 1

    try:
        virtual = evdev.UInput(capacidades(clasico), name=nombre,
                               vendor=vendor, product=product,
                               version=version)
    except (OSError, IOError) as e:
        if getattr(e, "errno", None) in (errno.EACCES, errno.EPERM):
            sys.stderr.write("mando_virtual: sin permiso para /dev/uinput\n")
        else:
            sys.stderr.write("mando_virtual: no se pudo crear (%s)\n" % e)
        return 1

    # El fisico se captura: si no, el juego veria DOS mandos y cada boton
    # contaria dos veces.
    capturado = False
    try:
        fisico.grab()
        capturado = True
    except (OSError, IOError) as e:
        sys.stderr.write("mando_virtual: no se pudo capturar el mando (%s);"
                         " el juego puede ver los dos\n" % e)

    print('[mando] "%s" -> %s (%s)' % (fisico.name, nombre, modo), flush=True)

    def soltar(*_):
        try:
            if capturado:
                fisico.ungrab()
        except (OSError, IOError):
            pass
        try:
            virtual.close()
        except Exception:
            pass
        print("[mando] mando virtual retirado", flush=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, soltar)
    signal.signal(signal.SIGINT, soltar)

    # Estado de los ejes fisicos, para saber si el stick esta en uso cuando
    # llega la cruceta.
    ejes = {ecodes.ABS_X: 0, ecodes.ABS_Y: 0}
    hat = {ecodes.ABS_HAT0X: 0, ecodes.ABS_HAT0Y: 0}

    try:
        for ev in fisico.read_loop():
            if ev.type == ecodes.EV_KEY:
                virtual.write(ecodes.EV_KEY, ev.code, ev.value)
                # LA CRUCETA QUE LLEGA COMO BOTON.
                #
                # En la Steam Deck y las Anbernic la cruceta no es un eje: son
                # cuatro botones. Sin esto, en esos mandos la opcion no haria
                # nada, que es justo donde mas falta hace.
                #
                # Se manda ademas como EJE, para que el juego la vea de las
                # dos formas, y se mueve el stick igual que con la otra.
                if ev.code in DPAD_BOTON:
                    # SIEMPRE de las dos formas, se pida o no lo del stick.
                    #
                    # Esto estaba dentro del "si se ha pedido la cruceta al
                    # stick", y era un error: en una Steam Deck la cruceta son
                    # botones, asi que sin esto llegaria SOLO como boton y un
                    # juego que espere el eje -que son casi todos- seguiria
                    # sin verla. Emular el mando bien es precisamente esto.
                    eje, direccion = DPAD_BOTON[ev.code]
                    valor = direccion if ev.value else 0
                    hat[eje] = valor
                    virtual.write(ecodes.EV_ABS, eje, valor)
                    # Y mover el stick, eso si, solo si se ha pedido.
                    if cruceta_al_stick:
                        destino = (ecodes.ABS_X if eje == ecodes.ABS_HAT0X
                                   else ecodes.ABS_Y)
                        virtual.write(ecodes.EV_ABS, destino,
                                      cruceta_a_stick(valor,
                                                      ejes.get(destino, 0)))
                virtual.syn()
                continue

            if ev.type != ecodes.EV_ABS:
                continue

            if ev.code in (ecodes.ABS_X, ecodes.ABS_Y):
                ejes[ev.code] = ev.value

            if ev.code in hat:
                hat[ev.code] = ev.value
                virtual.write(ecodes.EV_ABS, ev.code, ev.value)
                # Y TAMBIEN COMO BOTONES, que es la otra forma de leerla.
                #
                # Un mando manda la cruceta de una forma u otra, pero el juego
                # puede esperar cualquiera de las dos. Emular el mando bien es
                # ofrecer las dos y que el juego coja la que entienda.
                for _btn, (_eje, _dir) in DPAD_BOTON.items():
                    if _eje != ev.code:
                        continue
                    virtual.write(ecodes.EV_KEY, _btn,
                                  1 if ev.value == _dir else 0)
                if cruceta_al_stick:
                    destino = (ecodes.ABS_X if ev.code == ecodes.ABS_HAT0X
                               else ecodes.ABS_Y)
                    virtual.write(ecodes.EV_ABS, destino,
                                  cruceta_a_stick(ev.value,
                                                  ejes.get(destino, 0)))
                virtual.syn()
                continue

            # LOS GATILLOS, EN MODO CLASICO, SE MANDAN COMO BOTON.
            #
            # En un mando de aquella epoca los gatillos eran botones. Si se
            # mandan como eje, el juego ve uno que en reposo esta en un
            # extremo y cree que lo estas empujando: se acelera solo.
            if clasico and ev.code in (ecodes.ABS_Z, ecodes.ABS_RZ):
                boton = (ecodes.BTN_TL2 if ev.code == ecodes.ABS_Z
                         else ecodes.BTN_TR2)
                virtual.write(ecodes.EV_KEY, boton,
                              1 if ev.value > GATILLO_UMBRAL else 0)
                virtual.syn()
                continue
            # Y un eje que este mando no declara no se manda: el kernel lo
            # descartaria igualmente, pero asi queda dicho.
            if clasico and ev.code not in [c for c, _ in EJES_CLASICO]:
                continue

            # Cualquier otro eje se copia tal cual.
            virtual.write(ecodes.EV_ABS, ev.code, ev.value)
            # Si el stick vuelve al centro pero la cruceta sigue pulsada, se
            # mantiene la direccion de la cruceta: si no, soltar el stick
            # anularia la cruceta.
            if (cruceta_al_stick
                    and ev.code in (ecodes.ABS_X, ecodes.ABS_Y)
                    and abs(ev.value) <= 8000):
                origen = (ecodes.ABS_HAT0X if ev.code == ecodes.ABS_X
                          else ecodes.ABS_HAT0Y)
                if hat.get(origen):
                    virtual.write(ecodes.EV_ABS, ev.code,
                                  cruceta_a_stick(hat[origen], 0))
            virtual.syn()
    except (OSError, IOError) as e:
        sys.stderr.write("mando_virtual: se perdio el mando (%s)\n" % e)
        soltar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
