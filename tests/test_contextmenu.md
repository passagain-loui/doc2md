# test_contextmenu.py

```python
import sys

import pytest

from doc2md.core import contextmenu as cm


class FakeNode:
    def __init__(self):
        self.values = {}


class KeyHandle:
    def __init__(self, store, path):
        self.store = store
        self.path = path

    def __enter__(self):
        return (self, self.path)

    def __exit__(self, *exc):
        return False


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = "read"
    KEY_SET_VALUE = "write"
    REG_SZ = "REG_SZ"

    def __init__(self):
        self.store = {}

    def _path(self, parent, subpath):
        if isinstance(parent, tuple):
            parent = parent[0]
        parent_path = parent.path if isinstance(parent, KeyHandle) else str(parent)
        return f"{parent_path}\\{subpath}"

    def CreateKey(self, parent, subpath):
        path = self._path(parent, subpath)
        self.store.setdefault(path, FakeNode())
        return KeyHandle(self.store, path)

    def OpenKey(self, parent, subpath, reserved=0, access=None):
        path = self._path(parent, subpath)
        if path not in self.store:
            raise FileNotFoundError(path)
        return KeyHandle(self.store, path)

    def SetValueEx(self, handle_pair, name, reserved, typ, data):
        _, path = handle_pair
        self.store[path].values[name if name is not None else ""] = data

    def QueryValueEx(self, handle_pair, name):
        _, path = handle_pair
        values = self.store[path].values
        lookup = name if name is not None else ""
        if lookup not in values:
            raise FileNotFoundError(lookup)
        return values[lookup], self.REG_SZ

    def DeleteKey(self, parent_arg, name):
        parent_path = parent_arg.path if isinstance(parent_arg, KeyHandle) else str(parent_arg)
        child = f"{parent_path}\\{name}"
        if child not in self.store:
            raise FileNotFoundError(child)
        del self.store[child]




@pytest.fixture
def fake_registry(monkeypatch):
    fake = FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", fake)
    return fake


def test_install_creates_keys_and_command(fake_registry):
    message = cm.install()
    assert "installed" in message.lower()
    menu = fake_registry.store[f"HKCU\\{cm.MENU_KEY_PATH}"]
    assert menu.values[""] == cm.DISPLAY_NAME
    command = fake_registry.store[f"HKCU\\{cm.MENU_KEY_PATH}\\command"]
    assert '"%1"' in command.values[""]
    assert cm.is_installed()


def test_is_installed_false_when_absent(fake_registry):
    assert cm.is_installed() is False
    assert cm.status() == "not installed"


def test_uninstall_removes_entry(fake_registry):
    cm.install()
    assert "removed" in cm.uninstall().lower()
    assert cm.is_installed() is False


def test_uninstall_when_never_installed_is_graceful(fake_registry):
    assert "not installed" in cm.uninstall().lower()


def test_uninstall_tolerates_missing_command_subkey(fake_registry):
    cm.install()
    del fake_registry.store[f"HKCU\\{cm.MENU_KEY_PATH}\\command"]
    assert "removed" in cm.uninstall().lower()


def test_status_reports_installed(fake_registry):
    cm.install()
    assert "installed" in cm.status()
    assert cm.DISPLAY_NAME in cm.status()


def test_non_windows_platform_raises(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(cm.ContextMenuError):
        cm.install()
    with pytest.raises(cm.ContextMenuError):
        cm.uninstall()
    assert cm.is_installed() is False


def test_get_command_quotes_placeholder():
    command = cm.get_command()
    assert '"%1"' in command
    assert command.startswith('"')
```
