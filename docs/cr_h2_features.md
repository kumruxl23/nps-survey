# CR runbook — H2 features consolidated CR

Branch pushed to GitFarm: `h2-features` (from laptop `main`, contains all of
mainline incl. the BrazilPython conversion `7e4c9d8`, plus the 23 H2 commits).
Destination branch: `mainline`.

## Run on the Cloud Desktop (dev-dsk-kumruxl-2b-74d03bb8)

```bash
# 0. Fresh Midway if needed (WebAuthn unsupported on SSH console)
mwinit -o

# 1. Go to the existing workspace's package (adjust path to your workspace)
cd ~/workspace/NPSSurveyAutomation/src/NPSSurveyAutomation   # or your ws path

# 2. Get the pushed branch from GitFarm
git fetch origin
git checkout -B h2-features origin/h2-features

# 3. Build + test gate (save verbose output, then inspect the tail)
brazil-build release > build.log 2>&1 && echo "BUILD OK" && tail -n 20 build.log
#   if it fails: tail -n 100 build.log ; fix root cause ; rebuild

# 4. Raise the consolidated CR against mainline
cr --destination-branch mainline \
   --summary "[NPSSurveyAutomation] H2: Midway auto-login, PAPI leader resolution, org-scoped nomination links" \
   --description "$(cat docs/cr_h2_features_description.md)" \
   --reviewers <riwjit-alias> \
   --open
```

## Pre-CR sync check (steering requirement)

```bash
git merge-base --is-ancestor $(git ls-remote origin mainline | cut -f1) HEAD \
  && echo "Remote commit is in your history" || echo "Diverged or behind"
```
Expect "Remote commit is in your history" — the laptop already merged mainline in.

## Notes
- Reviewer: Riwjit (confirm exact alias). Vinay pending base source-code access —
  re-add on a later revision once his access lands.
- Optional: prime AutoSDE locally first (see git steering "Pre-CR Review with
  AutoSDE") to get a fast Pass on the CR check.
- After merge: retire `infra/ssm_deploy.py` once Phase 3 Apollo deploy stages exist.
