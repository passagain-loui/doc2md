# build_gpu_pack.py

```python
"""Build the optional doc2md GPU Pack (NVIDIA CUDA runtime for CTranslate2).

The CUDA runtime is ~2 GB and only benefits NVIDIA users - AMD and Intel GPUs
cannot be used by CTranslate2 at all (it exposes only `cpu` and `cuda` devices).
Bundling it into the main installer would multiply its size for users who can
never benefit, so it ships separately and doc2md detects it at runtime.

Usage:
    python build_gpu_pack.py          # stage + verify + build installer
    python build_gpu_pack.py --stage  # stage + verify only (no Inno Setup)

Output: dist/doc2md_GPU_Pack_v<version>.exe
Installs to: %LOCALAPPDATA%\\doc2md\\cuda
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAGE = ROOT / "build" / "gpu_pack" / "cuda"
ISS = ROOT / "setup_gpu_pack.iss"

sys.path.insert(0, str(ROOT))
from doc2md import __version__  # noqa: E402
from doc2md.engine.audio_engine import CUDA_COMPONENTS  # noqa: E402

# Components and DLLs CTranslate2's Whisper path never loads. Both were
# confirmed unnecessary by transcribing with the app's default model on a real
# GPU with everything else hidden (see build/gpu_pack verification).
#
#   cuda_nvrtc  - runtime CUDA source compilation; CTranslate2 ships prebuilt
#                 kernels and never JITs.
#   cudnn_adv   - legacy RNN / multi-head-attention API; CTranslate2 implements
#                 attention itself and does not call it.
#
# cuDNN's engine libraries (engines_precompiled, engines_runtime_compiled) are
# deliberately KEPT even though this machine transcribes fine without them:
# they are cuDNN's kernel store, and dropping them shifts kernel selection onto
# fallback paths that could fail on GPU architectures not available for testing
# here. The ~500 MB they cost buys correctness on hardware we cannot verify.
EXCLUDED_COMPONENTS = frozenset({"cuda_nvrtc"})
EXCLUDED_DLLS = frozenset({"cudnn_adv64_9.dll"})

INNO_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
]


def source_root() -> Path:
    """Locate the installed nvidia-*-cu12 wheel payload."""
    root = Path(sysconfig.get_paths()["purelib"]) / "nvidia"
    if not root.is_dir():
        raise SystemExit(
            "NVIDIA CUDA wheels not found. Install them first:\n"
            "  pip install nvidia-cublas-cu12 nvidia-cudnn-cu12 nvidia-cuda-runtime-cu12"
        )
    return root


def stage() -> int:
    """Copy the CUDA DLLs into build/gpu_pack/cuda/<component>/bin."""
    src_root = source_root()
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    total = 0
    skipped = 0
    for component in CUDA_COMPONENTS:
        if component in EXCLUDED_COMPONENTS:
            print(f"[gpu_pack] excluded {component} (unused by CTranslate2)")
            continue

        src = src_root / component / "bin"
        if not src.is_dir():
            print(f"[gpu_pack] skip {component} (not installed)")
            continue

        dst = STAGE / component / "bin"
        dst.mkdir(parents=True)
        count = 0
        for dll in sorted(src.glob("*.dll")):
            if dll.name in EXCLUDED_DLLS:
                skipped += dll.stat().st_size
                continue
            shutil.copy2(dll, dst / dll.name)
            total += dll.stat().st_size
            count += 1
        print(f"[gpu_pack] staged {component}: {count} DLL(s)")

    if skipped:
        print(f"[gpu_pack] excluded {skipped / 1024 / 1024:.0f} MB of unused DLLs")

    if total == 0:
        raise SystemExit("[gpu_pack] nothing staged - no CUDA DLLs found")

    print(f"[gpu_pack] staged total: {total / 1024 / 1024:.0f} MB -> {STAGE}")
    return total


def verify() -> None:
    """Prove the staged pack alone can initialise CUDA.

    Runs in a child process with DOC2MD_CUDA_DIR pointed at the staging folder
    and the wheel directory hidden, so a pass means the pack is genuinely
    self-contained rather than quietly borrowing DLLs from site-packages.
    """
    # Constructing the model is not enough: it allocates weights but does not
    # exercise the cuDNN convolution kernels the encoder needs. A real
    # transcription is what proves the pack is complete.
    script = (
        "import subprocess, tempfile, ctranslate2\n"
        "from pathlib import Path\n"
        "assert ctranslate2.get_cuda_device_count() > 0, 'no CUDA device visible'\n"
        "types = ctranslate2.get_supported_compute_types('cuda')\n"
        "assert 'float16' in types, f'float16 unsupported: {types}'\n"
        "from doc2md.engine.audio_engine import _get_ffmpeg_path\n"
        "clip = Path(tempfile.mkdtemp()) / 'probe.mp3'\n"
        "subprocess.run([_get_ffmpeg_path(), '-y', '-f', 'lavfi',\n"
        "                '-i', 'sine=frequency=440:duration=5', '-q:a', '9', str(clip)],\n"
        "               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,\n"
        "               stderr=subprocess.PIPE, timeout=120, check=True)\n"
        "from faster_whisper import WhisperModel\n"
        "model = WhisperModel('tiny', device='cuda', compute_type='float16')\n"
        "segments, info = model.transcribe(str(clip), beam_size=1)\n"
        "list(segments)\n"
        "print('CUDA transcription OK from staged pack')\n"
    )

    env = dict(os.environ)
    env["DOC2MD_CUDA_DIR"] = str(STAGE)
    # Hide the wheel payload so it cannot satisfy the load instead of the pack.
    env["PATH"] = os.pathsep.join(
        p for p in env.get("PATH", "").split(os.pathsep)
        if "site-packages" not in p.replace("/", "\\").lower()
    )

    bootstrap = (
        "import sys; sys.path.insert(0, r'%s')\n"
        "from doc2md.engine.audio_engine import _register_cuda_dll_dirs\n"
        "dirs = _register_cuda_dll_dirs()\n"
        "assert dirs, 'pack directories were not registered'\n"
        "print('registered:', len(dirs), 'dir(s)')\n" % ROOT
    ) + script

    print("[gpu_pack] verifying staged pack can initialise CUDA...")
    result = subprocess.run(
        [sys.executable, "-c", bootstrap],
        env=env, cwd=str(ROOT), capture_output=True, text=True, timeout=600,
    )
    print((result.stdout or "").strip())
    if result.returncode != 0:
        print((result.stderr or "").strip())
        raise SystemExit("[gpu_pack] VERIFICATION FAILED - pack is not self-contained")
    print("[gpu_pack] verification passed")


def find_iscc() -> Path | None:
    for candidate in INNO_CANDIDATES:
        if candidate.is_file():
            return candidate
    found = shutil.which("ISCC.exe")
    return Path(found) if found else None


def build_installer() -> int:
    iscc = find_iscc()
    if iscc is None:
        print("[gpu_pack] Inno Setup (ISCC.exe) not found; staged files are ready but "
              "no installer was produced.")
        return 1

    cmd = [str(iscc), f"/DVersion={__version__}", str(ISS)]
    print("[gpu_pack]", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        return result.returncode

    artifact = ROOT / "dist" / f"doc2md_GPU_Pack_v{__version__}.exe"
    if artifact.is_file():
        print("\n" + "=" * 62)
        print("GPU Pack build complete")
        print(f"  Artifact : {artifact}")
        print(f"  Size     : {artifact.stat().st_size / 1024 / 1024:.1f} MB")
        print(f"  Version  : {__version__}")
        print("  Installs : %LOCALAPPDATA%\\doc2md\\cuda")
        print("  Enables  : NVIDIA GPU transcription (AMD/Intel are CPU-only)")
        print("=" * 62)
    return 0


def main() -> int:
    stage()
    verify()
    if "--stage" in sys.argv:
        print("[gpu_pack] --stage given; skipping installer build")
        return 0
    return build_installer()


if __name__ == "__main__":
    raise SystemExit(main())
```
