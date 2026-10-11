"""Workspace Assembler for writing verified code chunks to disk."""

from __future__ import annotations
from pathlib import Path
from typing import Dict, List
from ponder.languages import LanguageRegistry
from ponder.models import ChunkOutput, SubGoal


class WorkspaceAssembler:
    """Assembles verified AST chunks into target workspace files using language profiles."""

    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root)

    def assemble(
        self,
        subgoals: Dict[str, SubGoal],
        verified_chunks: Dict[str, ChunkOutput],
    ) -> List[str]:
        """Merges verified chunks by module path and writes them to disk."""
        files_map: Dict[str, List[ChunkOutput]] = {}

        for subgoal_id, chunk in verified_chunks.items():
            subgoal = subgoals[subgoal_id]
            files_map.setdefault(subgoal.module_path, []).append(chunk)

        written_paths = []
        for rel_path, chunks in files_map.items():
            full_path = self.workspace_root / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)

            merged_content = self._merge_chunks(rel_path, chunks)
            full_path.write_text(merged_content, encoding="utf-8")
            written_paths.append(str(full_path))

        return written_paths

    def _merge_chunks(self, module_path: str, chunks: List[ChunkOutput]) -> str:
        """Merges chunks for a single file through the corresponding language profile."""
        ext = Path(module_path).suffix or module_path
        profile = LanguageRegistry.get(ext)
        return profile.assemble_source(chunks)
