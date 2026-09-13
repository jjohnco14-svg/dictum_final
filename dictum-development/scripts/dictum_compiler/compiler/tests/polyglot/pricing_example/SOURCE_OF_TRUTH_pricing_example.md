# pricing-example

A minimal worked example of Guide A §0 Phase 1b: Python orchestration
calling a verified Dictum pricing kernel.

## Roadmap

- [R1] v1 Calculates a shipping tariff from weight, distance, and rate class.
- [R2] v1 Validates a rate class before use.

## Language Boundary

### block: pricing_kernel
- language: dictum
- file: pricing_kernel.dict
- exposes: calculate_tariff, is_valid_rate
- rationale: pricing logic -- must be auditable and byte-reproducible
  across backends; a wrong answer here costs the client money.
- verified_by: dictum check (3 backends agree); dictum emit-binding
  (boundary signature can't hand-drift from the compiled kernel)

### block: orchestrator
- language: python
- file: orchestrator.py
- rationale: CLI glue and argument parsing; no verification requirement
  beyond it calling the kernel correctly.
- verified_by: integration test only
