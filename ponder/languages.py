"""Language Strategy & Profile Abstractions for Polyglot Code Synthesis."""

from __future__ import annotations
import re
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Set
from ponder.models import ChunkOutput


class LanguageProfile(ABC):
    """Abstract strategy defining language-specific scoping, headers, and file assembly."""

    name: str
    extensions: List[str]
    shares_directory_scope: bool = False

    @abstractmethod
    def extract_package_header(self, code: str) -> Optional[str]:
        """Extracts package/namespace declaration if required by language."""
        pass

    @abstractmethod
    def extract_imports(self, code: str) -> List[str]:
        """Extracts import / include directives."""
        pass

    @abstractmethod
    def clean_body(self, code: str, imports: Set[str], header: Optional[str]) -> str:
        """Strips extracted header and imports from code body."""
        pass

    def assemble_source(self, chunks: List[ChunkOutput]) -> str:
        """Assembles verified code chunks into a well-formed source file."""
        if len(chunks) == 1:
            return chunks[0].code.strip() + "\n"

        header: Optional[str] = None
        all_imports: Set[str] = set()
        bodies: List[str] = []

        for chunk in chunks:
            chunk_header = self.extract_package_header(chunk.code)
            if chunk_header and not header:
                header = chunk_header

            chunk_imports = self.extract_imports(chunk.code)
            all_imports.update(chunk_imports)
            for imp in chunk.imports:
                all_imports.add(imp.strip())

            body = self.clean_body(chunk.code, all_imports, header)
            if body.strip():
                bodies.append(body.strip())

        parts: List[str] = []
        if header:
            parts.append(header.strip())

        formatted_imports = self.format_imports(all_imports)
        if formatted_imports:
            parts.append(formatted_imports.strip())

        if bodies:
            parts.append("\n\n".join(bodies))

        return "\n\n".join(p for p in parts if p).strip() + "\n"

    def format_imports(self, imports: Set[str]) -> str:
        """Formats and deduplicates imports."""
        if not imports:
            return ""
        return "\n".join(sorted(imports))

    def get_scope_directive(self) -> Optional[str]:
        """Returns scoping rules for Actuator context conditioning."""
        if self.shares_directory_scope:
            return (
                f"In {self.name.capitalize()}, files in the same directory share package scope. "
                "Identifiers (functions, structs, types) from sibling files are automatically accessible. "
                "Do NOT re-declare or redefine them in this file."
            )
        return None


class GoProfile(LanguageProfile):
    name = "go"
    extensions = [".go"]
    shares_directory_scope = True

    def extract_package_header(self, code: str) -> Optional[str]:
        for line in code.splitlines():
            line_str = line.strip()
            if line_str.startswith("package "):
                return line_str
        return "package main"

    def extract_imports(self, code: str) -> List[str]:
        imports: List[str] = []
        # Match multi-line import (...)
        multi = re.search(r"import\s*\(([\s\S]*?)\)", code)
        if multi:
            for line in multi.group(1).splitlines():
                line_clean = line.strip()
                if line_clean and not line_clean.startswith("//"):
                    imports.append(line_clean)
        # Match single-line import "..."
        for line in code.splitlines():
            m = re.match(r'^import\s+("[^"]+"|\S+\s+"[^"]+")', line.strip())
            if m:
                imports.append(m.group(1))
        return imports

    def clean_body(self, code: str, imports: Set[str], header: Optional[str]) -> str:
        # Strip import (...) blocks
        cleaned = re.sub(r"import\s*\([\s\S]*?\)", "", code)
        lines = []
        for line in cleaned.splitlines():
            line_str = line.strip()
            if line_str.startswith("package "):
                continue
            if line_str.startswith("import ") and '"' in line_str:
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    def format_imports(self, imports: Set[str]) -> str:
        if not imports:
            return ""
        sorted_imps = sorted(imports)
        if len(sorted_imps) == 1 and not sorted_imps[0].startswith("("):
            return f"import {sorted_imps[0]}"
        body = "\n\t".join(sorted_imps)
        return f"import (\n\t{body}\n)"


class PythonProfile(LanguageProfile):
    name = "python"
    extensions = [".py"]
    shares_directory_scope = False

    def extract_package_header(self, code: str) -> Optional[str]:
        return None

    def extract_imports(self, code: str) -> List[str]:
        imports = []
        for line in code.splitlines():
            s = line.strip()
            if s.startswith("import ") or s.startswith("from "):
                imports.append(s)
        return imports

    def clean_body(self, code: str, imports: Set[str], header: Optional[str]) -> str:
        lines = []
        for line in code.splitlines():
            s = line.strip()
            if s in imports:
                continue
            lines.append(line)
        return "\n".join(lines).strip()


class GenericProfile(LanguageProfile):
    name = "generic"
    extensions = []
    shares_directory_scope = False

    def extract_package_header(self, code: str) -> Optional[str]:
        return None

    def extract_imports(self, code: str) -> List[str]:
        return []

    def clean_body(self, code: str, imports: Set[str], header: Optional[str]) -> str:
        return code.strip()


class LanguageRegistry:
    """Registry providing language profiles by language name or file extension."""

    _profiles: Dict[str, LanguageProfile] = {
        "go": GoProfile(),
        "python": PythonProfile(),
    }
    _default: LanguageProfile = GenericProfile()

    @classmethod
    def get(cls, language_or_ext: str) -> LanguageProfile:
        key = language_or_ext.lower().lstrip(".")
        if key in cls._profiles:
            return cls._profiles[key]
        for prof in cls._profiles.values():
            if f".{key}" in prof.extensions or key in prof.extensions:
                return prof
        return cls._default

    @classmethod
    def register(cls, profile: LanguageProfile):
        cls._profiles[profile.name.lower()] = profile
