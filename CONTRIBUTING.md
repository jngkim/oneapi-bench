# Contributing

- New workloads and applications follow [docs/adding-a-workload.md](docs/adding-a-workload.md)
  and [docs/adding-an-application.md](docs/adding-an-application.md).
- Before opening a pull request:

  ```bash
  python -m pytest -q
  ./obench validate
  ./obench list --markdown > docs/workloads.md
  ```

- Published workloads must cite their source (`publisher`, `reference`) and pin input
  checksums.
- Mark a workload `validated` only together with evidence from a real run: the
  cluster, the versions, and the relevant log lines showing GPU use and correct results.
- obench itself must keep working with the Python 3.9 standard library alone.
