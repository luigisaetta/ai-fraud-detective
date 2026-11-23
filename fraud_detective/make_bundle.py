"""
Author: L. Saetta
Date Last Modified: 2026-11-23
License: MIT
Description: Writes the bundle of the sample case and the reference hash
    recorded in the case file.

    The case: an anonymous report says that someone in accounts payable may
    be diverting supplier payments. The bundle is the extraction run by
    Halden IT for the forensic firm: ERP tables from January to September
    2026, the AP control policy, the AP shared mailbox and the case files.
    It hides a known fraud, an honest duplicate payment and red herrings
    (see docs/scenario-design.md and docs/sample-bundle.md).

    Two files are written:

    - the bundle, a zip with a manifest.json of file hashes inside;
    - next to it, a .sha256 file with the hash of the whole zip, in the
      format of ``sha256sum``: it stands for the value recorded in the case
      file, outside the bundle.

    The bundle is deterministic: the same command always writes the same
    bytes, so the hash never changes.

Usage:

    python -m fraud_detective.make_bundle                 # bundles/halden-ap-q3-2026.zip
    python -m fraud_detective.make_bundle --output my.zip
    python -m fraud_detective.make_bundle --answer-key    # print the answer key (Markdown)
    python -m fraud_detective.make_bundle --preview       # print a few lines of every file
"""

import argparse
import hashlib
import sys
from pathlib import Path
from typing import TextIO

from fraud_detective.sample_case.case import SampleCase

#: Default output file.
DEFAULT_OUTPUT = Path("bundles/halden-ap-q3-2026.zip")

#: Lines of each file shown by --preview (header included).
PREVIEW_LINES = 6


def hash_path(bundle: Path) -> Path:
    """The reference hash file of a bundle: same name, ``.sha256`` suffix.

    Args:
        bundle: The zip file.

    Returns:
        For example ``bundles/halden-ap-q3-2026.sha256``.
    """
    return bundle.with_suffix(".sha256")


class BundleWriter:
    """Writes the bundle and its reference hash.

    Args:
        case: The sample case to write.
    """

    def __init__(self, case: SampleCase | None = None) -> None:
        self._case = case or SampleCase()

    def write(self, output: Path) -> tuple[Path, str]:
        """Write the zip and the .sha256 file next to it.

        Args:
            output: The zip file to write; its folder is created if needed.

        Returns:
            The path of the zip and its SHA-256, in hex.
        """
        data = self._case.archive()
        digest = hashlib.sha256(data).hexdigest()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        hash_path(output).write_text(f"{digest}  {output.name}\n", encoding="utf-8")
        return output, digest

    def print_answer_key(self, stream: TextIO) -> None:
        """Print the answer key as a Markdown table.

        Args:
            stream: Where to print it.
        """
        print("| Finding | Location | What it shows |", file=stream)
        print("|---------|----------|---------------|", file=stream)
        for item in self._case.answer_key():
            print(f"| {item.finding} | `{item.location}` | {item.what} |", file=stream)

    def print_preview(self, stream: TextIO) -> None:
        """Print the first lines of every file, as Markdown, for a reviewer.

        Emails and case files are printed whole: they are short.

        Args:
            stream: Where to print it.
        """
        for path, text in self._case.files.items():
            lines = text.splitlines()
            whole = path.startswith(("mail/", "case/", "policy/"))
            shown = lines if whole else lines[:PREVIEW_LINES]
            count = len(lines) - (1 if path.endswith(".csv") else 0)
            unit = "data rows" if path.endswith(".csv") else "lines"
            print(f"### `{path}` ({count} {unit})\n", file=stream)
            print("```text", file=stream)
            print("\n".join(shown), file=stream)
            if not whole and len(lines) > len(shown):
                print("...", file=stream)
            print("```\n", file=stream)


def main(argv: list[str] | None = None) -> None:
    """Write the sample bundle and print where it is, or print the answer key.

    Args:
        argv: Arguments; sys.argv[1:] by default.
    """
    parser = argparse.ArgumentParser(description="Write the sample case bundle.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--answer-key", action="store_true", help="print the answer key and exit"
    )
    parser.add_argument(
        "--preview", action="store_true", help="print a preview of the files and exit"
    )
    args = parser.parse_args(argv)
    writer = BundleWriter()
    if args.answer_key:
        writer.print_answer_key(sys.stdout)
        return
    if args.preview:
        writer.print_preview(sys.stdout)
        return
    path, digest = writer.write(args.output)
    print(f"{path}: {path.stat().st_size / 1024:.0f} KB")
    print(f"{hash_path(path)}: sha256 {digest}")


if __name__ == "__main__":
    main()
