# ORCA math and engineering benchmark

The frozen `orca-math-engineering-v2` dataset is ORCA's regression benchmark for
quantitative reasoning. Keep the dataset unchanged when comparing models or
releases; create a new version rather than silently editing expected answers.

The benchmark reports two separate scores:

1. the conversational model answering without tools; and
2. the complete ORCA chat path with deterministic math and engineering tools.

Run sequentially with at least two repeats. Record the dataset SHA-256, exact
model alias, correctness, a Wilson 95% interval, median and nearest-rank p95
latency, and GPU temperatures before and after. Numeric scoring parses normal
display punctuation such as `1,657`; it does not compare formatted strings.

The suite is diagnostic, not a safety certification. A model may explain a
formula correctly and still fail the numeric answer. Quantitative engineering
conclusions should therefore use deterministic tool evidence rather than raw
language-model arithmetic.

Example on FORGE:

```sh
PYTHONPATH=/opt/orca/current \
ORCA_MATH_PYTHON=/opt/orca/math-runtime-1.14.0/bin/python \
python3 scripts/benchmark_orca_math.py benchmarks/orca_math_engineering_v2.json --repeats 2
```
