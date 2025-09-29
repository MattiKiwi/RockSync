#!/usr/bin/env python3
"""Example user script for RockSync.

This script prints a greeting multiple times to demonstrate how
user-provided scripts can integrate with the Advanced tab.  It can also be
invoked directly from the command line.
"""

import argparse
import sys


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Example RockSync user script")
    parser.add_argument("--name", default="RockSync", help="Name to greet")
    parser.add_argument("--times", type=int, default=1, help="Number of repetitions")
    return parser.parse_args(argv)


def main():
    args = parse_args()
    for idx in range(max(1, args.times)):
        print(f"[{idx + 1}] Hello, {args.name}!")


if __name__ == "__main__":
    main()
