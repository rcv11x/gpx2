# -*- coding: utf-8 -*-
"""
Perfiles guardados en la memoria del ratón (feature 0x8100).

Lo que se escribe aquí **sobrevive a apagar el ratón** y funciona sin software
en cualquier ordenador. Es lo que hace el programa de Logitech en Windows.

Hay dos disposiciones y no son intercambiables. Hasta el formato 0x06, la tasa
va en milisegundos y cada nivel de DPI es un u16 de un solo eje. El 0x07 la
cambió por un índice de la tabla de 0x8061 y le dio a cada nivel sus dos ejes y
su distancia de despegue. Leer uno con el molde del otro no da error: da
números, y encima verosímiles. El bloque de botones sí es igual en ambas.

El 0x07 está decodificado en `PROTOCOLO.md` a partir de volcados de un PRO X 2;
Solaar sólo maneja el 0x06, así que esa disposición no está publicada en ningún
otro sitio.

Regla que sigue todo este módulo: **al escribir se parte del sector que el
ratón ya tenía y sólo se cambian los campos que entendemos**. Del sector hay
trozos sin identificar, y reconstruirlo desde cero significaría inventarlos.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Índice -> Hz, la misma tabla que usa la feature 0x8061.
MAPEO_HZ = [125, 250, 500, 1000, 2000, 4000, 8000]

# Disposición del sector en el formato 0x07. Ver PROTOCOLO.md.
OFF_TASA = 0
OFF_TASA_2 = 1
OFF_NIVEL_DEFECTO = 2
OFF_NIVELES = 4
BYTES_POR_NIVEL = 5          # dpiX(2 LE), dpiY(2 LE), distancia de despegue(1)
NUM_NIVELES = 5

# Y en las anteriores: tasa en ms, nivel por defecto, nivel del botón de DPI,
# y cinco niveles de un solo eje.
CLASICO_OFF_NIVEL_DEFECTO = 1
CLASICO_OFF_NIVELES = 3
CLASICO_BYTES_POR_NIVEL = 2
FORMATO_NUEVO = 0x07         # a partir de aquí, la disposición del PRO X 2


def crc16_ccitt(datos: bytes) -> int:
    """CRC-16/CCITT-FALSE: polinomio 0x1021, inicio 0xFFFF, sin reflejar.

    Cierra cada sector y el ratón lo comprueba. Un sector con el CRC mal se
    rechaza, así que esto tiene que estar bien antes de escribir nada.
    """
    crc = 0xFFFF
    for byte in datos:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


@dataclass
class Nivel:
    """Uno de los cinco escalones de DPI que guarda el perfil."""
    x: int
    y: int
    despegue: int

    @property
    def isotropico(self) -> bool:
        return self.x == self.y


@dataclass
class PerfilOnboard:
    """Lo que sabemos leer y escribir de un perfil del ratón."""
    tasa_hz: int
    nivel_por_defecto: int
    niveles: list[Nivel]
    botones: list[bytes] = field(default_factory=list)

    # El sector tal cual lo dio el ratón. Es la base sobre la que se escribe:
    # así los campos que no entendemos viajan intactos.
    crudo: bytes = b""
    inicio_botones: int | None = None
    # Hace falta al escribir: decide dónde va cada campo. Por omisión, el del
    # PRO X 2, que es con el que se escribió este módulo.
    formato: int = FORMATO_NUEVO

    @property
    def clasico(self) -> bool:
        return self.formato < FORMATO_NUEVO

    @property
    def dpi_por_defecto(self) -> int:
        if 0 <= self.nivel_por_defecto < len(self.niveles):
            return self.niveles[self.nivel_por_defecto].x
        return self.niveles[0].x if self.niveles else 0


def _indice_tasa(hz: int) -> int:
    return MAPEO_HZ.index(hz)


def leer_perfil(crudo: bytes, num_botones: int,
                formato: int = FORMATO_NUEVO) -> PerfilOnboard:
    """Decodifica un sector de perfil, según la disposición de su formato."""
    clasico = formato < FORMATO_NUEVO
    niveles = []

    if clasico:
        # Un solo eje y sin distancia de despegue: se rellenan con el propio
        # DPI y con cero, para que el resto del programa no tenga que saber de
        # qué formato viene el perfil.
        for i in range(NUM_NIVELES):
            o = CLASICO_OFF_NIVELES + i * CLASICO_BYTES_POR_NIVEL
            if o + CLASICO_BYTES_POR_NIVEL > len(crudo):
                break
            dpi = int.from_bytes(crudo[o:o + 2], "little")
            if dpi in (0, 0xFFFF):      # nivel sin usar
                continue
            niveles.append(Nivel(x=dpi, y=dpi, despegue=0))
        ms = crudo[0]
        tasa_hz = 1000 // ms if ms else 0
        nivel_defecto = crudo[CLASICO_OFF_NIVEL_DEFECTO]
    else:
        for i in range(NUM_NIVELES):
            o = OFF_NIVELES + i * BYTES_POR_NIVEL
            if o + BYTES_POR_NIVEL > len(crudo):
                break
            niveles.append(Nivel(
                x=int.from_bytes(crudo[o:o + 2], "little"),
                y=int.from_bytes(crudo[o + 2:o + 4], "little"),
                despegue=crudo[o + 4]))
        idx = crudo[OFF_TASA]
        tasa_hz = MAPEO_HZ[idx] if idx < len(MAPEO_HZ) else 0
        nivel_defecto = crudo[OFF_NIVEL_DEFECTO]

    inicio = buscar_botones(crudo, num_botones)
    botones = []
    if inicio is not None:
        botones = [crudo[inicio + i * 4:inicio + i * 4 + 4]
                   for i in range(num_botones)]

    return PerfilOnboard(
        tasa_hz=tasa_hz, nivel_por_defecto=nivel_defecto,
        niveles=niveles, botones=botones,
        crudo=crudo, inicio_botones=inicio, formato=formato)


def escribir_perfil(perfil: PerfilOnboard) -> bytes:
    """Compone el sector a escribir, partiendo del que el ratón tenía.

    Sólo se sustituyen los campos conocidos; el resto se copia tal cual. El CRC
    se recalcula sobre todo menos sus propios dos bytes.
    """
    if not perfil.crudo:
        raise ValueError("hace falta el sector original: no se inventa uno")
    tam = len(perfil.crudo)
    cuerpo = bytearray(perfil.crudo[:tam - 2])

    if perfil.clasico:
        if perfil.tasa_hz:
            cuerpo[0] = max(1, round(1000 / perfil.tasa_hz))
        cuerpo[CLASICO_OFF_NIVEL_DEFECTO] = perfil.nivel_por_defecto
        for i, nivel in enumerate(perfil.niveles[:NUM_NIVELES]):
            o = CLASICO_OFF_NIVELES + i * CLASICO_BYTES_POR_NIVEL
            cuerpo[o:o + 2] = nivel.x.to_bytes(2, "little")
    else:
        cuerpo[OFF_TASA] = _indice_tasa(perfil.tasa_hz)
        cuerpo[OFF_NIVEL_DEFECTO] = perfil.nivel_por_defecto
        for i, nivel in enumerate(perfil.niveles[:NUM_NIVELES]):
            o = OFF_NIVELES + i * BYTES_POR_NIVEL
            cuerpo[o:o + 2] = nivel.x.to_bytes(2, "little")
            cuerpo[o + 2:o + 4] = nivel.y.to_bytes(2, "little")
            cuerpo[o + 4] = nivel.despegue

    if perfil.inicio_botones is not None:
        for i, b in enumerate(perfil.botones):
            o = perfil.inicio_botones + i * 4
            cuerpo[o:o + 4] = b

    return bytes(cuerpo) + crc16_ccitt(bytes(cuerpo)).to_bytes(2, "big")


# ---------------------------------------------------------------------------
# Botones
# ---------------------------------------------------------------------------

# Un botón son cuatro bytes: el nibble alto del primero dice qué hace.
ENVIAR, FUNCION = 0x8, 0x9

BOTONES_RATON = {0x0001: "Clic izquierdo", 0x0002: "Clic derecho",
                 0x0004: "Clic central", 0x0008: "Atrás", 0x0010: "Adelante"}
FUNCIONES = {0x00: "Nada", 0x03: "DPI siguiente", 0x04: "DPI anterior",
             0x05: "Ciclar DPI", 0x06: "DPI por defecto", 0x07: "DPI temporal",
             0x08: "Perfil siguiente", 0x09: "Perfil anterior",
             0x0A: "Ciclar perfil", 0x0C: "Estado de batería",
             0x0F: "Cambiar de host"}

# Lo que la interfaz puede ofrecer, por nombre.
ACCIONES: dict[str, bytes] = {
    **{n: bytes([0x80, 0x01, v >> 8, v & 0xFF])
       for v, n in BOTONES_RATON.items()},
    **{n: bytes([0x90, f, 0x00, 0x00]) for f, n in FUNCIONES.items() if f},
}


def describir_boton(b: bytes) -> str:
    """Traduce los cuatro bytes de un botón a algo que se pueda enseñar."""
    if len(b) < 4:
        return "?"
    comportamiento = b[0] >> 4
    if comportamiento == ENVIAR:
        if b[1] == 0x01:
            valor = (b[2] << 8) | b[3]
            return BOTONES_RATON.get(valor, f"Botón 0x{valor:04X}")
        if b[1] == 0x00:
            return "Nada"
        if b[1] == 0x02:
            return f"Tecla 0x{b[3]:02X}"
        if b[1] == 0x03:
            return f"Multimedia 0x{(b[2] << 8) | b[3]:04X}"
    if comportamiento == FUNCION:
        return FUNCIONES.get(b[1], f"Función 0x{b[1]:02X}")
    if comportamiento in (0x0, 0x1, 0x2):
        return "Macro"
    return f"Desconocido 0x{b[0]:02X}"


def buscar_botones(sector: bytes, cuantos: int) -> int | None:
    """Localiza dónde empieza el bloque de botones.

    No se supone la posición: en el formato 0x06 es el byte 32, pero el 0x07
    mete cinco bytes por nivel de DPI en vez de dos y los desplaza. Se exige
    que el segundo byte sea un tipo o una función que existan — con aceptar
    sólo el nibble de comportamiento, los bytes de los niveles de DPI daban un
    falso positivo.
    """
    def plausible(b: bytes) -> bool:
        if len(b) < 4:
            return False
        comportamiento = b[0] >> 4
        if comportamiento == ENVIAR:
            return b[1] in (0x00, 0x01, 0x02, 0x03)
        if comportamiento == FUNCION:
            return b[1] in FUNCIONES
        return False

    for inicio in range(0, len(sector) - cuantos * 4 + 1):
        if all(plausible(sector[inicio + i * 4:inicio + i * 4 + 4])
               for i in range(cuantos)):
            return inicio
    return None
