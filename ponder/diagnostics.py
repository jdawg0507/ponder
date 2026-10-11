"""Compiler and Test Harness Diagnostic Abstractions."""

from __future__ import annotations
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel


class DiagnosticCategory(str, Enum):
    REDECLARATION = "redeclaration"
    HEADER_ORDERING = "header_ordering"
    UNDECLARED_SYMBOL = "undeclared_symbol"
    TYPE_MISMATCH = "type_mismatch"
    SYNTAX_ERROR = "syntax_error"
    TEST_ASSERTION = "test_assertion"
    GENERIC = "generic"


class CompilerDiagnostic(BaseModel):
    category: DiagnosticCategory
    raw_message: str
    remediation_directive: Optional[str] = None


class DiagnosticAnalyzer:
    """Analyzes raw compiler/test logs and produces structured remediation directives."""

    @classmethod
    def analyze(cls, error_log: str, language: str) -> CompilerDiagnostic:
        log_lower = error_log.lower()

        # Symbol redeclaration in Go / C++
        if "redeclared in this block" in log_lower or "redefinition of" in log_lower:
            return CompilerDiagnostic(
                category=DiagnosticCategory.REDECLARATION,
                raw_message=error_log,
                remediation_directive=(
                    "A symbol is redeclared. Identifiers defined in sibling files or upstream contracts "
                    "are already in scope. Remove the duplicate definition from this file and invoke it directly."
                ),
            )

        # Header ordering (e.g. Go package header expected)
        if "expected 'package'" in log_lower or "package declaration missing" in log_lower:
            return CompilerDiagnostic(
                category=DiagnosticCategory.HEADER_ORDERING,
                raw_message=error_log,
                remediation_directive=(
                    "File header ordering is invalid. Ensure 'package <name>' is the very first statement "
                    "in the file, followed by imports and function bodies."
                ),
            )

        # Syntax error
        if "syntaxerror" in log_lower or "expected" in log_lower and "token" in log_lower:
            return CompilerDiagnostic(
                category=DiagnosticCategory.SYNTAX_ERROR,
                raw_message=error_log,
                remediation_directive="Resolve the exact syntax error indicated in the compiler trace.",
            )

        # Test failure
        if "test harness failed" in log_lower or "assertionerror" in log_lower:
            return CompilerDiagnostic(
                category=DiagnosticCategory.TEST_ASSERTION,
                raw_message=error_log,
                remediation_directive="Review the failing test assertions and align behavior with expected contract specifications.",
            )

        return CompilerDiagnostic(
            category=DiagnosticCategory.GENERIC,
            raw_message=error_log,
            remediation_directive="Address compiler diagnostic output directly.",
        )
