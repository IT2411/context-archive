# Changelog

All notable changes to this project will be documented in this file.

## [1.0.1] - 2026-11-01

### Added
- **Polyglot Language Support (`polyglot:1.0`):** Static analysis, symbol/contract extraction, dependency linking, and test mapping for **Kotlin** (`.kt`, `.kts`), **Java** (`.java`, including Spring Boot `@GetMapping`/`@PostMapping` endpoints and `@Test`), **C/C++** (`.c`, `.h`, `.cpp`, `.hpp`, `.cc`, `.cxx`, including `#include`, namespaces, classes/structs, and GoogleTest `TEST`/`TEST_F`), **Go** (`.go`), **Rust** (`.rs`), **C#** (`.cs`), **Ruby** (`.rb`), **PHP** (`.php`), and **Swift** (`.swift`).
- **Polyglot Build & Test Command Discovery:** Automatic detection of Gradle (`build.gradle`, `build.gradle.kts`), Maven (`pom.xml`), CMake (`CMakeLists.txt`), Cargo (`Cargo.toml`), and Go (`go.mod`) build/test commands in `PROJECT_CONTEXT.md`.
- **Automatic Primary Language Detection:** `PROJECT_CONTEXT.md` automatically lists all languages discovered in the repository.

### Fixed
- **Windows Compatibility:** Explicit SQLite connection closing (`contextlib.closing`) and LF line-ending preservation across Windows CI runners.

## [1.0.0] - 2026-10-30

### Added
- Initial production release of `context-archive` (`ctxa`).
