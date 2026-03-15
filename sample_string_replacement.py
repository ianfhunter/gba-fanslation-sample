# Reallocate Pointers.

# Takes a Japanese string, removes it from the ROM
# Finds an empty space in the ROM, writes the English string there
# and updates the pointers

# All mappings from .tbl only. Use fullwidth ＄ (U+FF04) for line break in both strings.

import argparse

TEST_STRING = "あなたの名前を\n登録してくださ～い"
TEST_TRANSLATION = "Your Name\nPlease~"


def parse_arguments():
    parser = argparse.ArgumentParser(description="Reallocate Pointers")
    parser.add_argument("rom", type=str, help="Path to the ROM file")
    parser.add_argument("-t", "--table", type=str, required=True, help="Path to the table file")
    return parser.parse_args()


def load_table(args):
    """Load table file and build char -> bytes map (format 'HEX=char')."""
    with open(args.table, "r", encoding="utf-8") as f:
        table = f.read()
    char_to_bytes = {}
    for line in table.splitlines():
        line = line.strip()
        if "=" in line:
            hex_part, _, rest = line.partition("=")
            hex_part = hex_part.strip()
            # Empty or single ASCII whitespace (space, tab, \r) after = -> newline; else use rest as-is (don't strip 　)
            char = "\n" if (not rest or (len(rest) == 1 and rest in " \t\r")) else rest
            if hex_part:
                char_to_bytes[char] = bytes.fromhex(hex_part)
    return char_to_bytes


def find_string_in_rom(args):
    """Load ROM, encode TEST_STRING with table, find its offset. Returns (rom, offset, search_bytes, char_to_bytes)."""
    with open(args.rom, "rb") as f:
        rom = f.read()
    char_to_bytes = load_table(args)
    # Try \n first; if not found, try line-break variants (ROM may use ＄ or $)
    for variant in (TEST_STRING, TEST_STRING.replace("\n", "＄"), TEST_STRING.replace("\n", "$")):
        search_bytes = b"".join(char_to_bytes[c] for c in variant)
        offset = rom.find(search_bytes)
        if offset != -1:
            return rom, offset, search_bytes, char_to_bytes
    raise SystemExit(f"String not found in ROM: {TEST_STRING!r}")


def encode_translation(char_to_bytes):
    """Encode TEST_TRANSLATION using table; use fullwidth form for ASCII letters/space for lookup."""
    def table_encode(s):
        out = []
        for c in s:
            if c == "\n":
                out.append(b"\x81\x90")  # Game line break (same as fullwidth ＄)
                continue
            if c == " ":
                out.append(b"\x81\x40")  # Fullwidth space; table entry can be wrong (e.g. 　 strips)
                continue
            if c in char_to_bytes:
                out.append(char_to_bytes[c])
            else:
                if "A" <= c <= "Z":
                    fc = chr(ord(c) - ord("A") + ord("Ａ"))
                elif "a" <= c <= "z":
                    fc = chr(ord(c) - ord("a") + ord("ａ"))
                elif c == " ":
                    fc = "　"
                elif c == "~":
                    fc = "～"
                else:
                    fc = "？"
                out.append(char_to_bytes.get(fc, char_to_bytes.get("？", b"\x81\x48")))
        return b"".join(out)
    return table_encode(TEST_TRANSLATION)


def dump_rom_string_hex(rom: bytes, offset: int, length: int, label: str = "ROM string"):
    """Print hex and byte positions for the string in ROM (to find actual line-break bytes)."""
    chunk = rom[offset : offset + length]
    hex_str = chunk.hex(" ")
    print(f"\n--- {label} at 0x{offset:X} ({length} bytes) ---")
    print("Hex:", hex_str)
    # Show position of each byte (so we can see what's between "name" and "register")
    for i in range(0, min(len(chunk), 80), 16):
        line = chunk[i : i + 16]
        pos_hex = " ".join(f"{offset + i + j:02X}" for j in range(len(line)))
        val_hex = " ".join(f"{b:02X}" for b in line)
        print(f"  +{i:2d}  {val_hex}")


def main():
    args = parse_arguments()
    rom, source_pointer, search_bytes, char_to_bytes = find_string_in_rom(args)
    # Diagnostic: show exact bytes in ROM for the original string (see what byte = line break)
    dump_rom_string_hex(rom, source_pointer, len(search_bytes), "Original string in ROM")
    encoded_translation = encode_translation(char_to_bytes)
    dump_rom_string_hex(
        bytes(encoded_translation), 0, len(encoded_translation),
        "Encoded translation (what we write)"
    )

    # Approach 1: In-place Memory Replacement
    original_len = len(search_bytes)
    if len(encoded_translation) <= original_len:
        replacement = encoded_translation + b"\x00" * (original_len - len(encoded_translation))
    else:
        replacement = encoded_translation[:original_len]
    rom_mut = bytearray(rom)
    rom_mut[source_pointer : source_pointer + original_len] = replacement
    with open("in_memory.gba", "wb") as f:
        f.write(rom_mut)

    # Approach 2: Allocate in unallocated space at end of ROM (trailing 0xFF/0x00), then fix pointer
    GBA_ROM_BASE = 0x08000000
    new_string_data = encoded_translation + b"\x00"  # terminator
    needed = len(new_string_data)
    # Search backwards from end for a run of unallocated bytes (0xFF or 0x00)
    free_run_len = 0
    for i in range(len(rom) - 1, -1, -1):
        if rom[i] in (0xFF, 0x00):
            free_run_len += 1
        else:
            break
    if free_run_len < needed:
        raise SystemExit(
            f"Not enough unallocated space at end of ROM: need {needed} bytes, found {free_run_len} (0xFF/0x00 run)"
        )
    new_offset = len(rom) - free_run_len
    rom_realloc = bytearray(rom)
    rom_realloc[new_offset : new_offset + needed] = new_string_data
    old_ptr = (GBA_ROM_BASE + source_pointer).to_bytes(4, "little")
    new_ptr = (GBA_ROM_BASE + new_offset).to_bytes(4, "little")
    ptr_pos = 0
    while True:
        ptr_pos = rom_realloc.find(old_ptr, ptr_pos)
        if ptr_pos == -1:
            break
        rom_realloc[ptr_pos : ptr_pos + 4] = new_ptr
        ptr_pos += 4
    with open("reallocation.gba", "wb") as f:
        f.write(rom_realloc)


if __name__ == "__main__":
    main()
