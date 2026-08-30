# README.md

``````text
# README.md

`````text
# README.md

````text
# README.md

```text
# doc2md v1.0.12

## Version 1.0.12 (2026-08-30) - INSTALLER HOTFIX

### Critical Fixes
- **Fix**: Installer file locking - auto-close running doc2md instances
- **Fix**: Silent application restart after installation
- **Fix**: Seamless upgrade without manual app closure

## Version 1.0.11 (2026-08-30) - HOTFIX

### Critical Fixes
- **Fix**: CustomTkinter theme initialization crash - removed hallucinated `set_color_scheme` method
- **Fix**: Use correct CustomTkinter API: `set_default_color_theme()` instead
- **Fix**: Graceful theme fallback prevents GUI startup crashes

## Version 1.0.10 (2026-08-30)

### Major Updates
- **Fix**: TkinterDnD2 drag & drop now safely handles Unicode paths and filenames with spaces/Thai characters
- **Feature**: Modern CustomTkinter-based GUI with dark/light theme support
- **Feature**: Real-time conversion progress with thread-safe logging
- **Hardening**: Deep audit applied - subprocess zombie process prevention on Windows
- **Hardening**: Singleton pattern for WhisperModel caching with memory release
- **Hardening**: Bulletproof exception guards for native C-extension crashes
```
````
`````
``````
