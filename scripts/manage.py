#!/usr/bin/env python3
"""Install and synchronize the portable subset of a Codex home directory."""

from __future__ import annotations

import argparse
import csv
import errno
import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, TextIO


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTING_BEGIN = "<!-- codex-profiles:begin -->"
ROUTING_END = "<!-- codex-profiles:end -->"
SOURCE_MARKER_RE = re.compile(r"^<!-- codex-config:source (.+) -->$", re.MULTILINE)
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class ConfigError(RuntimeError):
    pass


def normalized_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def canonical_text(value: str) -> str:
    return normalized_text(value).strip("\n") + "\n"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(canonical_text(value).encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def require_within(path: Path, root: Path) -> None:
    resolved_path = path.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ConfigError(f"Path escapes its allowed root: {path}")


def validate_safe_name(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not SAFE_NAME_RE.fullmatch(value)
        or value in {".", ".."}
        or value.endswith(".")
        or value.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES
    ):
        raise ConfigError(f"Invalid {label}: {value!r}")
    return value


def validate_relative_value(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ConfigError(f"Invalid {label}: {value!r}")
    candidate = Path(value)
    if (
        candidate == Path(".")
        or candidate.is_absolute()
        or ".." in candidate.parts
        or candidate.drive
        or any(
            part.endswith((".", " "))
            or part.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES
            for part in candidate.parts
        )
    ):
        raise ConfigError(f"Invalid {label}: {value!r}")
    return value


def ensure_no_links(path: Path, root: Path) -> None:
    require_within(path, root)
    current = root
    if is_link_like(current):
        raise ConfigError(f"Symlinked or junction path is not allowed: {current}")
    for part in path.relative_to(root).parts:
        current = current / part
        if is_link_like(current):
            raise ConfigError(f"Symlinked or junction path is not allowed: {current}")


def relative_path(root: Path, value: str) -> Path:
    validate_relative_value(value, "relative path")
    candidate = Path(value)
    result = root / candidate
    require_within(result, root)
    return result


def read_text(path: Path) -> str:
    return normalized_text(path.read_text(encoding="utf-8-sig"))


def atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(value)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(path: Path, value: str) -> None:
    atomic_write_bytes(path, canonical_text(value).encode("utf-8"))


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Cannot read JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"Expected a JSON object in {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write_bytes(
        path,
        (json.dumps(value, indent=2, sort_keys=False) + "\n").encode("utf-8"),
    )


def load_manifest(
    repo_root: Path, *, base_only: bool = False
) -> dict[str, Any]:
    manifest = load_json(repo_root / "manifest.json")
    private_manifest = manifest.get("private_manifest")
    if private_manifest is not None:
        validate_relative_value(private_manifest, "private manifest path")
        if not base_only:
            source_repo = skills_repository_root(repo_root)
            if source_repo == repo_root:
                raise ConfigError(
                    "A private manifest requires a separate codex-skills checkout"
                )
            secret_manifest = relative_path(source_repo, private_manifest)
            ensure_no_links(secret_manifest, source_repo)
            if not secret_manifest.is_file():
                raise ConfigError(
                    f"Private credential metadata is missing: {secret_manifest}"
                )
            overrides = load_json(secret_manifest)
            if overrides.get("schema_version") != 1:
                raise ConfigError("Unsupported private metadata schema")
            for key in ("encrypted_files", "skill_policy"):
                value = overrides.get(key, {})
                if not isinstance(value, dict):
                    raise ConfigError(f"Invalid private metadata {key}")
                if manifest.get(key):
                    raise ConfigError(
                        f"Private metadata {key} must not be duplicated in public manifest"
                    )
                manifest[key] = value
    if manifest.get("schema_version") != 1:
        raise ConfigError("Unsupported manifest schema")
    if not isinstance(manifest.get("profiles"), dict):
        raise ConfigError("Manifest profiles are missing")
    if not isinstance(manifest.get("markers"), dict):
        raise ConfigError("Manifest markers are missing")
    required_markers = {"global_begin", "global_end", "projects_begin", "projects_end"}
    if set(manifest["markers"]) != required_markers:
        raise ConfigError("Manifest marker keys are invalid")
    for key, value in manifest["markers"].items():
        if (
            not isinstance(value, str)
            or "\n" in value
            or not value.startswith("<!-- codex-config:")
        ):
            raise ConfigError(f"Manifest marker {key} is invalid")
    for name, config in manifest["profiles"].items():
        validate_safe_name(name, "profile name")
        if not isinstance(config, dict):
            raise ConfigError(f"Invalid profile: {name}")
        for group in ("global_fragments", "projects_fragments"):
            values = config.get(group)
            if not isinstance(values, list) or not values:
                raise ConfigError(f"Profile {name} has invalid {group}")
            for value in values:
                validate_relative_value(value, f"{name}.{group} entry")
            if len(values) != len(set(values)):
                raise ConfigError(f"Profile {name} has duplicate {group} entries")
        skills = config.get("skills")
        if not isinstance(skills, list):
            raise ConfigError(f"Profile {name} has invalid skills")
        for skill in skills:
            validate_safe_name(skill, "skill name")
        if len(skills) != len(set(skills)):
            raise ConfigError(f"Profile {name} has duplicate skills")
        project_skills = config.get("project_skills", [])
        if not isinstance(project_skills, list):
            raise ConfigError(f"Profile {name} has invalid project_skills")
        for skill in project_skills:
            validate_safe_name(skill, "project skill name")
        if len(project_skills) != len(set(project_skills)):
            raise ConfigError(f"Profile {name} has duplicate project_skills")
        overlap = set(skills) & set(project_skills)
        if overlap:
            raise ConfigError(
                f"Profile {name} has skills in both scopes: {', '.join(sorted(overlap))}"
            )
    encrypted_files = manifest.get("encrypted_files")
    if not isinstance(encrypted_files, dict):
        raise ConfigError("Manifest encrypted_files is invalid")
    for skill, encrypted in encrypted_files.items():
        validate_safe_name(skill, "encrypted skill name")
        if not isinstance(encrypted, dict):
            raise ConfigError(f"Invalid encrypted file entry: {skill}")
        validate_relative_value(
            encrypted.get("source"), f"encrypted source for {skill}"
        )
        validate_relative_value(
            encrypted.get("destination"), f"encrypted destination for {skill}"
        )
        plaintext_hash = encrypted.get("plaintext_sha256")
        if not isinstance(plaintext_hash, str) or not SHA256_RE.fullmatch(
            plaintext_hash
        ):
            raise ConfigError(f"Invalid plaintext SHA-256 for {skill}")
    return manifest


def ensure_skills_checkout(repo_root: Path) -> None:
    """Bootstrap the sibling private skills checkout after the source split.

    Do not change existing checkout directories or try other credential sources.
    """
    if os.environ.get("CODEX_SKILLS_REPO"):
        return
    destination = repo_root.parent / "codex-skills"
    if destination.exists():
        return
    if (repo_root / "skills").is_dir() or (
        repo_root / ".agents" / "skills"
    ).is_dir():
        return
    print(f"Cloning the private Codex skill source into {destination}")
    subprocess.run(
        [
            "git", "clone",
            "git@github.com:Kabaye/codex-skills.git",
            str(destination),
        ],
        check=True,
    )
    if not (destination / "skills-manifest.json").is_file():
        raise ConfigError(
            f"The private skill checkout has no skills-manifest.json: {destination}"
        )


def skills_repository_root(repo_root: Path) -> Path:
    """Prefer a separate sibling codex-skills checkout after its export is complete.

    Explicit CODEX_SKILLS_REPO must always exist. Do not silently fall back to
    vendored skills when an explicitly selected external source is missing.
    """
    configured = os.environ.get("CODEX_SKILLS_REPO")
    candidate = (
        Path(configured).expanduser() if configured
        else repo_root.parent / "codex-skills"
    )
    marker = candidate / "skills-manifest.json"
    if configured or marker.is_file():
        ensure_no_links(marker, candidate)
        if not marker.is_file():
            raise ConfigError(
                f"codex-skills is missing {marker}; clone the private skills "
                "repository or correct CODEX_SKILLS_REPO"
            )
        catalog = load_json(marker)
        if catalog.get("schema_version") != 1 or not isinstance(
            catalog.get("skills"), dict
        ):
            raise ConfigError(f"Invalid codex-skills manifest: {marker}")
        return candidate.resolve()
    if (repo_root / "skills").is_dir() or (
        repo_root / ".agents" / "skills"
    ).is_dir():
        return repo_root
    raise ConfigError(
        "Canonical skill sources were split out; clone private "
        "Kabaye/codex-skills next to codex-config or set CODEX_SKILLS_REPO"
    )


def skill_source_path(
    repo_root: Path, name: str, *, project_scoped: bool = False
) -> Path:
    validate_safe_name(name, "skill source name")
    source_repo = skills_repository_root(repo_root)
    if source_repo == repo_root:
        category = ".agents/skills" if project_scoped else "skills"
    else:
        category = "skills"
    source = source_repo / category / name
    ensure_no_links(source, source_repo)
    return source


def encrypted_source_path(repo_root: Path, relative: str) -> Path:
    source_repo = skills_repository_root(repo_root)
    path = relative_path(source_repo, relative)
    ensure_no_links(path, source_repo)
    return path


def profile_config(manifest: dict[str, Any], profile: str) -> dict[str, Any]:
    value = manifest["profiles"].get(profile)
    if not isinstance(value, dict):
        known = ", ".join(sorted(manifest["profiles"]))
        raise ConfigError(f"Unknown profile '{profile}'. Expected one of: {known}")
    return value


def configured_skill_names(manifest: dict[str, Any]) -> set[str]:
    return {
        skill
        for config in manifest["profiles"].values()
        for skill in config["skills"]
    }


def configured_project_skill_names(manifest: dict[str, Any]) -> set[str]:
    return {
        skill
        for config in manifest["profiles"].values()
        for skill in config.get("project_skills", [])
    }


def render_fragment_block(
    repo_root: Path,
    fragments: list[str],
    begin: str,
    end: str,
) -> str:
    sections = [begin]
    for fragment in fragments:
        source = relative_path(repo_root, fragment)
        if not source.is_file() or is_link_like(source):
            raise ConfigError(f"Missing or unsafe instruction fragment: {fragment}")
        sections.append(f"<!-- codex-config:source {fragment} -->")
        sections.append(read_text(source).strip("\n"))
    sections.append(end)
    return "\n\n".join(sections)


def legacy_fragment_text(repo_root: Path, fragments: list[str]) -> str:
    values = [
        read_text(relative_path(repo_root, item)).strip("\n") for item in fragments
    ]
    return "\n\n".join(values)


def locate_block(text: str, begin: str, end: str) -> tuple[int, int, str] | None:
    value = normalized_text(text)
    begin_positions = [match.start() for match in re.finditer(re.escape(begin), value)]
    end_positions = [match.start() for match in re.finditer(re.escape(end), value)]
    if not begin_positions and not end_positions:
        return None
    if len(begin_positions) != 1 or len(end_positions) != 1:
        raise ConfigError(f"Expected exactly one managed block for marker {begin}")
    start = value.rfind("\n", 0, begin_positions[0]) + 1
    marker_end = end_positions[0] + len(end)
    if marker_end < begin_positions[0]:
        raise ConfigError(f"Managed block markers are reversed: {begin}")
    stop = value.find("\n", marker_end)
    stop = len(value) if stop < 0 else stop + 1
    return start, stop, value[start:stop].strip("\n")


def join_sections(*sections: str) -> str:
    present = [normalized_text(item).strip("\n") for item in sections if item.strip()]
    return "\n\n".join(present) + ("\n" if present else "")


def strip_owned_regions(text: str, begin: str, end: str) -> tuple[str, bool]:
    """Remove every complete or unterminated line-delimited owned region."""
    depth = 0
    found = False
    kept: list[str] = []
    for line in normalized_text(text).splitlines():
        marker = line.strip()
        if marker == begin:
            depth += 1
            found = True
            continue
        if marker == end:
            found = True
            if not depth:
                raise ConfigError(f"Owned marker has no matching begin: {end}")
            depth -= 1
            continue
        if depth == 0:
            kept.append(line)
    if depth:
        raise ConfigError(f"Owned marker has no matching end: {begin}")
    return "\n".join(kept), found


def build_global_text(
    current: str,
    desired: str,
    legacy: str,
    begin: str,
    end: str,
    force: bool,
) -> str:
    routing = locate_block(current, ROUTING_BEGIN, ROUTING_END)
    if routing:
        r_start, r_stop, r_block = routing
        without_routing = join_sections(current[:r_start], current[r_stop:])
    else:
        r_block = ""
        without_routing = current

    outside, owned_found = strip_owned_regions(without_routing, begin, end)
    outside = outside.strip()
    if owned_found:
        return join_sections(outside, desired, r_block)

    if outside and canonical_text(outside) != canonical_text(legacy):
        if not force:
            raise ConfigError(
                "Unmanaged global AGENTS.md content does not match this profile"
            )
        return join_sections(outside, desired, r_block)
    return join_sections(desired, r_block)


def build_projects_text(
    current: str,
    desired: str,
    legacy: str,
    begin: str,
    end: str,
    force: bool,
) -> str:
    outside, owned_found = strip_owned_regions(current, begin, end)
    outside = outside.strip()
    if owned_found:
        return join_sections(outside, desired)
    if not outside or canonical_text(outside) == canonical_text(legacy):
        return canonical_text(desired)
    if not force:
        raise ConfigError(
            "Unmanaged Projects AGENTS.md content does not match the repository"
        )
    return join_sections(outside, desired)


def parse_fragment_block(block: str, begin: str, end: str) -> dict[str, str]:
    body = normalized_text(block).strip("\n")
    if not body.startswith(begin) or not body.endswith(end):
        raise ConfigError(f"Malformed managed block: {begin}")
    body = body[len(begin) : -len(end)].strip("\n")
    matches = list(SOURCE_MARKER_RE.finditer(body))
    if not matches:
        raise ConfigError(f"Managed block contains no source markers: {begin}")
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        source = match.group(1).strip()
        start = match.end()
        stop = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        if source in result:
            raise ConfigError(f"Duplicate source marker: {source}")
        result[source] = canonical_text(body[start:stop])
    return result


def iter_tree_files(root: Path) -> list[Path]:
    if is_link_like(root):
        raise ConfigError(f"Symlinked or junction directory is not allowed: {root}")
    files: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        safe_dirs = []
        for name in dirnames:
            child = directory_path / name
            if name == "__pycache__":
                continue
            if is_link_like(child):
                raise ConfigError(
                    f"Symlinked or junction directory is not allowed: {child}"
                )
            safe_dirs.append(name)
        dirnames[:] = safe_dirs
        for name in filenames:
            path = directory_path / name
            if path.suffix in {".pyc", ".pyo"}:
                continue
            if is_link_like(path) or not path.is_file():
                raise ConfigError(f"Unsafe file in managed tree: {path}")
            files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def tree_hashes(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in iter_tree_files(root)
    }


def copy_source_skill(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in iter_tree_files(source):
        relative = path.relative_to(source)
        if path.name == "access.yml" or path.suffix == ".age":
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def copy_installed_skill_for_capture(
    source: Path,
    destination: Path,
    secret_destination: str | None,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in iter_tree_files(source):
        relative = path.relative_to(source)
        if path.suffix == ".age":
            continue
        if (
            secret_destination
            and relative.as_posix() == Path(secret_destination).as_posix()
        ):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def current_user_sid() -> str:
    completed = subprocess.run(
        ["whoami.exe", "/user", "/fo", "csv", "/nh"],
        check=True,
        text=True,
        capture_output=True,
    )
    row = next(csv.reader([completed.stdout.strip()]))
    if len(row) < 2 or not row[1].startswith("S-"):
        raise ConfigError("Could not resolve the current Windows user SID")
    return row[1]


def restrict_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)
        return
    sid = current_user_sid()
    completed = subprocess.run(
        [
            "icacls.exe",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"*{sid}:(OI)(CI)F",
            "*S-1-5-18:(OI)(CI)F",
            "*S-1-5-32-544:(OI)(CI)F",
        ],
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise ConfigError(
            f"Could not restrict ACL on {path}: {completed.stderr.strip()}"
        )


class ManagerLock:
    def __init__(self, manager_root: Path) -> None:
        self.path = manager_root / "manager.lock"
        self.handle: Any = None

    def __enter__(self) -> "ManagerLock":
        ensure_no_links(self.path, self.path.parent)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"\0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                flock = getattr(fcntl, "flock")
                flock(
                    self.handle.fileno(),
                    getattr(fcntl, "LOCK_EX") | getattr(fcntl, "LOCK_NB"),
                )
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise ConfigError(
                "Another codex-config manager process is running"
            ) from exc
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                getattr(fcntl, "flock")(self.handle.fileno(), getattr(fcntl, "LOCK_UN"))
        finally:
            self.handle.close()
            self.handle = None


def remove_managed_path(path: Path, root: Path) -> None:
    require_within(path, root)
    if path.resolve(strict=False) == root.resolve(strict=False):
        raise ConfigError(f"Refusing to remove managed root: {root}")
    if not path.exists() and not is_link_like(path):
        return
    if is_link_like(path):
        raise ConfigError(f"Refusing to remove a linked path: {path}")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def directory_copy_staging(destination: Path, transaction: Path) -> Path:
    """Locate an unpublished copy on the destination volume for recovery."""
    return destination.with_name(f".{destination.name}.{transaction.name}.tmp")


def transfer_directory(
    source: Path,
    destination: Path,
    transaction: Path,
    *,
    retain_copy_source: bool = False,
) -> None:
    """Rename a tree, or publish a complete copy when volumes differ.

    A copied rollback source must survive until the entire transaction is
    recovered. Other copied sources are removed only after publication, so a
    failed copy or deletion never leaves a partial tree at the backup path.
    """
    try:
        source.rename(destination)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV and getattr(exc, "winerror", None) != 17:
            raise

    temporary = directory_copy_staging(destination, transaction)
    remove_managed_path(temporary, destination.parent)
    try:
        shutil.copytree(source, temporary, symlinks=True)
        temporary.rename(destination)
    finally:
        remove_managed_path(temporary, destination.parent)
    if not retain_copy_source:
        remove_managed_path(source, source.parent)


def backup_optional_file(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    if is_link_like(source) or not source.is_file():
        raise ConfigError(f"Unsafe transaction source file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def restore_optional_file(target: Path, backup: Path, existed: bool) -> None:
    if existed:
        if not backup.is_file() or is_link_like(backup):
            raise ConfigError(f"Transaction backup is missing or unsafe: {backup}")
        atomic_write_bytes(target, backup.read_bytes())
    elif target.exists():
        if is_link_like(target) or not target.is_file():
            raise ConfigError(f"Unexpected transaction target: {target}")
        target.unlink()


def restore_skill_directories(
    transaction: Path,
    backup_subdir: str,
    target_root: Path,
    skill_existence: dict[str, Any],
) -> None:
    for skill, existed in skill_existence.items():
        validate_safe_name(skill, "transaction skill name")
        if not isinstance(existed, bool):
            raise ConfigError(f"Invalid transaction skill state: {skill}")
        target = target_root / skill
        require_within(target, target_root)
        remove_managed_path(directory_copy_staging(target, transaction), target_root)
        backup = transaction / backup_subdir / skill
        if backup.exists():
            if is_link_like(backup):
                raise ConfigError(f"Unsafe transaction skill backup: {backup}")
            if target.exists() or is_link_like(target):
                remove_managed_path(target, target_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            transfer_directory(
                backup, target, transaction, retain_copy_source=True
            )
        elif not existed and (target.exists() or is_link_like(target)):
            remove_managed_path(target, target_root)


def transaction_matches(
    journal: dict[str, Any],
    home: Path,
    projects_root: Path,
    repo_root: Path,
    project_root: Path,
) -> None:
    expected = {
        "home": home,
        "projects_root": projects_root,
        "repo_root": repo_root,
    }
    for key, path in expected.items():
        value = journal.get(key)
        if not isinstance(value, str) or Path(value).resolve() != path.resolve():
            raise ConfigError(f"Interrupted transaction targets another {key}")
    if "project_root" in journal:
        value = journal.get("project_root")
        if (
            not isinstance(value, str)
            or Path(value).resolve() != project_root.resolve()
        ):
            raise ConfigError("Interrupted transaction targets another project_root")



def recover_transactions(
    manager_root: Path,
    home: Path,
    projects_root: Path,
    repo_root: Path,
    project_root: Path,
) -> None:
    for transaction in sorted(manager_root.glob("txn-*")):
        require_within(transaction, manager_root)
        if is_link_like(transaction) or not transaction.is_dir():
            raise ConfigError(f"Unsafe interrupted transaction: {transaction}")
        journal_path = transaction / "journal.json"
        if not journal_path.exists():
            shutil.rmtree(transaction)
            continue
        journal = load_json(journal_path)
        if journal.get("schema_version") != 1:
            raise ConfigError(
                f"Unsupported interrupted transaction: {transaction.name}"
            )
        transaction_matches(
            journal, home, projects_root, repo_root, project_root
        )
        phase = journal.get("phase")
        if phase in {"committed", "recovered"}:
            shutil.rmtree(transaction)
            continue
        if phase != "prepared":
            raise ConfigError(f"Interrupted transaction has invalid phase: {phase!r}")
        operation = journal.get("operation")
        skills = journal.get("skills")
        if not isinstance(skills, dict):
            raise ConfigError(
                f"Interrupted transaction has invalid skills: {transaction.name}"
            )
        for skill, existed in skills.items():
            validate_safe_name(skill, "transaction skill name")
            if not isinstance(existed, bool):
                raise ConfigError(f"Invalid transaction skill state: {skill}")
        project_skills = journal.get("project_skills", {})
        if not isinstance(project_skills, dict):
            raise ConfigError(
                f"Interrupted transaction has invalid project_skills: {transaction.name}"
            )
        for skill, existed in project_skills.items():
            validate_safe_name(skill, "transaction project skill name")
            if not isinstance(existed, bool):
                raise ConfigError(f"Invalid transaction project skill state: {skill}")

        backups = transaction / "backups"
        if operation in {"install", "remove"}:
            for key in ("global_existed", "projects_existed", "state_existed"):
                if not isinstance(journal.get(key), bool):
                    raise ConfigError(f"Interrupted transaction has invalid {key}")
            restore_optional_file(
                home / "AGENTS.md",
                backups / "global-agents.bin",
                journal.get("global_existed") is True,
            )
            restore_optional_file(
                projects_root / "AGENTS.md",
                backups / "projects-agents.bin",
                journal.get("projects_existed") is True,
            )
            restore_optional_file(
                state_path(home),
                backups / "state.json",
                journal.get("state_existed") is True,
            )

            journal_skills_root = journal.get("skills_root")
            if journal_skills_root is None:
                target_skills_root = home / "skills"
            elif isinstance(journal_skills_root, str):
                target_skills_root = Path(journal_skills_root).resolve()
            else:
                raise ConfigError("Interrupted transaction has invalid skills_root")
            ensure_no_links(target_skills_root, target_skills_root.parent)
            restore_skill_directories(
                transaction,
                "rollback" if operation == "install" else "skills",
                target_skills_root,
                skills,
            )

            legacy_skills = journal.get("legacy_skills", {})
            legacy_skills_root = journal.get("legacy_skills_root")
            if legacy_skills:
                if not isinstance(legacy_skills, dict):
                    raise ConfigError("Interrupted transaction has invalid legacy_skills")
                if not isinstance(legacy_skills_root, str):
                    raise ConfigError(
                        "Interrupted transaction has invalid legacy_skills_root"
                    )
                legacy_root = Path(legacy_skills_root).resolve()
                ensure_no_links(legacy_root, legacy_root.parent)
                restore_skill_directories(
                    transaction,
                    "legacy-rollback",
                    legacy_root,
                    legacy_skills,
                )

            project_skills_root_value = journal.get("project_skills_root")
            if project_skills_root_value is not None:
                if not isinstance(project_skills_root_value, str):
                    raise ConfigError(
                        "Interrupted transaction has invalid project_skills_root"
                    )
                target_project_skills_root = Path(
                    project_skills_root_value
                ).resolve()
                ensure_no_links(
                    target_project_skills_root, target_project_skills_root.parent
                )
                restore_skill_directories(
                    transaction,
                    "project-rollback"
                    if operation == "install"
                    else "project-skills",
                    target_project_skills_root,
                    project_skills,
                )

            previous_project_skills = journal.get("previous_project_skills", {})
            previous_project_skills_root = journal.get(
                "previous_project_skills_root"
            )
            if previous_project_skills:
                if not isinstance(previous_project_skills_root, str):
                    raise ConfigError(
                        "Interrupted transaction has invalid previous_project_skills_root"
                    )
                previous_root = Path(previous_project_skills_root).resolve()
                ensure_no_links(previous_root, previous_root.parent)
                restore_skill_directories(
                    transaction,
                    "previous-project-rollback",
                    previous_root,
                    previous_project_skills,
                )

            legacy_project_skills = journal.get("legacy_project_skills", {})
            legacy_project_skills_root = journal.get(
                "legacy_project_skills_root"
            )
            if legacy_project_skills:
                if not isinstance(legacy_project_skills_root, str):
                    raise ConfigError(
                        "Interrupted transaction has invalid legacy_project_skills_root"
                    )
                legacy_project_root = Path(legacy_project_skills_root).resolve()
                ensure_no_links(
                    legacy_project_root, legacy_project_root.parent
                )
                restore_skill_directories(
                    transaction,
                    "legacy-project-rollback",
                    legacy_project_root,
                    legacy_project_skills,
                )

        elif operation == "capture":
            fragments = journal.get("fragments")
            if not isinstance(fragments, list) or not fragments:
                raise ConfigError("Interrupted capture has invalid fragments")
            fragment_paths: list[Path] = []
            for source in fragments:
                validate_relative_value(source, "transaction fragment")
                fragment = relative_path(repo_root, source)
                ensure_no_links(fragment, repo_root)
                fragment_paths.append(fragment)
            if not isinstance(journal.get("state_existed"), bool):
                raise ConfigError("Interrupted capture has invalid state_existed")
            ensure_no_links(repo_root / "manifest.json", repo_root)
            source_value = journal.get("skills_source_root")
            if source_value is None:
                source_repo = repo_root
            elif isinstance(source_value, str):
                source_repo = Path(source_value).resolve()
                allowed = {repo_root.resolve(), (repo_root.parent / "codex-skills").resolve()}
                if os.environ.get("CODEX_SKILLS_REPO"):
                    allowed.add(Path(os.environ["CODEX_SKILLS_REPO"]).expanduser().resolve())
                if source_repo not in allowed:
                    raise ConfigError("Interrupted capture names an unexpected skill repository")
            else:
                raise ConfigError("Interrupted capture has invalid skills_source_root")
            global_source_root = source_repo / "skills"
            project_source_root = (
                repo_root / ".agents" / "skills"
                if source_repo == repo_root else global_source_root
            )
            ensure_no_links(global_source_root, source_repo)
            ensure_no_links(project_source_root, source_repo if source_repo != repo_root else repo_root)
            for index, fragment in enumerate(fragment_paths):
                restore_optional_file(
                    fragment,
                    backups / "fragments" / f"{index}.bin",
                    True,
                )
            private_value = journal.get("private_manifest_path")
            if private_value is not None:
                if not isinstance(private_value, str):
                    raise ConfigError("Interrupted capture has invalid private manifest")
                private_target = Path(private_value).resolve()
                require_within(private_target, source_repo)
                saved_public = load_json(backups / "manifest.json")
                name = saved_public.get("private_manifest")
                if (
                    not isinstance(name, str)
                    or private_target != relative_path(source_repo, name).resolve()
                ):
                    raise ConfigError("Interrupted capture private path mismatch")
                restore_optional_file(
                    private_target, backups / "private-manifest.json", True
                )
            restore_optional_file(
                repo_root / "manifest.json", backups / "manifest.json", True
            )
            restore_optional_file(
                state_path(home),
                backups / "state.json",
                journal.get("state_existed") is True,
            )
            restore_skill_directories(
                transaction,
                "source-backup",
                global_source_root,
                skills,
            )
            if project_skills:
                restore_skill_directories(
                    transaction,
                    "project-source-backup",
                    project_source_root,
                    project_skills,
                )
        else:
            raise ConfigError(
                f"Interrupted transaction has invalid operation: {operation!r}"
            )
        # Cleanup may remove only part of a retained copy before failing. Once
        # every target is restored, retries must never use those backups again.
        journal["phase"] = "recovered"
        write_json(journal_path, journal)
        shutil.rmtree(transaction)



def mark_transaction_committed(transaction: Path) -> None:
    journal_path = transaction / "journal.json"
    journal = load_json(journal_path)
    if journal.get("schema_version") != 1 or journal.get("phase") != "prepared":
        raise ConfigError(f"Cannot commit invalid transaction: {transaction.name}")
    journal["phase"] = "committed"
    write_json(journal_path, journal)


def _collect_masked_input(read_char: Callable[[], str], output: TextIO) -> str:
    """Read a console line while echoing stars and supporting Backspace."""
    characters: list[str] = []
    while True:
        char = read_char()
        if not char:
            output.write("\r\n")
            output.flush()
            raise EOFError
        if char in ("\r", "\n"):
            output.write("\r\n")
            output.flush()
            return "".join(characters)
        if char in ("\b", "\x7f"):
            if characters:
                characters.pop()
                output.write("\b \b")
        elif char == "\x03":
            output.write("\r\n")
            output.flush()
            raise KeyboardInterrupt
        elif char == "\x1a":
            output.write("\r\n")
            output.flush()
            raise EOFError
        elif char in ("\x00", "\xe0"):
            read_char()  # Windows extended key; ignore its scan code.
        else:
            if len(char) != 1:
                raise ConfigError("Unexpected console input")
            if 0xD800 <= ord(char) <= 0xDBFF:
                low = read_char()
                if len(low) != 1 or not 0xDC00 <= ord(low) <= 0xDFFF:
                    raise ConfigError("Invalid Unicode input")
                char = chr(0x10000 + ((ord(char) - 0xD800) << 10) + ord(low) - 0xDC00)
            if char.isprintable():
                characters.append(char)
                output.write("*")
        output.flush()


def read_masked_passphrase(prompt: str) -> str:
    """Read one passphrase without printing its characters on the terminal."""
    if not sys.stdin.isatty():
        raise ConfigError("An interactive terminal is required for the passphrase")
    if os.name != "nt":
        return getpass.getpass(prompt)
    import msvcrt

    sys.stdout.write(prompt)
    sys.stdout.flush()
    return _collect_masked_input(msvcrt.getwch, sys.stdout)


class PassphraseSession:
    """Keep one interactive passphrase in memory for a complete transaction."""

    MAX_ATTEMPTS = 3

    def __init__(self) -> None:
        try:
            from pyrage import DecryptError, EncryptError, passphrase
        except ImportError as exc:
            raise ConfigError("pyrage is missing; install requirements.txt") from exc
        self._passphrase_module = passphrase
        self._decrypt_error = DecryptError
        self._encrypt_error = EncryptError
        self._value: str | None = None
        self._verified = False

    def _read(self) -> str:
        try:
            value = read_masked_passphrase("Enter age passphrase: ")
        except EOFError as exc:
            raise ConfigError("An interactive terminal is required for the passphrase") from exc
        except KeyboardInterrupt as exc:
            raise ConfigError("Passphrase entry cancelled") from exc
        return value

    def decrypt(self, encrypted: Path) -> bytes:
        """Decrypt a source, retrying only before the shared passphrase is verified."""
        ciphertext = encrypted.read_bytes()
        if not ciphertext.startswith(b"age-encryption.org/v1\n"):
            raise ConfigError(f"Encrypted source is not an age file: {encrypted}")
        for attempt in range(self.MAX_ATTEMPTS):
            if self._value is None:
                self._value = self._read()
            if not self._value:
                self._value = None
                if attempt + 1 == self.MAX_ATTEMPTS:
                    raise ConfigError("Incorrect passphrase after three attempts")
                print("Empty passphrase; try again.")
                continue
            try:
                plaintext = self._passphrase_module.decrypt(ciphertext, self._value)
            except self._decrypt_error as exc:
                if self._verified:
                    raise ConfigError(
                        f"The same passphrase cannot decrypt {encrypted}"
                    ) from exc
                self._value = None
                if attempt + 1 == self.MAX_ATTEMPTS:
                    raise ConfigError("Incorrect passphrase after three attempts") from exc
                print("Incorrect passphrase; try again.")
            else:
                self._verified = True
                return plaintext
        raise AssertionError("Passphrase retry loop did not finish")

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt with the phrase already validated against the source bundle."""
        if not self._verified or self._value is None:
            raise ConfigError("Verify the passphrase before encrypting access files")
        try:
            return self._passphrase_module.encrypt(plaintext, self._value)
        except self._encrypt_error as exc:
            raise ConfigError("Could not encrypt access file") from exc


def decrypt_file(session: PassphraseSession, encrypted: Path, destination: Path) -> None:
    """Write decrypted content only after the passphrase succeeds."""
    plaintext = session.decrypt(encrypted)
    destination.write_bytes(plaintext)


def encrypt_file(session: PassphraseSession, source: Path, destination: Path) -> None:
    """Write an age-compatible ciphertext with the transaction passphrase."""
    ciphertext = session.encrypt(source.read_bytes())
    destination.write_bytes(ciphertext)


def encrypted_entry(manifest: dict[str, Any], skill: str) -> dict[str, Any] | None:
    value = manifest.get("encrypted_files", {}).get(skill)
    return value if isinstance(value, dict) else None


def reusable_installed_secret(
    manifest: dict[str, Any],
    skills_root: Path,
    skill: str,
    fallback_skills_root: Path | None = None,
) -> Path | None:
    encrypted = encrypted_entry(manifest, skill)
    if encrypted is None:
        return None
    roots = [skills_root]
    if (
        fallback_skills_root is not None
        and fallback_skills_root.resolve() != skills_root.resolve()
    ):
        roots.append(fallback_skills_root)
    for root in roots:
        installed = relative_path(root / skill, encrypted["destination"])
        ensure_no_links(installed, root)
        if not installed.is_file() or is_link_like(installed):
            continue
        if sha256_file(installed) == encrypted["plaintext_sha256"].lower():
            return installed
    return None



def secret_requires_decryption(
    manifest: dict[str, Any],
    skills_root: Path,
    skill: str,
    fallback_skills_root: Path | None = None,
) -> bool:
    return (
        encrypted_entry(manifest, skill) is not None
        and reusable_installed_secret(
            manifest, skills_root, skill, fallback_skills_root
        )
        is None
    )



def stage_skill(
    repo_root: Path,
    skills_root: Path,
    manifest: dict[str, Any],
    skill: str,
    staging_root: Path,
    session: PassphraseSession | None,
    fallback_skills_root: Path | None = None,
) -> Path:
    source = skill_source_path(repo_root, skill)
    if not source.is_dir() or is_link_like(source):
        raise ConfigError(f"Missing or unsafe source skill: {skill}")
    staged = staging_root / "desired" / skill
    copy_source_skill(source, staged)
    encrypted = encrypted_entry(manifest, skill)
    if encrypted is None:
        return staged

    staged_secret = relative_path(staged, encrypted["destination"])
    expected_hash = encrypted["plaintext_sha256"].lower()
    reusable = reusable_installed_secret(
        manifest, skills_root, skill, fallback_skills_root
    )
    if reusable is not None:
        staged_secret.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(reusable, staged_secret)
        if sha256_file(staged_secret) != expected_hash:
            staged_secret.unlink(missing_ok=True)
            raise ConfigError(
                f"Installed access file changed while staging {skill}; retry install"
            )
        return staged

    cipher = encrypted_source_path(repo_root, encrypted["source"])
    if session is None:
        raise ConfigError(f"Passphrase session is required for {skill}")
    decrypt_file(session, cipher, staged_secret)
    if sha256_file(staged_secret) != expected_hash:
        staged_secret.unlink(missing_ok=True)
        raise ConfigError(f"Decrypted hash does not match manifest for {skill}")
    return staged


def stage_project_skill(
    repo_root: Path,
    skill: str,
    staging_root: Path,
) -> Path:
    source = skill_source_path(repo_root, skill, project_scoped=True)
    if not source.is_dir() or is_link_like(source):
        raise ConfigError(f"Missing or unsafe repository-scoped source skill: {skill}")
    staged = staging_root / "desired-project" / skill
    copy_source_skill(source, staged)
    return staged


def source_fingerprint(
    repo_root: Path,
    manifest: dict[str, Any],
    profile: str,
) -> str:
    config = profile_config(manifest, profile)
    source_repo = skills_repository_root(repo_root)
    paths: set[Path] = {repo_root / "manifest.json"}
    for group in ("global_fragments", "projects_fragments"):
        for item in config[group]:
            paths.add(relative_path(repo_root, item))
    for skill in config["skills"]:
        paths.update(iter_tree_files(skill_source_path(repo_root, skill)))
    for skill in config.get("project_skills", []):
        paths.update(iter_tree_files(
            skill_source_path(repo_root, skill, project_scoped=True)
        ))
    if source_repo != repo_root:
        paths.add(source_repo / "skills-manifest.json")
        private_name = manifest.get("private_manifest")
        if private_name is not None:
            paths.add(relative_path(source_repo, private_name))
    entries = []
    for path in paths:
        if path.is_relative_to(repo_root):
            relative = path.relative_to(repo_root).as_posix()
        else:
            relative = "codex-skills/" + path.relative_to(source_repo).as_posix()
        entries.append((relative, path))
    digest = hashlib.sha256()
    for relative, path in sorted(entries):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def source_revision(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "uncommitted"


def state_path(home: Path) -> Path:
    return home / "codex-config" / "state.json"


def validate_target_locations(
    home: Path,
    projects_root: Path,
    skills_root: Path,
    project_root: Path,
) -> None:
    for path in (
        home / "AGENTS.md",
        home / "codex-config",
    ):
        ensure_no_links(path, home)
    ensure_no_links(skills_root, skills_root.parent)
    ensure_no_links(projects_root / "AGENTS.md", projects_root)
    ensure_no_links(project_root / ".agents" / "skills", project_root)
    ensure_no_links(project_root / ".codex" / "skills", project_root)



def load_state(home: Path) -> dict[str, Any] | None:
    path = state_path(home)
    if is_link_like(path):
        raise ConfigError(f"State file must not be a link: {path}")
    if not path.exists():
        return None
    state = load_json(path)
    if state.get("schema_version") != 1:
        raise ConfigError("Unsupported installed state schema")
    if not isinstance(state.get("profile"), str):
        raise ConfigError("Installed state profile is invalid")
    skills = state.get("skills")
    if not isinstance(skills, dict):
        raise ConfigError("Installed state skills are invalid")
    for skill, entry in skills.items():
        validate_safe_name(skill, "state skill name")
        if not isinstance(entry, dict) or not isinstance(entry.get("files"), dict):
            raise ConfigError(f"Installed state entry is invalid: {skill}")
        for relative, digest in entry["files"].items():
            validate_relative_value(relative, f"state file path for {skill}")
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                raise ConfigError(
                    f"Installed state hash is invalid: {skill}/{relative}"
                )
    project_skills = state.get("project_skills", {})
    if not isinstance(project_skills, dict):
        raise ConfigError("Installed state project_skills are invalid")
    for skill, entry in project_skills.items():
        validate_safe_name(skill, "state project skill name")
        if not isinstance(entry, dict) or not isinstance(entry.get("files"), dict):
            raise ConfigError(f"Installed project skill entry is invalid: {skill}")
        for relative, digest in entry["files"].items():
            validate_relative_value(relative, f"state project file path for {skill}")
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                raise ConfigError(
                    f"Installed project skill hash is invalid: {skill}/{relative}"
                )
    for key in ("source_fingerprint", "global_block_sha256", "projects_block_sha256"):
        value = state.get(key)
        if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
            raise ConfigError(f"Installed state {key} is invalid")
    installed_skills_root = state.get("skills_root")
    if installed_skills_root is not None and not isinstance(installed_skills_root, str):
        raise ConfigError("Installed state skills_root is invalid")
    installed_project_skills_root = state.get("project_skills_root")
    if (
        installed_project_skills_root is not None
        and not isinstance(installed_project_skills_root, str)
    ):
        raise ConfigError("Installed state project_skills_root is invalid")
    return state


def load_install_state(home: Path) -> dict[str, Any] | None:
    """Read only safe ownership hints; install replaces malformed old state."""
    path = state_path(home)
    if is_link_like(path):
        raise ConfigError(f"State file must not be a link: {path}")
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"profile": None, "skills": {}}
    if not isinstance(value, dict):
        return {"profile": None, "skills": {}}

    safe_skills: dict[str, dict[str, Any]] = {}
    skills = value.get("skills")
    if isinstance(skills, dict):
        for skill in skills:
            try:
                safe_name = validate_safe_name(skill, "state skill name")
            except ConfigError:
                continue
            safe_skills[safe_name] = {}
    safe_project_skills: dict[str, dict[str, Any]] = {}
    project_skills = value.get("project_skills")
    if isinstance(project_skills, dict):
        for skill in project_skills:
            try:
                safe_name = validate_safe_name(skill, "state project skill name")
            except ConfigError:
                continue
            safe_project_skills[safe_name] = {}
    profile = value.get("profile")
    installed_skills_root = value.get("skills_root")
    installed_project_skills_root = value.get("project_skills_root")
    return {
        "profile": profile if isinstance(profile, str) else None,
        "skills": safe_skills,
        "skills_root": (
            installed_skills_root if isinstance(installed_skills_root, str) else None
        ),
        "project_skills": safe_project_skills,
        "project_skills_root": (
            installed_project_skills_root
            if isinstance(installed_project_skills_root, str)
            else None
        ),
    }


def state_skills_root(
    state: dict[str, Any] | None,
    home: Path,
    configured_skills_root: Path,
) -> Path:
    if not state:
        return configured_skills_root.resolve()
    legacy = (home / "skills").resolve()
    value = state.get("skills_root")
    if value is None:
        return legacy
    candidate = Path(value).resolve()
    configured = configured_skills_root.resolve()
    if candidate not in {legacy, configured}:
        raise ConfigError(
            "Installed skills root differs from the configured root; "
            "rerun with --skills-root matching the installed state"
        )
    return candidate


def resolve_project_root(args: argparse.Namespace, repo_root: Path) -> Path:
    configured = getattr(args, "project_root", None)
    return configured.resolve() if configured is not None else repo_root.parent.resolve()


def state_project_skills_root(
    state: dict[str, Any] | None,
    configured_project_skills_root: Path,
) -> Path:
    configured = configured_project_skills_root.resolve()
    if not state:
        return configured
    value = state.get("project_skills_root")
    if value is None:
        return configured
    candidate = Path(value).resolve()
    if candidate != configured:
        raise ConfigError(
            "Installed project skill root differs from the configured project root; "
            "rerun with --project-root matching the installed state"
        )
    return candidate


def current_block_hash(path: Path, begin: str, end: str) -> str | None:
    if not path.exists():
        return None
    block = locate_block(read_text(path), begin, end)
    return sha256_text(block[2]) if block else None


def check_target_unchanged(
    target: Path,
    previous_hashes: dict[str, str] | None,
    force: bool,
) -> None:
    if not target.exists():
        if is_link_like(target):
            raise ConfigError(f"Managed skill target is a link: {target}")
        if previous_hashes and not force:
            raise ConfigError(f"Managed skill was removed locally: {target.name}")
        return
    if is_link_like(target):
        raise ConfigError(f"Managed skill target is a link: {target}")
    current = tree_hashes(target)
    if previous_hashes is not None and current != previous_hashes and not force:
        raise ConfigError(
            f"Managed skill has local edits: {target.name}; run capture first"
        )


def install_command(args: argparse.Namespace) -> None:
    repo_root = args.repo.resolve()
    if not args.dry_run:
        ensure_skills_checkout(repo_root)
    home = args.home.resolve()
    projects_root = args.projects_root.resolve()
    skills_root = args.skills_root.resolve()
    project_root = resolve_project_root(args, repo_root)
    project_skills_root = project_root / ".agents" / "skills"
    legacy_project_skills_root = project_root / ".codex" / "skills"
    manifest = load_manifest(repo_root)
    validate_source(repo_root, manifest)
    validate_target_locations(
        home, projects_root, skills_root, project_root
    )
    config = profile_config(manifest, args.profile)
    previous = load_install_state(home)
    previous_profile = previous.get("profile") if previous else None
    previous_skills_root = state_skills_root(previous, home, skills_root)
    reusable_skills_root = (
        previous_skills_root if previous and previous.get("skills") else skills_root
    )
    previous_project_skills_root = state_project_skills_root(
        previous, project_skills_root
    )

    markers = manifest["markers"]
    global_block = render_fragment_block(
        repo_root,
        config["global_fragments"],
        markers["global_begin"],
        markers["global_end"],
    )
    projects_block = render_fragment_block(
        repo_root,
        config["projects_fragments"],
        markers["projects_begin"],
        markers["projects_end"],
    )
    global_path = home / "AGENTS.md"
    projects_path = projects_root / "AGENTS.md"
    current_global = read_text(global_path) if global_path.exists() else ""
    current_projects = read_text(projects_path) if projects_path.exists() else ""
    new_global = build_global_text(
        current_global,
        global_block,
        legacy_fragment_text(repo_root, config["global_fragments"]),
        markers["global_begin"],
        markers["global_end"],
        args.force,
    )
    new_projects = build_projects_text(
        current_projects,
        projects_block,
        legacy_fragment_text(repo_root, config["projects_fragments"]),
        markers["projects_begin"],
        markers["projects_end"],
        args.force,
    )

    previous_skills = previous.get("skills", {}) if previous else {}
    desired_names = list(config["skills"])
    owned_names = set(previous_skills) | configured_skill_names(manifest)
    replacement_names = sorted(owned_names | set(desired_names))
    stale_names = sorted(owned_names - set(desired_names))

    previous_project_skills = previous.get("project_skills", {}) if previous else {}
    desired_project_names = list(config.get("project_skills", []))
    owned_project_names = (
        set(previous_project_skills) | configured_project_skill_names(manifest)
    )
    replacement_project_names = sorted(
        owned_project_names | set(desired_project_names)
    )
    stale_project_names = sorted(
        owned_project_names - set(desired_project_names)
    )

    passphrase_names = [
        name
        for name in desired_names
        if secret_requires_decryption(
            manifest, skills_root, name, reusable_skills_root
        )
    ]
    reused_secret_names = [
        name
        for name in desired_names
        if encrypted_entry(manifest, name) is not None and name not in passphrase_names
    ]

    for skill in replacement_names:
        ensure_no_links(skills_root / skill, skills_root)
        if previous_skills_root != skills_root:
            ensure_no_links(previous_skills_root / skill, previous_skills_root)
    for skill in replacement_project_names:
        ensure_no_links(project_skills_root / skill, project_skills_root)
        ensure_no_links(
            previous_project_skills_root / skill, previous_project_skills_root
        )
        ensure_no_links(
            legacy_project_skills_root / skill, legacy_project_skills_root
        )

    if args.dry_run:
        print(
            json.dumps(
                {
                    "action": "install",
                    "profile": args.profile,
                    "previous_profile": previous_profile,
                    "global_agents_changed": canonical_text(current_global)
                    != canonical_text(new_global),
                    "projects_agents_changed": canonical_text(current_projects)
                    != canonical_text(new_projects),
                    "skills_root": str(skills_root),
                    "skills_install": desired_names,
                    "skills_remove": stale_names,
                    "project_root": str(project_root),
                    "project_skills_root": str(project_skills_root),
                    "project_skills_install": desired_project_names,
                    "project_skills_remove": stale_project_names,
                    "legacy_project_skills_remove": [
                        name
                        for name in replacement_project_names
                        if (legacy_project_skills_root / name).exists()
                    ],
                    "secrets_reused": reused_secret_names,
                    "secrets_require_passphrase": passphrase_names,
                },
                indent=2,
            )
        )
        return

    manager_root = home / "codex-config"
    restrict_private_directory(manager_root)
    staging_root = manager_root / f"txn-install-{uuid.uuid4().hex}"
    restrict_private_directory(staging_root)
    desired_staged: dict[str, Path] = {}
    desired_project_staged: dict[str, Path] = {}
    journal_written = False
    success = False
    try:
        session = PassphraseSession() if passphrase_names else None
        for skill in desired_names:
            desired_staged[skill] = stage_skill(
                repo_root,
                skills_root,
                manifest,
                skill,
                staging_root,
                session,
                reusable_skills_root,
            )
        for skill in desired_project_names:
            desired_project_staged[skill] = stage_project_skill(
                repo_root, skill, staging_root
            )

        backups = staging_root / "backups"
        global_existed = backup_optional_file(
            global_path, backups / "global-agents.bin"
        )
        projects_existed = backup_optional_file(
            projects_path, backups / "projects-agents.bin"
        )
        state_existed = backup_optional_file(state_path(home), backups / "state.json")
        skill_existence = {
            skill: (skills_root / skill).exists()
            for skill in replacement_names
        }
        legacy_skill_existence = (
            {
                skill: (previous_skills_root / skill).exists()
                for skill in replacement_names
            }
            if previous_skills_root != skills_root
            else {}
        )
        project_skill_existence = {
            skill: (project_skills_root / skill).exists()
            for skill in replacement_project_names
        }
        previous_project_skill_existence = (
            {
                skill: (previous_project_skills_root / skill).exists()
                for skill in replacement_project_names
            }
            if previous_project_skills_root != project_skills_root
            else {}
        )
        legacy_project_skill_existence = {
            skill: (legacy_project_skills_root / skill).exists()
            for skill in replacement_project_names
        }

        rollback_root = staging_root / "rollback"
        rollback_root.mkdir(parents=True, exist_ok=True)
        project_rollback_root = staging_root / "project-rollback"
        project_rollback_root.mkdir(parents=True, exist_ok=True)

        write_json(
            staging_root / "journal.json",
            {
                "schema_version": 1,
                "phase": "prepared",
                "operation": "install",
                "repo_root": str(repo_root),
                "home": str(home),
                "projects_root": str(projects_root),
                "project_root": str(project_root),
                "global_existed": global_existed,
                "projects_existed": projects_existed,
                "state_existed": state_existed,
                "skills_root": str(skills_root),
                "skills": skill_existence,
                "legacy_skills_root": (
                    str(previous_skills_root)
                    if previous_skills_root != skills_root
                    else None
                ),
                "legacy_skills": legacy_skill_existence,
                "project_skills_root": str(project_skills_root),
                "project_skills": project_skill_existence,
                "previous_project_skills_root": (
                    str(previous_project_skills_root)
                    if previous_project_skills_root != project_skills_root
                    else None
                ),
                "previous_project_skills": previous_project_skill_existence,
                "legacy_project_skills_root": str(legacy_project_skills_root),
                "legacy_project_skills": legacy_project_skill_existence,
            },
        )
        journal_written = True

        home.mkdir(parents=True, exist_ok=True)
        projects_root.mkdir(parents=True, exist_ok=True)
        project_root.mkdir(parents=True, exist_ok=True)
        atomic_write_text(global_path, new_global)
        atomic_write_text(projects_path, new_projects)

        skills_root.mkdir(parents=True, exist_ok=True)
        for skill in replacement_names:
            target = skills_root / skill
            if target.exists():
                transfer_directory(target, rollback_root / skill, staging_root)
            if skill in desired_staged:
                transfer_directory(desired_staged[skill], target, staging_root)

        if previous_skills_root != skills_root:
            legacy_rollback = staging_root / "legacy-rollback"
            legacy_rollback.mkdir(parents=True, exist_ok=True)
            for skill in replacement_names:
                legacy_target = previous_skills_root / skill
                if legacy_target.exists():
                    transfer_directory(
                        legacy_target, legacy_rollback / skill, staging_root
                    )

        project_skills_root.mkdir(parents=True, exist_ok=True)
        for skill in replacement_project_names:
            target = project_skills_root / skill
            if target.exists():
                transfer_directory(target, project_rollback_root / skill, staging_root)
            if skill in desired_project_staged:
                transfer_directory(desired_project_staged[skill], target, staging_root)

        if previous_project_skills_root != project_skills_root:
            previous_project_rollback = staging_root / "previous-project-rollback"
            previous_project_rollback.mkdir(parents=True, exist_ok=True)
            for skill in replacement_project_names:
                old_target = previous_project_skills_root / skill
                if old_target.exists():
                    transfer_directory(
                        old_target, previous_project_rollback / skill, staging_root
                    )

        legacy_project_rollback = staging_root / "legacy-project-rollback"
        legacy_project_rollback.mkdir(parents=True, exist_ok=True)
        for skill in replacement_project_names:
            legacy_target = legacy_project_skills_root / skill
            if legacy_target.exists():
                transfer_directory(
                    legacy_target, legacy_project_rollback / skill, staging_root
                )

        state = {
            "schema_version": 1,
            "profile": args.profile,
            "source_revision": source_revision(repo_root),
            "source_fingerprint": source_fingerprint(repo_root, manifest, args.profile),
            "global_block_sha256": sha256_text(global_block),
            "projects_block_sha256": sha256_text(projects_block),
            "skills_root": str(skills_root),
            "skills": {
                name: {"files": tree_hashes(skills_root / name)}
                for name in desired_names
            },
            "project_skills_root": str(project_skills_root),
            "project_skills": {
                name: {"files": tree_hashes(project_skills_root / name)}
                for name in desired_project_names
            },
        }
        write_json(state_path(home), state)
        mark_transaction_committed(staging_root)
        success = True
    except Exception:
        if journal_written:
            recover_transactions(
                manager_root, home, projects_root, repo_root, project_root
            )
        raise
    finally:
        if staging_root.exists() and (success or not journal_written):
            shutil.rmtree(staging_root)
    print(f"Installed codex-config profile '{args.profile}'")



def status_command(args: argparse.Namespace) -> None:
    repo_root = args.repo.resolve()
    home = args.home.resolve()
    projects_root = args.projects_root.resolve()
    skills_root = args.skills_root.resolve()
    project_root = resolve_project_root(args, repo_root)
    project_skills_root = project_root / ".agents" / "skills"
    manifest = load_manifest(repo_root)
    validate_source(repo_root, manifest)
    validate_target_locations(
        home, projects_root, skills_root, project_root
    )
    state = load_state(home)
    if not state:
        result: dict[str, Any] = {"installed": False}
        print(json.dumps(result, indent=2))
        raise SystemExit(1)
    profile = state["profile"]
    installed_skills_root = state_skills_root(state, home, skills_root)
    installed_project_skills_root = state_project_skills_root(
        state, project_skills_root
    )
    markers = manifest["markers"]
    skills = {
        name: tree_hashes(installed_skills_root / name) == entry.get("files", {})
        for name, entry in state.get("skills", {}).items()
    }
    project_skills = {
        name: tree_hashes(installed_project_skills_root / name)
        == entry.get("files", {})
        for name, entry in state.get("project_skills", {}).items()
    }
    result = {
        "installed": True,
        "profile": profile,
        "source_revision": state.get("source_revision"),
        "skills_root": str(installed_skills_root),
        "skills_location_current": installed_skills_root == skills_root,
        "project_root": str(project_root),
        "project_skills_root": str(installed_project_skills_root),
        "project_skills_location_current": (
            installed_project_skills_root == project_skills_root
        ),
        "source_in_sync": source_fingerprint(repo_root, manifest, profile)
        == state.get("source_fingerprint"),
        "global_agents_in_sync": current_block_hash(
            home / "AGENTS.md", markers["global_begin"], markers["global_end"]
        )
        == state.get("global_block_sha256"),
        "projects_agents_in_sync": current_block_hash(
            projects_root / "AGENTS.md",
            markers["projects_begin"],
            markers["projects_end"],
        )
        == state.get("projects_block_sha256"),
        "skills": skills,
        "project_skills": project_skills,
    }
    result["healthy"] = all(
        [
            result["source_in_sync"],
            result["global_agents_in_sync"],
            result["projects_agents_in_sync"],
            result["skills_location_current"],
            result["project_skills_location_current"],
            all(skills.values()),
            all(project_skills.values()),
        ]
    )
    print(json.dumps(result, indent=2))
    if not result["healthy"]:
        raise SystemExit(1)



def capture_command(args: argparse.Namespace) -> None:
    repo_root = args.repo.resolve()
    home = args.home.resolve()
    projects_root = args.projects_root.resolve()
    skills_root = args.skills_root.resolve()
    project_root = resolve_project_root(args, repo_root)
    project_skills_root = project_root / ".agents" / "skills"
    manifest = load_manifest(repo_root)
    validate_source(repo_root, manifest)
    validate_target_locations(
        home, projects_root, skills_root, project_root
    )
    state = load_state(home)
    if not state:
        raise ConfigError("codex-config is not installed")
    profile = state["profile"]
    installed_skills_root = state_skills_root(state, home, skills_root)
    installed_project_skills_root = state_project_skills_root(
        state, project_skills_root
    )
    config = profile_config(manifest, profile)
    markers = manifest["markers"]
    global_located = locate_block(
        read_text(home / "AGENTS.md"), markers["global_begin"], markers["global_end"]
    )
    projects_located = locate_block(
        read_text(projects_root / "AGENTS.md"),
        markers["projects_begin"],
        markers["projects_end"],
    )
    if not global_located or not projects_located:
        raise ConfigError("Installed managed instruction blocks are incomplete")
    fragments = parse_fragment_block(
        global_located[2], markers["global_begin"], markers["global_end"]
    )
    project_fragments = parse_fragment_block(
        projects_located[2], markers["projects_begin"], markers["projects_end"]
    )
    expected_fragments = set(config["global_fragments"] + config["projects_fragments"])
    if set(fragments) != set(config["global_fragments"]):
        raise ConfigError(
            "Installed global source markers do not match the active profile"
        )
    if set(project_fragments) != set(config["projects_fragments"]):
        raise ConfigError(
            "Installed Projects source markers do not match the active profile"
        )
    if set(fragments) | set(project_fragments) != expected_fragments:
        raise ConfigError("Installed source markers do not match the active profile")

    changed_secrets: list[str] = []
    for skill in config["skills"]:
        encrypted = encrypted_entry(manifest, skill)
        if encrypted is None:
            continue
        raw = relative_path(installed_skills_root / skill, encrypted["destination"])
        ensure_no_links(raw, installed_skills_root)
        if not raw.is_file() or is_link_like(raw):
            raise ConfigError(f"Installed access file is missing or unsafe: {skill}")
        if sha256_file(raw) != encrypted["plaintext_sha256"].lower():
            changed_secrets.append(skill)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "action": "capture",
                    "profile": profile,
                    "instruction_fragments": sorted(expected_fragments),
                    "skills": list(config["skills"]),
                    "project_skills": list(config.get("project_skills", [])),
                    "secrets_to_encrypt": changed_secrets,
                },
                indent=2,
            )
        )
        return

    manager_root = home / "codex-config"
    restrict_private_directory(manager_root)
    staging_root = manager_root / f"txn-capture-{uuid.uuid4().hex}"
    restrict_private_directory(staging_root)
    staged_skills: dict[str, Path] = {}
    staged_project_skills: dict[str, Path] = {}
    manifest_path = repo_root / "manifest.json"
    public_manifest = load_json(manifest_path)
    private_name = manifest.get("private_manifest")
    private_manifest_path = (
        relative_path(skills_repository_root(repo_root), private_name)
        if private_name else None
    )

    journal_written = False
    success = False
    try:
        for skill in config["skills"]:
            installed_root = installed_skills_root / skill
            if not installed_root.is_dir() or is_link_like(installed_root):
                raise ConfigError(f"Installed skill is missing or unsafe: {skill}")
            encrypted = encrypted_entry(manifest, skill)
            staged = staging_root / "captured" / skill
            copy_installed_skill_for_capture(
                installed_root,
                staged,
                encrypted["destination"] if encrypted is not None else None,
            )
            staged_skills[skill] = staged
            if encrypted:
                source_root = skill_source_path(repo_root, skill)
                cipher = encrypted_source_path(repo_root, encrypted["source"])
                try:
                    cipher_relative = cipher.relative_to(source_root)
                except ValueError as exc:
                    raise ConfigError(
                        f"Encrypted source must be inside its skill: {skill}"
                    ) from exc
                staged_cipher = staged / cipher_relative
                staged_cipher.parent.mkdir(parents=True, exist_ok=True)
                if skill not in changed_secrets:
                    shutil.copy2(cipher, staged_cipher)

        for skill in config.get("project_skills", []):
            installed_root = installed_project_skills_root / skill
            if not installed_root.is_dir() or is_link_like(installed_root):
                raise ConfigError(
                    f"Installed repository-scoped skill is missing or unsafe: {skill}"
                )
            staged = staging_root / "captured-project" / skill
            copy_installed_skill_for_capture(installed_root, staged, None)
            staged_project_skills[skill] = staged
    except Exception:
        if staging_root.exists():
            shutil.rmtree(staging_root)
        raise

    try:
        if changed_secrets:
            session = PassphraseSession()
            for skill in config["skills"]:
                encrypted = encrypted_entry(manifest, skill)
                if encrypted is None:
                    continue
                cipher = encrypted_source_path(repo_root, encrypted["source"])
                plaintext = session.decrypt(cipher)
                if sha256_bytes(plaintext) != encrypted["plaintext_sha256"].lower():
                    raise ConfigError(
                        f"Decrypted hash does not match manifest for {skill}"
                    )
            for skill in changed_secrets:
                encrypted = encrypted_entry(manifest, skill)
                if encrypted is None:
                    raise ConfigError(f"Missing encrypted file metadata: {skill}")
                raw = relative_path(
                    installed_skills_root / skill, encrypted["destination"]
                )
                source_root = skill_source_path(repo_root, skill)
                cipher = encrypted_source_path(repo_root, encrypted["source"])
                staged_cipher = staged_skills[skill] / cipher.relative_to(source_root)
                encrypt_file(session, raw, staged_cipher)
                encrypted["plaintext_sha256"] = sha256_file(raw)

        backups = staging_root / "backups"
        fragment_names = sorted(expected_fragments)
        for index, source in enumerate(fragment_names):
            backup_optional_file(
                relative_path(repo_root, source),
                backups / "fragments" / f"{index}.bin",
            )
        backup_optional_file(manifest_path, backups / "manifest.json")
        if private_manifest_path is not None:
            if not private_manifest_path.is_file():
                raise ConfigError(f"Private metadata is missing: {private_manifest_path}")
            backup_optional_file(
                private_manifest_path, backups / "private-manifest.json"
            )
        state_existed = backup_optional_file(state_path(home), backups / "state.json")
        backup_root = staging_root / "source-backup"
        backup_root.mkdir(parents=True, exist_ok=True)
        project_backup_root = staging_root / "project-source-backup"
        project_backup_root.mkdir(parents=True, exist_ok=True)
        write_json(
            staging_root / "journal.json",
            {
                "schema_version": 1,
                "phase": "prepared",
                "operation": "capture",
                "repo_root": str(repo_root),
                "skills_source_root": str(skills_repository_root(repo_root)),
                "private_manifest_path": (
                    str(private_manifest_path)
                    if private_manifest_path is not None else None
                ),
                "home": str(home),
                "projects_root": str(projects_root),
                "project_root": str(project_root),
                "state_existed": state_existed,
                "fragments": fragment_names,
                "skills": {skill: True for skill in config["skills"]},
                "project_skills": {
                    skill: True for skill in config.get("project_skills", [])
                },
            },
        )
        journal_written = True

        for source, value in {**fragments, **project_fragments}.items():
            atomic_write_text(relative_path(repo_root, source), value)
        for skill, staged in staged_skills.items():
            source_root = skill_source_path(repo_root, skill)
            backup = backup_root / skill
            transfer_directory(source_root, backup, staging_root)
            transfer_directory(staged, source_root, staging_root)
        for skill, staged in staged_project_skills.items():
            source_root = skill_source_path(repo_root, skill, project_scoped=True)
            backup = project_backup_root / skill
            transfer_directory(source_root, backup, staging_root)
            transfer_directory(staged, source_root, staging_root)

        if private_manifest_path is not None:
            secret_metadata = load_json(private_manifest_path)
            secret_metadata["encrypted_files"] = manifest["encrypted_files"]
            secret_metadata["skill_policy"] = manifest.get("skill_policy", {})
            write_json(private_manifest_path, secret_metadata)
            # Never write private hashes or policy data into the public manifest.
            write_json(manifest_path, public_manifest)
        else:
            write_json(manifest_path, manifest)
        validate_source(repo_root, manifest)
        refreshed = load_manifest(repo_root)
        state.update(
            {
                "source_revision": source_revision(repo_root),
                "source_fingerprint": source_fingerprint(repo_root, refreshed, profile),
                "global_block_sha256": sha256_text(global_located[2]),
                "projects_block_sha256": sha256_text(projects_located[2]),
                "skills_root": str(installed_skills_root),
                "skills": {
                    name: {"files": tree_hashes(installed_skills_root / name)}
                    for name in config["skills"]
                },
                "project_skills_root": str(installed_project_skills_root),
                "project_skills": {
                    name: {
                        "files": tree_hashes(installed_project_skills_root / name)
                    }
                    for name in config.get("project_skills", [])
                },
            }
        )
        write_json(state_path(home), state)
        mark_transaction_committed(staging_root)
        success = True
    except Exception:
        if journal_written:
            recover_transactions(
                manager_root, home, projects_root, repo_root, project_root
            )
        raise
    finally:
        if staging_root.exists() and (success or not journal_written):
            shutil.rmtree(staging_root)
    print(f"Captured installed profile '{profile}' into the repository")



def remove_block(text: str, begin: str, end: str) -> str:
    located = locate_block(text, begin, end)
    if not located:
        return canonical_text(text) if text.strip() else ""
    start, stop, _ = located
    return join_sections(text[:start], text[stop:])


def remove_command(args: argparse.Namespace) -> None:
    repo_root = args.repo.resolve()
    home = args.home.resolve()
    projects_root = args.projects_root.resolve()
    skills_root = args.skills_root.resolve()
    project_root = resolve_project_root(args, repo_root)
    project_skills_root = project_root / ".agents" / "skills"
    manifest = load_manifest(repo_root)
    validate_target_locations(
        home, projects_root, skills_root, project_root
    )
    state = load_state(home)
    if not state:
        print("codex-config is not installed")
        return
    installed_skills_root = state_skills_root(state, home, skills_root)
    installed_project_skills_root = state_project_skills_root(
        state, project_skills_root
    )
    markers = manifest["markers"]
    global_path = home / "AGENTS.md"
    projects_path = projects_root / "AGENTS.md"
    if not args.force:
        if current_block_hash(
            global_path, markers["global_begin"], markers["global_end"]
        ) != state.get("global_block_sha256"):
            raise ConfigError(
                "The installed global Codex block has local edits; run capture first"
            )
        if current_block_hash(
            projects_path, markers["projects_begin"], markers["projects_end"]
        ) != state.get("projects_block_sha256"):
            raise ConfigError(
                "The installed Projects AGENTS block has local edits; run capture first"
            )
        for skill, entry in state.get("skills", {}).items():
            check_target_unchanged(
                installed_skills_root / skill, entry.get("files"), False
            )
        for skill, entry in state.get("project_skills", {}).items():
            check_target_unchanged(
                installed_project_skills_root / skill, entry.get("files"), False
            )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "action": "remove",
                    "profile": state["profile"],
                    "skills_root": str(installed_skills_root),
                    "skills": sorted(state.get("skills", {})),
                    "project_skills_root": str(installed_project_skills_root),
                    "project_skills": sorted(state.get("project_skills", {})),
                },
                indent=2,
            )
        )
        return

    manager_root = home / "codex-config"
    restrict_private_directory(manager_root)
    staging_root = manager_root / f"txn-remove-{uuid.uuid4().hex}"
    restrict_private_directory(staging_root)
    journal_written = False
    success = False
    try:
        backups = staging_root / "backups"
        global_existed = backup_optional_file(
            global_path, backups / "global-agents.bin"
        )
        projects_existed = backup_optional_file(
            projects_path, backups / "projects-agents.bin"
        )
        state_existed = backup_optional_file(state_path(home), backups / "state.json")
        skill_existence = {
            skill: (installed_skills_root / skill).exists()
            for skill in state.get("skills", {})
        }
        project_skill_existence = {
            skill: (installed_project_skills_root / skill).exists()
            for skill in state.get("project_skills", {})
        }
        write_json(
            staging_root / "journal.json",
            {
                "schema_version": 1,
                "phase": "prepared",
                "operation": "remove",
                "repo_root": str(repo_root),
                "home": str(home),
                "projects_root": str(projects_root),
                "project_root": str(project_root),
                "global_existed": global_existed,
                "projects_existed": projects_existed,
                "state_existed": state_existed,
                "skills_root": str(installed_skills_root),
                "skills": skill_existence,
                "project_skills_root": str(installed_project_skills_root),
                "project_skills": project_skill_existence,
            },
        )
        journal_written = True
        for skill in state.get("skills", {}):
            target = installed_skills_root / skill
            require_within(target, installed_skills_root)
            if target.exists():
                backup = staging_root / "skills" / skill
                backup.parent.mkdir(parents=True, exist_ok=True)
                transfer_directory(target, backup, staging_root)
        for skill in state.get("project_skills", {}):
            target = installed_project_skills_root / skill
            require_within(target, installed_project_skills_root)
            if target.exists():
                backup = staging_root / "project-skills" / skill
                backup.parent.mkdir(parents=True, exist_ok=True)
                transfer_directory(target, backup, staging_root)
        new_global = remove_block(
            read_text(global_path) if global_path.exists() else "",
            markers["global_begin"],
            markers["global_end"],
        )
        new_projects = remove_block(
            read_text(projects_path) if projects_path.exists() else "",
            markers["projects_begin"],
            markers["projects_end"],
        )
        if new_global:
            atomic_write_text(global_path, new_global)
        else:
            global_path.unlink(missing_ok=True)
        if new_projects:
            atomic_write_text(projects_path, new_projects)
        else:
            projects_path.unlink(missing_ok=True)
        state_path(home).unlink(missing_ok=True)
        mark_transaction_committed(staging_root)
        success = True
    except Exception:
        if journal_written:
            recover_transactions(
                manager_root, home, projects_root, repo_root, project_root
            )
        raise
    finally:
        if staging_root.exists() and (success or not journal_written):
            shutil.rmtree(staging_root)
    if manager_root.exists() and not any(manager_root.iterdir()):
        manager_root.rmdir()
    print("Removed codex-config managed content")



def validate_source(repo_root: Path, manifest: dict[str, Any]) -> None:
    markers = manifest["markers"]
    marker_values = list(markers.values())
    if len(marker_values) != len(set(marker_values)):
        raise ConfigError("Managed markers must be unique")
    all_skills: set[str] = set()
    all_project_skills: set[str] = set()
    for name, config in manifest["profiles"].items():
        if not isinstance(config, dict):
            raise ConfigError(f"Invalid profile: {name}")
        for group in ("global_fragments", "projects_fragments"):
            values = config.get(group)
            if not isinstance(values, list) or not values:
                raise ConfigError(f"Profile {name} has no {group}")
            for item in values:
                path = relative_path(repo_root, item)
                ensure_no_links(path, repo_root)
                if not path.is_file() or is_link_like(path):
                    raise ConfigError(f"Missing or unsafe source file: {item}")
                content = read_text(path)
                if ROUTING_BEGIN in content or ROUTING_END in content:
                    raise ConfigError(
                        f"Base instructions must not contain routing markers: {item}"
                    )
        skills = config.get("skills")
        if not isinstance(skills, list):
            raise ConfigError(f"Profile {name} has invalid skills")
        all_skills.update(skills)
        project_skills = config.get("project_skills", [])
        if not isinstance(project_skills, list):
            raise ConfigError(f"Profile {name} has invalid project_skills")
        all_project_skills.update(project_skills)

    source_repo = (
        skills_repository_root(repo_root)
        if (all_skills or all_project_skills)
        else repo_root
    )
    if source_repo != repo_root:
        catalog = load_json(source_repo / "skills-manifest.json")
        declared = set(catalog["skills"])
        missing = (all_skills | all_project_skills) - declared
        if missing:
            raise ConfigError(
                f"codex-skills catalog omits configured skills: {sorted(missing)}"
            )

    for skill in sorted(all_skills):
        source = skill_source_path(repo_root, skill)
        if not source.is_dir() or is_link_like(source):
            raise ConfigError(f"Missing or unsafe source skill: {skill}")
        if not (source / "SKILL.md").is_file():
            raise ConfigError(f"Skill has no SKILL.md: {skill}")
        if (source / "access.yml").exists():
            raise ConfigError(
                f"Plaintext access.yml is forbidden in the repository: {skill}"
            )

    for skill in sorted(all_project_skills):
        source = skill_source_path(repo_root, skill, project_scoped=True)
        if not source.is_dir() or is_link_like(source):
            raise ConfigError(
                f"Missing or unsafe repository-scoped source skill: {skill}"
            )
        if not (source / "SKILL.md").is_file():
            raise ConfigError(f"Repository-scoped skill has no SKILL.md: {skill}")
        if (source / "access.yml").exists():
            raise ConfigError(
                f"Plaintext access.yml is forbidden in repository-scoped skill: {skill}"
            )

    for skill, encrypted in manifest.get("encrypted_files", {}).items():
        if skill not in all_skills:
            raise ConfigError(f"Encrypted file belongs to an unmanaged skill: {skill}")
        cipher = encrypted_source_path(repo_root, encrypted["source"])
        source_root = skill_source_path(repo_root, skill)
        try:
            cipher.relative_to(source_root)
        except ValueError as exc:
            raise ConfigError(
                f"Encrypted source must be inside its skill: {skill}"
            ) from exc
        ensure_no_links(cipher, source_repo)
        if not cipher.is_file() or is_link_like(cipher):
            raise ConfigError(f"Encrypted source is missing or unsafe: {cipher}")
        with cipher.open("rb") as handle:
            if handle.readline().strip() != b"age-encryption.org/v1":
                raise ConfigError(f"Encrypted source is not an age file: {cipher}")



def validate_command(args: argparse.Namespace) -> None:
    repo_root = args.repo.resolve()
    manifest = load_manifest(repo_root, base_only=args.base_only)
    if args.base_only:
        base = dict(manifest)
        base["profiles"] = {
            name: {**config, "skills": [], "project_skills": []}
            for name, config in manifest["profiles"].items()
        }
        base["encrypted_files"] = {}
        validate_source(repo_root, base)
        print("Base source validation passed (private skills source omitted)")
        return
    validate_source(repo_root, manifest)
    print("Source validation passed")


def update_command(args: argparse.Namespace) -> None:
    repo_root = args.repo.resolve()
    if not args.dry_run:
        ensure_skills_checkout(repo_root)
    skill_repo = skills_repository_root(repo_root)
    repositories = [repo_root]
    if skill_repo != repo_root:
        repositories.append(skill_repo)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "action": "update",
                    "repository_fetch": [str(path) for path in repositories],
                    "repository_pull": [
                        f"would run git pull --ff-only in {path}"
                        for path in repositories
                    ],
                },
                indent=2,
            )
        )
        install_command(args)
        return

    # Fetch each checkout first. A failed fetch must not be mistaken for an
    # up-to-date remote, and no worktree mutation should occur before both
    # repositories are confirmed reachable and clean.
    for checkout in repositories:
        subprocess.run(
            ["git", "-C", str(checkout), "fetch"],
            check=True,
        )
    for checkout in repositories:
        status = subprocess.run(
            ["git", "-C", str(checkout), "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        if status.returncode != 0:
            raise ConfigError(f"Repository is not a Git checkout: {checkout}")
        if status.stdout.strip():
            raise ConfigError(
                f"Repository has local changes; commit or discard them before update: {checkout}"
            )
    for checkout in repositories:
        subprocess.run(
            ["git", "-C", str(checkout), "pull", "--ff-only"], check=True
        )
    install_command(args)



def default_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured) if configured else Path.home() / ".codex"


def default_skills_root() -> Path:
    return Path.home() / ".agents" / "skills"


def add_location_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    parser.add_argument("--home", type=Path, default=default_codex_home())
    parser.add_argument("--projects-root", type=Path, default=Path.home() / "Projects")
    parser.add_argument("--skills-root", type=Path, default=default_skills_root())
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Target repository for repository-scoped skills; defaults to repo parent",
    )


def add_install_arguments(parser: argparse.ArgumentParser) -> None:
    add_location_arguments(parser)
    parser.add_argument("--profile", "-Profile", required=True)
    parser.add_argument("--dry-run", "-DryRun", action="store_true")
    parser.add_argument("--force", "-Force", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser("install")
    add_install_arguments(install)
    install.set_defaults(handler=install_command)

    status = subparsers.add_parser("status")
    add_location_arguments(status)
    status.set_defaults(handler=status_command)

    capture = subparsers.add_parser("capture")
    add_location_arguments(capture)
    capture.add_argument("--dry-run", "-DryRun", action="store_true")
    capture.set_defaults(handler=capture_command)

    remove = subparsers.add_parser("remove")
    add_location_arguments(remove)
    remove.add_argument("--dry-run", "-DryRun", action="store_true")
    remove.add_argument("--force", "-Force", action="store_true")
    remove.set_defaults(handler=remove_command)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--repo", type=Path, default=REPO_ROOT)
    validate.add_argument("--base-only", "-BaseOnly", action="store_true")
    validate.set_defaults(handler=validate_command)

    update = subparsers.add_parser("update")
    add_install_arguments(update)
    update.set_defaults(handler=update_command)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "validate":
            args.handler(args)
            return 0

        repo_root = args.repo.resolve()
        home = args.home.resolve()
        projects_root = args.projects_root.resolve()
        skills_root = args.skills_root.resolve()
        project_root = resolve_project_root(args, repo_root)
        manager_root = home / "codex-config"
        dry_run = bool(getattr(args, "dry_run", False))
        if dry_run:
            if manager_root.exists():
                ensure_no_links(manager_root, home)
                interrupted = list(manager_root.glob("txn-*"))
                if interrupted:
                    raise ConfigError(
                        "An interrupted transaction must be recovered before dry-run"
                    )
            args.handler(args)
            return 0

        if args.command == "status" and not manager_root.exists():
            args.handler(args)
            return 0

        validate_target_locations(
            home, projects_root, skills_root, project_root
        )
        restrict_private_directory(manager_root)
        with ManagerLock(manager_root):
            recover_transactions(
                manager_root, home, projects_root, repo_root, project_root
            )
            args.handler(args)
        return 0
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"error: command failed with exit code {exc.returncode}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
