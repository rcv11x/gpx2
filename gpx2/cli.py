# -*- coding: utf-8 -*-
"""Puntos de entrada de los ejecutables.

Existen porque un «console script» se llama sin argumentos, y tanto la interfaz
como el demonio quieren mirar la línea de órdenes. Aquí se hace esa traducción
y nada más.
"""

from __future__ import annotations

import sys


def gui() -> int:
    from .gui.main_window import main
    return main(demo="--demo" in sys.argv)


def daemon() -> int:
    from .daemon import main
    return main(sys.argv[1:])
