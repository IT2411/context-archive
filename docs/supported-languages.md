# Supported Languages & Framework Extractors

| Adapter / Extractor | ID | Supported Extensions | Extracted Entities & Relationships |
| :--- | :--- | :--- | :--- |
| **Python AST** | `python_ast:1.0` | `.py`, `.pyi` | `File`, `Module`, `Class`, `Function`, `Method`, `Variable`, `Test`; `CONTAINS`, `DEFINES`, `IMPORTS`, `INHERITS`, `CALLS`, `TESTED_BY` |
| **FastAPI & Pydantic** | `fastapi_pydantic:1.0` | `.py` | `Endpoint`, `Schema`; `EXPOSES`, `VALIDATES_WITH`, `DEPENDS_ON` |
| **SQLAlchemy / SQLModel** | `sqlalchemy_entity:1.0` | `.py` | `DataEntity` (`__tablename__`, columns); `READS`, `WRITES` |
| **TypeScript / JavaScript** | `typescript:1.0` | `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs` | `File`, `Module`, exported `Function`, `interface`/`type` `Schema`; `IMPORTS`, cross-stack `CONSUMES` (`fetch`/`axios` -> `Endpoint`) |
| **Polyglot Static Analyzer** | `polyglot:1.0` | `.kt`, `.kts` (Kotlin), `.java` (Java), `.c`, `.h`, `.cpp`, `.hpp`, `.cc`, `.cxx` (C/C++), `.go` (Go), `.rs` (Rust), `.cs` (C#), `.rb` (Ruby), `.php` (PHP), `.swift` (Swift) | Packages/Namespaces (`Module`), Classes/Structs/Objects/Enums (`Class`), Interfaces/Traits (`Schema`), Functions/Methods (`Function`), Spring Boot routes (`Endpoint`), JUnit/GTest/Cargo/Go tests (`Test`); `IMPORTS`, `INHERITS`, `CALLS`, `EXPOSES`, `TESTED_BY` |
