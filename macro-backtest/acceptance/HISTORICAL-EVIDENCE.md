# Opt-in reviewed public historical evidence transport

This route is optional. No historical evidence is discovered, enrolled, uploaded or inferred automatically. Missing evidence rejects historical acceptance; common-window behavior remains unchanged. Use only already tracked, explicitly reviewed public material: never add a private canon, chat, account record or personal financial evidence to this public repository merely to satisfy the gate.

Before an already-authorized historical run, supply `capture --historical-evidence path/to/public-transport.json` before the `--` harness separator. The transport and all source files must exist byte-for-byte at the executed code commit. Its shape is:

```json
{
  "visibility": "PUBLIC_REVIEWED",
  "reviewer_assertion": "Identified reviewer and bounded public-source review; a factual assertion, not cryptographic authentication",
  "information_set": "Exact frozen information-set label matching the historical config",
  "historical_evidence": {
    "status": "COMPLETE",
    "scope": "Actual reviewed scope",
    "missing_items": [],
    "items": []
  },
  "sources": [
    {
      "path": "path/to/already-public-source.txt",
      "source_ref": "Actual original reference",
      "source_version": "Actual original version",
      "sha256": "SHA-256 of the entire bounded source file"
    }
  ]
}
```

The example is intentionally incomplete and cannot pass. Populate historical items under the existing v1.3 schema, with actual known/effective/applied dates, source references and versions, `bounded_sha256`, classifications, and event fingerprints. Every distinct source reference/version/digest must map exactly to retained source bytes. Multiple events may reference the same retained source. No synthetic evidence may be used for a real result.

Capture preserves the original transport, exact source bytes and extracted historical manifest. Post-completion verification binds those bytes to both executed code commit and persisted result commit, checks exact input/config/calendar identity and then applies all existing anchor/event/month/metric checks. `prepare_historical(bundle, result_commit, output_dir)` creates sidecars referencing captured evidence; it also exports a matching `historical-manifest.json` copy for the acceptance artifact. The observer must independently obtain real completed-run metadata; a fixture receipt is not authenticated GitHub evidence.

Tracked provenance and reviewer assertions **do not independently prove historical truth, correct dates or complete scope**. Digests prove retained-byte equality, not that a document existed on its asserted historical date. Public historical-source review remains necessary. This route does not transfer private evidence; if valid sources are private, that case remains blocked pending a separately authorized private transport.

Financial formulas are unchanged. Historical value-growth metrics with contributions are not contribution-adjusted investment performance; retain all engine-metrics limitations. No live portfolio execution or provider call was performed to test this route. Tests use synthetic public fixtures and temporary Git repositories.

The `PUBLIC_REVIEWED` marker and reviewer text are assertions, **not a privacy guarantee**. Human/source review of every referenced byte is mandatory before opting in. Path validation rejects absolute paths, traversal, symlink components and duplicate source mappings; structural checks cannot detect all private or falsely described material.
