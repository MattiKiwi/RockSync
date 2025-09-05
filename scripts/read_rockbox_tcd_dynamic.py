#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import json
import os
import re
import struct
import sys
from dataclasses import dataclass, asdict
from typing import Dict, Tuple, List, Optional

LE_U16 = "<H"
LE_U32 = "<I"
HEADER_STRUCT = struct.Struct("<III")  # version, payload_size, entry_count

# Friendly names for the first few tag indices seen in most Rockbox DBs.
# Anything not listed will be called tag_<n>.
DEFAULT_TAG_NAMES = {
    0: "artist",
    1: "album",
    2: "genre",
    3: "title",
    4: "path",       # full path/filename
    5: "composer",
    # 6+: device/build-dependent; we'll name them tag_6, tag_7, ...
}

@dataclass
class TcdHeader:
    version: int
    payload_size: int
    entry_count: int

class TcdParseError(Exception):
    pass

def read_header(f) -> TcdHeader:
    raw = f.read(HEADER_STRUCT.size)
    if len(raw) != HEADER_STRUCT.size:
        raise TcdParseError("Unexpected EOF reading TCD header")
    version, payload_size, entry_count = HEADER_STRUCT.unpack(raw)
    return TcdHeader(version, payload_size, entry_count)

def read_index_file(path: str, verbose: bool=False) -> Dict[int, Tuple[str, int]]:
    """
    Returns: mapping from entry file-offset -> (UTF-8 string, index_field)
    The key is the byte offset within this file where that entry begins.
    """
    mapping: Dict[int, Tuple[str, int]] = {}
    with open(path, "rb") as f:
        hdr = read_header(f)
        start = f.tell()
        end = start + hdr.payload_size

        if verbose:
            print(f"[index] {os.path.basename(path)}: version=0x{hdr.version:08X} "
                  f"payload={hdr.payload_size} entries={hdr.entry_count}")

        entries_read = 0
        while f.tell() < end:
            entry_offset = f.tell()
            b = f.read(4)
            if len(b) < 4:
                break
            slen, idx_field = struct.unpack(LE_U16 + LE_U16, b)
            raw = f.read(slen)
            if len(raw) != slen:
                raise TcdParseError(f"Corrupt index entry at offset {entry_offset}")
            s = raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
            mapping[entry_offset] = (s, idx_field)
            entries_read += 1

        if hdr.entry_count and verbose and entries_read != hdr.entry_count:
            print(f"[warn] {os.path.basename(path)}: header entry_count={hdr.entry_count}, "
                  f"parsed={entries_read}")
    return mapping

def read_master_file(path: str, verbose: bool=False):
    """
    Returns (hdr, serial, rows_as_u32_lists, fields_per_row)
    Detects row width from payload size and entry_count.
    """
    with open(path, "rb") as f:
        hdr = read_header(f)
        serial_bytes = f.read(4)
        if len(serial_bytes) != 4:
            raise TcdParseError("Corrupt master: missing serial")
        serial = struct.unpack(LE_U32, serial_bytes)[0]

        # Determine how many bytes remain for rows
        # Some builds may have exact hdr.payload_size, some may pad — trust entry_count.
        remaining = hdr.payload_size - 4  # minus the serial we just read
        if hdr.entry_count == 0:
            raise TcdParseError("Master reports zero rows; nothing to read.")
        if remaining % hdr.entry_count != 0:
            # Fall back: read until EOF based on entry_count and consistent row size.
            # We'll read the first row, then infer size by file position difference.
            # But usually remaining divides cleanly.
            pass
        row_size = remaining // hdr.entry_count
        if row_size % 4 != 0:
            raise TcdParseError(f"Row size {row_size} not aligned to 4 bytes")
        fields_per_row = row_size // 4
        row_struct = struct.Struct("<" + "I" * fields_per_row)

        if verbose:
            print(f"[master] {os.path.basename(path)}: version=0x{hdr.version:08X} "
                  f"rows={hdr.entry_count} serial={serial} fields_per_row={fields_per_row}")

        rows = []
        for i in range(hdr.entry_count):
            b = f.read(row_struct.size)
            if len(b) != row_struct.size:
                raise TcdParseError(f"Unexpected EOF in master at row {i}")
            rows.append(list(row_struct.unpack(b)))
        return hdr, serial, rows, fields_per_row

def discover_index_files(base_dir: str, verbose: bool=False) -> Dict[int, str]:
    """
    Finds database_N.tcd files, returns a dict {N: filepath} with integer keys.
    """
    found: Dict[int, str] = {}
    for name in os.listdir(base_dir):
        m = re.fullmatch(r"database_(\d+)\.tcd", name)
        if m:
            idx = int(m.group(1))
            found[idx] = os.path.join(base_dir, name)
    if verbose:
        if found:
            print(f"[info] Found index files: {', '.join(sorted(found_file for found_file in map(lambda kv: os.path.basename(kv[1]), sorted(found.items()))))}")
        else:
            print("[warn] No index files found alongside master; strings won't resolve")
    return found

def load_all_indices(index_paths: Dict[int, str], verbose: bool=False) -> Dict[int, Dict[int, Tuple[str, int]]]:
    maps: Dict[int, Dict[int, Tuple[str, int]]] = {}
    for tag_id, path in sorted(index_paths.items()):
        try:
            maps[tag_id] = read_index_file(path, verbose=verbose)
        except Exception as e:
            print(f"[error] Failed to read {os.path.basename(path)}: {e}", file=sys.stderr)
            maps[tag_id] = {}
    return maps

def resolve_offset(offset: int, idx_map: Dict[int, Tuple[str, int]]) -> Optional[str]:
    if offset == 0:
        return None
    return idx_map.get(offset, (None, 0))[0]

def guess_column_names(num_tag_fields: int) -> List[str]:
    names = []
    for i in range(num_tag_fields):
        names.append(DEFAULT_TAG_NAMES.get(i, f"tag_{i}"))
    return names

def find_base_dir(path: str):
    """
    Accepts either a directory (/.rockbox) or a direct path to database_idx.tcd.
    Returns (base_dir, master_path)
    """
    if os.path.isdir(path):
        base_dir = path
        master_path = os.path.join(base_dir, "database_idx.tcd")
    else:
        base_dir = os.path.dirname(path)
        master_path = path
    if not os.path.isfile(master_path):
        raise FileNotFoundError(f"Could not find master file: {master_path}")
    return base_dir, master_path

def main():
    ap = argparse.ArgumentParser(
        description="Read Rockbox Tag Cache (.tcd) files (dynamic) and export tracks."
    )
    ap.add_argument("path", help="Path to /.rockbox directory or to database_idx.tcd")
    ap.add_argument("-o", "--out", default="-", help="Output path (default: '-' for stdout JSON)")
    ap.add_argument("-f", "--format", choices=["csv", "json"], default="json", help="Output format")
    ap.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = ap.parse_args()

    try:
        base_dir, master_path = find_base_dir(args.path)
    except Exception as e:
        print(f"[fatal] {e}", file=sys.stderr)
        sys.exit(1)

    # Discover and load index files
    index_paths = discover_index_files(base_dir, verbose=args.verbose)
    index_maps = load_all_indices(index_paths, verbose=args.verbose)

    # Read master
    try:
        master_hdr, serial, rows_u32, fields_per_row = read_master_file(master_path, verbose=args.verbose)
    except Exception as e:
        print(f"[fatal] Failed to read master: {e}", file=sys.stderr)
        sys.exit(2)

    # Heuristic:
    # - Let num_tag_fields = highest index id present + 1 (contiguous from 0)
    # - Clamp to fields_per_row to avoid overruns.
    num_tag_fields = 0
    if index_paths:
        num_tag_fields = max(index_paths.keys()) + 1
    num_tag_fields = min(num_tag_fields, fields_per_row)

    tag_col_names = guess_column_names(num_tag_fields)

    # Remaining fields are numeric; we'll name them num_0, num_1, ...
    num_numeric_fields = max(0, fields_per_row - num_tag_fields)
    numeric_col_names = [f"num_{i}" for i in range(num_numeric_fields)]

    # Build output rows
    out_rows: List[dict] = []
    for r in rows_u32:
        row = {}
        # Resolve string tags via offsets
        for tag_id in range(num_tag_fields):
            off = r[tag_id]
            m = index_maps.get(tag_id, {})
            row[tag_col_names[tag_id]] = resolve_offset(off, m)
        # Copy numeric tails as-is
        for j in range(num_numeric_fields):
            row[numeric_col_names[j]] = r[num_tag_fields + j]
        out_rows.append(row)

    # Emit
    if args.out == "-":
        if args.format == "csv":
            writer = csv.DictWriter(sys.stdout, fieldnames=list(out_rows[0].keys()) if out_rows else [])
            writer.writeheader()
            for row in out_rows:
                writer.writerow(row)
        else:
            json.dump(out_rows, sys.stdout, ensure_ascii=False, indent=2)
            if sys.stdout.isatty():
                print()
    else:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        if args.format == "csv":
            with open(args.out, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()) if out_rows else [])
                writer.writeheader()
                for row in out_rows:
                    writer.writerow(row)
        else:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(out_rows, f, ensure_ascii=False, indent=2)

    if args.verbose:
        print(f"[done] Exported {len(out_rows)} tracks "
              f"(tag fields: {num_tag_fields}, numeric fields: {num_numeric_fields})")

if __name__ == "__main__":
    main()
