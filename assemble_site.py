"""Verify a public playtest bundle and reconstruct its unmodified Godot runtime."""
from pathlib import Path
import hashlib
import io
import json
import shutil
import tempfile
import urllib.request
import zipfile

ENGINE_URL = "https://github.com/godotengine/godot-builds/releases/download/4.7.2-stable/Godot_v4.7.2-stable_export_templates.tpz"
ENGINE_ARCHIVE_SHA256 = "f298490b8d44d934be425a5a65a51bf15f422428b229a06a6e11d9ffea248011"
ENGINE_WASM_SHA256 = "fc74679e3b97f76878947fcd4fbe1268cbfa6188182a2e33bbc3f5dc9bfa57d0"


def supply_official_runtime(root, wasm):
    """Use the verified vendor runtime if GitHub transport omitted binary parts."""
    if wasm["sha256"] != ENGINE_WASM_SHA256:
        raise ValueError("Only the independently verified pinned engine is supported")
    for index, part in enumerate(wasm["parts"]):
        if part["path"] != f"index.wasm.part-{index:03d}" or type(part["size"]) is not int or part["size"] <= 0:
            raise ValueError("Unexpected runtime part layout")
        destination = root / part["path"]
        if destination.is_symlink() or (destination.exists() and not destination.is_file()):
            raise ValueError("Runtime parts must be regular checkout files")
    cache_directory = root / ".engine-cache"
    cached = cache_directory / "godot.wasm"
    if cache_directory.is_symlink() or cached.is_symlink():
        raise ValueError("Runtime cache must not redirect outside the checkout")
    raw = cached.read_bytes() if cached.is_file() else b""
    if hashlib.sha256(raw).hexdigest() != ENGINE_WASM_SHA256:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "templates.tpz"
            digest = hashlib.sha256()
            with urllib.request.urlopen(ENGINE_URL, timeout=120) as response, archive.open("wb") as output:
                while block := response.read(1024 * 1024):
                    digest.update(block)
                    output.write(block)
            if digest.hexdigest() != ENGINE_ARCHIVE_SHA256:
                raise ValueError("Official engine archive checksum mismatch")
            with zipfile.ZipFile(archive) as outer:
                inner = outer.read("templates/web_nothreads_release.zip")
            with zipfile.ZipFile(io.BytesIO(inner)) as template:
                raw = template.read("godot.wasm")
        if hashlib.sha256(raw).hexdigest() != ENGINE_WASM_SHA256:
            raise ValueError("Official runtime does not match the tested export")
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(raw)
    offset = 0
    for part in wasm["parts"]:
        data = raw[offset:offset + part["size"]]
        if hashlib.sha256(data).hexdigest() != part["sha256"]:
            raise ValueError("Official engine part differs from tested bundle")
        (root / part["path"]).write_bytes(data)
        offset += part["size"]
    if offset != len(raw):
        raise ValueError("Unexpected runtime size")


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
    if any(not (root / part["path"]).is_file() for part in wasm["parts"]):
        supply_official_runtime(root, wasm)
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
