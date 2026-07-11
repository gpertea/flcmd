# Plugin strategy

Goal: Total Commander plugin API compatibility, tiered by platform.

## TC plugin types
- WLX (Lister/viewer): render a file inside the viewer window
- WCX (Packer): read/write archive formats
- WDX (Content): extra file columns / search fields
- WFX (File system): virtual filesystems in a pane

## Tiers
1. **Python plugin API (all platforms, first-class).** `flcmd.plugins.api`
   defines Python ABCs mirroring TC semantics one-to-one (same lifecycle,
   same capability flags) so TC plugin docs translate directly. Discovered
   from a plugins dir + entry points; enabled per-type in settings.
2. **TC binary plugins on Windows.** `tc_shim` loads real .wlx/.wcx/.wdx
   (.wfx later) DLLs via ctypes, implementing the documented C ABI.
   WLX embedding requires giving the plugin a real HWND: the viewer hosts a
   native child window and passes its handle to ListLoad().
3. **Same C ABI on Linux/macOS** for plugins recompiled as .so/.dylib --
   the shim is platform-neutral except window embedding (X11 window id).

## Path shim
Internal paths are canonical '/'-separated. The tc_shim converts to native
backslash form (and ANSI/Unicode variants per plugin flavor) at the call
boundary, and back for paths returned by plugins. Nothing outside tc_shim
ever sees a backslash path.

## Non-goals / limits
- No Wine-based loading of Windows DLLs on Linux/macOS.
- WLX plugins that draw arbitrary Win32 UI work only on Windows; on other
  platforms only native rebuilds work.
