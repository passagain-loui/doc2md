"""Windows Explorer context-menu registration under HKEY_CURRENT_USER."""

from __future__ import annotations

import sys

MENU_KEY_PATH = r"Software\Classes\*\shell\doc2md"
COMMAND_SUBKEY = "command"
DISPLAY_NAME = "Convert to Markdown"


class ContextMenuError(RuntimeError):
    pass


def _require_windows() -> None:
    if sys.platform != "win32":
        raise ContextMenuError("Context-menu integration requires Windows")


def _import_winreg():
    try:
        import winreg
    except ImportError as exc:
        raise ContextMenuError(f"winreg unavailable: {exc}") from exc
    return winreg


def get_command() -> str:
    """Quoted command line used for the registry *command* subkey."""
    if getattr(sys, "frozen", False):
        argv = [sys.executable, "convert"]
    else:
        argv = [sys.executable, "-m", "doc2md", "convert"]
    quoted = " ".join(f'"{part}"' for part in argv)
    return f'{quoted} "%1"'


def install() -> str:
    """Create the registry entries. Returns a human-readable confirmation."""
    _require_windows()
    winreg = _import_winreg()
    command_str = get_command()
    exe_path = sys.executable

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MENU_KEY_PATH) as menu_key:
        winreg.SetValueEx(menu_key, None, 0, winreg.REG_SZ, DISPLAY_NAME)
        try:
            winreg.SetValueEx(menu_key, "Icon", 0, winreg.REG_SZ, exe_path)
        except OSError:
            pass
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{MENU_KEY_PATH}\\{COMMAND_SUBKEY}") as cmd_key:
        winreg.SetValueEx(cmd_key, None, 0, winreg.REG_SZ, command_str)
    return f"Context menu installed: {DISPLAY_NAME}"


def uninstall() -> str:
    """Remove the registry entries gracefully."""
    _require_windows()
    winreg = _import_winreg()
    delete_access = getattr(winreg, "KEY_ALL_ACCESS", None)
    if delete_access is None:
        delete_access = winreg.KEY_READ

    menu_handle = None
    try:
        menu_handle = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, MENU_KEY_PATH, 0, delete_access
        )
    except (FileNotFoundError, OSError):
        return "Context menu not installed"

    try:
        try:
            winreg.OpenKey(menu_handle, COMMAND_SUBKEY, 0, delete_access)
        except (FileNotFoundError, OSError):
            pass
        else:
            winreg.DeleteKey(menu_handle, COMMAND_SUBKEY)
    finally:
        try:
            menu_handle.Close()
        except Exception:
            pass

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, MENU_KEY_PATH)
    except (FileNotFoundError, OSError):
        return "Context menu not installed"
    return "Context menu removed"


def is_installed() -> bool:
    if sys.platform != "win32":
        return False
    try:
        winreg = _import_winreg()
    except ContextMenuError:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, f"{MENU_KEY_PATH}\\{COMMAND_SUBKEY}", 0, winreg.KEY_READ
        ) as key:
            winreg.QueryValueEx(key, None)
        return True
    except (FileNotFoundError, OSError):
        return False


def status() -> str:
    if is_installed():
        return f"installed: '{DISPLAY_NAME}' on files under HKCU\\{MENU_KEY_PATH}"
    return "not installed"
