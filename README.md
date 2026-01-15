# SnOrcaSlicer Post-Processing: Automatic Tool Heater Shutdown (Snapmaker U1)

This repository provides a **post-processing script for SnOrcaSlicer** that automatically **turns off tool heaters**
after a tool is no longer used in a toolchanger print.

The script was developed for the **Snapmaker U1 with Klipper firmware**, but it also works with other
Klipper-based toolchanger setups as long as the heater names match the configuration.

---

## Motivation

In multi-tool prints, unused tools are often kept at temperature or at a cooldown temperature
(e.g. 70 °C) until the end of the print.

This leads to:

- unnecessary power consumption  
- increased thermal stress on hotends  
- potential filament degradation in idle extruders  
- unnecessary wear on your hotend fans as they spin at 20k rpm without beeing needed

This script solves these problems automatically and safely.

---

## What the Script Does

For **each tool that actually extrudes filament**, the script:

1. detects the **last real usage** (G-code move with extrusion)
2. waits for any slicer-generated **cooldown / temperature commands**
3. inserts a Klipper command **after those commands**:

   ```gcode
   SET_HEATER_TEMPERATURE HEATER=extruderX TARGET=0
   ```

4. documents the result in a **human-readable comment block** inside the G-code

---

## Features

- ✅ works with **1, 2, 3, or 4 tools**
- ✅ correctly handles tools that are **re-used later in the print**
- ✅ only affects tools that **actually extruded**
- ✅ does **not** modify start or end G-code
- ✅ does **not** override slicer logic, only complements it
- ✅ adds a clear documentation block to the G-code
- ✅ fail-safe: unknown tools are ignored

---

## Supported Tool Detection

The script detects tool usage via:

- `Tn`
- `M104 ... Tn`
- `M109 ... Tn`
- `; Change ToolX -> ToolY (layer N)`
- Snapmaker macros containing `INDEX=n`

---

## G-code Comment Block

After the **last** occurrence of:

```
; THUMBNAIL_BLOCK_END
```

the script inserts a documentation block like:

```gcode
;Heater off Block
; - extruder1 (T1) shutdown after layer 916
; - extruder2 (T2) shutdown after layer 849
;End Heater off Block
```

- Only **used tools** are listed
- Layer numbers reflect the **actual last usage**
- Entries are sorted by tool number

---

## Requirements

- SnOrcaSlicer **2.2.1**
- Python ≥ 3.8
- U1 Klipper firmware **1.0.0.0** (Supports both stock and paxx12s custom firmware
- Heater names following Klipper conventions:
  - `extruder`
  - `extruder1`
  - `extruder2`
  - `extruder3`

---

## Installation

1. Clone the repository or download the script
2. Make the script executable (Linux/macOS):

   ```bash
   chmod +x u1_heater_off.py
   ```

3. Configure OrcaSlicer → **Process-Tab -> Others -> Post-processing scripts**

### Windows

```text
python "C:\path\to\u1_heater_off.py" "[output_filepath]"
```

### Linux / macOS

```text
python3 /path/to/u1_heater_off.py "[output_filepath]"
```

---

## Configuration

### Tool → Heater Mapping

The mapping is intentionally explicit for safety:

```python
TOOL_TO_HEATER = {
    0: "extruder",
    1: "extruder1",
    2: "extruder2",
    3: "extruder3",
}
```

If your printer uses more tools, simply extend this mapping.

---

## Safety and Design Decisions

- Tools that never extrude are **never shut down**
- Tools outside the mapping are **ignored**
- No assumptions about automatic heater naming
- Layer detection uses a robust backward scan
- Script behavior is deterministic and repeatable

---

## Known Limitations

- Tools that never extrude are not affected
- Tools > T3 must be explicitly mapped
- End G-code is intentionally left untouched

---

## License

MIT License – free use, modification, and redistribution permitted.

---

## Feedback and Contributions

Issues, pull requests, and improvements are welcome.
This script was developed from a real-world toolchanger workflow
and is actively used in production prints.
