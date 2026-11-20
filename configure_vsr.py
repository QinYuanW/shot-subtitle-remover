"""Compatibility adjustments for our private checkout of upstream VSR 1.4.0."""
from pathlib import Path

ROOT=Path(__file__).resolve().parent/"engines"/"vsr"/"backend"/"tools"


def replace_once(path,before,after):
    content=path.read_text(encoding="utf-8")
    if after in content:
        return
    if content.count(before)!=1:
        raise RuntimeError(f"VSR 源码和 1.4.0 版本不匹配，请检查 {path.name}")
    path.write_text(content.replace(before,after),encoding="utf-8")


if __name__=="__main__":
    # VSR 1.4.0 checks a misspelled filename and would reassemble a 206 MB
    # model on every initialization, including each OCR predictor.
    replace_once(ROOT/"model_config.py","self.LAMA_MODEL_DIR, 'bit-lama.pt'",
                 "self.LAMA_MODEL_DIR, 'big-lama.pt'")
    # PaddleX HPI is a separate optional plugin. DML availability in ONNX
    # Runtime does not establish its availability to Paddle. Use native Paddle
    # CPU for detection while VSR keeps its own DirectML repair device.
    replace_once(ROOT/"subtitle_detect.py","enable_hpi=len(onnx_providers) > 0,",
                 "enable_hpi=False, enable_mkldnn=False, cpu_threads=4,")
    # The Windows Paddle native loader cannot open some absolute CJK paths.
    # The worker's cwd is the VSR checkout, so model-relative paths are ASCII.
    replace_once(ROOT/"subtitle_detect.py","import sys\n","import sys\nimport os\n")
    replace_once(ROOT/"subtitle_detect.py","model_dir=model_config.DET_MODEL_DIR,",
                 "model_dir=os.path.relpath(model_config.DET_MODEL_DIR),")
