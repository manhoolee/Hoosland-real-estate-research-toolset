from __future__ import annotations

import importlib.util
import shutil
from typing import Any


PDF_RENDER_COMMAND = "hoosland-pdf-render"
PDF_INSPECT_COMMAND = "hoosland-pdf-inspect"
PDF_SYSTEM_COMMANDS = ("pdftoppm",)
PDF_REQUIRED_PYTHON_MODULES = ("pypdf",)
PDF_OPTIONAL_PYTHON_MODULES = ("reportlab", "pdfplumber")


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def pdf_runtime_status() -> dict[str, Any]:
    """Return a public, secret-free readiness projection for direct PDF output."""

    commands = {
        PDF_RENDER_COMMAND: shutil.which(PDF_RENDER_COMMAND) is not None,
        PDF_INSPECT_COMMAND: shutil.which(PDF_INSPECT_COMMAND) is not None,
    }
    system_commands = {name: shutil.which(name) is not None for name in PDF_SYSTEM_COMMANDS}
    python_modules = {
        name: _module_available(name)
        for name in (*PDF_REQUIRED_PYTHON_MODULES, *PDF_OPTIONAL_PYTHON_MODULES)
    }
    missing = [name for name, available in commands.items() if not available]
    missing.extend(name for name, available in system_commands.items() if not available)
    missing.extend(
        name for name in PDF_REQUIRED_PYTHON_MODULES if not python_modules[name]
    )
    configured = not missing
    return {
        "name": "pdf_output",
        "label": "PDF 直接输出",
        "configured": configured,
        "status": "configured" if configured else "dependency_missing",
        "renderer": PDF_RENDER_COMMAND if commands[PDF_RENDER_COMMAND] else None,
        "inspector": PDF_INSPECT_COMMAND if commands[PDF_INSPECT_COMMAND] else None,
        "system_commands": system_commands,
        "python_modules": python_modules,
        "reason": None if configured else "缺少持久化 PDF 组件：" + "、".join(missing),
    }
