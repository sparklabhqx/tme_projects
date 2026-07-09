# Pi Zero local LLM setup

The runtime app expects a llama.cpp binary bundle and a GGUF model at these paths:

```text
/home/tinypi/chatbot/bin/llama-cli
/home/tinypi/chatbot/models/SmolLM2-135M-Instruct-Q2_K.gguf
```

If your Pi user is not `tinypi`, use the same relative layout under that user's home directory:

```text
~/chatbot/bin/llama-cli
~/chatbot/models/SmolLM2-135M-Instruct-Q2_K.gguf
```

## Model

Model used in the working build:

```text
Hugging Face SmolLM2-135M-Instruct, Q2_K GGUF
File: SmolLM2-135M-Instruct-Q2_K.gguf
Approx size: 85 MB
```

Likely download URL:

```bash
mkdir -p ~/chatbot/models
wget -O ~/chatbot/models/SmolLM2-135M-Instruct-Q2_K.gguf \
  https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct-GGUF/resolve/main/SmolLM2-135M-Instruct-Q2_K.gguf
```

If that URL changes, search Hugging Face for:

```text
HuggingFaceTB SmolLM2-135M-Instruct-GGUF SmolLM2-135M-Instruct-Q2_K.gguf
```

## llama.cpp binary

The working Pi had llama.cpp build/version:

```text
llama-cli version: 9886 (20a04b220)
Architecture: Linux aarch64
```

The binary was dynamically linked against shared libraries in `~/chatbot/bin`, so copying only `llama-cli` is not enough. You need the whole llama.cpp binary/lib bundle or you need to build it on the Pi.

### Option A: copy a known-working binary bundle

From a working TinyPi:

```bash
rsync -av tinypi:/home/tinypi/chatbot/bin/ ~/chatbot/bin/
```

Then on the target Pi:

```bash
export LD_LIBRARY_PATH="$HOME/chatbot/bin:${LD_LIBRARY_PATH:-}"
~/chatbot/bin/llama-cli --version
```

### Option B: build llama.cpp on the Pi

This may take a while on Pi Zero-class hardware.

```bash
sudo apt-get update
sudo apt-get install -y git cmake build-essential libcurl4-openssl-dev
mkdir -p ~/src ~/chatbot/bin
git clone https://github.com/ggml-org/llama.cpp ~/src/llama.cpp
cd ~/src/llama.cpp
cmake -B build -DGGML_NATIVE=OFF -DGGML_CPU_ARM_ARCH=armv8
cmake --build build --config Release -j2
```

Then copy binaries/libraries into the expected folder. The exact build output layout can vary by llama.cpp version; commonly:

```bash
mkdir -p ~/chatbot/bin
cp -av build/bin/* ~/chatbot/bin/ 2>/dev/null || true
cp -av build/src/*.so* ~/chatbot/bin/ 2>/dev/null || true
cp -av build/ggml/src/*.so* ~/chatbot/bin/ 2>/dev/null || true
cp -av build/common/*.so* ~/chatbot/bin/ 2>/dev/null || true
```

Test:

```bash
export LD_LIBRARY_PATH="$HOME/chatbot/bin:${LD_LIBRARY_PATH:-}"
~/chatbot/bin/llama-cli --version
```

## End-to-end LLM test

After model and llama.cpp are installed:

```bash
cd ~
python3 - <<'PY'
import importlib.util
spec = importlib.util.spec_from_file_location('deck', 'usb_keyboard_display.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(mod.ask_local_model('Say hello'))
PY
```

Expected output should be one short sentence, for example:

```text
Hello!
```
