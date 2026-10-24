"""Fetch only pinned Three.js runtime files, verify npm SHA-512 integrity."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request

VERSION = "0.180.0"
ROOT = Path(__file__).resolve().parents[1]
FILES = {"build/three.module.js": "three.module.js", "build/three.core.js": "three.core.js", "LICENSE": "LICENSE.txt",
         **{f"examples/jsm/{p}": f"addons/{p}" for p in ("controls/OrbitControls.js", "loaders/OBJLoader.js", "loaders/GLTFLoader.js", "loaders/TGALoader.js", "loaders/DDSLoader.js", "utils/BufferGeometryUtils.js")}}


def main():
    meta = json.load(urllib.request.urlopen(f"https://registry.npmjs.org/three/{VERSION}", timeout=40))
    data = urllib.request.urlopen(meta["dist"]["tarball"], timeout=90).read()
    expected = meta["dist"]["integrity"]
    actual = "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()
    if actual != expected:
        raise ValueError("npm tarball integrity mismatch")
    root = ROOT / "web/vendor"
    root.mkdir(parents=True, exist_ok=True)
    hashes = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for source, target in FILES.items():
            member = archive.getmember("package/" + source)
            if not member.isfile():
                raise ValueError("Unexpected non-file vendor member")
            content = archive.extractfile(member).read()
            path = root / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            hashes[target] = hashlib.sha256(content).hexdigest()
    (root / "provenance.json").write_text(json.dumps({"package":"three", "version":VERSION,"npm_integrity":actual,"files":hashes}, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"version":VERSION,"files":len(hashes),"bytes":sum((root/p).stat().st_size for p in hashes)}, indent=2))


if __name__ == "__main__":
    main()
