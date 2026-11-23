"""
Author: L. Saetta
Date Last Modified: 2026-11-23
License: MIT
Description: Verifies a case bundle (a zip file) and puts it into the
    sandbox, safely.

    Integrity: the extraction script recorded the SHA-256 of the bundle in
    the case file, outside the bundle; in the lab it is the .sha256 file next
    to the zip. The bundle is checked against it locally, before the upload,
    and again in the sandbox, on the uploaded copy, before the extraction.

    Safety: the content was written by suppliers and users, and may come
    from the person under investigation: it is untrusted. It is never
    extracted on the local machine. Locally, only the zip directory is read,
    to reject bundles that are too large or that contain dangerous entries
    (absolute paths, "..", symbolic links, encrypted files). Then the zip is
    uploaded to the sandbox and extracted there, under /workspace/bundle.

Usage:

    expected = reference_hash(Path("bundles/halden-ap-q3-2026.zip"))
    summary = BundleUploader(session).upload(bundle, expected_sha256=expected)
"""

import hashlib
import re
import shlex
import stat
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from triage.sandbox import SandboxSession

#: Where the bundle is extracted in the sandbox.
BUNDLE_DIR = "/workspace/bundle"

#: Where the zip file is uploaded in the sandbox.
UPLOAD_PATH = "/workspace/upload/bundle.zip"

#: Largest zip file accepted, in bytes.
MAX_BUNDLE_BYTES = 200 * 1024 * 1024

#: Largest total size of the extracted files, in bytes (zip bomb guard).
MAX_EXTRACTED_BYTES = 1024 * 1024 * 1024

#: Largest number of entries in the zip.
MAX_MEMBERS = 10_000

#: Seconds allowed to extract the bundle in the sandbox.
EXTRACT_TIMEOUT_SECONDS = 300

#: Seconds allowed to compute the hash of the uploaded copy in the sandbox.
HASH_TIMEOUT_SECONDS = 120

_SHA256 = re.compile(r"[0-9a-f]{64}")


class BundleError(ValueError):
    """The bundle is not a valid, safe zip file, or it fails the hash check."""


def file_sha256(path: Path) -> str:
    """The SHA-256 of a local file, in lower-case hex.

    Args:
        path: The file.

    Returns:
        The hash.

    Raises:
        BundleError: The file does not exist.
    """
    if not path.is_file():
        raise BundleError(f"{path} does not exist")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def reference_hash(bundle: Path) -> str:
    """The reference SHA-256 of a bundle, from its .sha256 file.

    The file stands for the value recorded in the case file: same name as
    the bundle, ``.sha256`` suffix, in the format of ``sha256sum``.

    Args:
        bundle: The zip file.

    Returns:
        The reference hash, in lower-case hex.

    Raises:
        BundleError: The .sha256 file is missing or malformed.
    """
    path = bundle.with_suffix(".sha256")
    if not path.is_file():
        raise BundleError(
            f"reference hash not found: {path} (it comes from the case file; "
            "or pass the value with --expected-sha256)"
        )
    words = path.read_text(encoding="utf-8").split()
    value = words[0].lower() if words else ""
    if not _SHA256.fullmatch(value):
        raise BundleError(f"{path} does not contain a SHA-256 value")
    return value


def verify_hash(path: Path, expected: str) -> str:
    """Check a local bundle against its reference hash.

    Args:
        path: The zip file.
        expected: The reference SHA-256, in hex.

    Returns:
        The hash of the file (equal to ``expected``).

    Raises:
        BundleError: The file is missing, ``expected`` is not a SHA-256 value,
            or the hashes differ.
    """
    expected = expected.strip().lower()
    if not _SHA256.fullmatch(expected):
        raise BundleError("the reference hash is not a SHA-256 value (64 hex digits)")
    actual = file_sha256(path)
    if actual != expected:
        raise BundleError(
            f"{path.name} does not match the reference hash (SHA-256 {actual[:12]}… "
            f"instead of {expected[:12]}…): it may have been changed after the "
            "extraction; do not analyse it"
        )
    return actual


@dataclass(frozen=True)
class BundleSummary:
    """What a bundle contains.

    Attributes:
        name: File name of the bundle.
        files: Number of files.
        compressed_bytes: Size of the zip file.
        extracted_bytes: Total size of the files once extracted.
        sha256: SHA-256 of the zip file, computed locally.
        verified_in_sandbox: True when the uploaded copy matched the
            reference hash in the sandbox.
    """

    name: str
    files: int
    compressed_bytes: int
    extracted_bytes: int
    sha256: str = ""
    verified_in_sandbox: bool = False

    def describe(self) -> str:
        """One line for the console, for example "sample.zip: 12 files, 3.1 MB"."""
        megabytes = self.extracted_bytes / (1024 * 1024)
        return f"{self.name}: {self.files} files, {megabytes:.1f} MB extracted"


class BundleInspector:
    """Checks a bundle locally, reading only its zip directory."""

    def inspect(self, path: Path) -> BundleSummary:
        """Check that a bundle is a safe zip file and describe it.

        Args:
            path: The local zip file.

        Returns:
            The number and size of the files.

        Raises:
            BundleError: The file is missing, too large, not a zip, or has a
                dangerous entry.
        """
        if not path.is_file():
            raise BundleError(f"{path} does not exist")
        compressed = path.stat().st_size
        if compressed > MAX_BUNDLE_BYTES:
            raise BundleError(f"{path.name} is larger than {MAX_BUNDLE_BYTES} bytes")
        if not zipfile.is_zipfile(path):
            raise BundleError(f"{path.name} is not a zip file")

        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
        if len(members) > MAX_MEMBERS:
            raise BundleError(f"{path.name} has more than {MAX_MEMBERS} entries")
        files = [member for member in members if not member.is_dir()]
        for member in files:
            self._check_member(member)
        extracted = sum(member.file_size for member in files)
        if extracted > MAX_EXTRACTED_BYTES:
            raise BundleError(
                f"{path.name} extracts to more than {MAX_EXTRACTED_BYTES} bytes"
            )
        return BundleSummary(
            path.name, len(files), compressed, extracted, file_sha256(path)
        )

    @staticmethod
    def _check_member(member: zipfile.ZipInfo) -> None:
        """Reject entries that could escape the bundle directory or hide content."""
        name = member.filename
        parts = PurePosixPath(name.replace("\\", "/")).parts
        if name.startswith(("/", "\\")) or ":" in name.split("/")[0] or ".." in parts:
            raise BundleError(f"unsafe path in the bundle: {name}")
        if stat.S_ISLNK(member.external_attr >> 16):
            raise BundleError(f"symbolic link in the bundle: {name}")
        if member.flag_bits & 0x1:
            raise BundleError(f"encrypted file in the bundle: {name}")


class BundleUploader:
    """Uploads a bundle to the sandbox and extracts it under BUNDLE_DIR.

    Args:
        session: The running sandbox.
        inspector: Checks the bundle before the upload.
    """

    def __init__(
        self, session: SandboxSession, inspector: BundleInspector | None = None
    ) -> None:
        self._session = session
        self._inspector = inspector or BundleInspector()

    def upload(self, path: Path, expected_sha256: str | None = None) -> BundleSummary:
        """Check, upload and extract a bundle; a previous bundle is replaced.

        Args:
            path: The local zip file.
            expected_sha256: The reference hash. When given, the bundle is
                checked against it locally and, after the upload, in the
                sandbox, before the extraction.

        Returns:
            The number and size of the files, and the hash checks.

        Raises:
            BundleError: The bundle failed a check, or could not be extracted.
            SandboxError: The sandbox could not be reached.
        """
        if expected_sha256 is not None:
            verify_hash(path, expected_sha256)
        summary = self._inspector.inspect(path)
        self._session.run(
            f"rm -rf {BUNDLE_DIR} {UPLOAD_PATH} && mkdir -p {BUNDLE_DIR}",
            timeout_seconds=60,
        )
        self._session.write_file(UPLOAD_PATH, path.read_bytes())
        if expected_sha256 is not None:
            self._verify_in_sandbox(expected_sha256.strip().lower())
            summary = replace(summary, verified_in_sandbox=True)
        result = self._session.run(
            f"python3 -m zipfile -e {UPLOAD_PATH} {BUNDLE_DIR} && rm -f {UPLOAD_PATH}",
            timeout_seconds=EXTRACT_TIMEOUT_SECONDS,
        )
        if not result.ok:
            raise BundleError(
                f"extraction failed in the sandbox (exit code {result.exit_code}): "
                f"{result.output[-300:]}"
            )
        return summary

    def _verify_in_sandbox(self, expected: str) -> None:
        """Hash the uploaded copy in the sandbox and compare it with ``expected``."""
        script = (
            "import hashlib, sys; "
            "print(hashlib.sha256(open(sys.argv[1], 'rb').read()).hexdigest())"
        )
        result = self._session.run(
            f"python3 -c {shlex.quote(script)} {UPLOAD_PATH}",
            timeout_seconds=HASH_TIMEOUT_SECONDS,
        )
        actual = result.output.strip().lower()
        if not result.ok or actual != expected:
            raise BundleError(
                "the copy uploaded to the sandbox does not match the reference "
                f"hash (SHA-256 {actual[:12] or 'unavailable'}… instead of "
                f"{expected[:12]}…); the bundle was not extracted"
            )
