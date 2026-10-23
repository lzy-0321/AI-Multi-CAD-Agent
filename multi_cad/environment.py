"""Read local CAD configuration without launching or modifying CAD applications."""
import json
import os
from pathlib import Path


def solidworks_status(config_path="cad.local.json"):
    config_file = Path(config_path)
    config = json.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
    configured = os.environ.get("SOLIDWORKS_EXECUTABLE") or config.get("solidworks_executable")
    executable = Path(configured) if configured else None
    clsid = None
    registered_executable = None
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"SldWorks.Application\CLSID") as key:
                clsid = winreg.QueryValueEx(key, "")[0]
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\LocalServer32") as key:
                registered_executable = winreg.QueryValueEx(key, "")[0]
        except OSError:
            pass
    if executable is None:
        default = Path("C:/Program Files/SOLIDWORKS Corp/SOLIDWORKS/SLDWORKS.exe")
        if default.is_file():
            executable = default
    exists = executable is not None and executable.is_file()
    return {"executable": str(executable) if executable else None,
            "executable_exists": exists, "com_clsid": clsid,
            "registered_server": registered_executable,
            "interop_exists": bool(exists and (executable.parent / "SolidWorks.Interop.sldworks.dll").is_file()),
            "connection": "not_tested", "adapter": "not_implemented"}
