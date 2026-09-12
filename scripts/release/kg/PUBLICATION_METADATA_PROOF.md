# Publication metadata assembler: synthetic acceptance proof

*2026-09-10T08:27:29Z by Showboat 0.6.1*
<!-- showboat-id: 938dee9e-39fb-4fb2-a9a3-cb6bbd6352e9 -->

This proof runs the synthetic acceptance tests. No production graph or publication directory is changed. Run from the repository root with the pinned .conda-env available.

```bash
.conda-env/bin/python -c 'import io, unittest; suite=unittest.defaultTestLoader.discover("tests", pattern="test_publication_metadata.py"); result=unittest.TextTestRunner(stream=io.StringIO()).run(suite); print(str(result.testsRun)+" synthetic tests; failures="+str(len(result.failures))+"; errors="+str(len(result.errors))); assert result.wasSuccessful()'
```

```output
8 synthetic tests; failures=0; errors=0
```
