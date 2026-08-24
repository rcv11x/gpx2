#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan_hidpp.py -- Paso 0 del proyecto: encontrar el ratón y hablar con él.

No necesita NINGUNA librería externa. Sólo lee /sys y abre /dev/hidraw*.

Qué hace:
  1. Lista todos los nodos /dev/hidraw* del sistema.
  2. Mira el "report descriptor" de cada uno para ver cuál expone el canal
     privado de Logitech (HID++), que es por donde se configura el ratón.
  3. Hace un "ping" HID++ para saber qué versión de protocolo habla.
  4. Enumera TODAS las features (capacidades) que el ratón dice tener.
  5. Lee el nombre y la batería si puede.

Uso:
    sudo python3 scan_hidpp.py                 # escanea todo
    sudo python3 scan_hidpp.py /dev/hidraw5    # fuerza un nodo concreto

Hace falta sudo hasta que instales la regla udev (ver 99-logitech-hidpp.rules).

Nota: este script duplica a propósito parte de gpx2/transport.py y gpx2/hidpp.py.
Es intencionado: así funciona en una máquina donde no hay nada instalado, que es
justo cuando más falta hace un diagnóstico.
"""

import os
import select
import sys
import time
from glob import glob

LOGITECH = 0x046D

# Tabla orientativa de features HID++ 2.0. Las que no esten aquí se imprimen
# igualmente como "0xXXXX (desconocida)" -- eso NO es un error, sólo significa
# que aún no le hemos puesto nombre.
FEATURES = {
    0x0000: "IRoot                     (raiz del protocolo)",
    0x0001: "IFeatureSet               (lista de features)",
    0x0002: "IFeatureInfo",
    0x0003: "DeviceInformation         (firmware, serial)",
    0x0005: "DeviceNameAndType         (nombre del ratón)",
    0x0007: "DeviceFriendlyName",
    0x0008: "KeepAlive",
    0x0020: "ConfigChange",
    0x0021: "UniqueIdentifier",
    0x00C2: "DFUControl                (actualización de firmware)",
    0x1000: "BatteryLevelStatus        (batería, modelo antiguo)",
    0x1001: "BatteryVoltage",
    0x1004: "UnifiedBattery            (batería, modelo nuevo)",
    0x1300: "LedControl",
    0x1802: "DeviceReset",
    0x1814: "ChangeHost",
    0x1815: "HostsInfo",
    0x1B04: "ReprogrammableKeysV4      *** REMAPEO DE BOTONES ***",
    0x2100: "VerticalScrolling",
    0x2110: "SmartShift",
    0x2201: "AdjustableDPI             *** DPI (modelo antiguo) ***",
    0x2202: "ExtendedAdjustableDPI     *** DPI (modelo nuevo) ***",
    0x2205: "PointerMotionScaling",
    0x2250: "AnalyticsTrackEvent       (telemetría - NO la usaremos)",
    0x8060: "ReportRate                *** HZ DE SONDEO ***",
    0x8061: "ExtendedAdjustableReportRate  *** HZ (hasta 8K) ***",
    0x8070: "ColorLedEffects",
    0x8071: "RGBEffects",
    0x8090: "ModeStatus                (onboard vs host)",
    0x8100: "OnboardProfiles           (perfiles en memoria del ratón)",
    0x8110: "MouseButtonSpy",
    0x8111: "LatencyMonitoring",
    0x8123: "ForceSensingButton",
}

# Codigos de error HID++ 2.0
ERRORS_20 = {
    0x00: "sin error", 0x01: "parámetro inválido", 0x02: "fuera de rango",
    0x03: "batería critica", 0x04: "función inválida", 0x05: "feature inválida",
    0x06: "sin permiso", 0x07: "índice de feature inválido", 0x08: "solicitud inválida",
    0x09: "no soportado",
}


class HidppError(Exception):
    def __init__(self, code, legacy=False):
        self.code = code
        self.legacy = legacy
        fam = "HID++1.0" if legacy else "HID++2.0"
        super().__init__(f"error {fam} 0x{code:02X} ({ERRORS_20.get(code, '?')})")


# ---------------------------------------------------------------------------
# 1. Descubrimiento: que nodos hidraw hablan HID++
# ---------------------------------------------------------------------------

def parse_descriptor(desc: bytes) -> dict:
    """Recorre un HID report descriptor y devuelve {usage_page: {report_ids}}.

    Es un formato de bytes tipo TLV. Sólo nos importan dos etiquetas globales:
    'Usage Page' (0x04) y 'Report ID' (0x84). Heurística suficiente: asociamos
    cada Report ID a la Usage Page vigente en ese momento.
    """
    out, usage_page, i = {}, 0, 0
    while i < len(desc):
        prefix = desc[i]
        if prefix == 0xFE:                      # item largo (raro)
            i += 3 + desc[i + 1]
            continue
        size = prefix & 0x03
        size = 4 if size == 3 else size
        data = int.from_bytes(desc[i + 1:i + 1 + size], "little") if size else 0
        tag = prefix & 0xFC
        if tag == 0x04:                          # Usage Page
            usage_page = data
        elif tag == 0x84:                        # Report ID
            out.setdefault(usage_page, set()).add(data)
        i += 1 + size
    return out


def hidraw_nodes():
    """Devuelve info de cada /dev/hidraw* leyendo /sys (no abre nada)."""
    nodes = []
    for sysdir in sorted(glob("/sys/class/hidraw/hidraw*")):
        name = os.path.basename(sysdir)
        info = {"dev": f"/dev/{name}", "vid": 0, "pid": 0, "name": "?", "hidpp": False}
        try:
            for line in open(f"{sysdir}/device/uevent"):
                k, _, v = line.strip().partition("=")
                if k == "HID_NAME":
                    info["name"] = v
                elif k == "HID_ID":                       # BUS:VID:PID en hex
                    parts = v.split(":")
                    info["vid"], info["pid"] = int(parts[1], 16), int(parts[2], 16)
            desc = open(f"{sysdir}/device/report_descriptor", "rb").read()
            pages = parse_descriptor(desc)
            # HID++ vive en una "usage page" de fabricante (>= 0xFF00) con los
            # report id 0x10 (corto, 7 bytes) y/o 0x11 (largo, 20 bytes).
            for page, rids in pages.items():
                if page >= 0xFF00 and (0x10 in rids or 0x11 in rids):
                    info["hidpp"] = True
                    info["page"] = page
                    info["rids"] = sorted(rids)
        except OSError:
            pass
        nodes.append(info)
    return nodes


# ---------------------------------------------------------------------------
# 2. La conversacion: HID++ 2.0 sobre hidraw
# ---------------------------------------------------------------------------

class Hidpp:
    SHORT, LONG = 0x10, 0x11
    SW_ID = 0x0A        # "firma" de nuestro software (1..15), para reconocer
                        # nuestras propias respuestas entre las notificaciones

    def __init__(self, path):
        self.path = path
        self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)

    def close(self):
        os.close(self.fd)

    def _drain(self):
        """Tira notificaciones pendientes antes de preguntar algo."""
        while select.select([self.fd], [], [], 0)[0]:
            try:
                os.read(self.fd, 64)
            except OSError:
                return

    def request(self, index, feature_index, function, params=b"", timeout=1.0):
        """Envía una petición y espera SU respuesta. Devuelve los bytes de datos.

        Formato del paquete:  [report_id][indice_dispositivo][indice_feature][función<<4 | sw_id][params...]
        """
        params = bytes(params)
        report_id, length = (self.SHORT, 7) if len(params) <= 3 else (self.LONG, 20)
        head = bytes([report_id, index, feature_index, (function << 4) | self.SW_ID])
        self._drain()
        os.write(self.fd, (head + params).ljust(length, b"\x00"))

        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("sin respuesta")
            if not select.select([self.fd], [], [], left)[0]:
                continue
            data = os.read(self.fd, 64)
            if len(data) < 6 or data[1] != index:
                continue
            if data[2] == 0xFF and data[3] == feature_index and data[4] == head[3]:
                raise HidppError(data[5])                    # error HID++ 2.0
            if data[2] == 0x8F:
                raise HidppError(data[5], legacy=True)       # error HID++ 1.0
            if data[2] == feature_index and data[3] == head[3]:
                return data[4:]                              # respuesta buena
            # cualquier otra cosa es una notificacion espontánea: la ignoramos

    # -- helpers de alto nivel ------------------------------------------------

    def ping(self, index, timeout=0.5):
        """IRoot.getProtocolVersion -> (major, minor) o None si no contesta."""
        r = self.request(index, 0x00, 0x01, b"\x00\x00\x5A", timeout=timeout)
        if r[2] != 0x5A:
            return None
        return (r[0], r[1])

    def get_feature(self, index, feature_id):
        """IRoot.getFeature -> índice local de esa feature (0 = no existe)."""
        r = self.request(index, 0x00, 0x00, feature_id.to_bytes(2, "big"))
        return r[0]

    def feature_table(self, index):
        """Enumera todas las features del dispositivo via IFeatureSet."""
        fs = self.get_feature(index, 0x0001)
        if fs == 0:
            return []
        count = self.request(index, fs, 0x00)[0]
        table = [(0, 0x0000, 0, 0)]
        for i in range(1, count + 1):
            r = self.request(index, fs, 0x01, bytes([i]))
            fid = int.from_bytes(r[0:2], "big")
            table.append((i, fid, r[2], r[3]))
        return table

    def device_name(self, index, fidx):
        """DeviceNameAndType: el nombre viene troceado de 16 en 16 caracteres."""
        total = self.request(index, fidx, 0x00)[0]
        out = b""
        while len(out) < total:
            out += self.request(index, fidx, 0x01, bytes([len(out)]))
        return out[:total].decode("utf-8", "replace")

    def unified_battery(self, index, fidx):
        r = self.request(index, fidx, 0x01)
        return {"porcentaje": r[0], "nivel": r[1], "estado": r[2],
                "cargando": bool(r[3] & 0x01)}


# ---------------------------------------------------------------------------
# 3. Programa principal
# ---------------------------------------------------------------------------

def probe(dev_path):
    print(f"\n>>> Probando {dev_path}")
    try:
        h = Hidpp(dev_path)
    except PermissionError:
        print("    SIN PERMISO. Ejecuta con sudo, o instala la regla udev.")
        return
    except OSError as e:
        print(f"    no se pudo abrir: {e}")
        return

    try:
        # El "índice de dispositivo" es a quién le hablamos por este cable:
        #   0xFF -> el propio ratón conectado directo (USB o vía driver del kernel)
        #   0x01..0x06 -> ratones emparejados detrás de un receptor Lightspeed
        for index in [0xFF] + list(range(1, 7)):
            try:
                ver = h.ping(index)
            except (TimeoutError, OSError):
                continue
            except HidppError as e:
                if e.legacy:
                    print(f"    índice 0x{index:02X}: habla HID++ 1.0 ({e})")
                continue
            if not ver:
                continue

            print(f"\n    *** DISPOSITIVO ENCONTRADO en índice 0x{index:02X} ***")
            print(f"    Protocolo HID++ {ver[0]}.{ver[1]}")

            table = h.feature_table(index)
            by_id = {fid: idx for idx, fid, _, _ in table}

            if 0x0005 in by_id:
                try:
                    print(f"    Nombre: {h.device_name(index, by_id[0x0005])}")
                except Exception as e:
                    print(f"    Nombre: (fallo: {e})")

            if 0x1004 in by_id:
                try:
                    b = h.unified_battery(index, by_id[0x1004])
                    print(f"    Batería: {b['porcentaje']}%  cargando={b['cargando']}")
                except Exception as e:
                    print(f"    Batería: (fallo: {e})")

            print(f"\n    {len(table)} features soportadas:")
            for idx, fid, ftype, fver in table:
                flags = []
                if ftype & 0x80: flags.append("obsoleta")
                if ftype & 0x40: flags.append("oculta")
                if ftype & 0x20: flags.append("interna")
                nombre = FEATURES.get(fid, "(desconocida)")
                extra = f"  [{', '.join(flags)}]" if flags else ""
                print(f"      idx {idx:2d}  0x{fid:04X}  v{fver}  {nombre}{extra}")
    finally:
        h.close()


def main():
    if len(sys.argv) > 1:
        for p in sys.argv[1:]:
            probe(p)
        return

    nodes = hidraw_nodes()
    print("Nodos hidraw del sistema:\n")
    print(f"  {'nodo':<16} {'VID:PID':<12} {'HID++':<6} nombre")
    print("  " + "-" * 70)
    for n in nodes:
        marca = "SI" if n["hidpp"] else "-"
        print(f"  {n['dev']:<16} {n['vid']:04x}:{n['pid']:04x}   {marca:<6} {n['name']}")

    candidatos = [n for n in nodes if n["hidpp"] and n["vid"] == LOGITECH]
    if not candidatos:
        print("\nNo hay ningún nodo Logitech con canal HID++.")
        print("Conecta el ratón (receptor Lightspeed o cable USB) y reintenta.")
        return

    for n in candidatos:
        probe(n["dev"])


if __name__ == "__main__":
    main()
