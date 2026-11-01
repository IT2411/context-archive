# Configuration Reference (`.ctxa.toml` / `[tool.ctxa]`)

`ctxa` loads configuration in the following precedence order:
1. CLI flags (`--output`, `--max-tokens`, `--tokenizer`)
2. `<repo_root>/.ctxa.toml`
3. `<repo_root>/pyproject.toml` (`[tool.ctxa]`)
4. Built-in defaults

## Example `.ctxa.toml`

```toml
[project]
name = "my-service"
description = "Core billing and checkout microservice"
primary_languages = ["python"]

[scanner]
max_file_size_bytes = 1048576
max_depth = 25
respect_gitignore = true

[journal]
auto_compact_record_threshold = 25
auto_compact_token_threshold = 4000

[context]
default_max_tokens = 8000
default_tokenizer = "heuristic"
output_path = "PROJECT_CONTEXT.md"
commit_context_dir = true
```
