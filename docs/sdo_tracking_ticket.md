# SDO Remediation Tracking Ticket (paste-ready)

Paste this into Taskei/SIM as the fast-follow tracking item for the SDO
work. File as a TASK, priority High, linked to the ASR app as
"Is related to". Record the ticket ID back in `sdo_remediation_plan.md`
once filed.

---

**Title:** NPSSurveyAutomation — SDO remediation: build gate + CI/CD pipeline

**Type:** TASK · **Priority:** High · **Owner:** kumruxl@ · **Backup:** kuvinu@

**ECD:** 2026-07-31 (target) · fallback 2026-08 week 2

## Summary

Bring `NPSSurveyAutomation` to the full SDO bar as a tracked fast-follow
to the ASR security certification (app WHS_AIFA-1763314908). Phase 1
(CR-required mainline) handled separately/immediately via CRUX Rules;
this ticket covers the build and deployment automation.

## Background

App began as a solo internal prototype and grew without full SDO setup.
It's a real Brazil package on GitFarm with 259 passing unit tests, but
the package is NoOpBuild and deploys manually (git pull + systemctl
restart on one EC2). Currently out of production (H1 cycle closed), so
this work carries no live-service risk. Next launch is the H2 cycle in
August.

Note: the package already inherits strong org-level CRUX analysis rules
(Security Code Scanner, Software Assurance, Integration Tests, Coverlay
coverage — all Require 'Pass' for merging CRs), so CR quality gates apply
automatically once CRs are required on mainline.

## Acceptance criteria

- [ ] Phase 1 — CRUX Auto Added Reviewer rule on mainline (1 locked
      approval); adopt AutoSDE: author + `autosde lint` + commit
      `AUTOSDE.yaml`, then point an AutoSDE Rule Config rule at its blob
      URL (file-first ordering to avoid blocking merges). Confirm the
      hard direct-push block mechanism with the certifier.
- [ ] Phase 2 — Replace NoOpBuild `Config` with a Python build that runs
      the full `pytest` suite (259 tests) as a build gate; add static
      analysis (Bandit/OneSAST) to the build.
- [ ] Phase 3 — Model a Pipelines + Apollo pipeline: build -> unit tests
      -> static analysis -> beta/gamma deploy -> approval -> prod, with
      automated rollback + deployment monitors.
- [ ] Phase 3 — Replace manual EC2 deploy with pipeline-driven Apollo
      deployment.
- [ ] Phase 4 — Decommission manual deploy as a normal path; retain SSH
      only as documented break-glass.
- [ ] Redeploy for the H2 cycle occurs via the pipeline, not manually.

## Effort estimate

Phase 2 ~1 day · Phase 3 ~3-5 days · Phase 4 ~0.5 day

## Related

- ASR app `33d9f777-6675-4612-bf3e-640960c021ad`
- SIM D465560471 (Uncertified Red App campaign)
- `docs/sdo_remediation_plan.md`
