# gpx2

Control de ratones Logitech en Linux por HID++ 2.0, con perfiles por juego y
sin telemetría. Pensado para el **G Pro X Superlight 2**, que hoy no está
soportado por libratbag/Piper.

Estado: **fases 0 a 5 completadas** — detección, protocolo, interfaz, perfiles,
demonio y cambio automático por juego. Todo probado contra un ratón simulado;
falta validar dos features contra el hardware real.
Ver `ARQUITECTURA.md` para el diseño completo y el roadmap.

## Requisitos

Sólo hay **dos dependencias externas**, y las dos vienen empaquetadas en
cualquier distribución. Todo lo demás es biblioteca estándar de Python.

| | Para qué | CachyOS / Arch | Fedora |
|---|---|---|---|
| PySide6 | la interfaz | `pyside6` | `python3-pyside6` |
| dbus-next | el demonio | `python-dbus-next` | `python3-dbus-next` |

```bash
sudo pacman -S pyside6 python-dbus-next      # CachyOS / Arch
sudo dnf install python3-pyside6 python3-dbus-next   # Fedora
```

Además: Linux 6.19+ (para que el kernel exponga el SL2) y Python 3.11+.

Instala PySide6 **desde la distro, no con pip**: los paquetes del sistema traen
los plugins de Wayland ya configurados y se integran con el tema de tu escritorio.

### Comprobar el ratón antes de nada

`scan_hidpp.py` no necesita ninguna dependencia — ni siquiera PySide6. Sirve
para saber si tu ratón se detecta antes de abrir la interfaz:

```bash
python3 scan_hidpp.py
```

## Permisos

Por defecto `/dev/hidraw*` es sólo de root:

```bash
sudo cp 99-logitech-hidpp.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
# desconecta y reconecta el receptor
```

## Instalación

```bash
./install.sh            # icono, entrada de menú y lanzador, todo en ~/.local
./install.sh --uninstall
```

No usa sudo ni toca el sistema. Lo único que necesita `sudo` es la regla udev,
y el script te dice el comando en lugar de ejecutarlo.

Para cómo distribuirlo a otra gente (AUR, Flatpak, AppImage), ver
`DISTRIBUCION.md`.

## Uso

```bash
gpx2                       # interfaz
gpx2 --demo                # interfaz con un SL2 simulado (sin hardware)

systemctl --user enable --now gpx2d.service    # demonio: perfiles automáticos
python3 -m gpx2.daemon --demo -v               # demonio a mano, para ver el log

python3 scan_hidpp.py      # diagnóstico por terminal, sin dependencias
python3 -m tests.prueba_humo   # prueba de humo, no necesita hardware
```

El demonio también se maneja desde la terminal, sin abrir la interfaz:

```bash
busctl --user call io.github.rcv11x.gpx2 /io/github/rcv11x/gpx2 \
    io.github.rcv11x.gpx2.Manager ApplyProfile s shooter
```

Si no aparece ningún ratón compatible, la interfaz lo dice y explica por qué
(no hay dispositivo HID++, o faltan permisos).

## Qué hace hoy

- Detecta los nodos `/dev/hidraw*` con canal HID++ analizando su descriptor HID
- Habla HID++ 2.0: ping, tabla de features, nombre, batería
- Lee y escribe DPI (0x2201 / 0x2202) y tasa de reporte (0x8060 / 0x8061)
- **Perfiles en TOML**, editables a mano, con reglas por ejecutable o AppID de Steam
- **Demonio** que aplica el perfil que toca y expone todo en D-Bus
- **Cambio automático al arrancar un juego**, vía GameMode y con sondeo de
  `/proc` como respaldo
- **Remapeo de botones** (0x1B04), respetando los grupos que permite el firmware
- Ajusta la sensibilidad del puntero en KDE, también para ratones genéricos
- Lee las versiones de firmware e integra la comprobación con **fwupd**
  (actualizar firmware lo hace fwupd, no este programa — ver la pestaña Firmware)
- Vuelca respuestas en crudo para decodificar features nuevas

## Qué falta

Desviar botones al demonio para asignarles teclas o macros, y escritura de
perfiles onboard (layout 0x06).
Y sobre todo: **validar 0x2202 y 0x8061 contra el ratón real**.
Ver el roadmap en `ARQUITECTURA.md`.

## Estructura

```
gpx2/
├── transport.py   capa 1 — nodos hidraw, lectura/escritura de bytes
├── hidpp.py       capa 2 — protocolo HID++ 2.0
├── features.py    capa 3a — DPI, tasa de reporte, batería, modo
├── device.py      capa 3b — modelo Mouse, construido desde la tabla de features
├── desktop.py     capa 3c — sensibilidad de KDE (KWin por D-Bus)
├── profiles.py    capa 4a — perfiles TOML
├── engine.py      capa 4b — aplica un perfil mandando sólo lo que cambia
├── watcher/       capa 5 — detección de juegos (GameMode, /proc)
├── daemon.py      el proceso que está siempre encendido
├── dbus_service.py  la cara pública del demonio
├── client.py      cliente D-Bus que usa la interfaz
├── mock.py        SL2 simulado, para desarrollar sin hardware
└── gui/           interfaz PySide6
```

## Licencia

MIT. Ver `LICENSE`.
