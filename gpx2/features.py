# -*- coding: utf-8 -*-
"""
Capa 3a — Capacidades (features).

Cada clase envuelve UNA feature HID++ y ofrece una interfaz limpia y agnóstica
(`dpi.get()`, `dpi.set(1600)`), para que las capas de arriba no sepan nunca qué
es un byte.

Sobre el campo CONFIANZA de cada clase:
  "verificada"  -> formato bien documentado por Solaar/libratbag y estable.
  "por validar" -> implementación razonada pero SIN probar contra hardware.
                   La pestaña de Diagnóstico vuelca la respuesta en crudo para
                   poder corregir el decodificador con el ratón delante.
"""

from __future__ import annotations

from dataclasses import dataclass

from .hidpp import IDX_DIRECT, Hidpp, HidppError, NoResponse


class EscrituraIgnorada(Exception):
    """El ratón contestó "sin error" pero el valor no cambió.

    No es un fallo de comunicación: el paquete llegó y el dispositivo lo
    aceptó. Simplemente decidió no aplicarlo — pasa cuando manda el perfil
    onboard, o cuando el enlace inalámbrico fija el ajuste. Merece un tipo
    propio porque la respuesta del programa es distinta a la de un error de
    protocolo: no hay nada que reintentar, hay algo que explicarle al usuario.
    """


class Capability:
    """Base de todas las capacidades."""
    FID: int = 0
    TITULO: str = ""
    CONFIANZA: str = "por validar"

    def __init__(self, hpp: Hidpp):
        self.hpp = hpp
        self.idx = hpp.of(self.FID)

    def call(self, function: int, params: bytes = b"") -> bytes:
        return self.hpp.call(self.idx, function, params)


# ---------------------------------------------------------------------------
# Identidad
# ---------------------------------------------------------------------------

class DeviceName(Capability):
    FID, TITULO, CONFIANZA = 0x0005, "Nombre del dispositivo", "verificada"

    def get(self) -> str:
        total = self.call(0x00)[0]
        buf = b""
        while len(buf) < total:
            buf += self.call(0x01, bytes([len(buf)]))
        return buf[:total].decode("utf-8", "replace").strip()


# ---------------------------------------------------------------------------
# Batería
# ---------------------------------------------------------------------------

@dataclass
class BatteryState:
    percent: int | None
    charging: bool
    texto: str


class UnifiedBattery(Capability):
    FID, TITULO, CONFIANZA = 0x1004, "Batería", "verificada"
    _ESTADOS = {0: "descargando", 1: "cargando", 2: "carga lenta",
                3: "carga completa", 4: "error de carga"}

    def get(self) -> BatteryState:
        r = self.call(0x01)
        estado = r[2]
        return BatteryState(percent=r[0], charging=estado in (1, 2),
                            texto=self._ESTADOS.get(estado, "?"))


class LegacyBattery(Capability):
    FID, TITULO, CONFIANZA = 0x1000, "Batería", "verificada"
    _ESTADOS = {0: "descargando", 1: "cargando", 2: "carga completa",
                3: "carga lenta", 4: "error"}

    def get(self) -> BatteryState:
        r = self.call(0x00)
        return BatteryState(percent=r[0], charging=r[2] in (1, 3),
                            texto=self._ESTADOS.get(r[2], "?"))


# ---------------------------------------------------------------------------
# DPI  (sensibilidad del sensor)
# ---------------------------------------------------------------------------

@dataclass
class DpiInfo:
    actual: int
    por_defecto: int
    minimo: int
    maximo: int
    paso: int
    valores: list[int]     # vacío si el sensor usa rango continuo


class AdjustableDpi(Capability):
    """Feature 0x2201: el modelo clásico. Muy bien documentado."""
    FID, TITULO, CONFIANZA = 0x2201, "DPI", "verificada"

    def sensor_count(self) -> int:
        return self.call(0x00)[0]

    def _lista(self, sensor: int = 0) -> tuple[list[int], int]:
        """Decodifica la lista de DPIs.

        Es una secuencia de u16 big-endian terminada en 0. Un valor con los tres
        bits altos a 1 (máscara 0xE000) no es un DPI: codifica el *paso* entre el
        valor anterior y el siguiente. Así el ratón describe tanto listas
        discretas como rangos continuos.
        """
        raw = self.call(0x01, bytes([sensor]))
        valores, paso = [], 0
        for i in range(1, len(raw) - 1, 2):
            v = int.from_bytes(raw[i:i + 2], "big")
            if v == 0:
                break
            if (v & 0xE000) == 0xE000:
                paso = v & 0x1FFF
            else:
                valores.append(v)
        return valores, paso

    def get(self, sensor: int = 0) -> DpiInfo:
        r = self.call(0x02, bytes([sensor]))
        actual = int.from_bytes(r[1:3], "big")
        defecto = int.from_bytes(r[3:5], "big")
        valores, paso = self._lista(sensor)
        if paso and len(valores) >= 2:
            # rango continuo: [mínimo, máximo] con el paso indicado
            return DpiInfo(actual, defecto, min(valores), max(valores), paso, [])
        return DpiInfo(actual, defecto,
                       min(valores) if valores else actual,
                       max(valores) if valores else actual,
                       paso or 50, valores)

    def valores_validos(self, sensor: int = 0) -> list[int]:
        return self._lista(sensor)[0]

    def niveles(self, sensor: int = 0) -> list[int]:
        """0x2201 no expone niveles predefinidos."""
        return []

    def set(self, dpi: int, sensor: int = 0) -> int:
        r = self.call(0x03, bytes([sensor]) + dpi.to_bytes(2, "big"))
        return int.from_bytes(r[1:3], "big")


class ExtendedDpi(Capability):
    """Feature 0x2202: el modelo nuevo, el que usa el PRO X 2.

    Los números de función están contrastados con la implementación de Solaar
    (`settings_templates.ExtendedAdjustableDpi`), que sí está probada contra
    hardware:  leer = función 5, escribir = función 6.  La versión anterior de
    esta clase usaba la 3 y la 4, que son *lecturas*: por eso escribir el DPI
    no daba error y tampoco hacía nada.
    """
    FID, TITULO, CONFIANZA = 0x2202, "DPI", "verificada"

    F_CAPS, F_RANGOS, F_NIVELES, F_LEER, F_ESCRIBIR = 0x01, 0x02, 0x03, 0x05, 0x06
    DIR_X, DIR_Y = 0, 1

    def __init__(self, hpp):
        super().__init__(hpp)
        self._cache_lista: dict[int, list[int]] = {}

    def sensor_count(self) -> int:
        return self.call(0x00)[0]

    def capacidades(self, sensor: int = 0) -> tuple[bool, bool]:
        """(¿eje Y independiente?, ¿distancia de despegue ajustable?)"""
        r = self.call(self.F_CAPS, bytes([sensor]))
        return bool(r[2] & 0x01), bool(r[2] & 0x02)

    def raw_current(self, sensor: int = 0) -> bytes:
        return self.call(self.F_LEER, bytes([sensor]))

    def _lista(self, sensor: int = 0, direccion: int = 0) -> list[int]:
        """Lista de DPIs válidos, reconstruida de las páginas de 0x2202 f2.

        La respuesta NO es autocontenida: cada página aporta 13 bytes al mismo
        flujo, y un valor se puede partir entre dos páginas. Se van pidiendo
        páginas consecutivas hasta que el flujo acaba en 0x0000.

        En el flujo, un valor con los tres bits altos a 1 no es un DPI: es el
        *paso*, y el valor que le sigue es el final del tramo. Así el ratón
        describe "de 100 a 200 de uno en uno, de 200 a 500 de dos en dos…".
        """
        if sensor in self._cache_lista and direccion == 0:
            return self._cache_lista[sensor]    # el sensor no cambia de rangos

        datos = b""
        for pagina in range(8):                 # tope de seguridad
            r = self.call(self.F_RANGOS, bytes([sensor, direccion, pagina]))
            datos += r[3:]                      # [0..2] son eco de la petición
            if datos[-2:] == b"\x00\x00":
                break

        valores: list[int] = []
        i = 0
        while i + 1 < len(datos):
            v = int.from_bytes(datos[i:i + 2], "big")
            if v == 0:
                break
            if (v >> 13) == 0b111:
                paso = v & 0x1FFF
                hasta = int.from_bytes(datos[i + 2:i + 4], "big")
                if valores and paso and hasta > valores[-1]:
                    valores += list(range(valores[-1] + paso, hasta + 1, paso))
                i += 4
            else:
                valores.append(v)
                i += 2
        if direccion == 0:
            self._cache_lista[sensor] = valores
        return valores

    def valores_validos(self, sensor: int = 0) -> list[int]:
        return self._lista(sensor)

    def niveles(self, sensor: int = 0) -> list[int]:
        """Los DPI que el ratón guarda en su perfil interno.

        Son los que recorre el botón de cambio de DPI del propio ratón, así que
        sirven de atajo: es lo que el usuario ya conoce de su dispositivo.
        """
        r = self.call(self.F_NIVELES, bytes([sensor]))
        niveles = []
        for i in range(2, len(r) - 1, 2):
            v = int.from_bytes(r[i:i + 2], "big")
            if v == 0:
                break
            niveles.append(v)
        return niveles

    def get(self, sensor: int = 0) -> DpiInfo:
        r = self.raw_current(sensor)
        # [0]=sensor [1:3]=DPI X [3:5]=X por defecto [5:7]=DPI Y [7:9]=Y por
        # defecto [9]=distancia de despegue. Un 0 en el actual significa
        # "estoy usando el de fábrica".
        actual = int.from_bytes(r[1:3], "big") or int.from_bytes(r[3:5], "big")
        defecto = int.from_bytes(r[3:5], "big") or actual

        valores = self._lista(sensor)
        if not valores:
            return DpiInfo(actual, defecto, actual, actual, 50, [])

        minimo, maximo = min(valores), max(valores)
        pasos = {b - a for a, b in zip(valores, valores[1:])}
        paso = min(pasos) if pasos else 50
        # Una lista larga es en realidad un rango continuo: al panel le
        # conviene un deslizador, no un desplegable de cientos de entradas.
        discretos = valores if len(valores) <= 24 else []
        return DpiInfo(actual, defecto, minimo, maximo, paso, discretos)

    def set(self, dpi: int, sensor: int = 0) -> int:
        """Escribe el DPI. Ajusta al valor válido más cercano si hace falta."""
        validos = self._lista(sensor)
        if validos:
            dpi = min(validos, key=lambda v: abs(v - dpi))

        tiene_y, tiene_lod = self.capacidades(sensor)
        actual = self.raw_current(sensor)

        payload = bytes([sensor]) + dpi.to_bytes(2, "big")
        # Con eje Y independiente hay que mandarlo también: si no, el ratón
        # quedaría con distinta sensibilidad en horizontal y en vertical.
        payload += dpi.to_bytes(2, "big") if tiene_y else b"\x00\x00"
        # La distancia de despegue no es cosa nuestra: se reenvía tal cual.
        payload += bytes([actual[9] if tiene_lod and len(actual) > 9 else 0])

        self.call(self.F_ESCRIBIR, payload)
        leido = self.get(sensor).actual
        if leido != dpi:
            raise EscrituraIgnorada(
                f"el ratón aceptó la orden pero sigue en {leido} DPI. "
                "Suele significar que manda su perfil interno: prueba a "
                "pasarlo a modo host.")
        return leido


# ---------------------------------------------------------------------------
# Tasa de reporte  (Hz de sondeo)
# ---------------------------------------------------------------------------

@dataclass
class RateInfo:
    actual_hz: int
    disponibles: list[int]              # las que admite la conexión de ahora
    otra_conexion: list[int] | None = None   # las de la otra vía, informativo


class ReportRate(Capability):
    """Feature 0x8060: el ratón contesta con un bitmap de periodos en ms."""
    FID, TITULO, CONFIANZA = 0x8060, "Tasa de reporte", "verificada"

    def get(self) -> RateInfo:
        bitmap = self.call(0x00)[0]
        # bit n activo -> soporta un periodo de (n+1) ms  ->  1000/(n+1) Hz
        hz = [1000 // (n + 1) for n in range(8) if bitmap & (1 << n)]
        actual_ms = self.call(0x01)[0] or 1
        return RateInfo(1000 // actual_ms, sorted(hz, reverse=True))

    def set(self, hz: int) -> None:
        self.call(0x02, bytes([max(1, round(1000 / hz))]))


class ExtendedReportRate(Capability):
    """Feature 0x8061: el modelo nuevo, necesario para 2K/4K/8K.

    Números de función contrastados con Solaar: 1 = lista, 2 = leer, 3 =
    escribir. Antes leíamos la tasa actual de la función 1, que devuelve el
    bitmap de la lista: el primer byte es 0x00 y se interpretaba como índice 0,
    o sea 125 Hz, dijera lo que dijera el ratón.
    """
    FID, TITULO, CONFIANZA = 0x8061, "Tasa de reporte", "por validar"

    F_CAPS_CONEXION, F_LISTA, F_LEER, F_ESCRIBIR = 0x00, 0x01, 0x02, 0x03
    # Comprobado con el PRO X 2 por cable y por receptor: el parámetro 0 es el
    # cable y el 1 el inalámbrico, no al revés como teníamos. En este ratón el
    # cable llega a 1000 Hz y el enlace inalámbrico a 8000 — los 8K son una
    # capacidad del Lightspeed, no del USB.
    WIRED, WIRELESS = 0, 1
    # Índice -> Hz. El ratón habla de periodos (8ms, 4ms… 125us); esta es la
    # misma tabla que usa Solaar, traducida a frecuencia.
    MAPEO_HZ = [125, 250, 500, 1000, 2000, 4000, 8000]

    def __init__(self, hpp):
        super().__init__(hpp)
        self._ultima: int | None = None
        self.id_dispositivo: str = ""    # lo rellena Mouse al construirlo
        self.demo: bool = False

    def _recordar(self, hz: int) -> None:
        self._ultima = hz
        if self.id_dispositivo:
            from .profiles import guardar_tasa_recordada
            try:
                guardar_tasa_recordada(self.id_dispositivo, hz, self.demo)
            except OSError:
                pass

    def _recordada(self) -> int | None:
        if self._ultima is not None:
            return self._ultima
        if not self.id_dispositivo:
            return None
        from .profiles import leer_tasa_recordada
        try:
            return leer_tasa_recordada(self.id_dispositivo, self.demo)
        except OSError:
            return None

    def _conexion_actual(self) -> int:
        """Por cable y por receptor el ratón admite tasas distintas."""
        return self.WIRED if self.hpp.index == IDX_DIRECT else self.WIRELESS

    def raw_capabilities(self, conexion: int) -> bytes:
        return self.call(self.F_CAPS_CONEXION, bytes([conexion]))

    def _hz_de_bitmap(self, bitmap: int) -> list[int]:
        return [self.MAPEO_HZ[n] for n in range(len(self.MAPEO_HZ))
                if bitmap & (1 << n)]

    def get(self, conexion: int | None = None) -> RateInfo:
        """Lo que admite la conexión de ahora, y lo que daría la otra.

        La lista que manda es la de la función 1: cambia según por dónde esté
        conectado el ratón, y es la que decide qué acepta la escritura. Por
        cable devuelve 0x0f, y escribir 8000 Hz responde "parámetro inválido";
        por receptor devuelve 0x7f y los acepta.

        La función 0 informa de cada vía por separado, y sirve para poder decir
        "de forma inalámbrica llegarías a 8000".
        """
        bitmap = int.from_bytes(self.call(self.F_LISTA)[0:2], "big")
        aqui = sorted(self._hz_de_bitmap(bitmap), reverse=True)

        if conexion is None:
            conexion = self._conexion_actual()
        try:
            otra = self.WIRELESS if conexion == self.WIRED else self.WIRED
            mapa = int.from_bytes(self.raw_capabilities(otra)[0:2], "big")
            alla = sorted(self._hz_de_bitmap(mapa), reverse=True)
        except (HidppError, NoResponse, OSError):
            alla = None

        idx = self.call(self.F_LEER)[0]
        actual = self.MAPEO_HZ[idx] if idx < len(self.MAPEO_HZ) else 0
        # La función 2 no se entera de los cambios: si alguna vez le hemos
        # escrito una tasa a este ratón, vale más eso que lo que conteste.
        recordada = self._recordada()
        if recordada is not None:
            actual = recordada
        return RateInfo(actual, aqui, alla)

    FID_OCULTAS = 0x1E00

    def _abrir_ocultas(self) -> bool | None:
        """Desbloquea las features internas. Devuelve si estaban ya abiertas.

        Sin esto, escribir la tasa por receptor se acepta sin error y el
        enlace no cambia. Con esto, cambia de verdad: medido en un PRO X 2,
        el intervalo pasa de 1,000 ms a 0,125 ms. Está en PROTOCOLO.md.

        None si el ratón no tiene la feature.
        """
        if not self.hpp.has(self.FID_OCULTAS):
            return None
        idx = self.hpp.of(self.FID_OCULTAS)
        try:
            ya = bool(self.hpp.call(idx, 0x00)[0])
            if not ya:
                self.hpp.call(idx, 0x01, b"\x01")
            return ya
        except (HidppError, NoResponse, OSError):
            return None

    def _cerrar_ocultas(self, estaban_abiertas: bool | None) -> None:
        if estaban_abiertas is not False:
            return          # no las abrimos nosotros, o no existen
        try:
            self.hpp.call(self.hpp.of(self.FID_OCULTAS), 0x01, b"\x00")
        except (HidppError, NoResponse, OSError):
            pass

    def set(self, hz: int) -> None:
        idx = self.MAPEO_HZ.index(hz)
        previo = self._abrir_ocultas()
        try:
            self.call(self.F_ESCRIBIR, bytes([idx]))
        finally:
            self._cerrar_ocultas(previo)

        # No se comprueba releyendo: la función 2 devuelve el índice anterior
        # aunque el enlace haya cambiado de verdad. Costó una sesión entera
        # descubrirlo, y sólo se ve cronometrando los informes que llegan al
        # kernel (`depurar.py --medir`). Se recuerda lo escrito para no
        # enseñar después un valor que sabemos que es falso.
        self._recordar(hz)
        if previo is None:
            # Sin 0x1E00 no hay forma de desbloquear, y ahí la función 2 sí
            # es el único indicio que tenemos.
            leido = self.call(self.F_LEER)[0]
            if leido != idx:
                actual = (self.MAPEO_HZ[leido] if leido < len(self.MAPEO_HZ)
                          else "?")
                raise EscrituraIgnorada(
                    f"el ratón aceptó la orden pero sigue a {actual} Hz, y no "
                    "expone la feature que desbloquea el cambio (0x1E00).")


# ---------------------------------------------------------------------------
# Modo onboard / host
# ---------------------------------------------------------------------------

class ModeStatus(Capability):
    """Feature 0x8090. Informativa: dice si manda el ratón o manda el PC.

    Su función de escritura devuelve "fuera de rango" en el PRO X 2, así que
    para *cambiar* de modo se usa OnboardProfiles (0x8100), que es lo que hace
    Solaar. Aquí sólo leemos.
    """
    FID, TITULO, CONFIANZA = 0x8090, "Modo de funcionamiento", "por validar"

    def get(self) -> str:
        r = self.call(0x00)
        return "host (manda el PC)" if r[0] & 0x01 else "onboard (manda el ratón)"


class OnboardProfiles(Capability):
    """Feature 0x8100. Es la que de verdad decide quién manda.

    Mientras los perfiles onboard estén activos, el firmware reimpone su propio
    DPI y su propia tasa de reporte, y lo que escribamos por 0x2202 se pierde.
    Los valores (0x01 activar, 0x02 desactivar) y los números de función salen
    de la implementación de Solaar, probada contra hardware.
    """
    FID, TITULO, CONFIANZA = 0x8100, "Perfiles onboard", "verificada"

    F_ESCRIBIR_MODO, F_LEER_MODO = 0x01, 0x02
    ONBOARD, HOST = 0x01, 0x02

    def __init__(self, hpp):
        super().__init__(hpp)
        self._cache_info: bytes | None = None

    def info(self) -> bytes:
        return self.call(0x00)

    def modo(self) -> int:
        return self.call(self.F_LEER_MODO)[0]

    def es_host(self) -> bool:
        return self.modo() != self.ONBOARD

    def set_host(self, host: bool = True) -> bool:
        """Pasa a modo host (o vuelve a onboard). Devuelve si quedó como se pidió."""
        self.call(self.F_ESCRIBIR_MODO, bytes([self.HOST if host else self.ONBOARD]))
        return self.es_host() == host

    def get(self) -> str:
        return "host (manda el PC)" if self.es_host() else "onboard (manda el ratón)"

    # -- memoria de perfiles --------------------------------------------------
    #
    # Lo que se escribe aquí sobrevive a apagar el ratón y funciona sin
    # software en cualquier ordenador. Ver `gpx2/onboard.py` y PROTOCOLO.md.

    F_LEER_MEM, F_ABRIR_ESCRITURA, F_TROZO, F_CERRAR = 0x05, 0x06, 0x07, 0x08

    def _info(self) -> bytes:
        if self._cache_info is None:
            self._cache_info = self.call(0x00)
        return self._cache_info

    @property
    def num_perfiles(self) -> int:
        return self._info()[3]

    @property
    def num_botones(self) -> int:
        return self._info()[5]

    @property
    def tam_sector(self) -> int:
        return int.from_bytes(self._info()[7:9], "big")

    @property
    def formato(self) -> int:
        return self._info()[1]

    def cabeceras(self) -> list[tuple[int, bool]]:
        """El directorio de perfiles: [(sector, habilitado), …]."""
        salida = []
        for base in (0, 1):                 # si el sector 0 está vacío, la ROM
            crudo = self.leer_sector(base, 16)
            if crudo is None:
                continue
            for i in range(0, 16, 4):
                sector = int.from_bytes(crudo[i:i + 2], "big")
                if sector in (0x0000, 0xFFFF):
                    break
                salida.append((sector, bool(crudo[i + 2])))
            if salida:
                break
        return salida

    def leer_sector(self, sector: int, tam: int | None = None) -> bytes | None:
        """Lee un sector entero.

        Cada petición devuelve 16 bytes y el tamaño de sector no es múltiplo de
        16, así que el último bloque se pide solapado desde el final: pedirlo
        en su sitio se saldría del sector y la petición falla.
        """
        tam = tam or self.tam_sector
        datos, desp = b"", 0
        try:
            while desp <= tam - 16:
                datos += self.call(self.F_LEER_MEM,
                                   bytes([sector >> 8, sector & 0xFF,
                                          desp >> 8, desp & 0xFF]))
                desp += 16
            if len(datos) < tam and tam % 16:
                cola = self.call(self.F_LEER_MEM,
                                 bytes([sector >> 8, sector & 0xFF,
                                        (tam - 16) >> 8, (tam - 16) & 0xFF]))
                datos += cola[16 - tam % 16:]
        except (HidppError, NoResponse, OSError):
            return None
        return datos[:tam]

    def escribir_sector(self, sector: int, datos: bytes) -> None:
        """Escribe un sector completo: abrir, mandar trozos, cerrar."""
        tam = len(datos)
        self.call(self.F_ABRIR_ESCRITURA,
                  bytes([sector >> 8, sector & 0xFF, 0, 0,
                         tam >> 8, tam & 0xFF]))
        for desp in range(0, tam, 16):
            self.call(self.F_TROZO, datos[desp:desp + 16])
        self.call(self.F_CERRAR)


# ---------------------------------------------------------------------------
# Registro: qué clase usar para cada feature, en orden de preferencia
# ---------------------------------------------------------------------------

DPI_CLASSES = [ExtendedDpi, AdjustableDpi]        # 0x2202 gana a 0x2201
RATE_CLASSES = [ExtendedReportRate, ReportRate]   # 0x8061 gana a 0x8060
BATTERY_CLASSES = [UnifiedBattery, LegacyBattery]


# ---------------------------------------------------------------------------
# Botones reprogramables  (fase 6)
# ---------------------------------------------------------------------------

# Identificadores de control conocidos. Los que no estén aquí se muestran como
# "Control 0xNNNN": no es un error, sólo que aún no le hemos puesto nombre.
CONTROLES = {
    0x0050: "Clic izquierdo",
    0x0051: "Clic derecho",
    0x0052: "Botón central",
    0x0053: "Atrás (botón 4)",
    0x0056: "Adelante (botón 5)",
    0x005B: "Rueda a la izquierda",
    0x005D: "Rueda a la derecha",
    0x00C3: "Cambio de DPI",
    0x00C4: "Botón de gesto",
}


@dataclass
class Control:
    """Un botón físico del ratón, tal y como lo describe el propio ratón."""
    cid: int             # identificador de este control
    task_id: int         # qué hace de fábrica
    flags: int
    pos: int
    group: int           # a qué grupo pertenece
    gmask: int           # qué grupos puede *adoptar* si lo remapeas
    extra: int

    @property
    def nombre(self) -> str:
        return CONTROLES.get(self.cid, f"Control 0x{self.cid:04X}")

    @property
    def es_boton_raton(self) -> bool:
        return bool(self.flags & 0x01)

    @property
    def reprogramable(self) -> bool:
        return bool(self.flags & 0x10)

    @property
    def divertible(self) -> bool:
        """Puede enviarse al software en vez de al sistema (para macros)."""
        return bool(self.flags & 0x20)

    @property
    def virtual(self) -> bool:
        return bool(self.flags & 0x80)

    def admite(self, destino: "Control") -> bool:
        """Regla del protocolo: sólo se puede remapear a un control cuyo grupo
        esté permitido en la máscara de este. No es una limitación nuestra, la
        impone el firmware — por eso el clic izquierdo casi nunca se puede
        mover."""
        if destino.group == 0:
            return False
        return bool(self.gmask & (1 << (destino.group - 1)))


@dataclass
class Reporte:
    """Cómo está configurado ahora mismo un control."""
    cid: int
    divertido: bool
    persistente: bool
    remapeado_a: int     # 0 = sin remapear, hace lo suyo de fábrica


class ReprogrammableControls(Capability):
    """Feature 0x1B04: leer los botones y reasignarlos.

    Implementado a partir de la documentación del protocolo, PENDIENTE de
    validar con el ratón real. La pestaña de Diagnóstico vuelca las respuestas
    en crudo para poder corregirlo sin adivinar.
    """
    FID, TITULO, CONFIANZA = 0x1B04, "Botones", "por validar"

    # bits del byte de flags en setCidReporting: cada ajuste va acompañado de
    # un bit de "sí, quiero cambiar esto", para poder tocar uno sin pisar los
    # demás.
    DIVERT, DIVERT_VALIDO = 0x01, 0x02
    PERSIST, PERSIST_VALIDO = 0x04, 0x08
    RAW_XY, RAW_XY_VALIDO = 0x10, 0x20

    def count(self) -> int:
        return self.call(0x00)[0]

    def controls(self) -> list[Control]:
        salida = []
        for i in range(self.count()):
            r = self.call(0x01, bytes([i]))
            salida.append(Control(
                cid=int.from_bytes(r[0:2], "big"),
                task_id=int.from_bytes(r[2:4], "big"),
                flags=r[4], pos=r[5], group=r[6], gmask=r[7],
                extra=r[8] if len(r) > 8 else 0))
        return salida

    def reporting(self, cid: int) -> Reporte:
        r = self.call(0x02, cid.to_bytes(2, "big"))
        return Reporte(cid=int.from_bytes(r[0:2], "big"),
                       divertido=bool(r[2] & self.DIVERT),
                       persistente=bool(r[2] & self.PERSIST),
                       remapeado_a=int.from_bytes(r[3:5], "big"))

    def remapear(self, cid: int, destino_cid: int) -> None:
        """Hace que `cid` se comporte como `destino_cid`. destino 0 = original."""
        self.call(0x03, cid.to_bytes(2, "big") + bytes([0])
                  + destino_cid.to_bytes(2, "big"))

    def restaurar(self, cid: int) -> None:
        self.remapear(cid, 0)


# ---------------------------------------------------------------------------
# Información del dispositivo / versiones de firmware
# ---------------------------------------------------------------------------

TIPOS_FIRMWARE = {
    0: "Firmware principal",
    1: "Bootloader",
    2: "Hardware",
    3: "Táctil",
    4: "Óptico",
    5: "Otro",
}


@dataclass
class Firmware:
    tipo: int
    prefijo: str
    numero: int
    revision: int
    build: int

    @property
    def nombre_tipo(self) -> str:
        return TIPOS_FIRMWARE.get(self.tipo, f"Tipo {self.tipo}")

    @property
    def version(self) -> str:
        # Formato de Logitech: PREFIJO NN.MM.BXXXX, con los números en BCD.
        return (f"{self.prefijo} {self.numero:02X}.{self.revision:02X}"
                f".B{self.build:04X}")


class DeviceInfo(Capability):
    """Feature 0x0003. Da las versiones de firmware y el identificador único.

    Sólo lectura: aquí no se escribe nada nunca. Actualizar firmware es harina
    de otro costal y no lo hace este programa (ver la pestaña de Firmware).
    """
    FID, TITULO, CONFIANZA = 0x0003, "Información del dispositivo", "verificada"

    def entidades(self) -> int:
        return self.call(0x00)[0]

    def unit_id(self) -> str:
        r = self.call(0x00)
        return r[1:5].hex()

    def firmwares(self) -> list[Firmware]:
        salida = []
        for i in range(self.entidades()):
            r = self.call(0x01, bytes([i]))
            salida.append(Firmware(
                tipo=r[0],
                prefijo=r[1:4].decode("ascii", "replace").strip("\x00"),
                numero=r[4], revision=r[5],
                build=int.from_bytes(r[6:8], "big")))
        return salida
