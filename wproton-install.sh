#!/usr/bin/env bash
# ============================================================================
#  WProton - instalador para un rootfs proot que YA EXISTE
#
#  Copyright (C) 2026  stshunz y colaboradores  -  GPL-3.0-or-later
# ----------------------------------------------------------------------------
#  PARA QUE SIRVE
#
#  Para no construir nada. Se ejecuta DENTRO del Linux que ya te da una app
#  como Linbox-WinEmu, Boxvidra o XoDos -o dentro de un proot-distro de
#  Termux- y deja WProton listo para lanzar juegos.
#
#  No toca la app anfitriona, no necesita root y no compila nada.
#
#  USO:
#     bash wproton-install.sh
#     bash wproton-install.sh --local /ruta/wproton_arm.sh
# ============================================================================

set -u

REPO_RAW="https://raw.githubusercontent.com/stshunz/WProton_ARM/main"
SCRIPT_REMOTO="wproton_arm.sh"
BLOQUE_REMOTO="wproton_android.sh"
DESTINO="${WPROTON_DIR:-$HOME/WProton}"
LOCAL=""

while [ $# -gt 0 ]; do
    case "$1" in
        --local) LOCAL="$2"; shift 2 ;;
        --dir)   DESTINO="$2"; shift 2 ;;
        *) printf 'Opcion desconocida: %s\n' "$1"; exit 1 ;;
    esac
done

msg()  { printf '\033[1;32m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$1"; }
fail() { printf '\033[1;31m[X]\033[0m %s\n' "$1"; exit 1; }

# ----------------------------------------------------------------------------
# 1. DONDE ESTAMOS
# ----------------------------------------------------------------------------
# No se da por hecho el anfitrion. Cada app monta su rootfs a su manera y
# hardcodear rutas es la forma mas rapida de que esto solo funcione en el
# aparato donde se probo.
msg "Mirando donde estamos..."

DISTRO="desconocida"
PKG=""
if command -v pacman >/dev/null 2>&1;  then DISTRO="arch";   PKG="pacman"
elif command -v apt-get >/dev/null 2>&1; then DISTRO="debian"; PKG="apt"
elif command -v dnf >/dev/null 2>&1;   then DISTRO="fedora"; PKG="dnf"
fi
[ -n "$PKG" ] || fail "No hay gestor de paquetes reconocible. Este script va
DENTRO del rootfs Linux, no en la consola de Android."

ANFITRION="proot/desconocido"
[ -n "${PROOT_L2S_DIR:-}${PROOT_TMP_DIR:-}" ] && ANFITRION="proot"
[ -d /data/data/com.termux/files ] && ANFITRION="termux-proot"
grep -qi android /proc/version 2>/dev/null && ANFITRION="$ANFITRION (Android)"

printf '    distro ....... %s\n' "$DISTRO"
printf '    anfitrion .... %s\n' "$ANFITRION"
printf '    arquitectura . %s\n' "$(uname -m)"
printf '    DISPLAY ...... %s\n' "${DISPLAY:-(sin definir)}"

case "$(uname -m)" in
    aarch64|arm64) ;;
    *) warn "Esto no es aarch64. Seguira, pero no es el objetivo." ;;
esac

# ----------------------------------------------------------------------------
# 2. DEPENDENCIAS
# ----------------------------------------------------------------------------
# unsquashfs es la unica IMPRESCINDIBLE: sin ella no se puede instalar ningun
# .wsquashfs y WProton no sirve para nada. El resto son deseables.
msg "Instalando dependencias..."

case "$PKG" in
    pacman)
        PAQ="bash coreutils curl tar zstd xz squashfs-tools unzip zip
             python python-pygame awk grep sed findutils procps-ng"
        sudo pacman -Sy --needed --noconfirm $PAQ 2>/dev/null \
            || pacman -Sy --needed --noconfirm $PAQ \
            || warn "pacman fallo: instala a mano squashfs-tools y python-pygame" ;;
    apt)
        PAQ="bash coreutils curl tar zstd xz-utils squashfs-tools unzip zip
             python3 python3-pygame gawk procps"
        (sudo apt-get update -qq || apt-get update -qq) >/dev/null 2>&1
        sudo apt-get install -y $PAQ 2>/dev/null \
            || apt-get install -y $PAQ \
            || warn "apt fallo: instala a mano squashfs-tools y python3-pygame" ;;
    dnf)
        sudo dnf install -y bash curl tar zstd xz squashfs-tools unzip zip \
             python3 python3-pygame 2>/dev/null || warn "dnf fallo" ;;
esac

command -v unsquashfs >/dev/null 2>&1 \
    || fail "Falta unsquashfs y es imprescindible. Instala squashfs-tools."

# ----------------------------------------------------------------------------
# 3. WPROTON
# ----------------------------------------------------------------------------
msg "Colocando WProton en $DESTINO"
mkdir -p "$DESTINO" || fail "No se puede escribir en $DESTINO"

traer() {
    # $1 = nombre remoto, $2 = destino local
    if [ -n "$LOCAL" ] && [ "$1" = "$SCRIPT_REMOTO" ]; then
        cp "$LOCAL" "$2" || fail "No se pudo copiar $LOCAL"
        return 0
    fi
    curl -fsSL "$REPO_RAW/$1" -o "$2" \
        || fail "No se pudo descargar $1 desde $REPO_RAW"
}

traer "$SCRIPT_REMOTO" "$DESTINO/wproton.sh"
chmod +x "$DESTINO/wproton.sh"

# El bloque 9b (capa Android) va al final del script si no esta ya dentro.
# Se comprueba por una funcion suya y no por el nombre del fichero: si algun
# dia se fusiona en el tronco, esto deja de anadirlo solo.
if grep -q 'mount_game_android()' "$DESTINO/wproton.sh"; then
    msg "El script ya trae la capa Android integrada"
else
    msg "Anadiendo la capa Android (bloque 9b)"
    if [ -f "$(dirname "$0")/$BLOQUE_REMOTO" ]; then
        cat "$(dirname "$0")/$BLOQUE_REMOTO" >> "$DESTINO/wproton.sh"
    else
        traer "$BLOQUE_REMOTO" "$DESTINO/.9b.sh"
        cat "$DESTINO/.9b.sh" >> "$DESTINO/wproton.sh"
        rm -f "$DESTINO/.9b.sh"
    fi
fi

# AVISO IMPORTANTE sobre el orden: el bloque 9b redefine mount_game con
# declare -f, asi que TIENE que quedar despues de la definicion original. Al
# anadirlo al final del fichero eso se cumple solo. Si algun dia se inserta a
# mano en medio del script, hay que ponerlo despues de la seccion 9.
bash -n "$DESTINO/wproton.sh" \
    || fail "El script resultante tiene un error de sintaxis. No se ha tocado nada mas."

mkdir -p "$DESTINO/games"

# ----------------------------------------------------------------------------
# 4. ENTORNO
# ----------------------------------------------------------------------------
# Las variables graficas no se ponen en el script: van en un fichero aparte que
# se puede editar sin tocar WProton, porque son lo primero que hay que trastear
# cuando un juego no arranca.
msg "Escribiendo el entorno en $DESTINO/android-env.sh"
cat > "$DESTINO/android-env.sh" <<'ENV'
# Entorno de WProton en Android. Se lee antes de lanzar.
# Editable: es lo primero que se toca cuando un juego no arranca.

export WPROTON_HOST=android-proot
export WP_ARCH=aarch64

export DISPLAY="${DISPLAY:-:0}"
export PULSE_SERVER="${PULSE_SERVER:-tcp:127.0.0.1:4713}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}"

# --- Adreno (RP5 = 650, Odin 2 = 740) ---
# Turnip por Vulkan y Zink para el OpenGL que quede. En Mali hay que dar el
# rodeo por ANGLE y esto no vale.
export MESA_LOADER_DRIVER_OVERRIDE=zink
export GALLIUM_DRIVER=zink
# noconform relaja comprobaciones que Turnip no cumple del todo y que hacen
# fallar a DXVK sin motivo real.
export TU_DEBUG=noconform
export MESA_VK_WSI_PRESENT_MODE=mailbox
export vblank_mode=0

# --- Box64 ---
export BOX64_DYNAREC_BIGBLOCK=1
export BOX64_DYNAREC_SAFEFLAGS=1
export BOX64_DYNAREC_FASTROUND=1
export BOX64_LOG=0
ENV

cat > "$DESTINO/jugar" <<EOF
#!/usr/bin/env bash
. "$DESTINO/android-env.sh"
exec "$DESTINO/wproton.sh" "\$@"
EOF
chmod +x "$DESTINO/jugar"

# ----------------------------------------------------------------------------
# 5. COMPROBACION
# ----------------------------------------------------------------------------
msg "Comprobando el entorno"
( . "$DESTINO/android-env.sh"; "$DESTINO/wproton.sh" --android-check ) \
    || warn "--android-check fallo. Puede ser que esta version del script
aun no lo tenga: mira que el bloque 9b se anadiera bien."

printf '\n'
msg "Listo."
printf '  Juegos:   %s/games/   (copia ahi tus .wsquashfs)\n' "$DESTINO"
printf '  Lanzar:   %s/jugar\n' "$DESTINO"
printf '  Entorno:  %s/android-env.sh\n\n' "$DESTINO"

if [ -z "${DISPLAY:-}" ]; then
    warn "DISPLAY esta vacio: no hay servidor X. Arranca primero la pantalla
    de la app anfitriona, o los menus no se veran."
fi
