#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
NetworkTool - Escáner de red, configuración IP y sesiones remotas (SSH, SFTP, Telnet, FTP).
Author: EstebanKZL
Compatible with Windows 7/10/11, Linux x86_64 and macOS (basic)

El código vive en el paquete networktool/; este archivo es el punto de entrada:
    python src/main.py [--debug] [--selftest informe.json]
"""

from networktool.app import main

if __name__ == "__main__":
    main()
