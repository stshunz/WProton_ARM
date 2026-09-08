#!/usr/bin/env bash
# WProton - generador de wproton.sh
#
# Copyright (C) 2026  stshunz y colaboradores
#
# Este programa es software libre: puedes redistribuirlo y/o modificarlo bajo
# los terminos de la Licencia Publica General GNU (GPL), version 3 o
# posterior, publicada por la Free Software Foundation.
#
# Se distribuye SIN NINGUNA GARANTIA. Ver <https://www.gnu.org/licenses/>.
# ----------------------------------------------------------------------------
# build.sh - genera wproton.sh a partir de wproton.base.sh y src/
#
#   ./build.sh              genera wproton.sh (pasando la auditoria antes)
#   ./build.sh --check      comprueba que el generado coincide con el actual
#   ./build.sh --extract F  vuelca los .py de un wproton.sh ya hecho a src/
#   ./build.sh --sin-auditar  genera sin auditar (para pruebas rapidas)
#
# El usuario final sigue descargando UN SOLO fichero: wproton.sh. Aquí dentro
# trabajamos con Python de verdad (con resaltado, linter y depurador) y este
# script se encarga de volver a montarlo todo.
# ----------------------------------------------------------------------------
set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
BASE="$AQUI/wproton.base.sh"
SRC="$AQUI/src"
SALIDA="${SALIDA:-$AQUI/wproton.sh}"

rojo()  { printf '\033[31m%s\033[0m\n' "$1" >&2; }
verde() { printf '\033[32m%s\033[0m\n' "$1"; }
info()  { printf '  %s\n' "$1"; }

# ---------------------------------------------------------------------------
# Marca de versión de cada helper, calculada del CONTENIDO.
#
# El script regenera runtime/menu_pygame.py solo si la marca cambió. Antes se
# escribía a mano (WPROTON_HELPER_V47) y más de una vez se nos olvidó subirla:
# el usuario se quedaba con el helper viejo y el fallo era invisible. Con una
# suma de comprobación eso no puede pasar.
# ---------------------------------------------------------------------------
marca_de() {
    local f="$1"
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$f" | cut -c1-12
    else
        cksum "$f" | awk '{print $1}'
    fi
}

comprobar_python() {
    local py="${PYTHON:-python3}" f err=0
    command -v "$py" >/dev/null 2>&1 || { info "sin $py: no se comprueba la sintaxis"; return 0; }
    for f in "$SRC"/*.py; do
        [ -f "$f" ] || continue
        if ! "$py" -m py_compile "$f" 2>/tmp/build_py_err; then
            rojo "ERROR de sintaxis en $(basename "$f"):"
            sed 's/^/    /' /tmp/build_py_err >&2
            err=1
        fi
    done
    rm -rf "$SRC/__pycache__" /tmp/build_py_err 2>/dev/null || true
    return $err
}

comprobar_json() {
    local py="${PYTHON:-python3}" f
    command -v "$py" >/dev/null 2>&1 || return 0
    for f in "$SRC"/lang/*.json; do
        [ -f "$f" ] || continue
        if ! "$py" -c "import json,sys; json.load(open(sys.argv[1],encoding='utf-8'))" "$f" 2>/dev/null; then
            rojo "ERROR: $(basename "$f") no es JSON válido"
            return 1
        fi
    done
    return 0
}

auditar() {
    [ -f "$AQUI/auditar.py" ] || return 0
    case " $* " in *" --sin-auditar "*) return 0 ;; esac
    "${PYTHON:-python3}" "$AQUI/auditar.py" || {
        rojo "La auditoria encontro fallos: corrigelos o usa --sin-auditar"
        return 1
    }
    return 0
}

generar() {
    [ -f "$BASE" ] || { rojo "Falta $BASE"; exit 1; }
    comprobar_python || exit 1
    comprobar_json   || exit 1
    auditar "$@"     || exit 1

    local tmp; tmp="$(mktemp)"
    local linea nombre f marca n=0
    while IFS= read -r linea; do
        case "$linea" in
            "@@INCLUIR:"*"@@")
                nombre="${linea#@@INCLUIR:}"; nombre="${nombre%@@}"
                f="$SRC/$nombre"
                [ -f "$f" ] || { rojo "Falta $f"; exit 1; }
                marca="$(marca_de "$f")"
                # marca de version al principio del fichero generado
                printf '# WPROTON_HELPER %s %s\n' "$nombre" "$marca" >> "$tmp"
                cat "$f" >> "$tmp"
                n=$((n+1))
                info "incluido $nombre ($(wc -l < "$f") líneas, marca $marca)" ;;
            "@@INCLUIR_DEFECTOS@@")
                # Los valores por defecto de bash salen del esquema de
                # perfil.py, no de una copia escrita a mano.
                f="$SRC/perfil.py"
                [ -f "$f" ] || { rojo "Falta $f"; exit 1; }
                "${PYTHON:-python3}" "$f" defectos-bash >> "$tmp" \
                    || { rojo "perfil.py defectos-bash fallo"; exit 1; }
                n=$((n+1))
                info "incluido profile_defaults() generado desde perfil.py" ;;
            "@@INCLUIR_LANG@@")
                f="$SRC/lang/en.json"
                [ -f "$f" ] || { rojo "Falta $f"; exit 1; }
                "${PYTHON:-python3}" - "$f" >> "$tmp" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
d['__version__'] = '1'
print(json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True))
PY
                n=$((n+1))
                info "incluido lang/en.json" ;;
            *)
                printf '%s\n' "$linea" >> "$tmp" ;;
        esac
    done < "$BASE"

    # 12: los 7 de antes, mas perfil.py, su profile_defaults() generado,
    # detectar.py, dlls.py, disco.py, teclas.py, teknoparrot.py, ficha.py, procesos.py y menu_qt.py.
    [ "$n" -eq 17 ] || { rojo "Se esperaban 17 inserciones y hubo $n"; exit 1; }

    # la marca que consulta el script para saber si debe regenerar el helper
    sincronizar_marcas "$tmp"

    if ! bash -n "$tmp"; then
        rojo "El wproton.sh generado tiene errores de sintaxis"
        exit 1
    fi
    mv -f "$tmp" "$SALIDA"
    chmod +x "$SALIDA"
    verde "Generado $SALIDA ($(wc -l < "$SALIDA") líneas)"
}

sincronizar_marcas() {
    # Pone en la comprobación 'grep -q "WPROTON_HELPER ..."' la misma marca que
    # se acaba de escribir en el fichero, para que el helper se regenere justo
    # cuando cambia su contenido y no cuando alguien se acuerda.
    local f="$1" nombre marca
    for nombre in menu_pygame.py mapeador.py steam_add.py menu_gtk.py biblioteca.py mando_virtual.py perfil.py detectar.py dlls.py disco.py teclas.py teknoparrot.py ficha.py procesos.py menu_qt.py; do
        [ -f "$SRC/$nombre" ] || continue
        marca="$(marca_de "$SRC/$nombre")"
        "${PYTHON:-python3}" - "$f" "$nombre" "$marca" <<'PY'
import re, sys
ruta, nombre, marca = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(ruta, encoding='utf-8').read()
# 'grep -q "WPROTON_HELPER menu_pygame.py <marca>"'
s = re.sub(r'(grep -q "WPROTON_HELPER %s )[^"]*(")' % re.escape(nombre),
           r'\g<1>%s\g<2>' % marca, s)
open(ruta, 'w', encoding='utf-8').write(s)
PY
    done
}

comprobar() {
    local ref="${1:-$AQUI/../wproton.sh}"
    [ -f "$ref" ] || { rojo "No encuentro el wproton.sh de referencia: $ref"; exit 1; }
    # OJO: 'SALIDA=x generar' solo valdria DURANTE la llamada; hay que asignarla
    SALIDA="$(mktemp)"
    generar >/dev/null
    # se comparan ignorando las marcas de version, que ahora se calculan solas
    if diff <(grep -vE 'WPROTON_HELPER|WPROTON_STEAMADD|WPROTON_MAPEADOR' "$ref") \
            <(grep -vE 'WPROTON_HELPER|WPROTON_STEAMADD|WPROTON_MAPEADOR' "$SALIDA") >/tmp/build_diff; then
        rm -f "$SALIDA"
        verde "El generado coincide con $ref"
    else
        rojo "DIFERENCIAS con $ref:"
        head -n 40 /tmp/build_diff >&2
        exit 1
    fi
}

extraer() {
    # Vuelca los .py de un wproton.sh ya montado a src/ (para migrar cambios
    # hechos a mano sobre el fichero grande).
    local f="${1:?uso: build.sh --extract wproton.sh}"
    "${PYTHON:-python3}" - "$f" "$SRC" <<'PY'
import sys, os, json
ruta, src = sys.argv[1], sys.argv[2]
s = open(ruta, encoding='utf-8').read()
for var, fin, dest in (('MENU_PYGAME_PY','PGEOF','menu_pygame.py'),
                       ('MAPEADOR_PY','MAPEOF','mapeador.py'),
                       ('MANDO_VIRTUAL_PY','MVIROF','mando_virtual.py'),
                       ('STEAM_ADD_PY','SAEOF','steam_add.py'),
                       ('MENU_GTK_PY','GTKEOF','menu_gtk.py'),
                       ('BIBLIOTECA_PY','BIBEOF','biblioteca.py'),
                       ('PERFIL_PY','PERFEOF','perfil.py'),
                       ('DETECTAR_PY','DETEOF','detectar.py'),
                       ('DLLS_PY','DLLEOF','dlls.py'),
                       ('DISCO_PY','DISEOF','disco.py'),
                       ('TECLAS_PY','TECEOF','teclas.py'),
                       ('TEKNOPARROT_PY','TKPEOF','teknoparrot.py'),
                       ('FICHA_PY','FICEOF','ficha.py'),
                       ('PROCESOS_PY','PROEOF','procesos.py'),
                       ('MENU_QT_PY','QTEOF','menu_qt.py')):
    st = s.index('cat > "$%s" <<' % var)
    ini = s.index('\n', st) + 1
    en = s.index('\n%s\n' % fin, st)
    cuerpo = s[ini:en+1]
    # quitar la marca de version, que la pone el build
    if cuerpo.startswith('# WPROTON_HELPER '):
        cuerpo = cuerpo.split('\n', 1)[1]
    open(os.path.join(src, dest), 'w', encoding='utf-8').write(cuerpo)
    print("  %s <- %d lineas" % (dest, cuerpo.count('\n')))
st = s.index('cat > "$f" <<\'ENJSON\'')
ini = s.index('\n', st) + 1
en = s.index('\nENJSON\n', st)
d = json.loads(s[ini:en+1]); d.pop('__version__', None)
json.dump(d, open(os.path.join(src, 'lang', 'en.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=2, sort_keys=True)
print("  lang/en.json <- %d cadenas" % len(d))
PY
    verde "Extraído a $SRC"
}

case "${1:-}" in
    --check)   comprobar "${2:-}" ;;
    --extract) extraer "${2:-}" ;;
    -h|--help) sed -n '2,12p' "$0" ;;
    *)         generar "$@" ;;
esac
