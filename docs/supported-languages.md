# Supported Languages & Framework Extractors

| Adapter / Extractor | ID | Extracted Entities & Relationships |
| :--- | :--- | :--- |
| **Python AST** | `python_ast:1.0` | `File`, `Module`, `Class`, `Function`, `Method`, `Variable`, `Test`; `CONTAINS`, `DEFINES`, `IMPORTS`, `INHERITS`, `CALLS`, `TESTED_BY` |
| **FastAPI & Pydantic** | `fastapi_pydantic:1.0` | `Endpoint`, `Schema`; `EXPOSES`, `VALIDATES_WITH`, `DEPENDS_ON` |
| **SQLAlchemy / SQLModel** | `sqlalchemy_entity:1.0` | `DataEntity` (`__tablename__`, columns); `READS`, `WRITES` |
| **TypeScript / JavaScript** | `typescript:1.0` | `File`, `Module`, exported `Function`, `interface`/`type` `Schema`; `IMPORTS`, cross-stack `CONSUMES` (`fetch`/`axios` -> `Endpoint`) |
