#!/usr/bin/env python3
"""Wrapper que carrega myo_server via import (usa cache .pyc) e monta routers extras."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api import myo_server

# Monta governance router no app existente
try:
    from api.governance_router import router as _gov_router

    myo_server.app.include_router(_gov_router)
    print(" Governance router montado em /api/governance/*")
except Exception as _e:
    print(f" Governance router falhou: {_e}")

# Monta execution control router
try:
    from api.execution_router import router as _exec_router

    myo_server.app.include_router(_exec_router)
    print(" Execution Control router montado em /api/execution/*")
except Exception as _e:
    print(f" Execution Control router falhou: {_e}")

myo_server.main()
