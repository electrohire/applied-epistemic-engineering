#!/bin/bash
set -eu
pyinstaller --distpath "$OUT" --workpath /tmp/aee-pyinstaller --onefile \
  --paths "$SRC/aee/src" --paths "$SRC/aee/fuzz" \
  --name bundle_fuzzer.pkg "$SRC/aee/fuzz/bundle_fuzzer.py"
cat > "$OUT/bundle_fuzzer" <<'EOF'
#!/bin/sh
# LLVMFuzzerTestOneInput: Atheris entry point for ClusterFuzzLite detection.
this_dir=$(dirname "$0")
exec "$this_dir/bundle_fuzzer.pkg" "$@"
EOF
chmod +x "$OUT/bundle_fuzzer"
cp "$SRC/aee/fuzz/bundle_fuzzer.options" "$OUT/bundle_fuzzer.options"
python3 - "$SRC/aee/fuzz/corpus" "$OUT/bundle_fuzzer_seed_corpus.zip" <<'PY'
import pathlib
import sys
import zipfile
with zipfile.ZipFile(sys.argv[2], "w") as archive:
    for seed in pathlib.Path(sys.argv[1]).iterdir():
        archive.write(seed, seed.name)
PY
