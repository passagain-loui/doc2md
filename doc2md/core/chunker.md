# chunker.py

````python
"""Semantic Markdown chunking bounded by a token budget.

Splitting priority: top-level headers (`#`..`##` start new chunks) -> blank-line
paragraphs -> sentence boundaries -> lines -> words. Fenced code blocks are
atomic: an oversized fence is re-sliced and each slice re-wrapped in a balanced
```-pair so no chunk ever leaves an open fence.
"""

from __future__ import annotations

import re

from doc2md.core.tokens import estimate_tokens

_HEADER_RE = re.compile(r"^#\s")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

def chunk_markdown(markdown: str, max_tokens: int, counter=None) -> list[str]:
 """Split *markdown* into chunks of at most *max_tokens* tokens (per *counter*)."""
 if max_tokens <= 0:
 raise ValueError("max_tokens must be a positive integer")
 measure = counter or estimate_tokens
 if not markdown.strip():
 return []
 units = _logical_blocks(markdown)
 return _pack_units(units, max_tokens, measure)

def _pack_units(units: list[str], budget: int, measure) -> list[str]:
 chunks: list[str] = []
 current: list[str] = []
 current_cost = 0
 for unit in units:
 cost = measure(unit)
 if cost > budget:
 if current:
 if all(
 ln.lstrip().startswith("#")
 for held in current
 for ln in held.splitlines()
 if ln.strip()
 ):
 pieces = _split_unit(unit, budget, measure)
 if pieces:
 pieces[0] = (_join(current) + "\n\n" + pieces[0]).strip()
 chunks.extend(pieces)
 current, current_cost = [], 0
 continue
 chunks.append(_join(current))
 current, current_cost = [], 0
 chunks.extend(_split_unit(unit, budget, measure))
 continue
 if current and current_cost + cost > budget:
 chunks.append(_join(current))
 current, current_cost = [unit], cost
 else:
 current.append(unit)
 current_cost += cost
 if current:
 joined = _join(current)
 if joined.strip():
 chunks.append(joined)
 return [c for c in (chunk.strip() for chunk in chunks) if c]

def _join(parts: list[str]) -> str:
 return "\n".join(parts)

def _join_sentences(parts: list[str]) -> str:
 return " ".join(p.strip() for p in parts)

def _split_unit(unit: str, budget: int, measure) -> list[str]:
 if unit.lstrip().startswith("```"):
 return _split_fenced(unit, budget, measure)
 paragraphs = [p for p in re.split(r"\n\s*\n", unit) if p.strip()]
 if len(paragraphs) <= 1:
 pieces = _split_prose_piece(unit, budget, measure)
 else:
 pieces = _pack_units(paragraphs, budget, measure)
 if all(measure(p) <= budget for p in pieces):
 return pieces
 result: list[str] = []
 for piece in pieces:
 if measure(piece) <= budget:
 result.append(piece)
 else:
 result.extend(_split_prose_piece(piece, budget, measure))
 return result

def _split_prose_piece(piece: str, budget: int, measure) -> list[str]:
 stripped = piece.strip()
 if _HEADER_RE.match(stripped) and "\n" not in stripped:
 return [piece]
 sentences = [s for s in _SENTENCE_RE.split(stripped) if s.strip()]
 if len(sentences) > 1:
 packed = _accumulate(sentences, budget, measure, joiner=_join_sentences)
 if all(measure(p) <= budget for p in packed):
 return packed
 return _split_by_lines(piece, budget, measure)
 if "\n" in piece.strip():
 return _split_by_lines(piece, budget, measure)
 return _split_by_words(piece, budget, measure)

def _split_by_lines(text: str, budget: int, measure) -> list[str]:
 lines = [ln for ln in text.splitlines()]
 packed = _accumulate(lines, budget, measure, joiner=_join)
 result: list[str] = []
 for piece in packed:
 if measure(piece) <= budget or ("\n" not in piece and _HEADER_RE.match(piece.strip())):
 result.append(piece)
 else:
 result.extend(_split_by_words(piece, budget, measure))
 return result

def _split_by_words(text: str, budget: int, measure) -> list[str]:
 words = text.split()
 if not words:
 return [text] if text.strip() else []
 tokens: list[str] = []
 for word in words:
 while measure(word) > budget and len(word) > 1:
 cut = max(1, len(word) // 2)
 head, word = word[:cut], word[cut:]
 tokens.append(head)
 tokens.append(word)
 packed = _accumulate(tokens, budget, measure, joiner=_join_sentences)
 return [piece for piece in packed if piece.strip()]

def _accumulate(items: list[str], budget: int, measure, *, joiner) -> list[str]:
 out: list[str] = []
 current: list[str] = []
 current_cost = 0
 for item in items:
 candidate = joiner(current + [item]) if current else item
 cost = measure(candidate)
 if current and cost > budget:
 out.append(joiner(current))
 current, current_cost = [item], measure(item)
 else:
 current = current + [item]
 current_cost = cost
 if current:
 out.append(joiner(current))
 return out

def _split_fenced(unit: str, budget: int, measure) -> list[str]:
 lines = unit.splitlines()
 opener = lines[0]
 closer = "```"
 body = [ln for ln in lines[1:] if ln.strip() != closer]
 overhead = measure(opener) + 1 + measure(closer)
 inner_budget = max(4, budget - overhead - 1)
 groups = _accumulate([ln for ln in body], inner_budget, measure,
 joiner=lambda parts: "\n".join(parts))
 if not groups:
 groups = [""]
 return [f"\n\n" for group in groups]

def _logical_blocks(markdown: str) -> list[str]:
 blocks: list[str] = []
 prose: list[str] = []

 def flush_prose():
 if prose:
 text = "\n".join(prose).strip("\n")
 if text.strip():
 blocks.append(text)
 prose.clear()

 in_fence = False
 fence_buffer: list[str] = []
 for line in markdown.splitlines():
 if not in_fence and _FENCE_RE.match(line):
 flush_prose()
 fence_buffer = [line]
 in_fence = True
 elif in_fence:
 fence_buffer.append(line)
 if line.strip().startswith(("```", "~~~")):
 blocks.append("\n".join(fence_buffer))
 fence_buffer = []
 in_fence = False
 elif _HEADER_RE.match(line) and any(ln.strip() for ln in prose):
 flush_prose()
 prose.append(line)
 elif not line.strip():
 flush_prose()
 else:
 prose.append(line)
 if fence_buffer:
 blocks.append("\n".join(fence_buffer))
 flush_prose()
 return blocks
````
