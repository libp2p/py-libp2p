#!/usr/bin/env python3
import glob
import sys


def main():
    rst_files = glob.glob("**/*.rst", recursive=True)
    if rst_files:
        print(
            f"Error: .rst files found. Please use markdown (.md) instead: {rst_files}"
        )
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
