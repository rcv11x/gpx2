# Cómo distribuir gpx2

## El dato que decide casi todo

gpx2 necesita **una regla udev instalada en el sistema anfitrión** para poder
abrir `/dev/hidraw*` sin root. Y esto es lo importante:

> **Ni Flatpak ni AppImage pueden instalar una regla udev.**

Un Flatpak vive en una caja aislada y no escribe en `/etc/udev/rules.d/`. Un
AppImage es un fichero suelto que no instala nada en ningún sitio. En ambos
casos el usuario acaba teniendo que copiar la regla a mano con `sudo`, y si no
lo hace, la aplicación arranca pero no ve el ratón. Es exactamente el problema
que arrastra Solaar con su Flatpak.

Por eso, para una herramienta de hardware, el orden correcto no es el mismo que
para una aplicación normal.

---

## Recomendación, en orden

### 1. Paquete nativo — lo primero y lo principal

Es lo único que puede dejar el sistema **bien configurado de una sola vez**:
la regla udev, el `.desktop`, el icono y (más adelante) el servicio systemd.

- **CachyOS / Arch → un `PKGBUILD` en el AUR.** Es tu distro de casa y es lo
  idiomático allí. Un PKGBUILD para un proyecto Python son unas 25 líneas.
- **Fedora → un COPR.** Igual de sencillo, y así lo tienes también en el trabajo.

No es casualidad que libratbag, Piper y Solaar se distribuyan así en primer
lugar: todos tienen el mismo problema de permisos.

### 2. Flatpak — para llegar a todo el mundo

Merece la pena **después**, cuando el proyecto esté maduro. Funciona, pero con
dos asteriscos que conviene saber de antemano:

- Necesita el permiso `--device=all` para llegar a `/dev/hidraw*`. Es un permiso
  amplio y en Flathub te lo van a preguntar en la revisión.
- Necesita `--talk-name=org.kde.KWin` para los ajustes de sensibilidad.
- **La regla udev se sigue instalando a mano.** No hay forma de evitarlo.

GOverlay, que es el ejemplo que citas, está tanto en Flathub como en el AUR — y
es un buen modelo a seguir: nativo para quien quiere integración, Flatpak para
quien quiere que funcione sin pensar.

### 3. AppImage — el peor encaje de los tres, aquí

Suena bien ("un fichero y ya") pero para *esta* aplicación concreta acumula
inconvenientes:

| Problema | Consecuencia |
|---|---|
| No instala la regla udev | La app no ve el ratón hasta que el usuario haga `sudo` a mano |
| No instala un `.desktop` | Vuelve el icono genérico de Wayland, y no aparece en el menú |
| Qt 6 + Wayland dentro de un AppImage | Frágil: fallos de escalado, de tema y de plugin de plataforma |
| Empaquetar PySide6 | 150–250 MB por un programa cuyo código son 50 KB |

Sigue siendo útil para una cosa: **una descarga de prueba** para quien quiera
verlo antes de instalarlo. Pero no como forma principal.

### 4. Mientras desarrollas: `uv` o `pipx`

Para ti, ahora mismo, lo más cómodo es directamente el repositorio:

```bash
git clone <tu-repo> && cd gpx2
./install.sh          # icono, .desktop y lanzador, sin sudo
./run_gui.py
```

`install.sh` no toca nada del sistema: instala en `~/.local/`. La única parte
que pide `sudo` es la regla udev, y el script te dice el comando en vez de
ejecutarlo por su cuenta.

---

## Resumen

| Fase del proyecto | Cómo se distribuye |
|---|---|
| Ahora (desarrollo) | `git clone` + `install.sh` |
| Cuando funcione con tu ratón | PKGBUILD en el AUR |
| Cuando le sirva a más gente | + COPR de Fedora |
| Cuando esté maduro | + Flatpak en Flathub |
| Opcional, para probar | AppImage de descarga suelta |

Lo importante: **el formato de paquete no cambia ni una línea del programa.**
Es un envoltorio. No merece la pena decidirlo hoy ni condicionar el diseño por
ello — sólo hay que evitar la trampa de asumir que un AppImage resuelve la
instalación, porque en una herramienta de hardware no lo hace.
