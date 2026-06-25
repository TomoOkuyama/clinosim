# clinosim audit report

**Overall: WARN**

- Cohort: `scratchpad/clinosim_audit_byte_diff/branch`
- Modules: hai
- Axes: structural, jp_language, clinical, silent_no_op

## Summary

| Module | structural | jp_language | clinical | silent_no_op |
|---|---|---|---|---|
| hai | PASS | PASS | WARN | PASS |

## hai (3/4 PASS)

### Axis 1: structural — PASS

- 5C070_n=1087
- 5C070_refRange_interp_pct=100.0
- 1988-5_n=886
- 1988-5_refRange_interp_pct=100.0
- 6690-2_n=2082
- 6690-2_refRange_interp_pct=100.0
- 2A010_n=2245
- 2A010_refRange_interp_pct=100.0

### Axis 2: jp_language — PASS

- us_non_ascii_display_violations=0
- jp_WBC_localized=2245
- jp_WBC_total=2245
- jp_CRP_localized=1087
- jp_CRP_total=1087

### Axis 3: clinical — WARN

- **WARN** jp/cauti: cohort too small for delta (n_WBC=0, n_CRP=0); acceptance not verified at cohort level (silent_no_op axis covers this).
- **WARN** jp/clabsi: cohort too small for delta (n_WBC=0, n_CRP=0); acceptance not verified at cohort level (silent_no_op axis covers this).
- **WARN** jp/vap: cohort too small for delta (n_WBC=0, n_CRP=0); acceptance not verified at cohort level (silent_no_op axis covers this).
- **WARN** us/cauti: cohort too small for delta (n_WBC=0, n_CRP=0); acceptance not verified at cohort level (silent_no_op axis covers this).
- **WARN** us/clabsi: cohort too small for delta (n_WBC=0, n_CRP=0); acceptance not verified at cohort level (silent_no_op axis covers this).
- **WARN** us/vap: cohort too small for delta (n_WBC=0, n_CRP=0); acceptance not verified at cohort level (silent_no_op axis covers this).
- jp_baseline_WBC_p50=11567.5
- jp_baseline_CRP_p50=20.3
- jp_cauti_n_WBC=0
- jp_cauti_n_CRP=0
- jp_clabsi_n_WBC=0
- jp_clabsi_n_CRP=0
- jp_vap_n_WBC=0
- jp_vap_n_CRP=0
- us_baseline_WBC_p50=11943.0
- us_baseline_CRP_p50=27.1
- us_cauti_n_WBC=0
- us_cauti_n_CRP=0
- us_clabsi_n_WBC=0
- us_clabsi_n_CRP=0
- us_vap_n_WBC=0
- us_vap_n_CRP=0

### Axis 4: silent_no_op — PASS

- constants_pass_hai_lab_lift.yaml=ok
- proof_WBC_delta=2520.0
