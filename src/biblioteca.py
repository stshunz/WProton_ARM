# -*- coding: utf-8 -*-
# WProton - composicion rapida de la biblioteca
#
# Copyright (C) 2026  stshunz y colaboradores
#
# Este programa es software libre: puedes redistribuirlo y/o modificarlo bajo
# los terminos de la Licencia Publica General GNU (GPL), version 3 o
# posterior, publicada por la Free Software Foundation.
#
# Se distribuye SIN NINGUNA GARANTIA. Ver <https://www.gnu.org/licenses/>.
"""Construye la lista de la biblioteca de UNA sola vez.

Antes esto lo hacia bash llamando a varias funciones por cada juego. Cada
llamada cuesta poco, pero con 141 juegos son miles, y en una Steam Deck eso
eran decenas de segundos de espera al abrir la lista.

Aqui se hace todo en una pasada: se leen los perfiles, se buscan las
caratulas y se compone cada fila. Bash solo lee el resultado.

Uso:
    biblioteca.py <fichero_mapa> <fichero_info> < lista_de_juegos
    biblioteca.py --rejilla <fichero_manifiesto> < lista_de_juegos

Vista de lista, escribe:
    - fichero_mapa:  etiqueta<TAB>ruta       (para volver de la etiqueta a la ruta)
    - fichero_info:  etiqueta|caratula|fav|veces|segundos|ficha|duracion|
                     completado|ficha_rawg
    - por pantalla:  una etiqueta por linea, en el mismo orden

Vista de rejilla, escribe:
    - manifiesto:    etiqueta|caratula|ruta|fav

La etiqueta de la rejilla lleva dentro el tiempo jugado y la fecha de la
ultima partida, y la forma de la caratula la manda WP_GRID_FORMA en vez de
LIST_COVER (cada vista de rejilla usa una distinta).

Las reglas (identificador, etiqueta, busqueda de caratula) son las mismas que
usa wproton.sh; si se cambian alli, hay que cambiarlas aqui.
"""
import os
import sys

EXTS_IMAGEN = ('png', 'jpg', 'jpeg', 'webp')
EXTS_EMPAQUETADO = ('.wsquashfs', '.squashfs', '.dwarfs')


def entorno(nombre, por_defecto=''):
    return os.environ.get(nombre, por_defecto)


def game_id(ruta):
    """Identificador del juego: como lo calcula wproton.sh."""
    gid = os.path.basename(ruta.rstrip('/'))
    if not os.path.isdir(ruta):
        gid = os.path.splitext(gid)[0]
    return gid.replace(' ', '_').replace('/', '_')


def etiqueta(ruta, raices):
    """Como se ve el juego en la lista: sin la extension del empaquetado.

    Si hay varias carpetas de juegos, se anade de cual viene, para poder
    distinguir dos juegos con el mismo nombre.
    """
    nom = os.path.basename(ruta.rstrip('/'))
    # Distinguiendo mayusculas, igual que el "case" de wproton.sh: un
    # Juego.WSQUASHFS puesto a mano conserva su extension en los dos caminos.
    # Si algun dia se acepta la mayuscula, hay que cambiarlo en los dos sitios.
    for ext in EXTS_EMPAQUETADO:
        if nom.endswith(ext):
            nom = nom[:-len(ext)]
            break
    if len(raices) > 1:
        for r in raices:
            if r and (ruta + '/').startswith(r.rstrip('/') + '/'):
                base = os.path.basename(r.rstrip('/'))
                if base:
                    return '%s   (%s)' % (nom, base)
                break
    return nom


def nombres_posibles(gid):
    """Nombres con los que puede estar guardada la caratula.

    El identificador cambia los espacios por guiones bajos; quien copia su
    coleccion a mano conserva los espacios. Se prueban las dos formas.

    Y TAMBIEN SIN LA EXTENSION DE LA CARPETA: game_id se la quita a los
    ficheros pero no a las carpetas, asi que un juego en "Alien Stars.pc"
    tiene el identificador "Alien_Stars.pc" mientras que su caratula se llama
    "Alien Stars.png", sin el .pc. Sin esto, los juegos en carpeta no
    encontraban ni su propia caratula en covers/.
    """
    vistos = []
    base = gid
    sin_ext = gid.rsplit('.', 1)[0] if '.' in gid else gid
    for g in (base, sin_ext):
        if not g or g in vistos:
            continue
        vistos.append(g)
        yield g
        con_espacios = g.replace('_', ' ')
        if con_espacios != g and con_espacios not in vistos:
            vistos.append(con_espacios)
            yield con_espacios


# Sufijos con los que el escaneo de ES-DE guarda cada forma de caratula.
SUFIJOS_ESCANEO = {
    'wide': ('-fanart', '-screenshot', '-titlescreen', '-image'),
    '43':   ('-screenshot', '-titlescreen', '-image'),
}
SUFIJOS_ESCANEO_VERTICAL = ('-cover', '-box2dfront', '-boxart', '-thumb',
                            '-image')
CARPETAS_ESCANEO = ('images', 'media', 'downloaded_images', 'covers', 'boxart')


def buscar_cover_escaneo(ruta, forma):
    """Caratula del escaneo de ES-DE que este junto al juego.

    Quien viene de Batocera o ES-DE ya tiene sus caratulas ahi. Esto ya estaba
    en la version en bash, pero la biblioteca RAPIDA -que es la que se usa de
    verdad- no lo hacia: los juegos en carpeta .pc seguian saliendo sin
    caratula.

    El nombre se prueba con y sin extension: una carpeta se llama "Juego.pc"
    pero el escaneo guarda "Juego-image.png".
    """
    if not ruta:
        return ''
    carpeta = os.path.dirname(ruta)
    if not carpeta or not os.path.isdir(carpeta):
        return ''
    base = os.path.basename(ruta)
    bases = [base]
    sin_ext = os.path.splitext(base)[0]
    if sin_ext != base:
        bases.append(sin_ext)

    sufijos = SUFIJOS_ESCANEO.get(forma, SUFIJOS_ESCANEO_VERTICAL) + ('',)
    for sub in CARPETAS_ESCANEO:
        dir_esc = os.path.join(carpeta, sub)
        if not os.path.isdir(dir_esc):
            continue
        for b in bases:
            for nom in nombres_posibles(b):
                for suf in sufijos:
                    for ext in EXTS_IMAGEN:
                        p = os.path.join(dir_esc, '%s%s.%s' % (nom, suf, ext))
                        if os.path.isfile(p):
                            return p
    return ''


def buscar_cover_exacta(gid, carpeta):
    """La caratula de la forma pedida, SIN el apaño de usar la vertical.

    Es el equivalente de cover_exacta() en wproton.sh, y hace falta por lo
    mismo: buscar_cover, si le pides la panoramica y no la hay, devuelve la
    vertical -mejor deformada que un hueco-. Muy comodo para dibujar, pero
    tapa lo que pueda haber en el escaneo: quien tuviera ahi una panoramica DE
    VERDAD veia nuestra vertical estirada en su lugar.

    Aqui se pregunta por la forma exacta y ya.
    """
    if not carpeta or not os.path.isdir(carpeta):
        return ''
    for nom in nombres_posibles(gid):
        for ext in EXTS_IMAGEN:
            p = os.path.join(carpeta, '%s.%s' % (nom, ext))
            if os.path.isfile(p):
                return p
    return ''


def buscar_cover(gid, carpeta, carpeta_vertical, legacy_wide=False):
    """Ruta de la caratula, o cadena vacia."""
    for nom in nombres_posibles(gid):
        for ext in EXTS_IMAGEN:
            p = os.path.join(carpeta, '%s.%s' % (nom, ext))
            if os.path.isfile(p):
                return p
    if legacy_wide:                      # nomenclatura anterior: <juego>.wide.*
        # Solo el identificador, sin la forma con espacios: es lo que hace
        # cover_for. Aqui no se prueban las dos formas a proposito.
        for ext in EXTS_IMAGEN:
            p = os.path.join(carpeta_vertical, '%s.wide.%s' % (gid, ext))
            if os.path.isfile(p):
                return p
    if carpeta != carpeta_vertical:      # respaldo: la vertical de siempre
        for nom in nombres_posibles(gid):
            for ext in EXTS_IMAGEN:
                p = os.path.join(carpeta_vertical, '%s.%s' % (nom, ext))
                if os.path.isfile(p):
                    return p
    return ''


SIN_PERFIL = ('0', '0', '0', '', '0')


def leer_perfiles(carpeta):
    """Todos los perfiles: gid -> (fav, veces, segundos, ultima, completado)."""
    datos = {}
    try:
        ficheros = [f for f in os.listdir(carpeta) if f.endswith('.conf')]
    except OSError:
        return datos
    for f in ficheros:
        fav, veces, segs, ultima, completado = '0', '0', '0', '', '0'
        try:
            with open(os.path.join(carpeta, f), encoding='utf-8',
                      errors='replace') as fh:
                for linea in fh:
                    if linea.startswith('FAVORITO='):
                        fav = linea.split('=', 1)[1].strip().strip('"')
                    elif linea.startswith('PLAY_COUNT='):
                        veces = linea.split('=', 1)[1].strip().strip('"')
                    elif linea.startswith('PLAY_SECONDS='):
                        segs = linea.split('=', 1)[1].strip().strip('"')
                    elif linea.startswith('LAST_PLAYED='):
                        ultima = linea.split('=', 1)[1].strip().strip('"')
                    elif linea.startswith('COMPLETADO='):
                        completado = linea.split('=', 1)[1].strip().strip('"')
        except OSError:
            continue
        datos[f[:-5]] = (fav or '0', veces or '0', segs or '0', ultima,
                         completado or '0')
    return datos


def fmt_playtime(segundos):
    """segundos -> "3 h 12 min" / "45 min" / "<1 min". Como fmt_playtime()."""
    horas, minutos = segundos // 3600, (segundos % 3600) // 60
    if horas > 0:
        return '%d h %d min' % (horas, minutos)
    if minutos > 0:
        return '%d min' % minutos
    return '<1 min'


def etiqueta_rejilla(ruta, raices):
    """La etiqueta de la rejilla: como la de la lista y, ademas, los tres
    recortes que hacia el bucle de bash por si la extension seguia ahi."""
    t = etiqueta(ruta, raices)
    corte = t.rfind('.wsquashfs')          # "${t2%.wsquashfs*}"
    if corte >= 0:
        t = t[:corte]
    for ext in ('.squashfs', '.dwarfs'):   # "${t2%.squashfs}" y "${t2%.dwarfs}"
        if t.endswith(ext):
            t = t[:-len(ext)]
    return t


def carpetas_de_covers(forma):
    """(carpeta de esa forma, carpeta vertical) para buscar_cover."""
    vertical = entorno('COVERS_DIR')
    carpeta = {
        'wide': entorno('COVERS_WIDE_DIR'),
        '43': entorno('COVERS_43_DIR'),
    }.get(forma, vertical) or vertical
    return carpeta, vertical


def rejilla(f_manifiesto, juegos, raices, perfiles):
    """Una fila por juego: etiqueta|caratula|ruta|fav."""
    forma = entorno('WP_GRID_FORMA', 'vertical')
    carpeta_cover, covers = carpetas_de_covers(forma)
    filas = []
    for ruta in juegos:
        etq = etiqueta_rejilla(ruta, raices)
        gid = game_id(ruta)
        # LA FORMA EXACTA MANDA, VENGA DE DONDE VENGA.
        #
        # Tres pasos, y en este orden (los mismos que rejilla_lenta):
        #
        #   1. la caratula de la forma pedida en NUESTRA carpeta;
        #   2. la de la forma pedida en el escaneo que este junto al juego;
        #   3. y solo si no aparece, el apaño: la nomenclatura anterior
        #      (covers/<juego>.wide.*) y, en ultimo lugar, la vertical.
        #
        # Antes aqui se llamaba directo a buscar_cover, que YA cae a la
        # vertical, asi que el paso 2 no se alcanzaba nunca: quien tenia una
        # panoramica de verdad en el escaneo veia nuestra vertical estirada.
        # La via lenta hacia lo correcto y esta no, y esta es la que se usa.
        #
        # Con forma vertical los tres pasos miran la misma carpeta, asi que el
        # resultado no cambia; el arreglo solo afecta a "wide" y "43".
        cov = buscar_cover_exacta(gid, carpeta_cover)
        if not cov:
            cov = buscar_cover_escaneo(ruta, forma)
        if not cov:
            cov = buscar_cover(gid, carpeta_cover, covers,
                               legacy_wide=(forma == 'wide'))
        fav, _veces, segs, ultima, _comp = perfiles.get(gid, SIN_PERFIL)

        info = ''
        try:                               # bash: [ "$sc" -gt 0 ] 2>/dev/null
            if int(segs) > 0:
                info = fmt_playtime(int(segs))
        except ValueError:
            pass
        if ultima:
            # Solo la fecha, sin la hora: la hora no cabe y ademas el ' - '
            # separa las dos cosas. OJO con las barras verticales.
            info = (info + ' - ' if info else '') + ultima.split(' ')[0]
        if info:
            etq = '%s   [%s]' % (etq, info)
        # El separador es sagrado: si una fecha o un nombre cuela un '|', la
        # fila se parte y el juego se queda sin caratula.
        etq = etq.replace('|', '/')

        filas.append('%s|%s|%s|%s' % (etq, cov, ruta, fav or '0'))

    with open(f_manifiesto, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(filas) + ('\n' if filas else ''))
    return 0


def main():
    if len(sys.argv) < 3:
        sys.stderr.write('uso: biblioteca.py <mapa> <info>\n'
                         '     biblioteca.py --rejilla <manifiesto>\n')
        return 2

    perfiles = leer_perfiles(entorno('PROFILE_DIR'))
    raices = [r for r in entorno('WP_RAICES', '').split('\n') if r.strip()]
    juegos = [l.rstrip('\n') for l in sys.stdin if l.strip()]

    if sys.argv[1] == '--rejilla':
        return rejilla(sys.argv[2], juegos, raices, perfiles)

    f_mapa, f_info = sys.argv[1], sys.argv[2]

    forma = entorno('LIST_COVER', 'vertical')
    carpeta_cover, covers = carpetas_de_covers(forma)
    datos_dir = entorno('DATOS_DIR')

    vistas = set()
    lineas_mapa, lineas_info, etiquetas = [], [], []

    for ruta in juegos:
        etq = etiqueta(ruta, raices)
        # dos juegos pueden quedar con la misma etiqueta al quitar la
        # extension: el segundo conserva su nombre completo
        if etq in vistas:
            etq = os.path.basename(ruta.rstrip('/'))
        vistas.add(etq)

        gid = game_id(ruta)
        cov = buscar_cover(gid, carpeta_cover, covers,
                           legacy_wide=(forma == 'wide'))
        # Si no hay caratula nuestra, la del escaneo que este junto al juego.
        # La nuestra manda: quien pone una en covers/ quiere esa.
        if not cov:
            cov = buscar_cover_escaneo(ruta, forma)
        fav, veces, segs, _ultima, completado = perfiles.get(gid, SIN_PERFIL)

        ficha = os.path.join(datos_dir, '%s.info.json' % gid)
        ficha = ficha if (datos_dir and os.path.isfile(ficha)
                          and os.path.getsize(ficha) > 0) else ''
        dur = os.path.join(datos_dir, '%s.hltb' % gid)
        dur = dur if (datos_dir and os.path.isfile(dur)
                      and os.path.getsize(dur) > 0) else ''
        # RAWG va en su propio fichero: mezclarlo con el de Steam haria
        # imposible saber de donde vino cada dato.
        rawg = os.path.join(datos_dir, '%s.rawg.json' % gid)
        rawg = rawg if (datos_dir and os.path.isfile(rawg)
                        and os.path.getsize(rawg) > 0) else ''

        lineas_mapa.append('%s\t%s' % (etq, ruta))
        lineas_info.append('%s|%s|%s|%s|%s|%s|%s|%s|%s'
                           % (etq, cov, fav, veces, segs, ficha, dur,
                              completado, rawg))
        etiquetas.append(etq)

    with open(f_mapa, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lineas_mapa) + ('\n' if lineas_mapa else ''))
    with open(f_info, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lineas_info) + ('\n' if lineas_info else ''))
    sys.stdout.write('\n'.join(etiquetas) + ('\n' if etiquetas else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
