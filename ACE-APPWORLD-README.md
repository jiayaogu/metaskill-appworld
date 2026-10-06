# Install a clean AppWorld environment for all baselines

This guide sets up a clean ACE AppWorld environment from source.

## Prerequisites

```bash
git lfs install # if not installed already
git clone https://github.com/ace-agent/ace-appworld.git ace-appworld
cd ace-appworld

export APPWORLD_PROJECT_PATH="$(pwd)"

python3.11 -m venv .venv-clean-appworld
source .venv-clean-appworld/bin/activate

python -m pip install --upgrade pip setuptools wheel
pip install -e .
pip install -e "experiments[simplified]"

appworld install --repo # install AppWorld
appworld download data
```

## Re-enter an Existing Environment

```bash
cd /home/jiayao/Metaskill-library/baselines/ace/ace-appworld
source .venv-clean-appworld/bin/activate
export APPWORLD_PROJECT_PATH="$(pwd)"
```

## Sanity Check

```bash
python -c "import click, typer; print('click', click.__version__); print('typer', typer.__version__)"
appworld --help
```

Expected:

- `click` should be `8.1.8`.
- `appworld --help` should run without a Typer/Click crash.

## Notes

- Do not install this environment with `pip install appworld`; use the local source checkout.
- `APPWORLD_PROJECT_PATH` should point to the `ace-appworld` repository root whenever you run AppWorld experiments.

# Set up baseline environment

## Set up ACE environment

```bash
cd ..
git clone https://github.com/ace-agent/ace.git
cd ace

# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install ACE and core dependencies
uv sync

# Set up API keys
cp .env.example .env
# set the API key(s) and base url in .env as you need
```

If you would like to use keys other than the default provider api key provided by sambanova, you need to change the `provider` field of the corresponding jsonnet file. For example:
```json
local generator_model_config = {
    "name": "your-choice-of-LLM",
    "provider": "api-providers-name",
    "temperature": 0,
    "seed": 100,
    "stop": ["<|endoftext|>", "<|eot_id|>", "<|start_header_id|>"],
    "logprobs": false,
    "top_logprobs": null,
    "frequency_penalty": 0,
    "presence_penalty": 0,
    "n": 1,
    "response_format": {"type": "text"},
    "retry_after_n_seconds": 10,
    "use_cache": true,
    "max_retries": 50,
};
```

