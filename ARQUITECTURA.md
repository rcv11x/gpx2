# Control del Logitech G Pro X Superlight 2 en Linux — arquitectura

> Documento de diseño. Se irá corrigiendo cuando el ratón nos diga qué sabe hacer
> de verdad (ejecutar `scan_hidpp.py`).

---

## 1. ¿Es posible? Sí, y no hace falta ingeniería inversa desde cero

El ratón **no tiene un driver cerrado**. Es un dispositivo HID normal que, además
del canal por el que envía el movimiento, expone un **canal privado del
fabricante** por el que se configura todo. Ese canal usa un protocolo llamado
**HID++ 2.0**, y está razonablemente documentado por la comunidad (Solaar,
libratbag, y documentación parcial de la propia Logitech).

Lo que hace G HUB en Windows es exactamente esto: escribir paquetes de 7 o 20
bytes en ese canal. Nosotros vamos a escribir los mismos paquetes desde Python.

En Linux ese canal aparece como un fichero: `/dev/hidraw*`. Lo abres, escribes
bytes, lees la respuesta. **No hay que compilar nada ni tocar el kernel.**

Verificado ya en tu equipo:
- El kernel 7.1.9 incluye los IDs del SL2 (`046d:c09b` ratón, `046d:c54d`
  receptor Lightspeed) en `hid-logitech-dj`, así que el dispositivo se expondrá
  correctamente en cuanto lo conectes. Lo mismo aplica a CachyOS.
- Sólo falta permiso de lectura/escritura sobre `/dev/hidraw*` (regla udev incluida).

### La idea clave del protocolo: el ratón se autodescribe

HID++ 2.0 no es "escribe el byte 5 para el DPI". Es un sistema de **features**:

1. Preguntas al ratón: *"¿tienes la feature 0x2202 (DPI extendido)?"*
2. Te contesta: *"sí, es mi feature número 9, versión 2"*
3. Ya puedes llamar a las funciones de esa feature usando el índice 9.

Consecuencia de diseño muy importante: **tu programa nunca debe llevar valores
hardcodeados de "el SL2 tiene estos DPI"**. Debe preguntar. Eso es lo que hará
que el día de mañana funcione también con otros ratones Logitech sin tocar nada.

---

## 2. ¿De dónde salen los datos? ¿Hay que hacer ingeniería inversa?

**Muy poca, y sólo en la última milla.** El trabajo se reparte en tres niveles:

### Nivel 1 — Documentado y estable (95% del proyecto)
La estructura del protocolo (paquetes de 7/20/64 bytes, índices de dispositivo,
`sw_id`, formato de error, la feature raíz 0x0000 y el catálogo 0x0001) está
publicada por Logitech en su documentación de HID++ 2.0 y reimplementada dos
veces de forma independiente por Solaar y libratbag. Aquí no hay nada que
adivinar: se lee y se implementa.

### Nivel 2 — Documentado por la comunidad (features concretas)
Cómo se codifica el DPI (0x2201), la tasa de reporte (0x8060), la batería
(0x1004)… El código de Solaar y libratbag es GPL y legible; se estudia el
decodificador y se reimplementa. Es lo que ya está hecho en `features.py`, con
un campo `CONFIANZA` en cada clase que distingue lo verificado de lo supuesto.

### Nivel 3 — Aquí sí toca investigar (2 o 3 features)
Las features nuevas que trae el SL2 y que aún nadie ha decodificado del todo:
`0x2202` (DPI extendido), `0x8061` (tasa de reporte hasta 8K) y sobre todo el
*layout 0x06* de los perfiles onboard.

Y esto no se hace a ciegas. El método es:

1. Le preguntas al ratón y **anotas la respuesta en crudo** (pestaña
   Diagnóstico → "Volcar respuestas en crudo").
2. Cambias **un solo ajuste** desde G HUB en Windows (o desde el propio ratón).
3. Vuelves a volcar y **comparas**: los bytes que han cambiado son ese ajuste.
4. Lo reproduces en `mock.py` y ya tienes un caso de prueba permanente.

Es tedioso pero no es difícil, y es exactamente donde un humano con el ratón
delante aporta lo que yo no puedo. Tú pruebas, yo decodifico y programo.

**Regla de oro:** nunca escribir en la memoria del ratón hasta entender qué se
está escribiendo. Leer es inofensivo; escribir a ciegas en la zona de perfiles
onboard es lo único que puede dejar el ratón en un estado raro.

---

## 2b. Estado del arte: quién es quién

Los cuatro proyectos que se suelen confundir:

| | Qué es exactamente | Lenguaje | Enfoque | ¿Sirve para el SL2? |
|---|---|---|---|---|
| **libratbag** | El **motor**. Un demonio (`ratbagd`) sin interfaz que habla con el ratón y expone una API D-Bus genérica | C | Multi-marca (Logitech, Razer, Steelseries, Roccat…) | **No.** El SL2 no está en `master`; PRs #1676 y #1806 atascados en `Profile layout not supported: 0x06` |
| **Piper** | La **cara** de libratbag. Sólo dibuja ventanas; toda la lógica está en ratbagd | Python + GTK | Lo que soporte libratbag | No, porque depende de libratbag |
| **Solaar** | Proyecto **independiente**, no relacionado con los anteriores. Implementa HID++ de cero | Python + GTK | Periféricos de *productividad* (Unifying/Bolt): emparejado, batería, teclas | Parcialmente. Es la mejor referencia de código HID++ que existe, pero no cubre DPI por etapas, Hz altos ni perfiles de gaming |
| **logitune** | El más parecido a lo que quieres. Sin demonio, habla directo por hidraw | C++20 + Qt Quick | Clona **Logitech Options+**, es decir la gama MX (MX Master 2S/3/3S/4, MX Anywhere, MX Vertical) | No. Su objetivo es la gama de oficina, no la de gaming: no toca tasa de reporte ni perfiles onboard de gaming |

Dos conclusiones prácticas:

- **Piper y libratbag son una sola cosa** (motor + cara), no dos alternativas.
- **logitune no es competencia, es un vecino.** Cubre la gama MX; tú cubres la
  gama G. Comparten protocolo (HID++ 2.0) pero casi ninguna feature: las MX
  llevan rueda libre y gestos, las G llevan DPI por etapas y 8000 Hz. Que él
  use C++ y tú Python es irrelevante: mandáis los mismos 20 bytes.

---

## 2c. Requisitos de kernel

El soporte del SL2 en el kernel se añadió en **Linux 6.19** (`hid-logitech-dj`,
IDs `046d:c54d` receptor y `046d:c09b` ratón por cable), y llegó al kernel junto
con el resto de mejoras HID de esa ventana.

| Kernel | ¿Soporta el SL2? |
|---|---|
| < 6.19 | No de serie. Existe un DKMS de terceros (`hid-logitech-dj-dkms`) |
| **6.19** | Sí, es donde entró |
| **7.0 / 7.1 / 7.2** | Sí |

CachyOS va siempre por delante en kernels, así que en casa lo tienes cubierto de
sobra. Se puede comprobar sin conectar nada:

```bash
modinfo hid-logitech-dj | grep -i c54d      # receptor Lightspeed
modinfo hid-logitech-hidpp | grep -i c09b   # ratón por cable
```

Ojo con lo que significa ese soporte: el kernel sólo se encarga de **exponer el
dispositivo y su canal HID++**. Todo lo demás (DPI, Hz, perfiles) es cosa de
nuestro programa en espacio de usuario. Por eso libratbag puede fallar aunque el
kernel vaya perfecto: son dos capas distintas.

---

## 3. Dos sitios donde puede vivir la configuración, y los dos se usan

> **Actualizado tras validar contra hardware.** Lo que sigue describía la
> memoria onboard como territorio sin documentar y desaconsejaba tocarla. Ya
> no: el formato **0x07** está decodificado en `PROTOCOLO.md` y escribirlo
> funciona, probado en un PRO X 2.

El ratón tiene memoria interna con cinco perfiles (feature `0x8100`). Y el PC
puede mandarle ajustes en caliente. **No son alternativas, son cosas
distintas**, y gpx2 usa las dos:

|  | Memoria del ratón | Perfiles en el PC |
|---|---|---|
| Dónde vive | flash del dispositivo | TOML en `~/.config/gpx2/` |
| Cuántos | cinco, tamaño fijo | ilimitados |
| Sobrevive a apagarlo | **sí** | no |
| Funciona en otro PC, sin software | **sí** | no |
| Cambia solo al arrancar un juego | no | **sí** |
| Configura los botones | **sí** | sólo si el ratón expone `0x1B04` |
| Ciclos de escritura | limitados: se escribe cuando toca | ninguno, es un fichero |

**Los perfiles por juego siguen viviendo en el PC**, porque el cambio en
caliente es lo que permite que salten al abrir un juego. La memoria del ratón
es para lo que debe sobrevivir a apagarlo: la pestaña "Memoria del ratón" la
edita.

### El modo decide quién manda

`0x8100` función 1: `0x01` onboard, `0x02` host. **No es `0x8090`**, que es
sólo informativa y cuya escritura este ratón rechaza.

- **onboard** — manda el perfil del dispositivo. Nuestras escrituras de DPI se
  rechazan con error interno (`0x05`).
- **host** — mandamos nosotros, y **nada persiste**: al apagar el ratón vuelve
  a lo que diga su perfil interno.

El modo host **tampoco persiste**, así que hay que asegurarlo antes de cada
escritura (`Mouse.asegurar_host()`), no una vez al arrancar.

La elección del usuario se guarda en `~/.config/gpx2/modo` y el demonio la
respeta: sin eso, deshacía la elección cada cinco segundos creyendo que el
ratón se había reiniciado solo.

---

## 4. Las capas

```
┌───────────────────────────────────────────────┐
│  GUI  (PySide6 / Qt 6)                        │   proceso 1 — se abre y se cierra
│  Sliders de DPI, editor de botones, perfiles  │
└──────────────────────┬────────────────────────┘
                       │  D-Bus de sesión
┌──────────────────────┴────────────────────────┐
│  DAEMON de usuario  (systemd --user)          │   proceso 2 — siempre vivo
│                                               │
│  ├─ 5. Detector de juegos    GameMode / KWin  │
│  ├─ 4. Gestor de perfiles    ~/.config/*.toml │
│  ├─ 3. Modelo de dispositivo Mouse, Feature   │
│  ├─ 2. Protocolo HID++ 2.0   request/response │
│  └─ 1. Transporte            /dev/hidraw*     │
└───────────────────────────────────────────────┘
```

Regla de oro: **cada capa sólo conoce a la de abajo.** La GUI no sabe qué es un
byte HID++; la capa 2 no sabe qué es un "perfil".

### Capa 1 — Transporte (`transport.py`)
Encuentra los nodos `/dev/hidraw*` correctos (parseando el *report descriptor*
para localizar la usage page de fabricante), los abre, y lee/escribe bytes.
Detecta conexión y desconexión vía `pyudev`.
**No entiende nada del contenido.** Ya está esbozada en `scan_hidpp.py`.

### Capa 2 — Protocolo (`hidpp.py`)
Convierte "llama a la función 3 de la feature 0x2202 con estos parámetros" en
bytes, y espera *su* respuesta. Tres cosas no obvias que resuelve esta capa:
- **`sw_id`**: firmas cada petición con un nibble para reconocer tu respuesta.
- **Notificaciones espontáneas**: el ratón manda avisos (batería, botón pulsado)
  en cualquier momento, mezclados con las respuestas. Hay que filtrarlos.
- **Errores**: hay dos formatos distintos (HID++ 1.0 y 2.0).

### Capa 3 — Modelo de dispositivo (`device/`)
Aquí es donde vive el conocimiento del ratón. Un objeto `Mouse` que, al
conectarse, **enumera la tabla de features** y va instanciando los módulos
correspondientes:

```python
capacidades = {
    0x2202: DpiExtendido,     # o 0x2201 si es el modelo antiguo
    0x8061: ReportRateExt,    # o 0x8060
    0x1B04: RemapeoBotones,
    0x1004: Bateria,
    0x8090: ModoOnboardHost,
}
```

Cada módulo expone una interfaz limpia y agnóstica: `mouse.dpi.set(1600)`,
`mouse.battery.read()`. Si la feature no está, el atributo no existe y la GUI
simplemente no dibuja ese panel. **Ésta es la capa que hace la app extensible.**

### Capa 4 — Perfiles (`profiles.py`)
Un perfil es un TOML legible y editable a mano:

```toml
[perfil]
nombre = "Valorant"
[ajustes]
dpi = 800
report_rate_hz = 4000
[botones]
boton_lateral_1 = "click_medio"
[activacion]
ejecutables = ["valorant.exe", "VALORANT-Win64-Shipping.exe"]
steam_appid = []
```

Guardados en `~/.config/gpx2/profiles/`. Se aplican **calculando el diff** contra
el estado actual del ratón: sólo se manda por HID++ lo que ha cambiado.

### Capa 5 — Detector de juegos (`watcher/`)
Ver sección 5.

---


### Módulos que se añadieron después

- **`onboard.py`** — decodifica y compone los perfiles de la memoria del ratón
  (formato 0x07). Regla que sigue entero: al escribir se parte del sector que
  el ratón ya tenía y sólo se sustituyen los campos conocidos. Hay trozos sin
  identificar, y reconstruirlos desde cero sería inventarlos. Una comprobación
  vigila que leer y reescribir sin cambios dé el sector idéntico.
- **`procesos.py`** — qué hay corriendo y cuáles de esas cosas parecen un
  juego, más los juegos de Steam instalados leyendo sus manifiestos. Existe
  para que nadie tenga que saberse el nombre del ejecutable de su juego.
- **`gui/dialogos.py`** — el selector de juegos, con carátulas de la caché
  local de Steam.
- **`cli.py`** — los puntos de entrada de los dos ejecutables. Un «console
  script» se llama sin argumentos y tanto la interfaz como el demonio quieren
  mirar la línea de órdenes.

### Dónde se guarda el estado

Todo cuelga de `~/.config/gpx2/`, y el **modo demo usa la subcarpeta `demo/`**
para no pisarlo:

| | Qué |
|---|---|
| `profiles/` | los perfiles por juego, en TOML |
| `modo` | onboard u host, la elección del usuario |
| `tasas` | la última frecuencia escrita a cada ratón, porque el dispositivo no informa de la suya |
| `respaldo/` | copia del sector de perfil antes de escribirlo |


## 5. ¿Por qué un daemon separado y no una sola app?

1. El perfil tiene que cambiar **aunque la GUI esté cerrada**. Nadie deja abierto
   el panel de configuración mientras juega.
2. `/dev/hidraw` debe tener **un solo dueño**. Dos procesos leyendo el mismo
   descriptor se roban las respuestas entre sí y el protocolo se corrompe.
3. La GUI puede crashear, actualizarse o reiniciarse sin tocar el estado del ratón.

Se comunican por **D-Bus de sesión** (`org.rcv11x.Gpx2`), que es el mecanismo
estándar en Linux para esto: el daemon expone métodos (`ApplyProfile`,
`ListProfiles`, `SetDpi`) y señales (`BatteryChanged`, `ProfileSwitched`, que la
GUI escucha para actualizarse sola).

El daemon se arranca como servicio de usuario (`systemd --user`), sin root.

### Lo que cuesta en memoria (medido, no estimado)

| Proceso | RSS | PSS (reparto justo de librerías compartidas) |
|---|---|---|
| Interfaz completa abierta | 112 MiB | **49 MiB** |
| Sólo protocolo + modelo de dispositivo (el futuro demonio) | **13 MiB** | ~9 MiB |

Casi todo el peso es Qt, no el programa: Python pelado son 12 MiB, y cargar Qt
lo sube a 74 MiB antes de dibujar una sola ventana.

Esto refuerza la decisión de partirlo en dos procesos: **lo que está siempre
encendido son 13 MiB**, y los 112 MiB sólo existen mientras la ventana está
abierta. Para comparar, G HUB en Windows ronda los 200–400 MB de forma
permanente.

Y explica por qué Python es una elección correcta aquí: el cuello de botella no
es el lenguaje, es el toolkit gráfico. En C++ con Qt la ventana pesaría
prácticamente lo mismo.

---

## 6. El cambio automático por juego en Wayland (KDE)

Aquí está la única dificultad real del proyecto. En X11 preguntabas "¿qué ventana
está activa?" y listo. **En Wayland eso no existe por seguridad**: ninguna app
puede espiar las ventanas de las demás.

Solución: tres fuentes, en orden de fiabilidad, todas detrás de la misma interfaz
`GameWatcher`.

### Fuente A — GameMode (la buena, y ya la tienes instalada)
Feral GameMode expone en D-Bus `com.feralinteractive.GameMode` con las señales
`GameRegistered(pid)` y `GameUnregistered(pid)`. Steam y Lutris lo activan solos.
Te da el **PID exacto** del juego justo al arrancar → `/proc/PID/exe` te dice
cuál es. Es preciso, instantáneo y no requiere polling.

*(Verificado: tienes `gamemoded` instalado y perteneces al grupo `gamemode`.)*

### Fuente B — KWin script (específico de KDE)
KDE deja cargar un pequeño script JS en el compositor que sí puede ver la ventana
activa y reenviarla por D-Bus. Cubre juegos que no pasan por GameMode.

### Fuente C — Sondeo de `/proc` (universal, red de seguridad)
Cada 2 segundos, mirar los nombres de los procesos. Feo pero funciona en
cualquier escritorio y cualquier distro.

Emparejamiento perfil↔juego por nombre de ejecutable, AppID de Steam o `wm_class`,
con un **perfil por defecto** al que se vuelve cuando el juego se cierra.

---

## 7. Permisos

Por defecto `/dev/hidraw*` es sólo de root. La regla `99-logitech-hidpp.rules`
incluida usa `TAG+="uaccess"`, que le da acceso mediante ACL al usuario que tiene
la sesión gráfica activa. Es lo que hacen Solaar y libratbag. **No hace falta que
el daemon corra como root**, y eso es importante: un proceso que escribe en
dispositivos USB no debería tener privilegios.

---

## 8. Stack elegido

| Pieza | Elección | Motivo |
|---|---|---|
| Lenguaje | **Python 3.13+** | Es el que conoces. El rendimiento es irrelevante: mandas 20 bytes cuando cambias un ajuste, no en bucle |
| GUI | **PySide6** (Qt 6, licencia LGPL) | Moderno, nativo, y en KDE se integra visualmente de forma perfecta. `pacman -S pyside6` en CachyOS |
| Widgets vs QML | **QtWidgets** para empezar | QML es más bonito pero tiene curva de aprendizaje. Se puede migrar después: la lógica está en el daemon, no en la GUI |
| HID | **Nada, stdlib** | `os.read`/`os.write` sobre hidraw. Sin `hidapi`, sin compilar C |
| Hotplug | `pyudev` | Detectar conexión/desconexión del receptor |
| Config | `tomllib` (stdlib) + `tomli-w` | Legible y editable a mano |
| D-Bus | `dbus-next` o `sdbus` | Async, en Python puro |
| Async | `asyncio` en el daemon | Un bucle esperando a la vez el hidraw, D-Bus y el watcher |

> Nota para PySide6: instálalo **desde el repositorio de la distro**, no con pip.
> Los paquetes de la distro traen los plugins de plataforma de Wayland ya
> configurados y te ahorras problemas de escalado y tema.

### Estructura de carpetas propuesta

```
gpx2/
├── gpx2/
│   ├── transport.py       # capa 1
│   ├── hidpp.py           # capa 2
│   ├── device/            # capa 3
│   │   ├── mouse.py
│   │   └── features/      # dpi.py, report_rate.py, battery.py, buttons.py
│   ├── profiles.py        # capa 4
│   ├── watcher/           # capa 5  (gamemode.py, kwin.py, procfs.py)
│   ├── daemon.py
│   └── gui/
├── data/
│   ├── 99-logitech-hidpp.rules
│   └── gpx2d.service
└── tests/
```

---

## 9. Roadmap por fases

- **F0 — Detección** ✅
- **F1 — Leer y escribir un ajuste** ✅ (DPI y tasa de reporte, con las clases
  de `features.py`)
- **F2 — Modelo de dispositivo + batería + reconexión** ✅ (el demonio detecta
  que has desconectado el ratón y lo recupera al volver)
- **F3 — Perfiles TOML + demonio + D-Bus** ✅
- **F4 — Interfaz gráfica** ✅ (falta pulido, no funcionalidad)
- **F5 — Cambio automático por juego** ✅ (GameMode + respaldo por /proc)
- **F6 — Remapeo de botones (0x1B04)** ✅ (reasignar un botón a la función
  de otro; asignar teclas o macros necesita el modo desvío, que viene después)
- **F7 — Escritura de perfiles onboard (layout 0x06)** ⬜ pendiente, opcional

Lo único que bloquea el resto: **validar `0x2202` y `0x8061` contra el ratón
real**. Todo lo demás está probado contra el simulador.

---

## 9b. Decisiones tomadas durante la fase 3

Tres cosas que no estaban en el diseño original y que conviene tener escritas,
porque no son obvias.

### El nodo hidraw se abre sólo durante cada petición

Al principio la interfaz mantenía `/dev/hidraw` abierto mientras estaba en
marcha. Eso rompe en cuanto aparece el demonio: HID++ es pregunta-respuesta
sobre un canal compartido, y si dos procesos leen a la vez **cada uno se lleva
las respuestas del otro**. El síntoma sería un valor de DPI absurdo de vez en
cuando, sin ningún error — el peor tipo de fallo.

Solución: `RawChannel` abre el nodo al empezar cada petición, pone un `flock`, y
lo cierra al terminar. Abrir un hidraw cuesta microsegundos, así que el coste es
irrelevante, y a cambio la interfaz y el demonio conviven sin coordinarse: el
que llega segundo espera unos milisegundos.

### Lo estructurado viaja como JSON dentro de D-Bus

El demonio usa `dbus-next` y la interfaz usa `QtDBus` (que ya viene con Qt, y
así la GUI no añade dependencias). Pero QtDBus entrega los tipos compuestos
como un `QDBusArgument` que hay que desmontar campo por campo, y cualquier
cambio del esquema obliga a tocar ese desmontaje.

Por eso los métodos que devuelven estructura (`ListProfiles`, `DeviceState`)
devuelven **JSON en una cadena**. Los valores sueltos siguen usando tipos D-Bus
normales. Ventaja añadida: se depura desde la terminal con `busctl … | jq`.

### Los dos vigilantes se solapan a propósito

GameMode es instantáneo y preciso, pero sólo ve los juegos que pasan por él.
El sondeo de `/proc` ve cualquier cosa, pero tarda unos segundos. Están los dos
activos a la vez y el mismo juego llega dos veces; el demonio se queda con el
primer aviso y descarta el resto (deduplicación por PID). Es redundancia
deliberada, no un despiste.

---

## 10. ¿Y hacer una app multi-marca?

**Correcto, no merece la pena, y tu instinto es bueno.** Cada fabricante tiene su
propio protocolo propietario y sin documentar: Razer usa su transporte USB, SteelSeries
otro, Corsair otro. libratbag lleva años en ello con varias personas y aun así el
soporte es irregular — de hecho tu propio ratón es un ejemplo de ello.

Lo sensato es lo contrario: **hacer una app excelente para un protocolo (HID++) y
que funcione bien con muchos ratones Logitech**, que son decenas. Eso sale casi
gratis si respetas la regla de "preguntar features en vez de hardcodear modelos".

La única concesión al futuro: que la capa 3 hable con una interfaz abstracta
(`Device`, `DpiCapability`...) y no directamente con HID++. Así, si algún día
alguien quiere añadir otra marca, cambia el backend y la GUI ni se entera. Pero
**no construyas hoy esa abstracción con más de un caso de uso en mente** — eso es
lo que arruina los proyectos pequeños.


---

## 12. Cómo se amplía a más ratones (y algún día a más marcas)

El orden importa, de más barato a más caro:

1. **Más ratones Logitech: casi gratis.** Ya funciona por diseño. Un G502, un
   G305 o un MX Master responden al mismo `IRoot`, declaran su tabla de features
   y la interfaz se adapta sola. Lo único que puede hacer falta es decodificar
   alguna feature que ese modelo tenga y el SL2 no.

2. **Otras marcas: caro, pero acotado.** No comparten *nada* del protocolo.
   Razer usa mensajes de 90 bytes por USB control transfer, con su propio
   esquema de checksum; SteelSeries y Corsair, otros distintos. Escribir un
   backend nuevo es semanas de trabajo por marca, y hay que repetir la
   investigación por cada familia de producto.

   Lo que **sí** hay que hacer hoy para no cerrarse esa puerta: que la capa 4
   (perfiles) y la GUI hablen con las clases de `features.py`
   (`dpi.set()`, `rate.set()`) y **nunca** con `hidpp.py` directamente. Si eso
   se respeta, añadir Razer el día de mañana es escribir un `razer.py` que
   produzca objetos con la misma interfaz. Nada más.

3. **Lo que NO hay que hacer ahora:** inventar abstracciones para una segunda
   marca que todavía no existe. Con un solo backend real, cualquier abstracción
   que diseñes hoy será la equivocada. La separación en capas ya es suficiente.

---

## 13. Herramientas de desarrollo del propio proyecto

- **`scan_hidpp.py`** — script sin dependencias, para diagnosticar en cualquier
  máquina (incluso una sin PySide6 instalado).
- **`run_gui.py --demo`** — añade un SL2 **simulado**. Permite desarrollar toda
  la interfaz sin tener el ratón delante. El simulador (`gpx2/mock.py`) responde
  al protocolo de verdad, así que ejercita el mismo código que el hardware real.
- **Pestaña Diagnóstico → Volcar respuestas en crudo** — el banco de trabajo de
  ingeniería inversa descrito en la sección 2.
