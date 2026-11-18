# Requirements Checklist: Existing Tailnet Lock Mode

**Purpose**: Review identity, mode and cutover requirements before implementation.
**Created**: 2026-11-17
**Feature**: [spec.md](../spec.md)
**Audience**: PR reviewer; focused security and acceptance review.

## Mode and identity requirements

- [x] CHK001 Are enabled and disabled modes both defined without treating missing state as disabled? [Clarity, Spec FR-020]
- [x] CHK002 Are identity requirements independent of signature availability in unlocked mode? [Completeness, Spec FR-008/020]
- [x] CHK003 Are existing trusted-signer and signed-proxy requirements preserved for enabled Lock? [Consistency, Spec FR-020]
- [x] CHK004 Are malformed, disagreeing and changing observations explicitly failure cases? [Coverage, Spec FR-020/021]
- [x] CHK005 Are stable identity, keys, tags, addresses and resource ownership sufficiently specified to exclude hostname-only matching? [Clarity, Spec FR-020; Plan mode selection]
- [x] CHK006 Is evidence terminology explicit that unlocked verification is not a signature? [Clarity, Spec mode acceptance scenario 4; Data model]

## Acceptance and operational boundaries

- [x] CHK007 Does the requirement bind mode/identity changes to acceptance invalidation before cutover? [Completeness, Spec FR-021; Plan evidence and races]
- [x] CHK008 Are the limits of non-atomic observation stated without claiming an impossible race-free guarantee? [Clarity, Spec clarification; Plan evidence and races]
- [x] CHK009 Are functional DNS, administration, recovery and normal-client requirements preserved? [Consistency, Spec FR-013/014/017/021]
- [x] CHK010 Are rollback requirements independent of failed resolver/signing readiness? [Recovery, Spec FR-015/021]
- [x] CHK011 Is the scope explicit about no Lock-policy mutation, new signing authority or unrelated workflow change? [Scope, Spec FR-020/021 and clarification]
- [x] CHK012 Are upstream schema assumptions and the retained locked-mode compatibility limitation disclosed? [Dependencies, Research unlocked amendment; Plan mode selection]

## Review notes

Generated before review. These items assess requirement quality only, not code
correctness, live connectivity, deployment or functional acceptance.

Independent requirements review by review_adguard_guards: CHK001–012 pass.
CHK001–006 trace to FR-008/020 and Plan mode selection; CHK007–008 to
FR-021 and Plan evidence/races; CHK009–010 to FR-013/014/015/017/021 and
rollback contracts; CHK011 to amendment scope; CHK012 to pinned upstream
research and disclosed legacy enabled-mode compatibility. No material gaps.
This evidence is a requirements review, not implementation or live acceptance.
