# -*- coding: utf-8 -*-
"""Piezas reutilizables de la interfaz."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                               QSizePolicy, QSlider, QStyle,
                               QStyledItemDelegate, QStyleOptionViewItem,
                               QVBoxLayout, QWidget)


def mezclar(a: QColor, b: QColor, factor: float) -> QColor:
    """Interpola dos colores. Sirve para derivar tonos del tema del sistema
    en vez de fijar colores a mano (así funciona en claro y en oscuro)."""
    f = max(0.0, min(1.0, factor))
    return QColor(round(a.red() * (1 - f) + b.red() * f),
                  round(a.green() * (1 - f) + b.green() * f),
                  round(a.blue() * (1 - f) + b.blue() * f))


def hoja_de_estilo(pal: QPalette) -> str:
    """QSS derivada de la paleta activa de Qt, para integrarse con Breeze."""
    ventana = pal.color(QPalette.ColorRole.Window)
    base = pal.color(QPalette.ColorRole.Base)
    texto = pal.color(QPalette.ColorRole.WindowText)
    realce = pal.color(QPalette.ColorRole.Highlight)
    borde_col = mezclar(ventana, texto, 0.18)
    borde = borde_col.name()
    tarjeta = mezclar(base, ventana, 0.35).name()
    lateral = mezclar(ventana, base, 0.45).name()
    suave = mezclar(ventana, texto, 0.45).name()

    return f"""
    QWidget#Lateral {{ background: {lateral}; }}
    QFrame#Tarjeta {{
        background: {tarjeta};
        border: 1px solid {borde};
        border-radius: 10px;
    }}
    QLabel#TituloTarjeta {{ font-weight: 600; }}
    QLabel#Suave {{ color: {suave}; }}
    QLabel#Titulo {{ font-size: 20pt; font-weight: 600; }}
    QLabel#Pastilla {{
        background: {mezclar(ventana, realce, 0.25).name()};
        border: 1px solid {mezclar(borde_col, realce, 0.35).name()};
        border-radius: 9px;
        padding: 2px 10px;
    }}
    QListWidget {{ background: transparent; border: none; }}
    QListWidget::item {{ padding: 9px 12px; border-radius: 8px; margin: 2px 6px; }}
    QListWidget::item:selected {{ background: {realce.name()}; color: {pal.color(QPalette.ColorRole.HighlightedText).name()}; }}
    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{ padding: 7px 16px; margin-right: 4px; border-radius: 7px; }}
    QTabBar::tab:selected {{ background: {mezclar(ventana, realce, 0.30).name()}; }}
    """


class Tarjeta(QFrame):
    """Un bloque con título y contenido. La unidad visual de toda la app."""

    def __init__(self, titulo: str, subtitulo: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Tarjeta")
        self.setFrameShape(QFrame.Shape.NoFrame)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(18, 16, 18, 16)
        raiz.setSpacing(4)

        if titulo:
            lbl = QLabel(titulo)
            lbl.setObjectName("TituloTarjeta")
            raiz.addWidget(lbl)

        if subtitulo:
            sub = QLabel(subtitulo)
            sub.setObjectName("Suave")
            sub.setWordWrap(True)
            raiz.addWidget(sub)

        raiz.addSpacing(8)
        self.cuerpo = QVBoxLayout()
        self.cuerpo.setSpacing(10)
        raiz.addLayout(self.cuerpo)

    def añadir(self, w: QWidget) -> None:
        # Cualquier etiqueta que entre en una tarjeta se ajusta sola. Si no, un
        # texto largo ensancha la tarjeta y aparece scroll horizontal en toda
        # la ventana.
        if isinstance(w, QLabel):
            w.setWordWrap(True)
        self.cuerpo.addWidget(w)

    def añadir_layout(self, layout) -> None:
        self.cuerpo.addLayout(layout)


class FilaSlider(QWidget):
    """Etiqueta + slider + valor. Emite el valor ya convertido."""

    cambiado = Signal(float)

    def __init__(self, etiqueta: str, minimo: float, maximo: float,
                 paso: float, sufijo: str = "", decimales: int = 0, parent=None):
        super().__init__(parent)
        self._min, self._paso, self._dec = minimo, paso, decimales
        self._sufijo = sufijo

        fila = QHBoxLayout(self)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(12)

        self.lbl = QLabel(etiqueta)
        self.lbl.setMinimumWidth(150)
        fila.addWidget(self.lbl)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, max(1, round((maximo - minimo) / paso)))
        self.slider.setSizePolicy(QSizePolicy.Policy.Expanding,
                                  QSizePolicy.Policy.Fixed)
        fila.addWidget(self.slider, 1)

        self.valor = QLabel("—")
        self.valor.setMinimumWidth(84)
        self.valor.setAlignment(Qt.AlignmentFlag.AlignRight |
                                Qt.AlignmentFlag.AlignVCenter)
        fuente = QFont(self.valor.font())
        fuente.setStyleHint(QFont.StyleHint.Monospace)
        self.valor.setFont(fuente)
        fila.addWidget(self.valor)

        self.slider.valueChanged.connect(self._al_mover)

    def _real(self, pasos: int) -> float:
        return self._min + pasos * self._paso

    def _al_mover(self, pasos: int) -> None:
        v = self._real(pasos)
        self.valor.setText(f"{v:.{self._dec}f}{self._sufijo}")
        self.cambiado.emit(v)

    def poner(self, valor: float) -> None:
        """Fija el valor sin emitir la señal (para cargar el estado inicial)."""
        self.slider.blockSignals(True)
        self.slider.setValue(round((valor - self._min) / self._paso))
        self.slider.blockSignals(False)
        self.valor.setText(f"{valor:.{self._dec}f}{self._sufijo}")


def pastilla(texto: str) -> QLabel:
    lbl = QLabel(texto)
    lbl.setObjectName("Pastilla")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lbl


# ---------------------------------------------------------------------------
# Lista lateral de dispositivos
# ---------------------------------------------------------------------------

ROL_SUB = Qt.ItemDataRole.UserRole + 1
ROL_ENCABEZADO = Qt.ItemDataRole.UserRole + 2


class DelegadoDispositivo(QStyledItemDelegate):
    """Pinta cada entrada como nombre + identificador atenuado, y las
    cabeceras de sección como una etiqueta pequeña."""

    ALTO_ITEM = 50
    ALTO_ENCABEZADO = 30

    def paint(self, painter, option, index):
        opciones = QStyleOptionViewItem(option)
        self.initStyleOption(opciones, index)
        opciones.text = ""
        widget = opciones.widget
        estilo = widget.style() if widget else QApplication.style()
        estilo.drawControl(QStyle.ControlElement.CE_ItemViewItem, opciones,
                           painter, widget)

        texto = index.data(Qt.ItemDataRole.DisplayRole) or ""
        sub = index.data(ROL_SUB)
        es_cabecera = bool(index.data(ROL_ENCABEZADO))
        seleccionado = bool(opciones.state & QStyle.StateFlag.State_Selected)

        base = (opciones.palette.highlightedText().color() if seleccionado
                else opciones.palette.text().color())
        painter.save()

        if es_cabecera:
            f = QFont(opciones.font)
            f.setPointSizeF(max(7.0, f.pointSizeF() - 1.0))
            f.setBold(True)
            atenuado = QColor(base)
            atenuado.setAlphaF(0.55)
            painter.setFont(f)
            painter.setPen(atenuado)
            zona = opciones.rect.adjusted(14, 0, -12, -4)
            fm = painter.fontMetrics()
            painter.drawText(zona,
                             Qt.AlignmentFlag.AlignLeft |
                             Qt.AlignmentFlag.AlignBottom,
                             fm.elidedText(texto.upper(),
                                           Qt.TextElideMode.ElideRight,
                                           zona.width()))
            painter.restore()
            return

        rect = opciones.rect.adjusted(14, 7, -12, -7)
        metrica_ancho = rect.width()

        f = QFont(opciones.font)
        painter.setFont(f)
        painter.setPen(base)
        fm = painter.fontMetrics()
        painter.drawText(QRect(rect.x(), rect.y(), metrica_ancho, fm.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         fm.elidedText(texto, Qt.TextElideMode.ElideRight, metrica_ancho))

        if sub:
            f2 = QFont(f)
            f2.setPointSizeF(max(7.0, f.pointSizeF() - 1.5))
            atenuado = QColor(base)
            atenuado.setAlphaF(0.6)
            painter.setFont(f2)
            painter.setPen(atenuado)
            fm2 = painter.fontMetrics()
            painter.drawText(
                QRect(rect.x(), rect.y() + fm.height() + 1, metrica_ancho, fm2.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                fm2.elidedText(sub, Qt.TextElideMode.ElideRight, metrica_ancho))
        painter.restore()

    def sizeHint(self, option, index):
        alto = (self.ALTO_ENCABEZADO if index.data(ROL_ENCABEZADO)
                else self.ALTO_ITEM)
        return QSize(0, alto)


class ColumnaCentrada(QWidget):
    """Contenedor de ancho fijo y centrado. Evita que los QLabel con ajuste de
    línea calculen mal su altura dentro de un layout centrado."""

    def __init__(self, ancho: int = 540, parent=None):
        super().__init__(parent)
        externo = QHBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        externo.addStretch(1)
        interno = QWidget()
        interno.setFixedWidth(ancho)
        externo.addWidget(interno)
        externo.addStretch(1)
        self.contenido = QVBoxLayout(interno)
        self.contenido.setContentsMargins(0, 0, 0, 0)
        self.contenido.setSpacing(8)
