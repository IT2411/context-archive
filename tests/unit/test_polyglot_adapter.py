"""Unit and integration tests for Kotlin, Java, C++, Go, and Rust polyglot projects."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from context_archive.cli import app
from context_archive.exceptions import ExitCode

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


@pytest.mark.unit
def test_kotlin_java_cpp_go_rust_polyglot_extraction_and_handoff(
    tmp_path: Path,
) -> None:
    """Verify Kotlin, Java, C++, Go, and Rust files are extracted, linked, and rendered."""
    repo = tmp_path / "polyglot_repo"
    repo.mkdir()

    # 1. Gradle + CMake + Cargo + Go manifests
    (repo / "build.gradle.kts").write_text('plugins { kotlin("jvm") }\n', encoding="utf-8")
    (repo / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\n", encoding="utf-8")
    (repo / "Cargo.toml").write_text('[package]\nname = "core"\n', encoding="utf-8")
    (repo / "go.mod").write_text("module example.com/poly\n", encoding="utf-8")

    # 2. Kotlin source & test files
    kt_dir = repo / "src" / "main" / "kotlin" / "com" / "acme"
    kt_dir.mkdir(parents=True)
    (kt_dir / "PaymentGateway.kt").write_text(
        "package com.acme\n\n"
        "interface PaymentGateway {\n"
        "    suspend fun chargeCard(amountCents: Long): Boolean\n"
        "}\n\n"
        "class StripeGateway : PaymentGateway {\n"
        "    override suspend fun chargeCard(amountCents: Long): Boolean {\n"
        "        return amountCents > 0\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    # 3. Java Spring Boot controller importing PaymentGateway
    java_dir = repo / "src" / "main" / "java" / "com" / "acme"
    java_dir.mkdir(parents=True)
    (java_dir / "PaymentController.java").write_text(
        "package com.acme;\n\n"
        "import com.acme.StripeGateway;\n\n"
        "public class PaymentController {\n"
        '    @PostMapping("/payments")\n'
        "    public boolean createPayment(long amountCents) {\n"
        "        return chargeCard(amountCents);\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    java_test_dir = repo / "src" / "test" / "java" / "com" / "acme"
    java_test_dir.mkdir(parents=True)
    (java_test_dir / "PaymentControllerTest.java").write_text(
        "package com.acme;\n\n"
        "public class PaymentControllerTest {\n"
        "    @Test\n"
        "    public void testCreatePayment() {\n"
        "        createPayment(500);\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    # 4. C++ header, implementation, and GoogleTest
    cpp_dir = repo / "cpp"
    cpp_dir.mkdir()
    (cpp_dir / "engine.hpp").write_text(
        "#pragma once\n"
        "namespace core {\n"
        "class MatrixEngine {\n"
        "public:\n"
        "    int computeDeterminant(int size) {\n"
        "        return size * size;\n"
        "    }\n"
        "};\n"
        "}\n",
        encoding="utf-8",
    )
    (cpp_dir / "engine.cpp").write_text(
        '#include "engine.hpp"\n'
        "namespace core {\n"
        "int runEngine(int n) {\n"
        "    return computeDeterminant(n);\n"
        "}\n"
        "}\n",
        encoding="utf-8",
    )
    (cpp_dir / "engine_test.cpp").write_text(
        '#include "engine.hpp"\n'
        "TEST(EngineSuite, ComputesDeterminant) {\n"
        "    runEngine(4);\n"
        "}\n",
        encoding="utf-8",
    )

    # 5. Go & Rust files
    (repo / "worker.go").write_text(
        "package main\n\nfunc DispatchJob(jobId string) error {\n    return nil\n}\n",
        encoding="utf-8",
    )
    (repo / "lib.rs").write_text(
        "pub fn hash_payload(input: &str) -> u64 {\n    42\n}\n",
        encoding="utf-8",
    )

    res_init = runner.invoke(app, ["init", str(repo), "--deterministic"])
    assert res_init.exit_code == int(ExitCode.SUCCESS)

    md_text = (repo / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")
    # Primary languages auto-detected
    for lang in ("kotlin", "java", "cpp", "go", "rust"):
        assert f"`{lang}`" in md_text

    # Build commands extracted
    assert "./gradlew build" in md_text
    assert "cmake -B build" in md_text
    assert "cargo test" in md_text
    assert "go test ./..." in md_text

    # Extracted symbols across Kotlin, Java, C++, Go, Rust
    assert "com.acme.PaymentGateway.PaymentGateway" in md_text
    assert "com.acme.PaymentGateway.StripeGateway" in md_text
    assert "com.acme.PaymentController.createPayment" in md_text
    assert "[Endpoint] `POST /payments`" in md_text
    assert "core.engine.MatrixEngine" in md_text
    assert "core.engine.runEngine" in md_text
    assert "EngineSuite_ComputesDeterminant" in md_text
    assert "DispatchJob" in md_text
    assert "hash_payload" in md_text

    # Modify C++ file and run `ctxa update` and `ctxa diff`
    (cpp_dir / "engine.cpp").write_text(
        '#include "engine.hpp"\n'
        "namespace core {\n"
        "int runEngine(int n, int scale) {\n"
        "    return computeDeterminant(n) * scale;\n"
        "}\n"
        "}\n",
        encoding="utf-8",
    )
    diff_res = runner.invoke(app, ["diff", str(repo), "--format", "text"])
    assert diff_res.exit_code == int(ExitCode.SUCCESS)
    assert "core.engine.runEngine" in diff_res.stdout
    assert "EngineSuite_ComputesDeterminant" in diff_res.stdout

    upd_res = runner.invoke(app, ["update", str(repo), "--deterministic"])
    assert upd_res.exit_code == int(ExitCode.SUCCESS)
