# Turbo discovery architecture

`imr-sqliblind` uses this mode only for authorized laboratories, CTFs, and explicitly permitted assessments. Request, item, row, value-length, and byte limits remain enforced.

## Goal

Reduce the critical-path latency of schema and table discovery while preserving exact results and robust fallback behavior.

A boolean oracle returns at most one bit of information per response. For an alphabet of 95 printable ASCII characters, an exact algorithm needs at least `ceil(log2(95)) = 7` independent decisions in the general case. Turbo mode does not claim to violate this information-theoretic bound. It makes those independent decisions concurrently.

## Algorithm

### Breadth-first bit planes

For every pending bounded integer, length, entity, and character position, turbo schedules independent binary-bit predicates in one global worker pool:

```sql
((value_expression) & 1) <> 0
((value_expression) & 2) <> 0
((value_expression) & 4) <> 0
...
```

Traditional binary or weighted inference creates a dependency chain: probe `n` cannot be selected until probe `n-1` returns. The breadth-first scheduler removes that dependency between bits and between entities.

### Modulo-3 error detection

Two additional predicates encode the residue class:

```sql
((value_expression) % 3) = 0
((value_expression) % 3) = 1
```

If both are false, the residue is `2`. If both are true, the oracle is inconsistent.

Every single flipped binary bit is detected because a power of two is never divisible by three. The reconstructed integer must satisfy:

```text
candidate mod 3 == observed residue
```

A mismatch invokes the existing robust binary/majority fallback for only the affected value.

### Aggregate identifier confirmation

After reconstructing all positions, turbo confirms the complete identifier with one equality predicate. This replaces one normal equality request per character:

```sql
(text_expression) = 'reconstructed_identifier'
```

If the batch confirmation fails, only that identifier is revalidated position by position. Percent and underscore remain numeric character codes and are never inserted into `LIKE` inference patterns.

## Smallest-schema-first workflow

Schema size is defined by table count because it is bounded metadata that can be inferred before table names or content.

The mapper now executes:

1. Discover all schema names.
2. Infer all schema table counts concurrently.
3. Sort by `(table_count, case-insensitive schema name)`.
4. For the smallest schema, discover every table name.
5. After all table names are known, discover every table's columns.
6. Extract bounded rows for every table, or only optional `schema.table` filters.
7. Complete that schema before starting the next schema.

Rows remain bounded by `max_rows`, `max_data_columns`, `max_value_length`, and `max_data_bytes`. Sensitive-looking values remain redacted unless explicitly requested.

## Performance validation

Run the deterministic latency-depth benchmark:

```bash
python benchmarks/inference_benchmark.py \
  --value 'A_9%' \
  --latency 0.01 \
  --workers 64 \
  --require-speedup 0.75
```

The benchmark exits non-zero if turbo is less than 75% faster than adaptive mode in this controlled clean-oracle scenario.

The speedup target is a reproducible laboratory threshold, not a universal guarantee for remote systems. Actual time depends on latency, rate limits, oracle noise, transport failures, configured workers, and explicit delay. Turbo keeps AIMD backoff for HTTP 429 and transport failures.

## Operational defaults

CLI and web defaults are optimized for bounded authorized scans:

- inference mode: `turbo`
- workers: `16`
- global start delay: `0`
- adaptive concurrency: enabled
- bounded row extraction: enabled
- optional table filter: empty means all discovered tables

Use `--delay` to impose a fixed start interval, `--workers` to reduce concurrency, or `--metadata-only` to omit row values.
