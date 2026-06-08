# mac-code provenance

This repository includes a narrow, pinned source import from:

- Repository: <https://github.com/walter-grace/mac-code>
- Commit: `07401cb1eccc7108047434d7f55b51f48abbedee`
- Imported on: `2026-06-08`

## Imported paths

The following paths retain their original relative locations:

- `agent.py`
- `chat.py`
- `mlx/`
- `research/expert-sniper/cli-agent/`
- `research/expert-sniper/mlx-sniper/`

The imported files are preserved unchanged so their behavior can be audited
before selected ideas are adapted behind first-party `mac_llm` interfaces.

## Prototype boundary

All imported code is prototype and research material. It is not the
`mac-llm` production CLI and must not be treated as a safe runtime interface.
Some files contain direct process, shell, network, model, or filesystem
behavior. Verification of this import must compile or inspect source only; it
must not execute imported modules, start models, or invoke those behaviors.

## Excluded paths

This import intentionally excludes the upstream dashboard and web UI,
PicoClaw setup, distributed and RunPod components, 1-bit experiments,
Corsair, Tiny Bit Terminal, flash-streaming experiments outside mlx-sniper,
and the wider research tree.

## License status

No `LICENSE`, `COPYING`, or `NOTICE` file was present in the pinned upstream
snapshot, and GitHub did not report a detected repository license at import
time. This provenance record does not grant or infer a license. Publication
and redistribution rely on authorization maintained separately by the
repository owner.
