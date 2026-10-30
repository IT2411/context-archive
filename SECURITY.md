# Security Policy

## Core Security Guarantees

1. **Zero Code Execution:** `ctxa` statically parses source files and never imports or executes untrusted repository code.
2. **Zero Network Calls by Default:** All core CLI operations run 100% locally.
3. **Secret Exclusion:** `.env`, private keys (`*.pem`, `*.key`), and credential files are excluded by default.
4. **Prompt-Injection Defense:** Repository docstrings and identifiers are sanitized of `CTXA:` sentinel markers and marked as untrusted data.

## Reporting a Vulnerability

Please report security vulnerabilities privately via GitHub Security Advisories rather than public issues.
