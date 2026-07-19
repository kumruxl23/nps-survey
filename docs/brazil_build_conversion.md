# Brazil build conversion (Phase 2) — draft to iterate on the Cloud Desktop

Mirrors the sibling `LMTCVS2ScienceAlgorithms` convention
(`build-system = brazilpython`, BrazilPython 3.0, pytest test-deps).

> **Process:** copy the `Config` + `setup.py` below into the workspace
> package (`~/NPSSurveyAutomation/src/NPSSurveyAutomation/`), run
> `brazil-build release`, paste errors back, we fix forward. Do NOT commit
> to mainline until the build is green. Dependency **names/versions must
> resolve against the `live` version set** — expect 1–2 rounds of fixes.

## 1. `Config` (replace the NoOpBuild one)

```brazil-config
package.NPSSurveyAutomation = {
    interfaces = (1.0);

    build-system = brazilpython;
    build-tools = {
        1.0 = {
            BrazilPython = 3.0;
        };
    };

    dependencies = {
        1.0 = {
            Python = default;
            Python-flask = 3.x;
            Boto3 = 1.x;
            BotoCore = 1.x;
            Python-requests = 2.x;
            Python-APScheduler = 3.x;
            Python-openpyxl = 3.x;
            Python-bcrypt = 4.x;
            Python-gunicorn = 21.x;
            Python-setuptools = default;
            BrazilPython-setuptools = default;
        };
    };

    test-dependencies = {
        1.0 = {
            BrazilPython-Pytest = any;
            Pytest = 6.x;
            Python-Pytest-cov = 4.x;
            Coverage = 7.x;
            BrazilPythonTestSupport = 3.0;
            Python-moto = 4.x;
            BrazilPython-formatters = 1.0;
        };
    };

    targets = {
        python = { type = python; };
    };

    python = {
        unittesttype = pytest;
    };
};
```

Notes / likely iteration points:
- Dep names are the standard `Python-<pkg>` / `Boto3`+`BotoCore` forms.
  If `brazil-build` says a package/version isn't in `live`, we adjust the
  version or run `brazil ws merge` to pull it in.
- `Python-moto` is needed because tests use moto. If unavailable in
  `live`, we either add it or gate those tests.
- Bandit SAST: add `BrazilPython-Bandit = any` (or `Python-bandit`) once we
  confirm the name in `live`; can be a follow-up so the test gate lands first.

## 2. `setup.py` (BrazilPython expects one at the package root)

```python
from setuptools import find_packages, setup

setup(
    name="NPSSurveyAutomation",
    version="1.0",
    # app code lives in the top-level `app` package; exclude tests from the
    # shipped artifact (they still run during the build).
    packages=find_packages(exclude=["*.test", "*.tests", "test", "tests"]),
    include_package_data=True,
    # BrazilPython setuptools extension kwargs:
    root_script_source_version="python3.11",
    check_format=False,        # flip on later once black/isort are wired
    test_command="brazilpython_pytest",
    doc_command="amazon_doc_utils_build_sphinx",
)
```

## 3. pytest discovery (add `setup.cfg` if the build doesn't find tests)

Our tests are colocated (`app/**/test_*.py`, `app/test_app_factory.py`).
If BrazilPython-Pytest doesn't discover them, add `setup.cfg`:

```ini
[tool:pytest]
testpaths = app
python_files = test_*.py
```

## 4. Build (on the Cloud Desktop)

```bash
cd ~/NPSSurveyAutomation/src/NPSSurveyAutomation
# paste the Config + setup.py in, then:
brazil-build release 2>&1 | tee /tmp/build.log
tail -n 60 /tmp/build.log
```

Paste the tail (or any ERROR lines) back and we fix forward until the
259 tests run green as a build gate. Then we commit the Config to
mainline and move to the Pipelines CDK (Phase 3).
