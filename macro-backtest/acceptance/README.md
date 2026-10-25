# Two-phase Macro result acceptance

The two named generation workflows capture exact code, configuration, provider/engine input bytes, runtime versions, and primary outputs without changing financial formulas. Capture is not acceptance. The read-only observer on the default branch joins an actual completed successful GitHub run/attempt to its immutable uploaded capture and committed result bytes, then validates every primary scenario. It does not run a backtest or execute artifact code.

Common-window retrospective architecture results can be accepted automatically. Historical/anchor/event results require the default-off `historical_evidence` workflow input: an already tracked, explicitly `PUBLIC_REVIEWED` transport manifest and exact source bytes at the executed code commit. See [HISTORICAL-EVIDENCE.md](HISTORICAL-EVIDENCE.md). The observer checks byte identity, declared temporal consistency and applied-event linkage; the public marker is a reviewer assertion, not independent authentication of historical truth. Without this input, historical acceptance remains incomplete. Private historical evidence is excluded from this public repository/artifact route; no private execution channel is added. Missing, partial, mismatched or invalid evidence produces an explicit rejected/incomplete receipt and a failed acceptance job. Supplemental fractional/benchmark/stress outputs are retained but not certified.

Input pickle snapshots are opaque hashed evidence; never unpickle untrusted artifacts. Git hashes bind bytes, not financial truth or permanent storage: Actions artifacts expire after 30 days and repository maintainers can change Git history. Retain independently if stronger immutability is needed.

## Financial interpretation boundaries

See engine-metrics.md. Core return statistics exclude contemporaneous trading fee drag although ending value includes fees. Historical value-growth returns include contributions and are **not contribution-adjusted investment performance** when flows are nonzero. Drawdown omits the initial wealth baseline. Legacy month-end helpers alone do not establish complete monthly observations; the acceptance layer separately checks calendar coverage. No financial formulas or portfolio/capital rules are changed here.

## Offline checks

Run `python macro-backtest/acceptance/test_contract.py`, `python macro-backtest/acceptance/test_engine_metrics.py`, `python -m unittest discover -s macro-backtest/acceptance -p 'test_integration*.py'`, and `python macro-backtest/acceptance/test_workflow_wiring.py`. Fixtures use synthetic providers/data/receipts and temporary repositories, not a live portfolio.

Deployment/fixture CI is not evidence of an actual authorized portfolio run. The downstream observer only certifies future qualifying runs with genuine completed-run receipts. No workflow is dispatched by installing this integration.
