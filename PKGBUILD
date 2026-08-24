# Maintainer: rcv11x <alejandrooymariaa1@gmail.com>
#
# Paquete de desarrollo: construye desde la rama principal. Cuando haya
# versiones etiquetadas, el paquete estable se llamará 'gpx2' y usará el
# tarball de la etiqueta en vez de clonar.

pkgname=gpx2-git
_pkgname=gpx2
pkgver=0.1.0
pkgrel=1
pkgdesc="Configurador de ratones Logitech por HID++ 2.0, con perfiles por juego"
arch=('any')
url="https://github.com/rcv11x/gpx2"
license=('MIT')
depends=('python' 'pyside6' 'python-dbus-next' 'hicolor-icon-theme')
makedepends=('git' 'python-build' 'python-installer' 'python-wheel'
             'python-setuptools')
provides=("$_pkgname=$pkgver")
conflicts=("$_pkgname")
source=("$_pkgname::git+$url.git")
sha256sums=('SKIP')

pkgver() {
    cd "$srcdir/$_pkgname"
    # Si hay etiquetas, se usan; si no, la versión del propio paquete más el
    # número de commits, que es lo que pide el AUR para los paquetes -git.
    if git describe --long --tags >/dev/null 2>&1; then
        git describe --long --tags | sed 's/^v//;s/\([^-]*-g\)/r\1/;s/-/./g'
    else
        printf "0.1.0.r%s.%s" \
            "$(git rev-list --count HEAD)" "$(git rev-parse --short HEAD)"
    fi
}

build() {
    cd "$srcdir/$_pkgname"
    python -m build --wheel --no-isolation
}

check() {
    cd "$srcdir/$_pkgname"
    # No necesita ratón ni interfaz: usa el simulador.
    python -m tests.prueba_humo
}

package() {
    cd "$srcdir/$_pkgname"
    python -m installer --destdir="$pkgdir" dist/*.whl

    # La regla udev es la razón de ser de este paquete: sin ella hay que
    # lanzar la aplicación como root, y una interfaz gráfica con sudo trae
    # más problemas de los que resuelve.
    install -Dm644 99-logitech-hidpp.rules \
        "$pkgdir/usr/lib/udev/rules.d/99-logitech-hidpp.rules"

    install -Dm644 data/io.github.rcv11x.gpx2.desktop \
        "$pkgdir/usr/share/applications/io.github.rcv11x.gpx2.desktop"
    install -Dm644 data/gpx2.svg \
        "$pkgdir/usr/share/icons/hicolor/scalable/apps/io.github.rcv11x.gpx2.svg"

    # Unidad de usuario, no de sistema: el demonio necesita el D-Bus de sesión
    # y no requiere privilegios.
    install -Dm644 data/gpx2d.service \
        "$pkgdir/usr/lib/systemd/user/gpx2d.service"

    # MIT lleva el aviso de copyright dentro, así que el fichero se instala
    # aunque Arch tenga una copia común de la licencia.
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"

    for doc in README.md ARQUITECTURA.md PROTOCOLO.md DISTRIBUCION.md; do
        install -Dm644 "$doc" "$pkgdir/usr/share/doc/$_pkgname/$doc"
    done
}
