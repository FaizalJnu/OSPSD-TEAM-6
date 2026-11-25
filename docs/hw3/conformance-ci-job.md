# CI job: shared conformance suite against our routes

For HW2 submission item 4 ("the pipeline run for the submitted commit, including the
conformance check results"). Add under `jobs:` in `.github/workflows/ci.yml`, in a PR
of its own, after the Create/Replace routes PR (commit a5180a0) is merged into `dev`.
Until then 46 of the 55 tests fail.

The suite lives only on Prateek's fork: shared PR #6
(Dayana20/ospsd26-cloud-storage) was never merged. Pin the exact commit.

```yaml
  # The shared conformance suite against our own HTTP routes, on the in-memory
  # backend, so it needs no credentials. Pinned to an exact commit: shared PR #6
  # is not merged, so the suite lives on Prateek's fork.
  conformance:
    runs-on: ubuntu-latest
    env:
      CONFORMANCE_BASE_URL: http://127.0.0.1:8781
    steps:
      - uses: actions/checkout@v5
        with:
          ref: ${{ github.event.pull_request.head.sha || github.sha }}

      - name: Check out the shared conformance suite
        uses: actions/checkout@v5
        with:
          repository: prateeks99/ospsd26-cloud-storage
          ref: a8bd8323b3accdae67ab3f97aeccafca9b46d512
          path: conformance-suite

      - uses: astral-sh/setup-uv@v7

      - name: Install our service exactly as locked
        run: uv sync --locked

      - name: Install the suite exactly as locked
        working-directory: conformance-suite
        run: uv sync --locked --all-packages --extra dev

      - name: Start our service on the in-memory backend
        run: |
          STORAGE_BACKEND=memory nohup uv run uvicorn storage_service.main:create_app \
            --factory --port 8781 > service.log 2>&1 &
          for _ in $(seq 30); do
            curl -fsS "$CONFORMANCE_BASE_URL/health" && exit 0
            sleep 1
          done
          cat service.log
          exit 1

      - name: Run the shared conformance suite against our routes
        working-directory: conformance-suite
        run: uv run pytest conformance/tests --no-cov -v --junitxml=../conformance-results.xml

      - name: Keep the results with the run
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: conformance-results
          path: |
            conformance-results.xml
            service.log
```

## Before pushing it

Run the suite locally the same way, against our routes on the in-memory backend:

```bash
# terminal 1, in this repository
STORAGE_BACKEND=memory uv run uvicorn storage_service.main:create_app --factory --port 8781
# terminal 2
git clone https://github.com/prateeks99/ospsd26-cloud-storage.git conformance-suite
cd conformance-suite && git checkout a8bd8323b3accdae67ab3f97aeccafca9b46d512
uv sync --locked --all-packages --extra dev
CONFORMANCE_BASE_URL=http://127.0.0.1:8781 uv run pytest conformance/tests --no-cov -v
```

If the suite's lockfile does not match, use `--frozen` instead of `--locked`.

## In the same PR

* Add `conformance` to the required checks for `main` (Settings > Branches).
* TESTING.md, "Shared conformance suite": add the new run and update the Gaps list
  ("CI does not run the suite").
