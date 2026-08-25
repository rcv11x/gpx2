# Ratones probados

Qué se sabe de cada ratón que ha pasado por aquí, y qué le funciona. Si el
tuyo no está, [al final](#si-tu-ratón-no-está) se explica cómo añadirlo: son
dos minutos y no hace falta saber programar.

**gpx2 no lleva una lista de modelos.** Le pregunta al ratón qué sabe hacer y
enseña lo que haya: si tiene la feature, aparece el panel, y si no, no
aparece. Un ratón que no esté en esta página puede funcionar perfectamente.
Esto es lo probado, no lo soportado.

## Resumen

| Ratón | ID | Conexión | DPI | Tasa | Botones | Perfil | Luces |
|-------|-----|----------|-----|------|---------|--------|-------|
| G PRO X SUPERLIGHT 2 | `046d:c54d` | receptor / cable | `0x2202` | `0x8061` | por perfil | `0x07` | no tiene |
| G203 LIGHTSYNC | `046d:c092` | cable | `0x2201` | `0x8060` | por perfil | `0x04` | `0x8071` |

Los dos se complementan a propósito: el PRO X 2 lleva las features nuevas y el
G203 las clásicas, así que entre los dos se ejercita todo el código. Ambos
están en el simulador (`gpx2/modelos.py`), y las pruebas los recorren sin
necesidad de tener ninguno delante.

---

## G PRO X SUPERLIGHT 2 — `046d:c54d`

Inalámbrico por receptor Lightspeed o Bolt, y por cable. Sin luces. Es el
ratón con el que nació el proyecto, porque libratbag/Piper no lo soporta.

**Funciona:**

- **DPI** por `0x2202`, de 100 a 44000, con 957 valores válidos. Tiene eje Y
  independiente: hay que mandar los dos o queda anisotrópico.
- **Tasa de reporte** hasta **8000 Hz por receptor**, que es lo que en Linux no
  conseguía nadie. Hace falta desbloquear las features ocultas (`0x1E00`)
  antes de escribir; sin eso el ratón contesta "sin error" y no hace nada.
- **Perfiles onboard** en formato `0x07`, decodificado aquí y no publicado en
  ningún otro sitio. Se leen y se escriben, con el CRC verificado.
- **Botones**, por el perfil onboard.
- **Batería** por `0x1004`.

**No funciona / no tiene:**

- **`0x1B04`**: no la expone. Los botones no se remapean "desde el sistema",
  sólo por perfil onboard.
- **Luces**: no tiene.
- **Tasa por cable**: topa en 1000 Hz. Es del ratón, no nuestro.

---

## G203 LIGHTSYNC — `046d:c092`

Por cable, sin batería, con RGB. Llegó por el primer informe de la comunidad
y es el que ejercita todo el camino "clásico".

**Funciona:**

- **DPI** por `0x2201`, de 200 a 8000, de 50 en 50.
- **Tasa de reporte** por `0x8060`: 1000, 500, 250 y 125 Hz. Aquí la tasa es
  el periodo en milisegundos, no un índice.
- **Perfiles onboard** en formato `0x04`, con la disposición clásica: la tasa
  en ms y cada nivel de DPI en un solo eje. Sus cuatro niveles de fábrica son
  400, 800, 1600 y 3200. El CRC cuadra, así que se puede reescribir.
- **Botones**, por el perfil onboard. El bloque es idéntico al del `0x07`.
- **Luces** por `0x8071`: **una zona** con **siete efectos** (`0x00`, `0x01`,
  `0x03`, `0x04`, `0x0A`, `0x0D`, `0x0E`).

**Lo que se sabe de sus luces** (ver `PROTOCOLO.md` para los bytes):

| | |
|---|---|
| `0x00` | apagado — confirmado |
| `0x01` | color fijo, RGB en los bytes 1-3 — confirmado escribiendo rojo y azul |
| `0x04` | arcoíris en movimiento — confirmado |
| byte 10 | velocidad: a más valor, más lento — confirmado en las dos direcciones |
| bytes 7 y 8 | también afectan a la velocidad; encajan como un `u16` en little-endian, sin cerrar |
| `0x03`, `0x0A`, `0x0D`, `0x0E` | sin identificar |
| el brillo | sin localizar: en la primera tanda sólo se probaron los bytes que no estaban a cero, y puede estar en uno de los que sí |

**No tiene:**

- `0x1B04`, `0x1004` (va por cable), `0x2202`, `0x8061`, `0x8070`, `0x1300`.

---

## Si tu ratón no está

Hace falta un volcado. Sólo lee, no escribe nada, no necesita instalar nada
más que Python 3, y el fichero que sale no lleva nada personal: el modelo del
ratón y lo que contesta al protocolo.

```
git clone https://github.com/rcv11x/gpx2
cd gpx2
sudo python3 depurar.py --informe
```

Cierra Solaar o Piper antes, si los usas: comparten el canal con el ratón y se
pisan. Te deja un `gpx2-informe.txt`; ábrelo si quieres y mándalo.

Con eso se puede añadir un ratón sin tenerlo delante: pasa a ser un `Modelo`
en `gpx2/modelos.py` y las pruebas empiezan a cubrirlo.

Si tu ratón **tiene luces**, hay una segunda prueba que es la que de verdad
hace falta, porque un volcado no puede contarla: `--probar-efectos` va
poniendo cada efecto y pregunta qué se ve. Eso sí escribe en el ratón, con
copia previa y restauración automática al terminar.

## Cómo se decide qué es "verificado"

Nada entra aquí por deducción. Un dato se apunta cuando:

1. sale de un **volcado real**, con los bytes al lado;
2. si es una escritura, se **relee** para confirmarla —estos ratones contestan
   "sin error" a cosas que ignoran—;
3. y si el ratón puede mentir sobre su propio estado, se **mide**: la tasa de
   reporte se cronometra en `/dev/input`, y los efectos de luz se miran.

Lo que aún no se ha comprobado va marcado como tal, aquí y en el código. Esa
marca es lo que separa una referencia útil de una que repite nuestros propios
errores.
