"""Native Windows common-item dialogs, with a Tk fallback on macOS/Linux.

Windows uses the OS COM API directly, so Python's optional Tcl/Tk installation
is not needed. Each call owns its COM apartment and releases every interface.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .models import EXTENSIONS


def pick_in_process(purpose: str, kind: str, initial: str, directory: Path):
    """Run Tk on its own process's main thread (required by macOS Cocoa)."""
    paths = []
    try:
        for suffix in (".request.json", ".response.json"):
            fd, name = tempfile.mkstemp(prefix="picker-", suffix=suffix, dir=directory)
            os.close(fd)
            paths.append(Path(name))
        request, response = paths
        request.write_text(
            json.dumps({"purpose": purpose, "kind": kind, "initial": initial}), encoding="utf-8"
        )
        command = (
            [sys.executable]
            if getattr(sys, "frozen", False)
            else [sys.executable, "-m", "simplemedia"]
        )
        result = subprocess.run(
            [*command, "--picker", str(request), str(response)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
            cwd=None
            if getattr(sys, "frozen", False)
            else str(Path(__file__).resolve().parent.parent),
        )
        if result.returncode:
            raise RuntimeError(
                "The system file picker could not start. Check your Tkinter installation."
            )
        answer = json.loads(response.read_text(encoding="utf-8"))
        if "error" in answer:
            raise RuntimeError(answer["error"])
        return answer["value"]
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


def pick(purpose: str, kind: str, initial: str, owner: int = 0):
    title = {
        "folder": "Choose a media folder",
        "output": "Choose output folder",
        "ffmpeg": "Select FFmpeg executable",
    }.get(purpose, "Select media")
    extensions = EXTENSIONS[kind] if kind in EXTENSIONS else set().union(*EXTENSIONS.values())
    filters = [
        ("Supported media", ";".join("*" + ext for ext in sorted(extensions))),
        ("All files", "*.*"),
    ]
    if purpose == "ffmpeg":
        filters = [("FFmpeg executable", "ffmpeg.exe" if os.name == "nt" else "ffmpeg")]
    folder = purpose in {"folder", "output"}
    multiple = purpose == "files"
    if os.name == "nt":
        with WindowsDialog(title, folder, multiple, initial, filters) as dialog:
            return dialog.show(owner)
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        if folder:
            return filedialog.askdirectory(parent=root, title=title, initialdir=initial)
        args = dict(
            parent=root,
            title=title,
            initialdir=initial,
            filetypes=[(label, pattern.replace(";", " ")) for label, pattern in filters],
        )
        return (
            filedialog.askopenfilenames(**args) if multiple else filedialog.askopenfilename(**args)
        )
    finally:
        root.destroy()


class WindowsDialog:
    def __init__(self, title, folder, multiple, initial, filters):
        import ctypes as ct
        from ctypes import wintypes as wt
        from uuid import UUID

        self.ct, self.wt = ct, wt
        self.ole = ct.OleDLL("ole32")
        self.shell = ct.WinDLL("shell32")
        self.dialog = ct.c_void_p()
        self.multiple = multiple
        self.initialized = False

        class GUID(ct.Structure):
            _fields_ = [
                ("data1", ct.c_uint32),
                ("data2", ct.c_uint16),
                ("data3", ct.c_uint16),
                ("data4", ct.c_ubyte * 8),
            ]

        def guid(value):
            return GUID.from_buffer_copy(UUID(value).bytes_le)

        self.guid = guid
        self.ole.CoInitializeEx.argtypes = [ct.c_void_p, ct.c_uint32]
        self.ole.CoInitializeEx.restype = ct.c_long
        self.ole.CoCreateInstance.argtypes = [
            ct.POINTER(GUID),
            ct.c_void_p,
            ct.c_uint32,
            ct.POINTER(GUID),
            ct.POINTER(ct.c_void_p),
        ]
        self.ole.CoCreateInstance.restype = ct.c_long
        self.ole.CoTaskMemFree.argtypes = [ct.c_void_p]
        self.ole.CoTaskMemFree.restype = None
        self.ole.CoUninitialize.argtypes = []
        self.ole.CoUninitialize.restype = None
        self.check(self.ole.CoInitializeEx(None, 2))
        self.initialized = True
        try:
            clsid = guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")
            iid = guid("D57C7288-D4AD-4768-BE02-9D969532D960")
            self.check(
                self.ole.CoCreateInstance(
                    ct.byref(clsid), None, 1, ct.byref(iid), ct.byref(self.dialog)
                )
            )
            self.call(self.dialog, 17, [wt.LPCWSTR], title)
            options = ct.c_uint32()
            self.call(self.dialog, 10, [ct.POINTER(ct.c_uint32)], ct.byref(options))
            flags = options.value | 0x40 | 0x800 | 0x02000000 | 0x8
            flags |= 0x20 if folder else 0x1000
            if multiple:
                flags |= 0x200
            self.call(self.dialog, 9, [ct.c_uint32], flags)
            if not folder:

                class Filter(ct.Structure):
                    _fields_ = [("name", wt.LPCWSTR), ("spec", wt.LPCWSTR)]

                self.filters = (Filter * len(filters))(*(Filter(*f) for f in filters))
                self.call(
                    self.dialog,
                    4,
                    [ct.c_uint32, ct.POINTER(Filter)],
                    len(filters),
                    self.filters,
                )
            if initial and Path(initial).is_dir():
                item = ct.c_void_p()
                shell_iid = guid("43826D1E-E718-42EE-BC55-A1E261C37BFE")
                self.shell.SHCreateItemFromParsingName.argtypes = [
                    wt.LPCWSTR,
                    ct.c_void_p,
                    ct.POINTER(GUID),
                    ct.POINTER(ct.c_void_p),
                ]
                self.shell.SHCreateItemFromParsingName.restype = ct.c_long
                hr = self.shell.SHCreateItemFromParsingName(
                    str(Path(initial).resolve()),
                    None,
                    ct.byref(shell_iid),
                    ct.byref(item),
                )
                if hr >= 0:
                    try:
                        self.call(self.dialog, 12, [ct.c_void_p], item)
                    finally:
                        self.release(item)
        except BaseException:
            self.close()
            raise

    @staticmethod
    def check(result):
        if result < 0:
            raise OSError(f"Windows file dialog failed (HRESULT 0x{result & 0xFFFFFFFF:08X}).")
        return result

    def call(self, pointer, index, types, *args, check=True):
        ct = self.ct
        table = ct.cast(pointer, ct.POINTER(ct.POINTER(ct.c_void_p))).contents
        function = ct.WINFUNCTYPE(ct.c_long, ct.c_void_p, *types)(table[index])
        result = function(pointer, *args)
        return self.check(result) if check else result

    def release(self, pointer):
        if pointer:
            self.call(pointer, 2, [], check=False)

    def path(self, item):
        ct = self.ct
        name = ct.c_void_p()
        self.call(item, 5, [ct.c_uint32, ct.POINTER(ct.c_void_p)], 0x80058000, ct.byref(name))
        try:
            return ct.wstring_at(name)
        finally:
            self.ole.CoTaskMemFree(name)

    def show(self, owner=0):
        ct = self.ct
        hr = self.call(self.dialog, 3, [ct.c_void_p], owner or None, check=False)
        if hr & 0xFFFFFFFF == 0x800704C7:
            return [] if self.multiple else ""
        self.check(hr)
        if not self.multiple:
            item = ct.c_void_p()
            self.call(self.dialog, 20, [ct.POINTER(ct.c_void_p)], ct.byref(item))
            try:
                return self.path(item)
            finally:
                self.release(item)
        items = ct.c_void_p()
        self.call(self.dialog, 27, [ct.POINTER(ct.c_void_p)], ct.byref(items))
        try:
            count = ct.c_uint32()
            self.call(items, 7, [ct.POINTER(ct.c_uint32)], ct.byref(count))
            paths = []
            for index in range(count.value):
                item = ct.c_void_p()
                self.call(
                    items,
                    8,
                    [ct.c_uint32, ct.POINTER(ct.c_void_p)],
                    index,
                    ct.byref(item),
                )
                try:
                    paths.append(self.path(item))
                finally:
                    self.release(item)
            return paths
        finally:
            self.release(items)

    def close(self):
        if self.dialog:
            self.release(self.dialog)
            self.dialog = self.ct.c_void_p()
        if self.initialized:
            self.ole.CoUninitialize()
            self.initialized = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
