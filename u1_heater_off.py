#!/usr/bin/env python3
import re
import sys
from pathlib import Path
from typing import Dict, Optional, List

COMMENT_PREFIX = ";GRETA:"
THUMB_END_MARKER = "; THUMBNAIL_BLOCK_END"

# Tool -> Heater Mapping
TOOL_TO_HEATER = {
    0: "extruder",
    1: "extruder1",
    2: "extruder2",
    3: "extruder3",
}

def heater_off_cmd(tool: int) -> str:
    return f"SET_HEATER_TEMPERATURE HEATER={TOOL_TO_HEATER[tool]} TARGET=0"

# ------------------------------------------------------------
# Tool detection (for SnOrca)
# ------------------------------------------------------------
RE_TOOL = re.compile(r"^\s*T(\d+)\s*(?:;.*)?$")  # "T2"
RE_CHANGE_TOOL = re.compile(r"^\s*;\s*Change Tool\d+\s*->\s*Tool(\d+)\b", re.IGNORECASE)
RE_M104_T = re.compile(r"^\s*M104\b.*\bT(\d+)\b", re.IGNORECASE)
RE_M109_T = re.compile(r"^\s*M109\b.*\bT(\d+)\b", re.IGNORECASE)

# Snapmaker macro often includes the target tool index
RE_SM_INDEX = re.compile(r"\bINDEX\s*=\s*(\d+)\b", re.IGNORECASE)

# ------------------------------------------------------------
# Motion / E usage
# ------------------------------------------------------------
RE_G92_E = re.compile(r"^\s*G92\b.*\bE\b", re.IGNORECASE)         # reset only
RE_MOVE = re.compile(r"^\s*G0?1\b(.*)$", re.IGNORECASE)          # G0/G1
RE_E = re.compile(r"(?:^|\s)E(-?\d+(?:\.\d+)?)\b", re.IGNORECASE)

# ------------------------------------------------------------
# Temperature / cooldown detection
# ------------------------------------------------------------
RE_M104_TOOL = re.compile(r"^\s*M104\b.*\bS.*\bT(\d+)\b", re.IGNORECASE)
RE_SET_HEATER = re.compile(
    r"^\s*SET_HEATER_TEMPERATURE\b.*\bHEATER=([A-Za-z0-9_]+)\b.*\bTARGET=",
    re.IGNORECASE
)
RE_TOOLCHANGE_MARKER = re.compile(r"^\s*;\s*Change Tool\b", re.IGNORECASE)

# ------------------------------------------------------------
# Layer detection (strict + contextual fallback)
# ------------------------------------------------------------
# Unambiguous markers:
RE_LAYER_A = re.compile(r"^\s*;\s*LAYER\s*:\s*(\d+)\b", re.IGNORECASE)               # ;LAYER:123
RE_LAYER_B = re.compile(r"^\s*;\s*layer\s*#\s*(\d+)\b", re.IGNORECASE)               # ; layer #123
RE_LAYER_ANY = re.compile(r"^\s*;.*\blayer\b\D*(\d+)\b", re.IGNORECASE)              # ; ... layer ... 123
RE_CHANGE_TOOL_LAYER = re.compile(
    r"^\s*;\s*Change Tool\d+\s*->\s*Tool\d+\s*\(layer\s*(\d+)\)",
    re.IGNORECASE
)

# Bare numeric comment (fragile): ; 849
RE_LAYER_C = re.compile(r"^\s*;\s*(\d+)\s*$")

# Context helpers for accepting bare numeric layer lines
RE_M109 = re.compile(r"^\s*M109\b", re.IGNORECASE)
RE_TLINE = re.compile(r"^\s*T\d+\b")

def detect_layer_from_line_strict(line: str) -> Optional[int]:
    s = line.strip()
    for rx in (RE_LAYER_A, RE_LAYER_B, RE_CHANGE_TOOL_LAYER, RE_LAYER_ANY):
        m = rx.match(s)
        if m:
            return int(m.group(1))
    return None

def looks_like_bare_layer_context(lines: List[str], idx: int, forward_window: int = 30) -> bool:
    """
    Accept '; <number>' only if nearby lines look like a toolchange section.
    We check forward for M109 or a Tn line or a Change Tool comment within a small window.
    """
    end = min(len(lines), idx + 1 + forward_window)
    for j in range(idx + 1, end):
        s = lines[j].strip()
        if RE_M109.match(s) or RE_TLINE.match(s) or RE_CHANGE_TOOL.match(lines[j]):
            return True
    return False

def find_layer_before(lines: List[str], idx: int, max_back: int = 20000) -> Optional[int]:
    """
    Backscan in two phases:
    1) Strict markers (reliable).
    2) Fallback to bare numeric comment '; 123' only if it sits in toolchange context.
    """
    start = max(0, idx - max_back)

    # Phase 1: strict markers
    for j in range(idx, start - 1, -1):
        lyr = detect_layer_from_line_strict(lines[j])
        if lyr is not None:
            return lyr

    # Phase 2: contextual bare numeric fallback
    for j in range(idx, start - 1, -1):
        m = RE_LAYER_C.match(lines[j].strip())
        if m and looks_like_bare_layer_context(lines, j, forward_window=30):
            return int(m.group(1))

    return None

# ------------------------------------------------------------
# Insert helper: AFTER LAST marker occurrence
# ------------------------------------------------------------
def insert_after_last_marker(lines: list, marker: str, block_lines: list) -> None:
    last_idx = None
    for i, ln in enumerate(lines):
        if marker in ln:
            last_idx = i
    if last_idx is not None:
        lines[last_idx + 1:last_idx + 1] = block_lines
    else:
        # fallback early in file
        insert_at = min(5, len(lines))
        lines[insert_at:insert_at] = block_lines

# ============================================================
# MAIN
# ============================================================
def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: u1_greta.py <gcode_file>", file=sys.stderr)
        return 2

    gcode_path = Path(sys.argv[1]).resolve()
    lines = gcode_path.read_text(encoding="utf-8", errors="replace").splitlines(True)

    current_tool: Optional[int] = None

    # Track last E-move per tool (includes retract/unretract)
    last_e_move_by_tool: Dict[int, int] = {}

    # --------------------------------------------------------
    # PASS 1: Scan file, attribute E-moves to tools
    # --------------------------------------------------------
    for i, line in enumerate(lines):
        # Tool from "Change Tool..." comment
        if (m := RE_CHANGE_TOOL.match(line)):
            current_tool = int(m.group(1))
            continue

        # Tool from M109/M104 Tn (often appears before/around real Tn)
        if (m := RE_M109_T.match(line)):
            current_tool = int(m.group(1))
            continue

        if (m := RE_M104_T.match(line)):
            current_tool = int(m.group(1))
            continue

        # Tool from Snapmaker macro INDEX= (best-effort)
        if "INDEX" in line.upper():
            mi = RE_SM_INDEX.search(line)
            if mi:
                current_tool = int(mi.group(1))

        # Classic tool select "Tn"
        if (m := RE_TOOL.match(line.strip())):
            current_tool = int(m.group(1))
            continue

        # Ignore E reset
        if RE_G92_E.match(line):
            continue

        # Record last "E-move" per tool
        if current_tool is not None and RE_MOVE.match(line):
            if RE_E.search(line):
                last_e_move_by_tool[current_tool] = i

    if not last_e_move_by_tool:
        return 0

    # Determine last layer per tool via backscan from last E-move
    last_layer_by_tool: Dict[int, Optional[int]] = {
        tool: find_layer_before(lines, idx) for tool, idx in last_e_move_by_tool.items()
    }

    # --------------------------------------------------------
    # PASS 2: Insert heater-off AFTER cooldown for each tool
    # --------------------------------------------------------
    used_tools: List[int] = []

    for tool, last_idx in sorted(last_e_move_by_tool.items(), key=lambda x: x[1], reverse=True):
        if tool not in TOOL_TO_HEATER:
            continue

        heater = TOOL_TO_HEATER[tool]
        insert_after = last_idx

        # Scan forward until next toolchange marker; find last temp-set for THIS tool/heater
        j = last_idx + 1
        while j < len(lines):
            if RE_TOOLCHANGE_MARKER.match(lines[j]):
                break

            if (m := RE_M104_TOOL.match(lines[j])):
                if int(m.group(1)) == tool:
                    insert_after = j

            if (m := RE_SET_HEATER.match(lines[j])):
                if m.group(1) == heater:
                    insert_after = j

            j += 1

        lines[insert_after + 1:insert_after + 1] = [
            f"{COMMENT_PREFIX} heater off after cooldown of T{tool}\n",
            f"{heater_off_cmd(tool)}\n",
        ]
        used_tools.append(tool)

    # --------------------------------------------------------
    # PASS 3: Documentation block after LAST THUMBNAIL_BLOCK_END
    # --------------------------------------------------------
    doc = [";Heater off Block\n"]
    for tool in sorted(set(used_tools)):
        heater = TOOL_TO_HEATER[tool]
        layer = last_layer_by_tool.get(tool)
        if layer is None:
            doc.append(f"; - {heater} (T{tool}) off after last use (Layer can not be found)\n")
        else:
            doc.append(f"; - {heater} (T{tool}) off after Layer {layer}\n")
    doc.append(";End Heater off Block\n")

    insert_after_last_marker(lines, THUMB_END_MARKER, doc)

    gcode_path.write_text("".join(lines), encoding="utf-8", newline="\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
