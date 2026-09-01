# pyhcl

![Python](https://img.shields.io/badge/python-3.10%2B-blue)

**pyhcl** validates and lints HCL/Terraform files without switching stacks. It scans `.tf`, `.tfvars`, and `.hcl` files for syntax issues, empty blocks, unclosed braces, possible secrets, and style problems.

## Features

- Detects unclosed and empty Terraform resource/data/provider blocks
- Catches simple syntax errors such as empty attribute sides
- Warns about possible secrets in `password`-like attributes
- Warns when `count = 0` is used
- Reports tab characters and long lines (>200 chars)
- Supports file and directory scanning recursively
- Text or JSON output
- `--check` exit code for CI integration
- Pure stdlib implementation with zero dependencies

## Installation

```bash
python -m pip install -e .
```

## Usage

```bash
pyhcl main.tf
pyhcl --json main.tf
pyhcl --check .
pyhcl module/ output.json
```

## Project Structure

```
pyhcl/
  pyhcl.py
  pyproject.toml
  README.md
  .gitignore
  tests/
    test_pyhcl.py
```

## Tags

python, hcl, terraform, lint, validator, iac, cli
