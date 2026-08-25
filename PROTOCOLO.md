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

### RESUELTO: hace falta desbloquear las features ocultas

`0x8061` función 3 **no aplica nada por receptor** si se llama a secas. La
orden se acepta sin error y el enlace sigue igual. Lo que faltaba es abrir
antes la feature **`0x1E00` (Enable Hidden Features)**:

```
0x1E00 función 1 con 0x01      -> desbloquea
0x8061 función 3 con [índice]  -> AHORA SÍ cambia el enlace
0x1E00 función 1 con 0x00      -> vuelve a cerrar
```

Medido con `depurar.py --medir`, que cronometra los informes que llegan al
kernel y no le pregunta nada al ratón:

| | intervalo típico | tasa |
|---|---|---|
| antes | 1,000 ms (4486 informes en 5 s) | 1000 Hz |
| después de escribir el índice 5 | **0,250 ms** (16478 informes) | **4000 Hz** |

El cambio **sobrevive a volver a cerrar `0x1E00`**.

> **Ojo: la función 2 miente.** Después de cambiar la tasa sigue devolviendo
> el índice anterior. Por eso dimos por fallido el intento durante toda una
> sesión: mirábamos lo que el ratón decía en vez de lo que hacía. La única
> comprobación válida es cronometrar los informes.

Esto no está documentado en ningún sitio, y Solaar no lo hace: define la
constante `ENABLE_HIDDEN_FEATURES` y no la usa nunca. Es la razón de que a
Solaar tampoco le funcione cambiar la tasa en este ratón.

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
| `b[4..28]` | cinco niveles de **5 bytes**: `dpiX(2 LE), dpiY(2 LE), despegue(1)` |
| `b[29..47]` | sin identificar. En `b[44..47]` hay `3c 00` y `2c 01`, que en LE son 60 y 300: encajarían con los tiempos de ahorro y apagado en segundos |
| `b[48..67]` | **los cinco botones**, 4 bytes cada uno |
| `b[68..159]` | `ff` en este ratón; ahí irían los botones de G-Shift |
| `b[160..207]` | nombre del perfil en UTF-16LE; sin poner |
| `b[208..251]` | cuatro efectos de LED de 11 bytes, como en el 0x06 |
| `b[253..254]` | **CRC-16/CCITT** del resto del sector |

### Los botones

Cuatro bytes cada uno. El nibble alto del primero es el comportamiento:

| Valor | Comportamiento | Resto |
|---|---|---|
| `0x8` | enviar | `b[1]` tipo: 1 botón, 2 modificador+tecla, 3 multimedia · `b[2:4]` el valor |
| `0x9` | función interna | `b[1]` la función: 3 DPI siguiente, 5 ciclar DPI, 0x0A ciclar perfil… |
| `0x0`–`0x2` | macros | sector y dirección de la macro |

Volcado real del PRO X 2, que son sus cinco botones en orden:

```
80 01 00 01   clic izquierdo
80 01 00 02   clic derecho
80 01 00 04   clic central
80 01 00 08   atrás
80 01 00 10   adelante
```

El valor es una máscara de un bit por botón. **Cuidado al buscar el bloque**:
aceptar cualquier nibble conocido da un falso positivo con los bytes de los
niveles de DPI, que también empiezan por `0x0` y `0x8`. Hay que exigir además
que el segundo byte sea un tipo o una función que exista.

### Escribir un sector

Tres funciones, en este orden:

| Función | Qué hace | Parámetros |
|---|---|---|
| 6 | abre la escritura | `[sector(2), desplazamiento(2), longitud(2)]` |
| 7 | manda un trozo | hasta 16 bytes de datos, repetida |
| 8 | cierra y confirma | — |

Los dos últimos bytes del sector son el **CRC-16/CCITT** (polinomio `0x1021`,
inicio `0xFFFF`, sin reflejar, sin XOR final) de todo lo anterior. El ratón lo
comprueba. Verificado leyendo antes de escribir nada: para el sector 1 del
PRO X 2, el ratón trae `0x84DB` y nuestro cálculo da `0x84DB`.

**Antes de escribir nada que importe** conviene reescribir un sector con lo
mismo que ya tenía, y hacerlo sobre un perfil **deshabilitado** (el 2, el 3 o
el 4): así se ejercita el mecanismo entero sin que un fallo afecte a nada que
el ratón use. `depurar.py --probar-escritura` hace eso, guardando antes una
copia del sector en un fichero por si hay que restaurarlo.

**Comprobado en el PRO X 2**, en dos pasos:

1. El sector 2 (un perfil deshabilitado) se reescribió con sus propios bytes y
   volvió idéntico. El mecanismo y el CRC son correctos.
2. Se cambió el botón 3 del perfil activo de «atrás» a «clic central»
   (`80 01 00 08` → `80 01 00 04` en el byte 60, más el CRC nuevo), se pasó el
   ratón a modo onboard, y **el botón lateral pasó a pegar el portapapeles**.
   Escribir perfiles onboard funciona.

> **El perfil onboard sólo manda en modo onboard.** Cambiar un botón en el
> perfil no se nota mientras el ratón esté en modo host, que es donde lo pone
> gpx2 para controlar el DPI. Son dos mundos: en host mandamos nosotros y nada
> persiste; en onboard manda el perfil y todo persiste. Configurar botones
> obliga a elegir, y esa decisión está sin tomar.

### Leer un sector entero

El tamaño de sector es 255, que **no es múltiplo de 16**, y cada lectura
devuelve 16 bytes. Pedir el último bloque en su sitio (byte 240) se sale del
sector y la petición falla. Se lee solapado desde `tamaño - 16` y se descarta
lo repetido. Sin esto faltan los 15 últimos bytes — entre ellos el CRC.

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

## Cómo pedir ayuda con otro ratón

`depurar.py --informe` recoge en un fichero todo lo que se puede leer del
dispositivo: sus features, la batería, el DPI y sus rangos, la tasa, el perfil
onboard y lo que declare de iluminación. **No escribe nada**, y el fichero sólo
lleva el modelo del ratón y sus respuestas al protocolo.

Es la forma de añadir soporte para un ratón que no se tiene delante: alguien lo
ejecuta, manda el fichero, y se decodifica desde bytes reales — que es
exactamente como salieron el formato 0x07 y el flujo paginado de DPI.

La iluminación está sin decodificar. Se sabe dónde vive —cuatro bloques de 11
bytes en el perfil onboard, desde el byte 208, y las features `0x8070`,
`0x8071` y `0x1300`— pero el PRO X 2 no tiene luces y no hay volcados que
mirar. `--leds` los recoge cuando aparezca alguien que sí las tenga.

## Cómo se verifica algo nuevo

1. `sudo python3 depurar.py` — lee y decodifica, sin tocar nada.
2. Si un decodificador no cuadra con los bytes, se corrige.
3. **La respuesta real se copia literal a `gpx2/mock.py`**, para que el caso
   quede cubierto por el simulador para siempre.
4. Se añade la comprobación a `tests/prueba_humo.py`.
5. Se pasa el `CONFIANZA` de la clase a `"verificada"` y se anota aquí.

Nunca al revés: primero el volcado, después el decodificador.

## Iluminación (0x8071 y el perfil onboard)

Decodificada en parte contra un **G203 LIGHTSYNC** (`046d:c092`, por cable),
el 25-08-2026. Lo de aquí está confirmado mirando la luz, no deducido.

### Qué efectos tiene un ratón

`0x8071` función **0** es `getInfo(zona, efecto, tipo)`, y **0xFF significa
"háblame de ti"**. Con ceros contesta dieciséis ceros, que despistó un rato.
Los **dos primeros bytes de la respuesta son el eco de lo preguntado**: los
datos empiezan en el tercero.

```
f0 con FF FF 00  ->  ff 00 01 00 03 00 04 …
                           ^^ nº de zonas de luz (1)

f0 con 00 FF 00  ->  00 00 00 02 07 01 …
                        ^^^^^ dónde está la luz (0x0002)
                              ^^ efectos que admite (7)

f0 con 00 03 00  ->  00 03 00 04 84 21 00 1e
                     ^^ zona
                        ^^ índice del efecto
                           ^^^^^ IDENTIFICADOR del efecto (0x0004)
                                 ^^^^^^^^^^^ sus parámetros por defecto
```

El G203 declara siete: `0x00`, `0x01`, `0x03`, `0x04`, `0x0A`, `0x0D`, `0x0E`.

### El perfil onboard guarda el mismo identificador

En la disposición clásica hay **dos** bloques de 11 bytes desde el byte 208
(la del 0x07 reserva sitio para cuatro). El primer byte de cada bloque sale de
la **misma lista** que declara `0x8071`: el G203 tenía `0x04` guardado y `0x04`
en su lista. No son dos espacios de valores distintos.

```
04 00 00 00 00 00 00 40 01 00 1f
^^ identificador del efecto
   ^^^^^^^^ color: R, G, B
            ^^^^^^^^^^^^^^^^^^^^ parámetros, según el efecto
```

**El color está confirmado**: se le escribió `01 FF 00 00` y la luz se puso
roja, y `01 00 00 FF` y se puso azul.

### Efectos identificados

| id | qué se ve | cómo se sabe |
|----|-----------|--------------|
| `0x00` | apagado | escrito y mirado |
| `0x01` | color fijo, con RGB en los bytes 1-3 | escrito y mirado |
| `0x04` | arcoíris en movimiento | era el que tenía puesto |
| `0x03`, `0x0A`, `0x0D`, `0x0E` | sin identificar | — |

### Los parámetros mandan

El mismo efecto con los parámetros a cero deja de ser el mismo:

```
04 00 00 00 00 00 00 40 01 00 1f  ->  arcoíris que se mueve
04 00 00 00 00 00 00 00 00 00 00  ->  rojo fijo
```

Un ciclo de color con el periodo a cero no avanza y se queda parado en su
primer color, que es el rojo. Por eso escribir los identificadores "pelados"
daba resultados engañosos: el `0x03` y el `0x04` salían rojo fijo, el `0x0A` y
el `0x0D` apagados, y el `0x0E` parpadeando. Eso dice que necesitan
parámetros, no qué son.

**Sin decodificar todavía**: cuál de los bytes 4 a 10 es la velocidad y cuál el
brillo. En el G203 sólo tres no están a cero: el 7 (`0x40`), el 8 (`0x01`) y el
10 (`0x1F`). `depurar.py --afinar-luces` los varía de uno en uno y pregunta qué
cambia.
