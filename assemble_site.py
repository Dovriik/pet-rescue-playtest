"""Verify a public playtest bundle and reconstruct its unmodified Godot runtime."""
from pathlib import Path
import hashlib
import json
import shutil


def checked_path(root, name):
    if not isinstance(name, str) or Path(name).name != name or name in {"", ".", ".."} or "\\" in name:
        raise ValueError("Bundle entries must be flat filenames")
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing regular bundle file: {name}")
    return path


def verified_bytes(root, entry):
    data = checked_path(root, entry["path"]).read_bytes()
    if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise ValueError(f"Bundle integrity mismatch: {entry['path']}")
    return data


def assemble(root, output):
    manifest = json.loads(checked_path(root, "playtest-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 1 or manifest.get("levelCount") != 50:
        raise ValueError("Expected the reviewed fifty-level playtest")
    allowed = {"index.html", "index.js", "index.pck", "index.png", "index.audio.worklet.js", "index.audio.position.worklet.js", "README.md", "NOTICE.md", "GODOT_NOTICES.txt", ".nojekyll"}
    paths = [entry["path"] for entry in manifest["files"]]
    if len(paths) != len(set(paths)) or not set(paths).issubset(allowed) or not {"index.html", "index.js", "index.pck", "NOTICE.md", "GODOT_NOTICES.txt", ".nojekyll"}.issubset(paths):
        raise ValueError("Public bundle contains unexpected or missing files")
    wasm = manifest["wasm"]
    if wasm["path"] != "index.wasm" or not wasm["parts"]:
        raise ValueError("Unexpected runtime layout")
    parts = []
    for index, part in enumerate(wasm["parts"]):
        if part["path"] != f"index.wasm.part-{index:03d}":
            raise ValueError("Unexpected runtime part order")
        parts.append(verified_bytes(root, part))
    runtime = b"".join(parts)
    if len(runtime) != wasm["size"] or hashlib.sha256(runtime).hexdigest() != wasm["sha256"]:
        raise ValueError("Reconstructed runtime is not the original export")
    files = [(entry["path"], verified_bytes(root, entry)) for entry in manifest["files"]]
    if output.exists() and any(output.iterdir()):
        raise ValueError("Site destination must be empty")
    output.mkdir(parents=True, exist_ok=True)
    for name, data in files:
        (output / name).write_bytes(data)
    (output / "index.wasm").write_bytes(runtime)
    shutil.copyfile(root / "playtest-manifest.json", output / "playtest-manifest.json")
    print(f"Verified {len(files)} public files and original runtime; {manifest['levelCount']} levels")


if __name__ == "__main__":
    assemble(Path.cwd(), Path("_site"))

