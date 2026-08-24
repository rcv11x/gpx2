# -*- coding: utf-8 -*-
"""Ventana principal de gpx2."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem,
                               QMainWindow, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QSizePolicy,
                               QSplitter, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from .. import desktop
from ..client import ClienteDemonio
from ..device import Discovery, Mouse, discover
from ..engine import Motor
from ..profiles import Almacen, Perfil
from .widgets import (ColumnaCentrada, DelegadoDispositivo, FilaSlider,
                      ROL_ENCABEZADO, ROL_SUB, Tarjeta, hoja_de_estilo,
                      pastilla)

ROL_DATOS = Qt.ItemDataRole.UserRole


def _envolver(widget: QWidget) -> QScrollArea:
    """Mete un panel en un área con scroll, para ventanas pequeñas."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setWidget(widget)
    return area


def _columna(*widgets, espaciado: int = 14, margen: int = 18) -> QWidget:
    caja = QWidget()
    lay = QVBoxLayout(caja)
    lay.setContentsMargins(margen, margen, margen, margen)
    lay.setSpacing(espaciado)
    for w in widgets:
        lay.addWidget(w)
    lay.addStretch(1)
    return caja


# ---------------------------------------------------------------------------
# Página: nada que configurar
# ---------------------------------------------------------------------------

class PaginaVacia(QWidget):
    def __init__(self, al_reescanear, parent=None):
        super().__init__(parent)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 24, 24, 24)
        raiz.addStretch(1)

        columna = ColumnaCentrada(540)

        icono = QLabel("\U0001F5B1")
        f = QFont(icono.font())
        f.setPointSize(44)
        icono.setFont(f)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titulo = QLabel("No se ha detectado ningún ratón compatible")
        titulo.setObjectName("Titulo")
        titulo.setWordWrap(True)
        titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.detalle = QLabel()
        self.detalle.setObjectName("Suave")
        self.detalle.setWordWrap(True)
        self.detalle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detalle.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)

        boton = QPushButton("Buscar de nuevo")
        boton.clicked.connect(al_reescanear)
        fila = QHBoxLayout()
        fila.addStretch(1)
        fila.addWidget(boton)
        fila.addStretch(1)

        columna.contenido.addWidget(icono)
        columna.contenido.addWidget(titulo)
        columna.contenido.addSpacing(4)
        columna.contenido.addWidget(self.detalle)
        columna.contenido.addSpacing(10)
        columna.contenido.addLayout(fila)

        raiz.addWidget(columna)
        raiz.addStretch(1)

    def poner_detalle(self, texto: str) -> None:
        self.detalle.setText(texto)


# ---------------------------------------------------------------------------
# Página: ratón HID++
# ---------------------------------------------------------------------------

class PaginaRaton(QWidget):
    def __init__(self, raton: Mouse, parent=None):
        super().__init__(parent)
        self.raton = raton
        self.estado = raton.leer_todo()
        self.puntero_kde = desktop.buscar_puntero(raton.node.vid, raton.node.pid)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._cabecera())

        pestañas = QTabWidget()
        pestañas.addTab(_envolver(self._tab_sensibilidad()), "Sensibilidad")
        pestañas.addTab(_envolver(self._tab_rendimiento()), "Rendimiento")
        pestañas.addTab(_envolver(self._tab_botones()), "Botones")
        pestañas.addTab(_envolver(self._tab_perfiles()), "Perfiles")
        pestañas.addTab(_envolver(self._tab_diagnostico()), "Diagnóstico")
        lay.addWidget(pestañas, 1)

    # -- cabecera -------------------------------------------------------------

    def _cabecera(self) -> QWidget:
        caja = QWidget()
        lay = QHBoxLayout(caja)
        lay.setContentsMargins(18, 16, 18, 10)

        textos = QVBoxLayout()
        textos.setSpacing(2)
        titulo = QLabel(self.estado["nombre"])
        titulo.setObjectName("Titulo")
        sub = QLabel(f"{self.raton.id_str} · {self.raton.conexion} · "
                     f"HID++ {self.raton.protocolo[0]}.{self.raton.protocolo[1]} · "
                     f"{self.raton.node.path}")
        sub.setObjectName("Suave")
        textos.addWidget(titulo)
        textos.addWidget(sub)
        lay.addLayout(textos)
        lay.addStretch(1)

        bat = self.estado.get("battery")
        if bat and bat.percent is not None:
            icono = "⚡" if bat.charging else "🔋"
            lay.addWidget(pastilla(f"{icono} {bat.percent}% · {bat.texto}"))
        return caja

    # -- pestañas -------------------------------------------------------------

    def _tab_sensibilidad(self) -> QWidget:
        tarjetas = []

        dpi = self.estado.get("dpi")
        if dpi:
            cap = self.raton.dpi
            t = Tarjeta("DPI del sensor",
                        f"Resolución física del sensor. Feature 0x{cap.FID:04X} "
                        f"({cap.CONFIANZA}).")
            if dpi.valores:
                # lista discreta: un desplegable es más honesto que un slider
                combo = QComboBox()
                for v in dpi.valores:
                    combo.addItem(f"{v} DPI", v)
                if dpi.actual in dpi.valores:
                    combo.setCurrentIndex(dpi.valores.index(dpi.actual))
                combo.currentIndexChanged.connect(
                    lambda i, c=combo: self._set_dpi(c.itemData(i)))
                t.añadir(combo)
            else:
                fila = FilaSlider("Resolución", dpi.minimo, dpi.maximo,
                                  dpi.paso, sufijo=" DPI")
                fila.poner(dpi.actual)
                fila.cambiado.connect(lambda v: self._set_dpi(int(v)))
                t.añadir(fila)
            t.añadir(QLabel(f"Por defecto del ratón: {dpi.por_defecto} DPI"))
            tarjetas.append(t)
        else:
            tarjetas.append(Tarjeta(
                "DPI del sensor",
                "Este dispositivo no expone ninguna feature de DPI ajustable "
                "(0x2201 ni 0x2202)."))

        tarjetas.append(self._tarjeta_kde())
        return _columna(*tarjetas)

    def _tarjeta_kde(self) -> Tarjeta:
        t = Tarjeta("Aceleración del escritorio (KDE)",
                    "Esto no es el ratón, es lo que hace Plasma con lo que el "
                    "sensor mide. Para jugar interesa el perfil plano: sin "
                    "aceleración, la distancia depende sólo del movimiento físico.")
        if self.puntero_kde is None:
            t.añadir(QLabel("KWin no expone este dispositivo como puntero."))
            return t
        info = self.puntero_kde.info()
        fila = FilaSlider("Velocidad", -1.0, 1.0, 0.05, decimales=2)
        fila.poner(info.aceleracion)
        fila.cambiado.connect(self.puntero_kde.set_aceleracion)
        t.añadir(fila)

        chk = QCheckBox("Perfil plano (sin aceleración)")
        chk.setChecked(info.perfil_plano)
        chk.toggled.connect(self.puntero_kde.set_perfil_plano)
        t.añadir(chk)
        return t

    def _tab_rendimiento(self) -> QWidget:
        rate = self.estado.get("rate")
        if rate:
            cap = self.raton.rate
            t = Tarjeta("Tasa de reporte",
                        f"Veces por segundo que el ratón informa de su posición. "
                        f"Feature 0x{cap.FID:04X} ({cap.CONFIANZA}).")
            combo = QComboBox()
            for hz in rate.disponibles:
                combo.addItem(f"{hz} Hz", hz)
            if rate.actual_hz in rate.disponibles:
                combo.setCurrentIndex(rate.disponibles.index(rate.actual_hz))
            combo.currentIndexChanged.connect(
                lambda i, c=combo: self._set_rate(c.itemData(i)))
            t.añadir(combo)
        else:
            t = Tarjeta("Tasa de reporte",
                        "Este dispositivo no expone las features 0x8060 ni 0x8061.")

        modo = self.estado.get("mode")
        t2 = Tarjeta("Modo de funcionamiento",
                     "Si manda la memoria interna del ratón (onboard) o el PC (host). "
                     "Los perfiles por juego necesitan modo host.")
        t2.añadir(QLabel(modo if modo else "No disponible (feature 0x8090 ausente)."))
        return _columna(t, t2)

    def _tab_botones(self) -> QWidget:
        t = Tarjeta("Remapeo de botones — pendiente (fase 6)",
                    "Requiere la feature 0x1B04 (botones reprogramables). El plan "
                    "es listar los controles físicos, sus acciones posibles, y "
                    "permitir reasignarlos por perfil.")
        tabla = self.raton.hpp.features()
        disponible = 0x1B04 in tabla
        t.añadir(QLabel("✅ El ratón soporta 0x1B04, se puede implementar."
                        if disponible else
                        "❌ Este ratón no expone 0x1B04."))
        return _columna(t)

    def _tab_perfiles(self) -> QWidget:
        return PanelPerfiles(self.raton)

    def _tab_diagnostico(self) -> QWidget:
        t = Tarjeta("Capacidades que declara el ratón",
                    "Esta tabla no está escrita a mano: la responde el propio "
                    "dispositivo. Es la base de todo lo demás.")
        tabla = QTableWidget()
        filas = self.raton.feature_table
        tabla.setRowCount(len(filas))
        tabla.setColumnCount(4)
        tabla.setHorizontalHeaderLabels(["Índice", "ID", "Versión", "Qué es"])
        tabla.verticalHeader().setVisible(False)
        tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for fila, info in enumerate(filas):
            marcas = [m for m, on in (("obsoleta", info.obsolete),
                                      ("oculta", info.hidden),
                                      ("interna", info.internal)) if on]
            nombre = info.name + (f"  [{', '.join(marcas)}]" if marcas else "")
            for col, txt in enumerate([str(info.index), f"0x{info.fid:04X}",
                                       f"v{info.version}", nombre]):
                tabla.setItem(fila, col, QTableWidgetItem(txt))
        tabla.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch)
        tabla.setMinimumHeight(260)
        t.añadir(tabla)

        t2 = Tarjeta("Volcado en crudo",
                     "Para las features aún sin validar (0x2202, 0x8061), esto "
                     "muestra la respuesta byte a byte. Es la herramienta con la "
                     "que se corrige el decodificador sin adivinar nada.")
        salida = QPlainTextEdit()
        salida.setReadOnly(True)
        salida.setMinimumHeight(160)
        fuente = QFont("monospace")
        fuente.setStyleHint(QFont.StyleHint.Monospace)
        salida.setFont(fuente)
        boton = QPushButton("Volcar respuestas en crudo")
        boton.clicked.connect(lambda: salida.setPlainText(self._volcado()))
        t2.añadir(boton)
        t2.añadir(salida)

        if self.estado.get("errores") or self.estado.get("fallos"):
            t3 = Tarjeta("Incidencias durante la lectura")
            for e in self.estado.get("errores", []):
                t3.añadir(QLabel(f"• {e}"))
            for k, v in (self.estado.get("fallos") or {}).items():
                t3.añadir(QLabel(f"• {k}: {v}"))
            return _columna(t, t2, t3)
        return _columna(t, t2)

    # -- acciones -------------------------------------------------------------

    def _volcado(self) -> str:
        lineas = []
        pruebas = [
            ("0x2202 getSensorCount", 0x2202, 0x00, b""),
            ("0x2202 getSensorCapabilities", 0x2202, 0x01, b"\x00"),
            ("0x2202 getSensorDpiRanges", 0x2202, 0x02, b"\x00\x00\x00"),
            ("0x2202 getSensorDpi", 0x2202, 0x03, b"\x00"),
            ("0x2201 getSensorDpiList", 0x2201, 0x01, b"\x00"),
            ("0x2201 getSensorDpi", 0x2201, 0x02, b"\x00"),
            ("0x8061 getCapabilities (wireless)", 0x8061, 0x00, b"\x00"),
            ("0x8061 getCapabilities (cable)", 0x8061, 0x00, b"\x01"),
            ("0x8061 getActualReportRate", 0x8061, 0x01, b""),
            ("0x8060 getReportRateList", 0x8060, 0x00, b""),
            ("0x8060 getReportRate", 0x8060, 0x01, b""),
            ("0x8090 getModeStatus", 0x8090, 0x00, b""),
            ("0x8100 getOnboardProfilesInfo", 0x8100, 0x00, b""),
        ]
        tabla = self.raton.hpp.features()
        for etiqueta, fid, func, params in pruebas:
            if fid not in tabla:
                lineas.append(f"{etiqueta:38} — feature ausente")
                continue
            try:
                r = self.raton.hpp.call(tabla[fid].index, func, params)
                lineas.append(f"{etiqueta:38} {r.hex(' ')}")
            except Exception as e:
                lineas.append(f"{etiqueta:38} ⚠ {e}")
        return "\n".join(lineas)

    def _set_dpi(self, valor: int) -> None:
        try:
            self.raton.dpi.set(int(valor))
        except Exception as e:
            QMessageBox.warning(self, "No se pudo cambiar el DPI", str(e))

    def _set_rate(self, hz: int) -> None:
        try:
            self.raton.rate.set(int(hz))
        except Exception as e:
            QMessageBox.warning(self, "No se pudo cambiar la tasa de reporte", str(e))


# ---------------------------------------------------------------------------
# Página: puntero genérico (sin HID++)
# ---------------------------------------------------------------------------

class PaginaPuntero(QWidget):
    def __init__(self, puntero: desktop.KdePointer, parent=None):
        super().__init__(parent)
        self.p = puntero
        info = puntero.info()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        cab = QWidget()
        cl = QVBoxLayout(cab)
        cl.setContentsMargins(18, 16, 18, 10)
        cl.setSpacing(2)
        titulo = QLabel(info.nombre)
        titulo.setObjectName("Titulo")
        sub = QLabel(f"{info.id_str} · {info.sysname} · "
                     + ("endpoint de ratón de un teclado"
                        if info.es_de_teclado else "sin canal HID++"))
        sub.setObjectName("Suave")
        cl.addWidget(titulo)
        cl.addWidget(sub)
        lay.addWidget(cab)

        if info.es_de_teclado:
            aviso = Tarjeta(
                "Esto es un teclado, no un ratón",
                "Aparece aquí porque el teclado declara además un endpoint de "
                "ratón: es la función de mover el cursor con las teclas, típica "
                "del firmware QMK/VIA. El sistema lo trata como un ratón real, "
                "así que estos ajustes funcionan — pero sólo afectan al cursor "
                "movido desde el teclado, no a tu ratón.")
        else:
            aviso = Tarjeta(
                "Este ratón no es configurable por hardware",
                "No expone el canal HID++ de Logitech, así que no hay DPI ni tasa de "
                "reporte que tocar. Lo que sí se puede ajustar es cómo interpreta "
                "Plasma su movimiento, exactamente igual que en Ajustes del sistema.")

        sens = Tarjeta("Sensibilidad del puntero")
        fila = FilaSlider("Velocidad", -1.0, 1.0, 0.05, decimales=2)
        fila.poner(info.aceleracion)
        fila.cambiado.connect(self.p.set_aceleracion)
        fila.setEnabled(info.soporta_aceleracion)
        sens.añadir(fila)
        chk = QCheckBox("Perfil plano (sin aceleración)")
        chk.setChecked(info.perfil_plano)
        chk.toggled.connect(self.p.set_perfil_plano)
        sens.añadir(chk)

        comp = Tarjeta("Comportamiento")
        for texto, valor, setter in (
                ("Desplazamiento natural", info.scroll_natural, self.p.set_scroll_natural),
                ("Modo zurdo (invertir botones)", info.zurdo, self.p.set_zurdo),
                ("Emular botón central", info.emulacion_central, self.p.set_emulacion_central)):
            c = QCheckBox(texto)
            c.setChecked(valor)
            c.toggled.connect(setter)
            comp.añadir(c)

        lay.addWidget(_envolver(_columna(aviso, sens, comp)), 1)


# ---------------------------------------------------------------------------
# Ventana
# ---------------------------------------------------------------------------

class PanelPerfiles(QWidget):
    """Lista de perfiles, con o sin demonio.

    Si el demonio está en marcha, es él quien manda al ratón (y quien cambia de
    perfil solo al arrancar un juego). Si no lo está, la interfaz aplica los
    perfiles directamente. En ambos casos los perfiles son los mismos ficheros
    TOML del disco, así que no hay dos verdades.
    """

    def __init__(self, raton: Mouse, parent=None):
        super().__init__(parent)
        self.raton = raton
        self.motor = Motor(raton)
        self.cliente = ClienteDemonio()
        self.almacen = Almacen()

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(18, 18, 18, 18)
        raiz.setSpacing(14)

        self.aviso = Tarjeta("")
        self.aviso_texto = QLabel()
        self.aviso_texto.setWordWrap(True)
        self.aviso.añadir(self.aviso_texto)
        raiz.addWidget(self.aviso)

        tarjeta = Tarjeta("Perfiles",
                          "Cada perfil es un fichero TOML en "
                          f"{self.almacen.dir}, editable a mano.")
        self.lista = QListWidget()
        self.lista.setItemDelegate(DelegadoDispositivo(self.lista))
        self.lista.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lista.setMinimumHeight(220)
        self.lista.itemDoubleClicked.connect(lambda _: self._aplicar())
        tarjeta.añadir(self.lista)

        botones = QHBoxLayout()
        for texto, accion in (("Aplicar", self._aplicar),
                              ("Crear desde el estado actual", self._crear),
                              ("Juegos…", self._editar_juegos),
                              ("Por defecto", self._por_defecto),
                              ("Borrar", self._borrar)):
            b = QPushButton(texto)
            b.clicked.connect(accion)
            botones.addWidget(b)
        botones.addStretch(1)
        abrir = QPushButton("Abrir carpeta")
        abrir.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.almacen.dir))))
        botones.addWidget(abrir)
        tarjeta.añadir_layout(botones)
        raiz.addWidget(tarjeta)
        raiz.addStretch(1)

        self.refrescar()

    # -- estado ---------------------------------------------------------------

    def refrescar(self) -> None:
        errores = self.almacen.cargar()
        if self.cliente.activo:
            self.aviso.setToolTip("")
            self.aviso_texto.setText(
                "✅  El demonio está en marcha: los perfiles cambian solos cuando "
                "arranca un juego, y los cambios que hagas aquí los aplica él.")
            self.cliente.recargar()
            activo = self.cliente.estado().get("perfil_activo", "")
        else:
            self.aviso_texto.setText(
                "⚠  El demonio no está en marcha. Puedes aplicar perfiles a mano "
                "desde aquí, pero no cambiarán solos al arrancar un juego.\n\n"
                "Para activarlo:  systemctl --user enable --now gpx2d.service")
            activo = self.motor.perfil_activo or ""

        self.lista.clear()
        for p in self.almacen.lista():
            marcas = []
            if p.por_defecto:
                marcas.append("por defecto")
            if p.id == activo:
                marcas.append("activo ahora")
            ajustes = p.ajustes.campos()
            resumen = ", ".join(
                f"{'DPI' if k == 'dpi' else 'Hz'} {v}" for k, v in ajustes.items()) or "sin ajustes"
            juegos = ", ".join(p.activacion.ejecutables)
            detalle = resumen + (f"  ·  {juegos}" if juegos else "")
            if marcas:
                detalle += f"  ·  {' · '.join(marcas)}"
            item = QListWidgetItem(p.nombre)
            item.setData(ROL_SUB, detalle)
            item.setData(ROL_DATOS, p.id)
            self.lista.addItem(item)

        for e in errores:
            self.lista.addItem(QListWidgetItem(f"⚠ perfil ilegible — {e}"))
        if self.lista.count():
            self.lista.setCurrentRow(0)

    def _seleccionado(self) -> Perfil | None:
        item = self.lista.currentItem()
        if item is None:
            return None
        return self.almacen.obtener(item.data(ROL_DATOS) or "")

    # -- acciones -------------------------------------------------------------

    def _aplicar(self) -> None:
        perfil = self._seleccionado()
        if perfil is None:
            return
        if self.cliente.activo:
            resultado = self.cliente.aplicar(perfil.id)
            if not resultado.get("ok"):
                QMessageBox.warning(self, "No se pudo aplicar",
                                    resultado.get("error", "error desconocido"))
                return
            cambios = resultado.get("cambios", [])
        else:
            cambios = [str(c) for c in self.motor.aplicar(perfil)]
        self.refrescar()
        self.window().statusBar().showMessage(
            f"{perfil.nombre}: " + ("; ".join(cambios) if cambios else "ya estaba aplicado"),
            6000)

    def _crear(self) -> None:
        nombre, ok = QInputDialog.getText(
            self, "Nuevo perfil",
            "Nombre del perfil (se guarda con el DPI y los Hz que tiene el "
            "ratón ahora mismo):")
        if not ok or not nombre.strip():
            return
        perfil = Perfil(nombre=nombre.strip(), ajustes=self.motor.estado())
        self.almacen.guardar(perfil)
        self.refrescar()

    def _editar_juegos(self) -> None:
        perfil = self._seleccionado()
        if perfil is None:
            return
        texto, ok = QInputDialog.getText(
            self, f"Juegos de «{perfil.nombre}»",
            "Ejecutables separados por comas. Vale el nombre exacto o un trozo "
            "de la ruta:\nejemplo:  valorant.exe, cs2, Hades2",
            text=", ".join(perfil.activacion.ejecutables))
        if not ok:
            return
        perfil.activacion.ejecutables = [
            t.strip() for t in texto.split(",") if t.strip()]
        self.almacen.guardar(perfil)
        self.refrescar()

    def _por_defecto(self) -> None:
        perfil = self._seleccionado()
        if perfil is None:
            return
        self.almacen.marcar_por_defecto(perfil.id)
        self.refrescar()

    def _borrar(self) -> None:
        perfil = self._seleccionado()
        if perfil is None:
            return
        if QMessageBox.question(
                self, "Borrar perfil",
                f"¿Borrar «{perfil.nombre}»? Se elimina el fichero del disco.") \
                != QMessageBox.StandardButton.Yes:
            return
        self.almacen.borrar(perfil.id)
        self.refrescar()


class VentanaPrincipal(QMainWindow):
    def __init__(self, demo: bool = False):
        super().__init__()
        self.demo = demo
        self.setWindowTitle("gpx2 — control de ratones Logitech"
                            + ("  ·  MODO DEMO" if demo else ""))
        self.resize(1040, 700)
        self.hallazgo: Discovery | None = None

        divisor = QSplitter(Qt.Orientation.Horizontal)

        lateral = QWidget()
        lateral.setObjectName("Lateral")
        lat = QVBoxLayout(lateral)
        lat.setContentsMargins(0, 14, 0, 10)
        lat.setSpacing(8)

        cab = QLabel("  Dispositivos")
        cab.setObjectName("TituloTarjeta")
        lat.addWidget(cab)

        self.lista = QListWidget()
        self.lista.setItemDelegate(DelegadoDispositivo(self.lista))
        self.lista.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lista.setUniformItemSizes(False)
        self.lista.currentItemChanged.connect(self._seleccion)
        lat.addWidget(self.lista, 1)

        self.btn_rescan = QPushButton("Volver a escanear")
        self.btn_rescan.clicked.connect(self.escanear)
        lat.addWidget(self.btn_rescan)

        self.pila = QStackedWidget()
        self.vacia = PaginaVacia(self.escanear)
        self.pila.addWidget(self.vacia)

        divisor.addWidget(lateral)
        divisor.addWidget(self.pila)
        divisor.setStretchFactor(1, 1)
        divisor.setSizes([270, 770])
        self.setCentralWidget(divisor)

        self.statusBar().showMessage("Listo")
        QTimer.singleShot(0, self.escanear)

    # -- escaneo --------------------------------------------------------------

    def escanear(self) -> None:
        self.statusBar().showMessage("Buscando dispositivos…")
        QApplication.processEvents()

        if self.hallazgo:
            for r in self.hallazgo.ratones:
                r.close()

        self.hallazgo = discover()
        punteros = desktop.listar_punteros()

        if self.demo:
            # Ratón inventado, para trabajar en la interfaz sin hardware.
            from ..mock import raton_simulado
            self.hallazgo.ratones.append(raton_simulado())

        # Los ratones HID++ ya tienen su propia entrada; no los repetimos abajo.
        ids_hidpp = {(m.node.vid, m.node.pid) for m in self.hallazgo.ratones}
        candidatos = [(p, p.info()) for p in punteros]
        otros = [p for p, i in candidatos
                 if (i.vid, i.pid) not in ids_hidpp
                 and i.soporta_aceleracion and not i.es_de_teclado]
        teclados = [p for p, i in candidatos
                    if i.soporta_aceleracion and i.es_de_teclado]

        self.lista.clear()
        while self.pila.count() > 1:
            w = self.pila.widget(1)
            self.pila.removeWidget(w)
            w.deleteLater()

        if self.hallazgo.ratones:
            self._encabezado("Compatibles")
            for raton in self.hallazgo.ratones:
                pagina = PaginaRaton(raton)
                self.pila.addWidget(pagina)
                self._entrada(raton.nombre, raton.id_str, pagina)

        if otros:
            self._encabezado("Otros punteros")
            for p in otros:
                info = p.info()
                pagina = PaginaPuntero(p)
                self.pila.addWidget(pagina)
                self._entrada(info.nombre, info.id_str, pagina)

        if teclados:
            self._encabezado("Teclados que emulan ratón")
            for p in teclados:
                info = p.info()
                pagina = PaginaPuntero(p)
                self.pila.addWidget(pagina)
                self._entrada(info.nombre, info.id_str, pagina)

        self._actualizar_vacio()
        if self.lista.count():
            for i in range(self.lista.count()):
                if self.lista.item(i).data(ROL_DATOS) is not None:
                    self.lista.setCurrentRow(i)
                    break
        self.statusBar().showMessage(
            f"{len(self.hallazgo.ratones)} ratón(es) HID++ · "
            f"{len(otros)} puntero(s) genérico(s) · "
            f"{len(teclados)} teclado(s) con emulación · "
            f"{len(self.hallazgo.sin_permiso)} sin permiso")

    def _encabezado(self, texto: str) -> None:
        item = QListWidgetItem(texto)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setData(ROL_ENCABEZADO, True)
        self.lista.addItem(item)

    def _entrada(self, titulo: str, sub: str, pagina: QWidget) -> None:
        item = QListWidgetItem(titulo)
        item.setData(ROL_SUB, sub)
        item.setData(ROL_DATOS, pagina)
        item.setToolTip(f"{titulo} — {sub}")
        self.lista.addItem(item)

    def _seleccion(self, actual: QListWidgetItem | None, _previo=None) -> None:
        if actual is None:
            return
        pagina = actual.data(ROL_DATOS)
        if pagina is not None:
            self.pila.setCurrentWidget(pagina)

    def _actualizar_vacio(self) -> None:
        h = self.hallazgo
        if h and h.sin_permiso:
            rutas = ", ".join(n.path for n in h.sin_permiso)
            self.vacia.poner_detalle(
                f"Se han encontrado dispositivos Logitech con canal HID++ ({rutas}) "
                "pero no hay permiso para abrirlos.\n\n"
                "Instala la regla udev incluida en el proyecto:\n"
                "sudo cp 99-logitech-hidpp.rules /etc/udev/rules.d/ && "
                "sudo udevadm control --reload-rules && sudo udevadm trigger")
        elif h and not h.ratones:
            self.vacia.poner_detalle(
                "No hay ningún dispositivo Logitech que exponga el canal HID++.\n\n"
                "Conecta el ratón por cable USB o enchufa su receptor Lightspeed "
                "y vuelve a escanear. Los ratones genéricos aparecen igualmente "
                "en la lista, pero sólo permiten ajustar la sensibilidad de Plasma.")
        if not self.lista.count():
            self.pila.setCurrentWidget(self.vacia)

    def closeEvent(self, evento):
        if self.hallazgo:
            for r in self.hallazgo.ratones:
                r.close()
        super().closeEvent(evento)


APP_ID = "io.github.rcv11x.gpx2"


def _icono() -> QIcon:
    """El icono del proyecto. Primero el instalado en el sistema; si no, el
    del repositorio (para ejecutar sin instalar)."""
    from pathlib import Path
    icono = QIcon.fromTheme(APP_ID)
    if not icono.isNull():
        return icono
    local = Path(__file__).resolve().parents[2] / "data" / "gpx2.svg"
    return QIcon(str(local)) if local.exists() else QIcon()


def main(demo: bool = False) -> int:
    import sys
    app = QApplication(sys.argv)
    app.setApplicationName("gpx2")
    app.setApplicationDisplayName("gpx2")
    # En Wayland el icono de la barra de tareas NO sale de la ventana: el
    # compositor lo busca en el .desktop cuyo nombre coincida con este app_id.
    # Sin esto sale el logo genérico de Wayland.
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(_icono())
    app.setStyleSheet(hoja_de_estilo(app.palette()))
    ventana = VentanaPrincipal(demo=demo)
    ventana.show()
    return app.exec()
