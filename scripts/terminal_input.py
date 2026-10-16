import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description="Record text typed into a real verification terminal.")
    parser.add_argument("output", type=Path)
    parser.add_argument("--launch", action="store_true")
    args = parser.parse_args()
    if args.launch:
        subprocess.Popen(["xterm", "-T", "Boxes-input-proof", "-e", sys.executable,
                          str(Path(__file__).resolve()), str(args.output)],
                         start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        args.output.write_text(input())


if __name__ == "__main__":
    main()
