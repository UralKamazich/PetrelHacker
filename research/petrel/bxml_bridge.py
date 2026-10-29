from __future__ import annotations

from pathlib import Path
import os
import subprocess


PERSISTENCE_DLL = "Slb.Ocean.Petrel.Data.Persistence.dll"


def find_petrel_persistence_assembly(petrel_home: str | Path | None = None) -> Path | None:
    if petrel_home:
        candidate = Path(petrel_home) / "Public" / PERSISTENCE_DLL
        return candidate if candidate.is_file() else None

    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    root = program_files / "Schlumberger"
    if not root.is_dir():
        return None
    candidates = sorted(
        root.glob(f"Petrel */Public/{PERSISTENCE_DLL}"),
        key=lambda item: item.parent.parent.name,
        reverse=True,
    )
    return candidates[0] if candidates else None


def ensure_bxml_bridge(
    output_path: str | Path,
    *,
    source_path: str | Path | None = None,
) -> Path:
    destination = Path(output_path).resolve()
    source = Path(source_path).resolve() if source_path else Path(__file__).resolve().parent / "PetrelBxmlBridge.cs"
    if destination.is_file() and destination.stat().st_mtime_ns >= source.stat().st_mtime_ns:
        return destination

    compiler = _find_csharp_compiler()
    if compiler is None:
        raise FileNotFoundError(".NET Framework C# compiler was not found")
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(compiler),
        "/nologo",
        "/optimize+",
        "/target:exe",
        f"/out:{destination}",
        "/reference:System.Runtime.Serialization.dll",
        str(source),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_no_window_flag(),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Cannot compile Petrel BXML bridge:\n{result.stdout}\n{result.stderr}")
    return destination


def convert_bxml_to_xml(
    input_path: str | Path,
    output_path: str | Path,
    *,
    bridge_path: str | Path,
    persistence_assembly: str | Path,
) -> None:
    command = [
        str(Path(bridge_path).resolve()),
        str(Path(persistence_assembly).resolve()),
        str(Path(input_path).resolve()),
        str(Path(output_path).resolve()),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_no_window_flag(),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Cannot decode Petrel BXML:\n{result.stdout}\n{result.stderr}")


def convert_bxml_batch(
    files: list[tuple[str | Path, str | Path]],
    *,
    manifest_path: str | Path,
    bridge_path: str | Path,
    persistence_assembly: str | Path,
) -> None:
    manifest = Path(manifest_path).resolve()
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        "".join(f"{Path(source).resolve()}\t{Path(target).resolve()}\n" for source, target in files),
        encoding="utf-8",
    )
    command = [
        str(Path(bridge_path).resolve()),
        "--batch",
        str(Path(persistence_assembly).resolve()),
        str(manifest),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_no_window_flag(),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Cannot decode Petrel BXML batch:\n{result.stdout}\n{result.stderr}")


def profile_bxml_to_tsv(
    input_path: str | Path,
    output_path: str | Path,
    *,
    bridge_path: str | Path,
    persistence_assembly: str | Path,
) -> None:
    command = [
        str(Path(bridge_path).resolve()),
        "--profile",
        str(Path(persistence_assembly).resolve()),
        str(Path(input_path).resolve()),
        str(Path(output_path).resolve()),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_no_window_flag(),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Cannot profile Petrel BXML:\n{result.stdout}\n{result.stderr}")


def _find_csharp_compiler() -> Path | None:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    candidates = [
        windows / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe",
        windows / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe",
    ]
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _no_window_flag() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)
