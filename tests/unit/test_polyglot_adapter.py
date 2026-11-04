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


@pytest.mark.unit
def test_poker_night_kotlin_evaluation_scenarios(tmp_path: Path) -> None:
    """Verify task-specific ranking, relationship rendering, and test linking on Kotlin app."""
    repo = tmp_path / "poker_night"
    src_dir = repo / "app" / "src" / "main" / "kotlin" / "com" / "poker"
    test_dir = repo / "app" / "src" / "test" / "kotlin" / "com" / "poker"
    src_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)

    (src_dir / "BettingEngine.kt").write_text(
        "package com.poker\n\n"
        "class PotCalculator {\n"
        "    fun calculateSidePots(total: Int): Int {\n"
        "        return total\n"
        "    }\n"
        "}\n\n"
        "class BettingEngine(private val potCalculator: PotCalculator) {\n"
        "    fun validateAction(playerBet: Int, minRaise: Int): Boolean {\n"
        "        calculateSidePots(playerBet)\n"
        "        return playerBet >= minRaise\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (src_dir / "PokerHostServer.kt").write_text(
        "package com.poker\n\n"
        "class ClientSessionRegistry {\n"
        "    fun registerClient(clientId: String): Boolean {\n"
        "        return true\n"
        "    }\n"
        "}\n\n"
        "class PokerMultiplayerClient {\n"
        "    suspend fun connectToHost(hostUrl: String): Boolean {\n"
        "        return true\n"
        "    }\n"
        "}\n\n"
        "class PokerHostServer(private val registry: ClientSessionRegistry) {\n"
        "    suspend fun handleClientConnection(clientId: String): Boolean {\n"
        "        return registerClient(clientId)\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (src_dir / "SessionPersistenceService.kt").write_text(
        "package com.poker\n\n"
        "class StateReplayer {\n"
        "    fun replaySessionState(snapshotJson: String): Boolean {\n"
        "        return true\n"
        "    }\n"
        "}\n\n"
        "class SessionPersistenceService(private val replayer: StateReplayer) {\n"
        "    fun recoverSessionAfterRestart(sessionId: String): Boolean {\n"
        "        return replaySessionState(sessionId)\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    # Kotlin tests including backtick test names
    (test_dir / "BettingEngineTest.kt").write_text(
        "package com.poker\n\n"
        "class BettingEngineTest {\n"
        "    @Test\n"
        "    fun `should validate betting action and min raise`() {\n"
        "        val engine = BettingEngine(PotCalculator())\n"
        "        engine.validateAction(100, 50)\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (test_dir / "PokerHostServerTest.kt").write_text(
        "package com.poker\n\n"
        "class PokerHostServerTest {\n"
        "    @Test\n"
        "    fun testMultiplayerHostConnection() {\n"
        "        val server = PokerHostServer(ClientSessionRegistry())\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (test_dir / "PersistenceAndRecoveryTest.kt").write_text(
        "package com.poker\n\n"
        "class PersistenceAndRecoveryTest {\n"
        "    @Test\n"
        "    fun testRecoverSessionAfterRestart() {\n"
        "        val svc = SessionPersistenceService(StateReplayer())\n"
        '        svc.recoverSessionAfterRestart("s1")\n'
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    assert runner.invoke(app, ["init", str(repo), "--deterministic"]).exit_code == 0

    # Verify .ctxa.toml recorded primary_languages = ["kotlin"] instead of ["python"]
    ctxa_toml_text = (repo / ".ctxa.toml").read_text(encoding="utf-8")
    assert 'primary_languages = ["kotlin"]' in ctxa_toml_text

    # Task A: Domain logic ("Fix an issue in poker betting and action validation")
    res_a = runner.invoke(
        app,
        [
            "context",
            "Fix an issue in poker betting and action validation",
            str(repo),
            "--max-tokens",
            "6000",
        ],
    )
    assert res_a.exit_code == 0
    out_a = res_a.stdout
    assert "BettingEngine" in out_a
    assert "validateAction" in out_a
    assert "BettingEngineTest" in out_a
    assert "Verified by:" in out_a or "Uses/Calls:" in out_a
    # Top candidate must have a high semantic match score (not fallback 10)
    assert "score=`10`" not in out_a.splitlines()[12]

    # Task B: Multiplayer networking
    res_b = runner.invoke(
        app,
        [
            "context",
            "Investigate multiplayer connection failures between host and clients",
            str(repo),
            "--max-tokens",
            "6000",
        ],
    )
    assert res_b.exit_code == 0
    out_b = res_b.stdout
    assert "PokerHostServer" in out_b
    assert "PokerMultiplayerClient" in out_b
    assert "PokerHostServerTest" in out_b

    # Task C: Persistence
    res_c = runner.invoke(
        app,
        [
            "context",
            "Fix session persistence and recovery after application restart",
            str(repo),
            "--max-tokens",
            "6000",
        ],
    )
    assert res_c.exit_code == 0
    out_c = res_c.stdout
    assert "SessionPersistenceService" in out_c
    assert "recoverSessionAfterRestart" in out_c
    assert "PersistenceAndRecoveryTest" in out_c
