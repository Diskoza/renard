"""Renard agent package.

Renard runs under pythonw (no console). On Windows every console program it starts (powershell, git, npx/uvx for
MCP servers, ffmpeg, cmd…) then gets its OWN console window, which flashes on screen for a moment. Libraries start
such programs too, without asking. So: every child process gets CREATE_NO_WINDOW unless the caller explicitly asked
for a visible console (CREATE_NEW_CONSOLE); DETACHED_PROCESS is turned into a hidden console too (see below).
GUI programs (explorer, apps) are not affected.
"""
import os
import subprocess

if os.name == "nt" and not getattr(subprocess.Popen, "_renard_no_window", False):
    _orig_init = subprocess.Popen.__init__

    def _init(self, *args, **kwargs):
        flags = kwargs.get("creationflags", 0) or 0
        if len(args) < 13 and not flags & 0x00000010:
            kwargs["creationflags"] = (flags & ~0x00000008) | 0x08000000
        _orig_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _init
    subprocess.Popen._renard_no_window = True
