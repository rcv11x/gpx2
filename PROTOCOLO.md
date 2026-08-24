# HID++ 2.0 — referencia propia

Todo lo que sabemos del protocolo, verificado contra hardware. Existe para que
**no haga falta consultar otros proyectos**: lo que hay aquí está comprobado con
el ratón delante y contrastado con lo que decodifica `gpx2/features.py`.

Cada apartado dice qué está verificado y qué no. Lo no verificado se marca, no
se disimula.

Hardware de referencia: **Logitech PRO X 2** (`046d:c54d` por receptor
Lightspeed, `046d:40a9` como dispositivo; HID++ 4.2, 33 features).
Volcados del 24-08-2026.

---

## Reglas generales

Un paquete de petición es:

```
[report_id][índice_dispositivo][índice_feature][función<<4 | sw_id][parámetros…]
```

- `report_id`: `0x10` corto (7 bytes en total) o `0x11` largo (20 bytes). Se
  elige por tamaño: hasta 3 bytes de parámetros cabe el corto.
- `índice_dispositivo`: `0xFF` el propio ratón, `1..6` los emparejados detrás de
  un receptor.
- `índice_feature`: **local a cada dispositivo**. Se obtiene preguntando por el
  identificador universal (p. ej. `0x2202`) a `IRoot`. Nunca se codifica fijo.
- `sw_id`: nibble de firma para reconocer nuestra respuesta entre el tráfico
  ajeno. Usamos `0x0A`.

Respuestas de error: `[·][·][0xFF][idx_feature][func|sw_id][código]` en HID++
2.0, y `[·][·][0x8F][…]` en HID++ 1.0. Los códigos que hemos visto:
`0x01` parámetro inválido, `0x02` fuera de rango, `0x09` no soportado.

### Qué significa el error 0x05 en este ratón

`0x05` es *LOGITECH_ERROR* (error interno), no "feature inválida" — nuestra
tabla estaba desplazada y daba diagnósticos falsos. En el PRO X 2 aparece al
**escribir el DPI con los perfiles onboard activos**: el firmware rechaza el
cambio porque manda su perfil interno.

Como el modo host no persiste, cualquier escritura tiene que asegurarlo antes
(`Mouse.asegurar_host()`). Si no, basta apagar y encender el ratón para que
todos los ajustes empiecen a fallar con un error que no dice por qué.

### La trampa importante

**Este ratón responde `00 00 00…` (éxito) a escrituras que luego no aplica.**
No basta con mirar si hubo error: hay que **releer y comprobar**. Nos costó dos
rondas de depuración con el DPI. Toda escritura nueva se valida releyendo.

---

## 0x2202 — DPI extendido · VERIFICADA

Versión v0 en este ratón. Es la que usan los ratones modernos; `0x2201` no está.

| Función | Qué hace | Parámetros | Respuesta |
|---|---|---|---|
| 0 | `getSensorCount` | — | `[nº sensores]` |
| 1 | `getSensorCapabilities` | `[sensor]` | `[sensor, ?, flags, 0]` |
| 2 | `getSensorDpiRanges` | `[sensor, dirección, página]` | eco de 3 bytes + 13 de flujo |
| 3 | lista de DPI del perfil onboard | `[sensor]` | `[0, 0, dpi×5]` |
| 4 | distancia de despegue por nivel | `[sensor]` | `[0, lod×5]` |
| **5** | **`getSensorDpi`** | `[sensor]` | `[sensor, X, Xdef, Y, Ydef, LOD]` |
| **6** | **`setSensorDpi`** | `[sensor, X(2), Y(2), LOD(1)]` | eco |

`flags` de la función 1: bit 0 = eje Y independiente, bit 1 = distancia de
despegue ajustable. En el PRO X 2 vale `0x0f`, o sea que tiene los dos: **hay
que mandar los dos ejes en la escritura** o el ratón queda con distinta
sensibilidad en horizontal y en vertical. El byte 1 (`0x05`) no lo hemos
identificado; no hace falta para nada.

Un `0` en el DPI actual significa "estoy usando el de fábrica"; entonces vale el
campo `Xdef`.

### El flujo de rangos (función 2)

No es autocontenido. Cada página aporta **13 bytes al mismo flujo** (los 3
primeros de cada respuesta son eco de la petición), y **un valor puede quedar
partido entre dos páginas**. Se piden páginas consecutivas hasta que el flujo
termina en `0x0000`.

Dentro del flujo, u16 big-endian:

- si `(v >> 13) == 0b111` → no es un DPI: `paso = v & 0x1FFF`, y el **siguiente**
  u16 es el final del tramo, que va desde el último valor conocido;
- si no → es un valor suelto que abre el siguiente tramo.

Volcado real del PRO X 2 (4 páginas):

```
pág 0: 00 00 00 | 00 64 e0 01 00 c8 e0 02 01 f4 e0 05 03
pág 1: 00 00 01 | e8 e0 0a 07 d0 e0 14 13 88 e0 32 27 10
pág 2: 00 00 02 | e0 64 4e 20 e0 7d 7d 00 e0 c8 ab e0 00
pág 3: 00 00 03 | 00 00 …                                   (fin)
```

Fíjate en que la página 0 acaba en `03` y la 1 empieza en `e8`: juntos son
`0x03E8` = 1000. Interpretarlo como "página siguiente" fue un error nuestro que
escondía el máximo real del sensor.

Tramos que salen: 100 · paso 1 →200 · paso 2 →500 · paso 5 →1000 · paso 10
→2000 · paso 20 →5000 · paso 50 →10000 · paso 100 →20000 · paso 125 →32000 ·
paso 200 →**44000**. Total: **957 DPIs válidos**.

---

## 0x8100 — Perfiles onboard · VERIFICADA

**Es la feature que de verdad manda.** Mientras los perfiles onboard estén
activos, el firmware reimpone su propio DPI y su tasa de reporte, y todo lo que
escribamos se pierde *sin dar error*.

| Función | Qué hace | Parámetros | Respuesta |
|---|---|---|---|
| 0 | `getOnboardProfilesInfo` | — | ver abajo |
| 1 | `setOnboardMode` | `[0x01]` onboard · `[0x02]` host | — |
| 2 | `getOnboardMode` | — | `[modo]` |

Volcado de la función 0: `01 07 01 05 01 05 10 00 ff 0a 04 00`. El segundo byte
es el **formato de perfil, 0x07** — no el 0x06 con el que se atascó libratbag.

> **El modo host NO persiste.** El ratón vuelve solo a onboard al apagarse, al
> dormirse o al reconectar el receptor. Hay que comprobarlo **antes de cada
> escritura**, no una vez al arrancar: `Mouse.asegurar_host()`.

> **Y lo que se escribe en modo host tampoco persiste.** El DPI vive en RAM: al
> apagar el ratón vuelve al de su perfil interno (800 en el PRO X 2, aunque
> hubiéramos puesto 1600). No es un fallo: en modo host el estado lo guarda el
> PC, por definición. Por eso hay que **reaplicar los ajustes cuando el ratón
> vuelve**, que es justo lo que hace el demonio en `vigilar_conexion()`.

---

## 0x8061 — Tasa de reporte extendida · LECTURA VERIFICADA

| Función | Qué hace | Parámetros | Respuesta |
|---|---|---|---|
| 0 | capacidades **por vía** | `[0]` cable · `[1]` inalámbrico | bitmap u16 en `[0:2]` |
| **1** | **tasas de la conexión actual** | — | bitmap u16 en `[0:2]` |
| **2** | **`getReportRate`** | — | `[índice]` |
| 3 | `setReportRate` | `[índice]` | ver abajo |

Índice → Hz: `0`=125, `1`=250, `2`=500, `3`=1000, `4`=2000, `5`=4000, `6`=8000.

**El parámetro de la función 0 es la vía, y va al revés de lo que parece:**
`0` es el cable y `1` el inalámbrico. En el PRO X 2, cable `0x000f` (hasta
1000 Hz) e inalámbrico `0x007f` (hasta 8000). Los 8K son una capacidad del
enlace Lightspeed, no del USB — el cable de este ratón es para cargar.

**La función 1 devuelve las tasas de la conexión por la que estés hablando**, y
es la que decide qué acepta la escritura. Se comprobó conectando el mismo ratón
por las dos vías:

| | por receptor | por cable |
|---|---|---|
| `f1` | `0x7f` (hasta 8000) | `0x0f` (hasta 1000) |
| `f0(0)` | `0x0f` | `0x0f` |
| `f0(1)` | `0x7f` | `0x7f` |

La tasa actual es la **función 2**; leerla de la 1 devuelve el bitmap, cuyo
primer byte es `0x00`, y se interpreta como "índice 0 = 125 Hz" dijera lo que
dijera el ratón. Fue un fallo nuestro que hacía mentir a la interfaz.

### Escritura: funciona por cable, no por receptor

**Por cable escribe.** El formato es `[índice]`, un solo byte. Un índice fuera
de lo que admite la conexión responde **error 0x02 (parámetro inválido)**: por
cable, el índice 6 (8000 Hz) se rechaza, y el 1 (250 Hz) se aplica.

**Por receptor no.** Los cinco formatos probados responden `00 00 00…` sin error
y la tasa no se mueve, ni siquiera a 500 Hz, que está dentro de lo que la
función 1 declara ahí. **A Solaar le pasa lo mismo**:
`solaar config 1 report_rate_extended 2ms` anuncia el cambio y la relectura
—que hace con `read(cached=False)`, contra el dispositivo— sigue devolviendo
`1ms`. Sin resolver.

### Sin resolver: el hardware sí puede, falta saber cómo se pide

Medida la tasa real con `depurar.py --medir`, que cronometra los informes que
llegan al kernel: **1000 Hz exactos**, 4484 intervalos con mediana de 1,000 ms.

Se dio por cerrado como límite del receptor, y **era una conclusión precipitada**:
estaba deducida, no medida. Mirando el árbol USB resulta que no se sostiene.

```
046d:c54d   velocidad 480 Mb/s (high-speed)
  1-3.2.2:1.0  ep_81  Interrupt  bInterval=01  ->  125 us  ->  8000 Hz
  1-3.2.2:1.1  ep_82  Interrupt  bInterval=01  ->  125 us  ->  8000 Hz
  1-3.2.2:1.2  ep_83  Interrupt  bInterval=01  ->  125 us  ->  8000 Hz
```

En USB *high-speed* el intervalo del endpoint es `2^(bInterval-1) x 125 us`. Un
receptor de 1 kHz declararía `bInterval=4`. Éste declara **1**, o sea que el
anfitrión lo sondea cada 125 µs y su lado USB está preparado para 8000 Hz.

Con eso, lo que sabemos es:

- el rato&#769;n dice que sabe llegar a 8000 sin cable (`0x7f`);
- el receptor tiene endpoints de 125 µs, así que tampoco topa por USB;
- y sin embargo sólo llegan 1000 informes por segundo.

El límite está en **cómo se configura el enlace de radio**, y ésa es la pieza
que no hemos encontrado. Las vías que quedan por explorar:

1. **Los registros del receptor.** Habla HID++ 1.0 por registros, no por
   features, y expone tres interfaces (`hidraw6`, `hidraw8`, `hidraw9` en este
   equipo) de las que sólo hemos hablado con una.
2. **Escribir el perfil onboard.** Su primer byte es la tasa como índice, y es
   lo que toca G HUB en Windows.

Lo que **está descartado**: que lo impida el modo onboard/host, que la escritura
se guarde para aplicarse al reconectar, y que el cable sirva de algo (por ahí el
tope son 1000 Hz de verdad, y ahí sí se puede escribir).

Por eso `ExtendedReportRate.set()` **relee y lanza `EscrituraIgnorada`** si el
valor no cambió: sin eso, la interfaz enseñaría una tasa que el ratón no tiene.

## 0x8090 — ModeStatus · SÓLO LECTURA

Función 0 devuelve `00 02` en el PRO X 2. La escritura responde **error 0x02
(fuera de rango)** con todos los formatos probados. Para cambiar de modo se usa
`0x8100`, no esta. La dejamos como informativa.

---

## 0x1004 — Batería unificada · VERIFICADA

| Función | Qué hace | Respuesta |
|---|---|---|
| 0 | `getCapabilities` | `[niveles, flags, ?]` — real: `0f 0f 02` |
| 1 | `getStatus` | `[carga %, nivel, estado, alimentación]` |

Volcado real: `4e 08 00 00` = **78 %**, nivel 8, descargando. El byte 0 es el
porcentaje de carga de verdad, no una estimación. Niveles: `1` crítico, `2`
bajo, `4` bueno, `8` lleno. Estado: `0` descargando, `1` cargando, `2` carga
lenta, `3` completa, `4` error.

---

## 0x8100 — Formato de perfil 0x07 · DECODIFICADO

Este ratón usa **formato de perfil 0x07**. Solaar sólo parsea el 0x06, así que
esta disposición está deducida de nuestro propio volcado y no aparece
documentada en ningún otro sitio.

Leer memoria es la **función 5**: `[sector(2), desplazamiento(2)]` → 16 bytes.
El directorio está en el sector 0, con entradas de 4 bytes
`[sector(2), habilitado(1), relleno(1)]` hasta `ffff`.

Volcado real del perfil 1 (sector 0x0001) del PRO X 2:

```
+00  03 03 00 00 20 03 20 03 02 b0 04 b0 04 02 40 06
+16  40 06 02 60 09 60 09 02 80 0c 80 0c 02 00 00 00
```

| Byte | Qué es |
|---|---|
| `b[0]` | tasa de reporte, **como índice** de la tabla de `0x8061` |
| `b[1]` | otra tasa — probablemente la de la otra vía |
| `b[2]` | nivel de DPI por defecto |
| `b[3]` | sin identificar |
| `b[4]` en adelante | cinco niveles de **5 bytes**: `dpiX(2 LE), dpiY(2 LE), despegue(1)` |

Dos cosas confirman la lectura: `b[0]` vale 3, exactamente lo que devuelve
`0x8061` función 2 (1000 Hz), y `b[2]` vale 0, que apunta al nivel de 800 DPI,
que es el que el ratón declara "de fábrica" en `0x2202`. Los cinco niveles
salen 800/1200/1600/2400/3200, los mismos que da `0x2202` función 3.

**Aquí está la diferencia con el 0x06**: allí la tasa va en milisegundos y cada
nivel de DPI ocupa un solo u16. En milisegundos no se pueden expresar 8000 Hz
(serían 0,125 ms), así que el cambio a índice es justo lo que hacía falta para
las tasas altas. Refuerza la sospecha de que la tasa del enlace inalámbrico
sale de aquí y no de `0x8061`.

Los DPI van en **little endian**, al revés que en `0x2202`. No hay una razón
buena; es así.

---

## 0x1B04 — Botones reprogramables · NO EXISTE EN ESTE RATÓN

El PRO X 2 **no expone esta feature**. Sus botones se configuran por perfil
onboard (`0x8100`). La implementación que tenemos es correcta para los ratones
que sí la declaren, y la interfaz detecta su ausencia y lo dice.

---

## Medir la tasa de verdad

Lo que el ratón declara por HID++ y lo que hace pueden no coincidir —de hecho
en este ratón no coinciden. `depurar.py --medir` no le pregunta nada: abre el
`/dev/input/event*` del puntero y cronometra los informes que llegan al kernel,
que es la única medida independiente. Hay que mover el ratón mientras mide,
porque parado no manda nada, y los huecos de más de 50 ms se descartan por ser
pausas y no la tasa.

No necesita sudo si está puesta la regla udev: `uaccess` cubre también
`/dev/input`.

## Cómo se verifica algo nuevo

1. `sudo python3 depurar.py` — lee y decodifica, sin tocar nada.
2. Si un decodificador no cuadra con los bytes, se corrige.
3. **La respuesta real se copia literal a `gpx2/mock.py`**, para que el caso
   quede cubierto por el simulador para siempre.
4. Se añade la comprobación a `tests/prueba_humo.py`.
5. Se pasa el `CONFIANZA` de la clase a `"verificada"` y se anota aquí.

Nunca al revés: primero el volcado, después el decodificador.
