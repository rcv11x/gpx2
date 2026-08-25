#!/usr/bin/env python3
"""Renderiza pestañas de la ventana y las guarda como PNG (revisión de diseño)."""
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

modo = sys.argv[1] if len(sys.argv) > 1 else "real"
destino = sys.argv[2] if len(sys.argv) > 2 else f"captura_{modo}.png"
pestana = int(sys.argv[3]) if len(sys.argv) > 3 else 0

app = QApplication(sys.argv[:1])
app.setApplicationName("gpx2")

from gpx2.gui.widgets import hoja_de_estilo
from gpx2.gui import main_window
from gpx2 import desktop

if modo == "vacio":
    desktop.listar_punteros = lambda: []
    main_window.desktop.listar_punteros = lambda: []

if modo.startswith("demo") or modo in ("g203", "sl2"):
    # En demo emparejamos el ratón inventado con un puntero real de KWin,
    # sólo para que la tarjeta de aceleración muestre datos.
    _reales = desktop.listar_punteros()
    main_window.desktop.buscar_puntero = lambda v, p: (_reales[0] if _reales else None)

app.setStyleSheet(hoja_de_estilo(app.palette()))
v = main_window.VentanaPrincipal(demo=(modo if modo.startswith("demo") or modo in ("g203", "sl2") else False))
v.resize(1040, 700)
v.show()

def capturar():
    from PySide6.QtWidgets import QListWidget, QTabWidget
    # Cuando se pide un modelo concreto hay que seleccionarlo: el simulado se
    # añade junto a los ratones reales, y el que sale es el que esté elegido.
    if modo in ("g203", "sl2"):
        for lista in v.findChildren(QListWidget):
            if lista.objectName() != "ListaDispositivos":
                continue
            for fila in range(lista.count()):
                if modo in lista.item(fila).text().lower().replace(" ", ""):
                    lista.setCurrentRow(fila)
                    break
            break
    for tw in v.pila.currentWidget().findChildren(QTabWidget):
        tw.setCurrentIndex(pestana)
        break
    QTimer.singleShot(500, guardar)

def guardar():
    v.grab().save(destino)
    print("guardado:", destino)
    app.quit()

QTimer.singleShot(1400, capturar)
sys.exit(app.exec())
