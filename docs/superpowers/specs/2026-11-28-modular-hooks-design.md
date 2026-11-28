# Modular structure, extension points and shared structures for clinosim — design

Status: approved by the maintainer on 2026-11-28. Baseline: clinosim v0.7.5 (`bb054f23f`); every `path:line` refers to that commit. **(verified)** = re-read in the code for this design; **(reported)** = from the pre-design code review, not re-read; **(measured)** = a read-only count or script was run. No test suite and no cohort was run for this design: every "byte-identical" below is a claim each PR must prove with the machinery of §9.1.

The guiding rule of this revision is *simpler*: move domain code to its owner and keep explicit calls; build a registry only where contributors add entries.

---

## 1. Intent, goals, non-goals, anti-goals

**Intent.** Let many contributors, including clinical domain experts, change or extend their own area by touching that area's files and data, without lowering determinism or output quality and without a rewrite.

**Goals**
1. Each clinical domain's logic, YAML, tests and README live in one module; the encounter drivers in `clinosim/simulator/` only sequence calls.
2. Two in-stay extension points where contributors add entries (complication action handlers, discharge criteria); everything else is named functions in their owner modules called in a fixed, visible order.
3. One shared structure per cross-cutting concern, specified in the form of `docs/design-guides/code-mapping-and-localization-spec.md` (rules, canonical functions, YAML format, guard test), en + ja, listed in `docs/design-guides/shared-helpers-catalog.md`.
4. Past ad-hoc fixes folded into those structures.
5. Values in validated YAML, control flow in named code; nothing an author writes in YAML is silently ignored.
6. Data-quality improvements as separate, sourced, measured, behavior-changing work.

**Non-goals**
- No rewrite of the engine, forward loop, dispatch or RNG phases.
- No CIF change inside a refactoring PR; no FHIR profile change.
- No Python entry-point plug-ins (§4.5).
- The in-stay extension points cover the known-disease inpatient loop (`_run_daily_loop`) only. The unknown-condition loop (`simulator/unknown_condition.py:257`, own `_generate_mar` call at `:367`, verified), the ED visit and the outpatient visit keep explicit calls; a contributor who needs a rule there adds the call explicitly with maintainer pairing, and a guard test lists the functions both inpatient loops must call (§4.4).
- No performance regression budget beyond today's release-checklist check; the design adds no per-day copies on the hot path.

**Anti-goals**
- A generic event bus or before/after hooks around every phase; typed view/sink/tracker frameworks around `_Stay` / `_Run`.
- A YAML condition mini-language (`and`/`or`).
- Mass re-exports through `__init__.py`.
- A refactoring PR that also fixes something, or a behavior-changing PR on top of a structure whose refactoring is not yet proven.

---

## 2. Current state (measured facts)

| Fact | Evidence |
|---|---|
| Core file sizes: `daily_loop.py` 2,742 lines, `medication_pipeline.py` 1,696, `outpatient.py` 1,670, `perinatal.py` 1,542, `inpatient.py` 1,306, `emergency.py` 1,128, `discharge_rx.py` 860 (verified, `wc -l`). `daily_loop.py` was 2,316 lines at v0.7.4 (reported, `git log --numstat`). | `clinosim/simulator/` |
| The day's order is one hand-written sequence in `_run_daily_loop`, `daily_loop.py:2438-2716`; the after-results responses are four consecutive calls (`:2561-2565`, verified). | |
| Mid-stay medication starts differ in kind (verified): vasopressor `daily_loop.py:1155-1199` (MAR, no gate); antithrombotic plan `:1202-1284` (gate, no MAR — the day's main MAR charts it); complication antibiotic `:1626-1716` (two-block loop with early return, gate, MAR); complication treatment `:1812-2113` (up to three gate calls with different accepted lists, one MAR call on one seed at `:2101-2112`); DKA `:2331-2373` (orders only). The same accepted-list comprehension is written at `:1263-1270`, `:1648-1655`, `:1884-1891`. | |
| Archetype and escalation starts are not gated when placed; they are charted by the daily MAR and gated only at the end of the stay by `_gate_new_medication_orders` (`daily_loop.py:2384-2435`, called at `:2683`) (verified). This deviates from `docs/design-guides/medication-lifecycle-spec.md:37` ("passes the drug-safety gate … before it is placed"). | |
| Complication actions are dispatched by hand in `_apply_complications`, `daily_loop.py:1541-1625`, including the literal AKI → cancel `metformin` (`:1619-1625`) (verified). | |
| MAR hold precedence is a "last writer wins" chain vasoactive → K⁺ → AKI → lactate (`medication_pipeline.py:1231-1249`), with per-order flags at `:1036-1039` and the vasoactive infusions taken from the order list of the call (`:1030`) (verified). Only the main daily call passes `potassium_hold`, `aki`, `lactate` (`daily_loop.py:2578-2592`); the complication, vasopressor and unknown-condition calls pass none (verified). | |
| The discharge decision (`daily_loop.py:2620-2669`, verified) is: release when `day ≥ first_release_day`, state-based discharge applies, not rate-uncontrolled, not ventilated and `_check_discharge_ready(..., on_vasoactive_support, findings_unresolved)`; at the ceiling, keep one more day if ventilated, or `extend_stay_for_symptoms` (`discharge_gate.py:239-262`: on support `los_ceiling < max_los + max_extension_days`, else `los_ceiling < max_los and unsafe_for_home`), or rate-uncontrolled with `los_ceiling < max_los`, or findings unresolved with `los_ceiling < target_los + discharge_extension_days(...)`. | |
| `clinosim/simulator/__init__.py:13-15` eagerly imports `cli`, `engine`, `helpers` (verified). | |
| About 39 module → simulator import statements in 26 files; 46–68 cross-package private-name imports depending on the counting method; 11 direct reads of another module's `reference_data` (reported). Only `tests/unit/test_types_layering_2210.py` and the `codes` guards enforce boundaries (reported). | |
| The code/data ratchet is keyed by file path (`tests/unit/code_data_separation.py:134-140`, verified) and its tests require lowering the baseline in the same change (reported: `tests/unit/test_code_data_separation_3137.py:66,77,85`). A file move therefore looks like a raise at the new path. | |
| `simulator/reference_data/` holds 27 YAML files, `simulator/` 87 Python files (verified). | |
| Two Cockcroft-Gault implementations with different edge semantics: `simulator/renal_antibiotic_dose.py:93-100`, `modules/prophylaxis/renal_dose.py:18-31` (verified). | |
| A medication stop is an `Order` whose `display_name` starts with `DISCONTINUE:` — 52 occurrences in 12 Python files (measured: `grep -rn 'DISCONTINUE:' clinosim --include='*.py'`). | |
| Holds have six sources (verified by `ls` / grep): `locale/shared/chronic_medications.yaml hold_conditions`, `simulator/reference_data/{renal_medication_rules,aki_response,vasoactive_hold,permissive_hypertension_hold,oral_intake}.yaml`, `drug_safety/reference_data/hyperkalemia_response.yaml`, and the disease-protocol `medication_holds` of AD-51 (7 disease YAMLs). | |
| The ED-phase window is rebuilt at 7 sites with closed and half-open conventions (`simulator/inpatient.py:534, 826-830`, `modules/triage/engine.py:445`, `modules/document/engine.py:623-626`, `output/fhir_r4/conditions/conditions.py:296-305`, `output/fhir_r4/lib/inline_bb.py:103-112`, `output/fhir_r4/lib/ed_reattribution.py:245-254`; verified). | |
| `DiseaseProtocol` has 20+ fields typed `dict[str, Any]` / `list[dict[str, Any]]` (`modules/disease/protocol.py:727-785`, verified); 218 of 768 authored condition entries always evaluate False (reported). | |
| Complications: 218 blocks under 121 names; of the 28 names used in more than one protocol, none is identical across protocols apart from probability and onset (reported, measured by the reviewer). Key order of `state_impact`, `risk_factors` and the protocol list drives RNG draw order and float product order (`daily_loop.py:1564-1571`, `clinical_course/engine.py:537-565`; reported). | |
| `load_validated_yaml` returns the raw dict and does not name the file (`clinosim/datafiles.py:55-61`, verified); 85 test sites use `pytest.raises(ValidationError)` (measured). | |
| `course_time_scale.yaml` reproduces `round(clamp(jp_mean/us_mean, 1.0, 4.0), 2)` for 91 of 91 entries (measured), already enforced by `tests/unit/test_course_time_scale_3931.py:42-54` (reported). | |
| In-stay seeds are already named digests with no central table, e.g. `complication_treatment_seed` = `_digest_int(f"complication-treatment:{encounter_id}:{day}:{complication}:{action}", 8)` (`clinosim/seeding.py:483-487`, verified); only enricher offsets use the central `ENRICHER_SEED_OFFSETS` (`seeding.py:333-355`, verified). | |
| `in_shock` already reads the perfusion drop below baseline (`daily_loop.py:264-273`, verified), but the pH lactic-acid coupling reads absolute `perfusion_status` (`modules/physiology/engine.py:675-676`, verified) while the lactate lab reads the deviation. | |
| Process: no CODEOWNERS; PR template says `Fixes #123` (`.github/PULL_REQUEST_TEMPLATE.md:14`); `docs/add-your-country.md:12,39` names a removed `_COUNTRY_DIR_MAP`; `AGENTS.md:387` "No engine code changes required" for a new disease (all verified); goldens were rewritten by 15 of 72 commits in v0.7.4..v0.7.5 (reported). | |

---

## 3. Target architecture

### 3.1 Layers and allowed dependency directions

| Layer | Packages | May import | Must not import |
|---|---|---|---|
| L0 Foundation | `datafiles`, `determinism`, `seeding`, `age_bands`, `timeutil`, `reference_data`, `log` (new home of `simulator/log.py`), `countries/__init__`, `country_profile`, `codes`, `locale`, `types`, `modules/_shared` | L0 | modules, simulator, output, eval, audit |
| L1 Domain modules | `clinosim/modules/<m>/` except `output` | L0; public names of the modules in its README `## Dependencies` | `clinosim.simulator.*`; `_`-prefixed names of another package |
| L2 Orchestration | `clinosim/simulator/` | L0, L1 public names | L1 private names |
| L3 Output adapters | `clinosim/modules/output/` | L0, CIF types, L1 public contract constants and loaders | `clinosim.simulator.*` (AD-17, AD-58) |
| L4 Country implementations | `clinosim/countries/<cc>/` | L0, L1, L3 public names | private names |
| QA | `eval/`, `audit/` | L0, L3, L1 public names | `clinosim.simulator.*` |

Exceptions written into the boundary guard: `_<topic>_thresholds.py` / `_<topic>_defaults.py` constant modules (the canonical constants home, policy §5.1); `_bb_*` builders imported only by `output/fhir_r4/builder.py` and `*/audit.py`; `modules/_shared.py`. Cross-module YAML validation goes through public `validate_*` functions of the vocabulary's owner (today `disease/protocol.py:824,959` import private validators, reported).

### 3.2 Domain → module map

New modules are created only where no existing module owns the concept:

- **`renal`** (new): creatinine clearance / eGFR provider for decisions, renal dose bands, AKI response, RRT. Today split across `simulator/renal_antibiotic_dose.py`, `simulator/aki_response.py`, `simulator/renal_replacement.py`, their YAML and `prophylaxis/renal_dose.py`. `physiology` owns the renal *state*, not drug or care decisions; `order` owns dose arithmetic, not AKI care. `renal` supplies renal values and dose bands; it does not own holds (§5.1).
- **`critical_care`** (new): airway/shock/ICU predicates (`daily_loop.py:256-290`), oxygen course, NIV/ventilation, vasoactive support and weaning, ICU step-down, and the lactate course (perfusion, not kidney). No existing module covers organ support.

Not created: `obstetric` — first the delivery order sets move out of `perinatal.py:944-1198` into YAML; a module is decided afterwards; `emergency` — ED rules go to `encounter` (owner of the ED protocols) and `triage` (owner of the ED-phase duration); `oncology` and `dosing` — no second consumer.

| Domain | Owner | Moves in |
|---|---|---|
| Complications: vocabulary, risk conditions, action decisions and handlers, diagnosis codes, sustained effects, delirium, terminal course | `clinical_course` | `simulator/{complications,complication_actions,complication_dx,sustained_complication,delirium,terminal_course}.py` + YAML; handler bodies from `daily_loop.py:1626-2113` (§4.2) |
| Renal | `renal` (new) | as above |
| Critical care | `critical_care` (new) | as above |
| Holds, gate, reconciliation | `drug_safety` | the hold chain, `apply_drug_safety_gate_to_orders` (`medication_pipeline.py:1295-1605`), `allergy_blocked`, `limit_triple_antithrombotic` (`discharge_rx.py:164`), all six hold sources (§5.1) |
| Orders, MAR scheduling, dose text, frequency, stop marker, medication course | `order` | `child_dosing`, `_generate_mar` (its own child issue), `maintenance_iv_fluid.py`, `_determine_route` (`simulator/helpers.py:424`) |
| Metabolic | `metabolic` | `ketoacidosis_resolution.py`, DKA SC transition (`daily_loop.py:2331-2373`), `statin_monitoring.py` |
| Device / nursing | `device` / `nursing` | `device_removal.py`; `oral_intake.py`, `adl_ceiling.py`, diet ladder (`daily_loop.py:1387-1411`) |
| Disease traits | `disease` | disease-id sets (`vitals_pipeline.py:208-222`, `disease/acuity.py:29-54`, `imaging/engine.py:99`) → disease YAML traits |
| Diagnosis | `diagnosis` | `diagnosis_rules.py`, `sepsis_severity.py`, `sex_gating.py` + YAML; coded-diagnosis view (§5.8) |
| Observation | `observation` | domain parts of `vitals_pipeline.py`, `ventricular_rate.py`, finding thresholds, `latest_lab_at` |
| ED | `encounter` / `triage` | ED release criteria; ED-phase window helper |
| Encounter timing | `encounter` | placement helper |
| HAI | `hai` | snapshot truncation and lab lift now in `inpatient.py:616-663` |

Stays in `simulator/`: `engine.py`, `_dispatch.py`, `_setup.py`, `phases/`, `enrichers.py`, `memoize.py`, `enumerate.py`, `cli_*`, `encounter_setup.py`, `event_refs.py`, `hospital_ops.py`, and the encounter drivers reduced to sequencing.

**Moves update every caller and test in the same PR**; a re-export shim is kept only for names exported by `clinosim.api`. Reason: a test that monkeypatches an old shim path no longer affects the call from the new module and passes while testing nothing.

### 3.3 Public API rule (revises `docs/design-guides/implementation-rules.md:123`)

- In the repository, a module's public API is the non-underscore names of its non-underscore submodules, listed in the README `## Public API`. Only the private-name rule is enforced. Mass re-export is not required (it would make lazy import cycles eager).
- For external code, `clinosim.api` (`clinosim/api.py:1-17`) is the only stable surface.
- `CONTRIBUTING-modules.md:199` ("engine.py: no cross-module imports") becomes "imports only the public API of the modules declared under `## Dependencies`".

---

## 4. Extension points inside the inpatient day

### 4.1 Principles

- Named functions in the owner module, called in a fixed order from `_run_daily_loop`, with narrow explicit arguments. No typed view/sink/tracker framework; `_Stay` and `_Run` stay as they are.
- A registry exists only where contributors add entries: complication action handlers (§4.2) and discharge criteria (§4.3). Their entry lists live in the owner module, not in `simulator/`.
- No draw from `stay.rng`. New randomness uses a named digest seed in the style of `seeding.py:469-516` (`_digest_int(f"<name>:…")`), which needs no central table.
- Characterization first: every extraction PR names the paths it moves and shows each one fired in the corpus of §9.1.

### 4.2 Complication action handlers (registry)

- **Call site:** `_apply_complications` (`daily_loop.py:1541`), per triggered complication, after state impact, sustained holds, record and consciousness lowering (`:1563-1592`), which stay in the loop; `evaluate_complications` stays on `stay.rng`.
- **Shape:** `ComplicationActionHandler(kind: str, order: int, applies(entry) -> bool, run(event, ctx))`, registered in `clinical_course/complication_actions/__init__.py` (the module's own list). `event` = typed complication entry (§5.4), onset time, day.
- **Dependency inversion:** handlers do not import the simulator. The simulator passes `ctx: ComplicationActionContext` (a small `Protocol` defined in `clinical_course`) with exactly the capabilities the handlers use today: the stay's orders and results (live, so a second complication on the same day sees what the first one added, as `daily_loop.py:1849-1855, 1931` require), `start_medications(entries, …)` (protocol orders → gate), `chart(orders, seed)` (MAR), `log_safety_skip(...)`, `trigger_icu(day)`, `start_oxygen_support(kind, at)`, `secure_airway(at)`. The simulator implements it over `_Stay`/`_Run`. Once `_generate_mar` has moved to `order` (its own child issue), `chart` may call `order` directly.
- **Order (byte-identity condition, today's sequence):** antibiotic 10 → treatment/stop 20 → NIV 30 → airway 40 → ICU transfer 50 → AKI drug cancellation 60 (kept as a literal inside its handler until a behavior-changing issue declares it in YAML; it sets `CANCELLED`, not a stop marker).
- **Seeds:** unchanged (`complication_antibiotic_seed`, `complication_treatment_seed`); a new kind derives `_digest_int(f"complication-action:{kind}:…")`.
- **Corrected dependency order:** (1) complication vocabulary to `clinical_course`; (2) typed validation of today's inline complication blocks (§5.4, key order preserved); (3) pure decision functions and YAML of `simulator/complication_actions.py` to `clinical_course`; (4) the two small medication helpers (§5.0); (5) the handler registry with the context Protocol; (6) later, `_generate_mar` to `order`.
- **Not covered (stated):** complication monitoring labs fire only while a sustained hold is active (`daily_loop.py:626-630`, reported), and discharge continuation of complication drugs lives in `inpatient.py:467-489` and `discharge_rx.py:270-289, 802-810` (reported). Both stay maintainer-paired core edits; a Stage 2 behavior-changing child may add "monitoring while active" and "carried to discharge" as handler outputs.

### 4.3 Discharge criteria (list of named criteria)

- **Shape:** `DischargeCriterion(name, blocks_release(args) -> bool, keeps_at_ceiling(args, los_ceiling) -> bool)`, listed in `clinical_course/discharge_criteria.py`; each function lives in its owner (critical_care, observation, renal). The loop computes `any(blocks_release)` and `any(keeps_at_ceiling)`. All criteria are side-effect and draw free, so evaluation order does not matter.
- **Today's criteria expressed exactly:** ventilation/NIV (release blocked; at ceiling kept, unbounded); vasoactive support (passed to `_check_discharge_ready`; at ceiling kept while `los_ceiling < max_los + max_extension_days`); uncontrolled ventricular rate (release blocked; kept while `max_los is not None and los_ceiling < max_los`); unresolved AKI/fever/metabolic/dialysis (passed to `_check_discharge_ready`; kept while `los_ceiling < target_los + discharge_extension_days(...)`, with the fever and AKI caps of `aki_response.py:308-324`). The state-based checks (`_check_discharge_ready`, `unsafe_for_home` inside `extend_stay_for_symptoms`) stay as the gate's own logic, not criteria. The flags carried to `DailyLoopResult` (`daily_loop.py:2705-2715`) are unchanged in this step.
- **Characterization first:** a table test over criterion combinations × `on_support` × `los_ceiling ∈ {< max_los, = max_los, > max_los}` × fever vs AKI extension caps × `day` vs `first_release_day`.

### 4.4 Fixed-order calls (no registry)

- **After-results responses:** `drug_safety.respond_to_hyperkalemia` → `renal.aki_course` → `renal.renal_replacement` → `critical_care.lactate_course`, called explicitly at `daily_loop.py:2561-2565`. A registry is added when a fifth responder appears.
- **MAR holds:** `drug_safety.mar_hold_reason(order, scheduled, holds: MarHolds) -> str | None` with the four checks in today's order and the same "last applies" result. `MarHolds` is a small dataclass the caller builds from its own arguments (including the infusions of the call's order list); the complication, vasopressor and unknown-condition call sites build an empty one, exactly as today. A separate behavior-changing issue asks whether complication-started doses should honour the stay's holds. A registry is added only when a new hold source needs it and byte-identity has been shown.
- **Guard:** a test that both inpatient loops (`_run_daily_loop`, `unknown_condition`) call `mar_hold_reason` and `apply_vital_holds`, so a new rule cannot reach one loop only by accident.

### 4.5 Deferred and rejected

- `day_start` and `bedside_activity` hooks: deferred (their candidates sit at different positions relative to `stay.rng` draws, `daily_loop.py:2540-2576`).
- Enricher registration: left central (`simulator/enrichers.py:112-591`); a new enricher may derive its seed by name instead of a new `ENRICHER_SEED_OFFSETS` entry, so `seeding.py` is no longer edited (existing offsets unchanged).
- Python entry points: not now. This defers AD-58's stated evolution path (setuptools entry-point discovery, `docs/architecture/architecture-notes.md:483`): there is no external plug-in author, and environment-dependent discovery would make execution order depend on installed packages (AD-16/AD-59).
- New ADR (next number in `docs/architecture/adr-history.md`, AD-72): "In-stay extension points: complication action handlers and discharge criteria; fixed-order calls elsewhere; no `stay.rng` draws". `medication-lifecycle-spec.md:37` changes the gate's location to `drug_safety`.

---

## 5. Shared structures

Each gets a spec section (en + ja), a catalog entry (real symbols only) and a guard test. BP = byte-identical; BC = behavior-changing, its own PR with numbers. Every PR is labelled BP or BC before it is scheduled.

### 5.0 Two medication helpers (prerequisite for §4.2)

- `running_medication_names(run)` replaces the identical comprehension at `daily_loop.py:1263-1270, 1648-1655, 1884-1891`; `chart_new_orders(stay, run, orders, day, seed, renal)` wraps the `_generate_mar` call with the stay's arguments (`:1189, 1704, 2101`). BP. Vasopressor, antithrombotic plan and DKA starts stay as they are.
- Separate BC issue: gate archetype and escalation starts when placed and remove the end-of-stay retro gate (`daily_loop.py:2384-2435`), measuring MAR rows whose order is later dropped. This brings the code in line with `medication-lifecycle-spec.md:37`.

### 5.1 Medication course timeline, typed stop event, one hold home

- **Rules:** a stay's medication course is `MedicationCourse(drug_id, order_ids, start, stop | None, stop_reason, superseded_by)`, derived only from orders; "running at t" is answered only by `running_at`; only `stop_marker.py` knows the marker encoding; a drug-safety pair rule states its resolution once (`resolution: {keep: <class> | earlier, spare: [<class>]}`) for admission, complication, discharge and ED take-home; "may this dose be given now" holds have one home, `drug_safety`, with renal thresholds read from the `renal` provider.
- **Functions:** `order/stop_marker.py` (`is_stop_marker`, `stopped_drug`, `make_stop_marker`, `is_complication_hold`); `order/medication_course.py` (`medication_courses`, `running_at`, `stopped_between`); `drug_safety.active_medications(...)` (replaces 12 hand-built lists, reported); `drug_safety.resolve_conflict(...)`.
- **YAML:** `drug_safety/reference_data/hold_rules.yaml` with typed kinds (vital, renal_function, aki, potassium, lactate, vasoactive, permissive_hypertension, oral_intake, protocol) absorbing all six hold sources; the AD-51 disease-protocol `medication_holds` stay authored in the disease YAML (AD-51 is kept) and are evaluated by the same `drug_safety` function. `contraindications.yaml` gains `resolution`.
- **CIF:** typed `Order.stops_order_id` + `stop_reason` (MINOR).
- **Guard:** `"DISCONTINUE:"` only in `stop_marker.py` and locale text; every MAR row inside a course interval.
- **AD-71:** `MedicationCourse` is a read view over one encounter's orders, not a generator; it does not replace `TemporalStatePeriod` (`docs/architecture/adr-history.md:683`), which stays the pattern for person-level time-boxed episodes (e.g. an anticoagulation course across encounters). The spec states the relation.
- **Also here:** the FHIR same-class dedup by display substring over `codes/data/medication-class-members.yaml` (`output/fhir_r4/medications/medications.py:1905-2010`, reported) is replaced by the pair rules at CIF time (BC).
- **Order:** stop-marker helper (BP, Stage 1) → course builder porting `_running_order`, `discontinue_flip`, `inline_bb`, `supersede` (BP only if byte-diff shows `discontinue_flip`'s substring match equals `same_drug`; else BC) → `active_medications` (BP per site) → `resolution` (BP) → hold home (BP where the same drugs are held; re-keying name-keyed `hold_conditions` to ids is checked and, if it moves output, BC) → typed stop event (CIF) → `medications_in_effect` honours stops (BC) → FHIR class dedup (BC).

### 5.2 Renal function and dose resolution

- **Rules:** one CrCl and one eGFR provider; one dose-band schema for every drug (dose, interval, avoid, first-dose-unchanged) — holds stay in `drug_safety`; the renal dose is decided at placement, not inside MAR generation; drug decisions never use `has_ckd` or static `renal_reserve`; one dosing weight (`encounter_weight_kg`, `population/encounter_anthropometry.py:354-357`, reported) for renal and weight-based doses.
- **Functions (`renal`):** `cockcroft_gault(...)` (coefficients in `_renal_dose_thresholds.py`), `creatinine_clearance(patient, encounter, at, results, *, selection, age_rule)`, `egfr_at(...)` via `physiology/egfr.py`, `renal_band(drug_id, country, value)`; `observation.latest_lab_at(results, lab, at, *, inclusive, fallback_first)`.
- **YAML:** `renal/reference_data/renal_dose_rules.yaml` (absorbs `renal_antibiotic_dosing.yaml`, prophylaxis `renal_adjustment`, the edoxaban `dose_reductions` at `complication_actions.yaml:391-396`, and the protocol `renal_adjustment` entries).
- **Order:** one formula with each caller's edge semantics as parameters (BP) → files into `renal` (BP) → placement-time decision (BC unless the corpus shows identity) → unified edge semantics (BC) → one schema and protocol migration (BC, each band sourced) → holds read the provider (BC).

### 5.3 Encounter window, ED phase, FHIR attribution

- **Rules:** a timed CIF item of an encounter lies in its window, except the classes in a sourced allowance table (`encounter/reference_data/temporal_allowances.yaml`: e.g. microbiology final reports, pathology, discharge-summary signing may follow discharge by a bounded interval); the ED phase is `[admission − admitted_ed_stay(), admission)`; the window is enforced at generation and FHIR clamps become zero-fire assertions; the FHIR encounter of a resource is decided once, before builders link resources.
- **Functions:** `encounter/timing.py` (`EncounterWindow.of`, `place_in_window(anchor, offset, window, policy)` with policies clamp / scale_into_ambulatory / drop / shift_keep_length); `triage.ed_phase_window`, `triage.ed_bridge_encounter_id` next to `admitted_ed_stay` (`triage/engine.py:145`); `EncounterAttribution` on `BundleContext` with `encounter_for(...)`.
- **Order:** helpers (BP; the boundary instant is checked by byte-diff, BC if it moves) → attribution index with the walker as assertion (BP) → delete the walker and the fix-ups at `builder.py:935-938` (BP after zero-fire).
- The early fixes of #3957, #3959 and #3958 (§9.3) are written as the clamp / grouping these helpers later absorb.

### 5.4 Complication entries: typed validation and a drift report

- Phase 1 (BP): a Pydantic model of today's inline blocks (`extra="forbid"`, unknown tokens fail naming file and key), **preserving key order**; the guard compares `json.dumps(expanded, sort_keys=False)` strings of every protocol's complication list before and after, not dicts. Blocks without `onset_day_range` keep using `COMPLICATION_ONSET_RANGE_DEFAULT`.
- A drift report test lists cross-protocol differences per complication name and field so reviewers see them.
- Shared definitions only for what is already protocol-independent (diagnosis code, display, action kinds). Any cross-protocol reconciliation of values is a later BC issue per complication with a clinical argument — much of the drift is legitimately disease-specific.

### 5.5 Clinical finding classifier

- `observation/reference_data/clinical_findings.yaml` (threshold, inclusive, age band, exit threshold) with `observation.findings.has_finding`; `document/narrative/_state_change.py` `classify_transition(prev, cur, rule) -> Transition`. Call sites: `lab_timeseries.py:160-192`, `_progress_course.py:173-189`, `_progress_state.py:62-100`, `_progress_exam.py:490-530`, `_progress_symptoms.py:115-148` (reported lines). Thresholds move with identical values (BP) → enum with each caller's rule (BP) → merge the two lab-change rules (BC). The vaccination "febrile" precaution stays a separate finding.

### 5.6 Age, pediatric cut-off, country slot, language

- `age_bands.age_in_years` (completed years), one pediatric cut-off in shared config (legal adulthood separate); `countries.lang_for` normalizes through `country_code` (today codes only, `countries/__init__.py:91-98`); `country_slot` (`:131`) replaces inline `"jp" if is_jp(c) else "us"`. BP except the two fractional-age sites (`renal_antibiotic_dose.py:141`, `complication_actions.py:368`, reported) and the `lang_for` fix, which are BC.

### 5.7 Structured dose and frequency (staged)

- `order/dose_text.py` (`parse_strength`, `parse_interval`, `rewrite_dose`) with `parse_dose_string` (`order/engine.py:505`) delegating, each current parser reproduced as a named variant (BP); frequency predicates move from `output/fhir_r4/lib/dosage.py:601-611` to `order` (BP); variants merged (BC); structured `Order` dose phases last (CIF, BC).

### 5.8 Coded-diagnosis view per stay

- The stay's coded diagnoses (principal, secondary, complications with codes, carried complications) are computed once into `ClinicalDiagnosis` and read by both the discharge summary and the FHIR `Encounter.diagnosis` / `Condition` builders; the E11.9 subsumption and F31/F32/F33 rules (`condition_mutex.py:52, 75-77`, reported) become a YAML table. BP at FHIR; any narrative change is reported as BC.

---

## 6. YAML/code boundary decisions

### 6.1 Placement rule (revises `docs/design-guides/configuration-and-reference-data-spec.md:40`)

1. Python `_<topic>_thresholds.py`: coefficients and cut-points of one formula or of the latent-state model, RNG salts.
2. YAML with a source: values a clinician, epidemiologist or hospital tunes or a guideline/label/statistic states (doses, measured-value cut-offs, age tiers, per-severity tables, clock routines, release criteria, rates, order sets).
3. Fallback defaults: in `_<topic>_defaults.py` or the model default, never both, never restated by `.get(key, default)`.

### 6.2 Ratchets: rename-aware, conflict-free

All ratchets (existing code/data, new boundary, size, loose-field, provenance):
- store **totals per rule** in the baseline JSON, plus an informational list of content-keyed entries (key = rule + enclosing qualified name without module path + normalized node text, so a `git mv` keeps the key);
- fail only when a rule's total exceeds the stored total; a decrease passes without editing the JSON;
- the stored totals are lowered by one command (`python -m tests.unit.<ratchet> --write`) run by a nightly job or the coordinator, never required inside a feature PR, so parallel lanes do not edit the same file;
- report new content keys in the test output (a net-zero swap is visible to the reviewer, not a failure).
The code/data ratchet's tests (`test_code_data_separation_3137.py`) and rules text ("the baseline may only go down") are revised accordingly; the configuration spec states "a move is not a raise".

The core-file size check is report-only (it appears in the success metrics, §9.5) so that small fixes to `daily_loop.py` are never blocked.

### 6.3 Named predicates instead of condition vocabularies

Four vocabularies (`disease/severity.py:101-118`, `clinical_course/engine.py:198-227`, `:572-680` + `_complication_risk_conditions.py`, device/ROS; reported) become one registry of named predicates in `clinical_course/predicates.py`; thresholds behind named states move to one YAML vocabulary; the simple comparison form stays structured with one parser; unknown names fail at load naming file and key. New spec `condition-vocabulary-spec.md`.

### 6.4 Inert YAML — DECIDED

Per item: (a) **implement** a condition or key with a well-defined clinical meaning buildable from existing state — BC, grouped by vocabulary or protocol, and **marginal-preserving**: the base probability is rescaled by E[compound multiplier] so the cohort-level complication or severity rate per disease is unchanged unless a source gives a new marginal; rates shown before/after (AD-68 is the precedent for activating dead YAML); (b) **delete** a key with no reader that duplicates other data or has no defined semantics (`complications[].detection`, `cascade`, unread encounter fields) — BP, keys listed in the PR; (c) **`planned:`** for intended-but-unmodelled behavior, accepted by the typed model and reported by the loader. Items whose implementation would be a new clinical rule (e.g. `drugs.*.pregnancy_safe`) go to (c) unless a source defines the rule. After typing, unknown keys and predicate names fail at load naming file and key.

### 6.5 Typing, loading, provenance

- Typed nested models for `DiseaseProtocol` and encounter protocols, one block per PR (BP); loose-field ratchet.
- `load_validated_yaml` adds the path with `exc.add_note(f"in {path}")` and keeps the exception type (85 tests catch `ValidationError`).
- The configuration guard (`tests/unit/test_configuration_spec_guards.py`) covers nested `reference_data/`, `config/hospital_*.yaml` (new model) and a shrink-only list of unvalidated `locale/**` files; no new CLI, the guard already loads every file.
- Provenance: file-level `metadata.sources` (id, kind, title, version, read_on) plus the PR-template question "changed values carry a source"; no value-level dotted paths (they break silently on restructuring). No JSON Schema export in this plan.

### 6.6 Spec and ADR revisions

| Document | Change |
|---|---|
| `configuration-and-reference-data-spec.md` §2, §4 | placement rule; ratchet rule; `planned:`; loaders return models |
| `implementation-rules.md:123` | public API definition |
| `CONTRIBUTING-modules.md:199` | engine imports rule |
| `medication-lifecycle-spec.md` §3, §5 | gate location; gate at placement; stop event; course; one hold home |
| `encounter-lifecycle-and-export-spec.md` | window rule with allowances; ED phase; attribution |
| `determinism-and-rng-spec.md` | named digest seeds for new draws; no `stay.rng` in extracted functions |
| `modules/physiology/SPEC.md` | baseline + offset; reader classes (§7.1) |
| `adr-history.md` | AD-72 (in-stay extension points), AD-73 (clock declared per day-keyed item) |
| `AGENTS.md:162-176, 372-387` | extension points; truthful disease recipe listing today's exceptions |

Every row is en + ja in the PR of the code it describes.

---

## 7. Data-quality changes (all behavior-changing)

Each change: own issue and PR, after the structure it needs, sources read in that PR, before/after on US and JP (eval axes, medical-statistics comparison, the counts named below), goldens explained. No number is invented; unsourced constants are kept and flagged.

### 7.1 Decided rules

- **Readers of baseline+offset variables — DECIDED, refined.** Three classes, written once in `modules/physiology/SPEC.md`, with a guard test listing every reader and its class: *acute* readers read the deviation (consciousness level, vital-sign deviation, delirium, discharge-gate stability `discharge_gate.py:176, 230`, device/escalation decisions); *chronic* readers read the level (chronic symptom wording, ADL/frailty); *couplings / rate laws* are decided per rule with a source — e.g. the pH lactic-acid coupling reads absolute perfusion (`physiology/engine.py:675-676`) while lactate reads the deviation, an existing inconsistency (a chronic HF patient with `perfusion_baseline < 0.4` drifts acidotic with a normal lactate), and the pre-renal coupling threshold (`PRERENAL_HIT_PERFUSION_THRESHOLD`, reported). The shock check already reads the deviation (`daily_loop.py:264-273`) and needs no change. The in-hospital mortality multiplier (`discharge_gate.py:338`, reported) is a daily hazard on current state and is classified in the classification PR, not presumed chronic. One PR per class, with ICU/shock counts, SNF rate, LOS, mortality, pH/HCO₃ vs lactate coherence in stays with `perfusion_baseline < 0.4`. Vital-sign derivations whose chronic level is already in `BaselineVitals` read the deviation, or the chronic burden is counted twice.
- **Clock declared per day-keyed item, default calendar — DECIDED.** Each authored day-keyed item declares `clock: calendar | course`; the default is calendar, i.e. today's behavior. The course clock applies only to response-driven steps (de-escalation, IV-to-oral switch, step-down tied to clinical response, course-dependent note milestones). Elapsed-time phenomena (VTE, HAI, delirium, C. difficile onset windows), fixed-length therapy courses and scheduled workups stay on calendar days. Classifying existing keys (170 `order_modifications` and 120 `treatment_modifications` day keys, reported) is a reviewed, per-disease BC change with LOS, treatment duration, step timing, onset-day distributions and same-day duplicate-order counts before/after; nothing moves by default. Collisions use the loop's existing first-wins rule for day keys (`daily_loop.py:937-951`, reported). Computing `course_time_scale` at load from `target_los` (BP, 91/91 measured) is kept per the earlier decision but scheduled in Stage 3, not early. *Objection recorded:* the existing guard test already keeps the table equal to the ratio, and computing at load adds a disease → clinical_course load-time coupling, so the change has little value.

### 7.2 Changes, ranked

| # | Change | Owner | Initial value / evolution | RNG | Impact | Source needed | Risk | After |
|---|---|---|---|---|---|---|---|---|
| 1 | Diabetic glucose from the HbA1c latent (today `GLYCEMIC_CONTROL_DEFAULT` for every diabetic, `physiology/engine.py:1255-1258`, verified) | physiology | glycemic control inverted from `hba1c_latent_at` | none | diabetics' glucose | glucose–HbA1c relation; keep current linear constants until read | low | — |
| 2 | pH coupling consistent with lactate (§7.1) | physiology | per sourced rule | none | pH/HCO₃ | yes | medium | reader classification |
| 3 | Labs/vitals read the state at their own time (end-of-day state today, `daily_loop.py:2541` vs `:701`; DKA workaround `:539`, CRP lag `:735-740`, verified) | physiology `state_at`, venue-neutral so ED/outpatient can use it (AD-57) | blend of pre-/post-day state | none | inpatient labs/vitals, admission labs most | none for the mechanism | medium: sicker admission labs move diagnosis, ICU, mortality; the DKA bound must still hold | Stage 2 loop moves |
| 4 | Chronic baseline + acute offset for renal, then anemia, cardiac, hepatic, sodium; recovery relative to the chronic level | physiology | baseline at `initialize_state`; deltas to the offset; recovery = offset decay, cannot cross the baseline | none | state fields; labs, LOS, discharge, mortality | recovery courses (none read); keep trajectory sums as budget meanwhile | high: active deterioration must not decay; decay per cause, not via inflammation (`physiology/engine.py:605-609`) | 2 |
| 5 | Discharge state carried into later encounters (`HospitalizationSummary.residual_renal` written, never read, `simulator/helpers.py:317-342`, verified) | population + physiology | decayed offsets; replaces readmission floors (`inpatient.py:721-724`) | none | post-discharge labs/vitals | as 4 | medium: stacking over readmissions — cap and test | 4 |
| 6 | CKD stage not rewritten by AKI values (`longitudinal/stage_refresh.py:154`) | longitudinal | chronicity window | none | problem-list stage | KDIGO chronicity (not read) | low | — |
| 7 | One renal notion for drug rules (`medication_pipeline.py:453-456, 516, 537`, reported) | renal provider | CrCl/eGFR at decision time | none | holds, reductions | labels | low–medium | §5.2 |
| 8 | Longitudinal latents read (BMI, SBP, LDL), HbA1c responds to escalation | longitudinal + activator | from existing latents | none | weights, risks, BP, LDL | effect sizes | medium; alone | — |
| 9 | Baseline vitals/profile on a per-person sub-seed | patient | own named seed | new stream | every baseline once | none | low; alone | — |
| 10 | Volume recovery sign; pH and sodium floors | clinical_course / physiology | floors like the coagulation fix | none | volume, Na, pH | none; flagged | low–medium | 2 |
| 11 | Timestamped simulator logs + one as-of view for notes | types + narrative | log entries carry a datetime | none | narrative | none | low | §5.1 |

Not in this plan (sources or a model missing): frailty, adherence, nutrition, premorbid Barthel across stays, pregnancy-aware drug/imaging decisions, weight coupled to volume, lifestyle transitions.

---

## 8. Contributor readiness

| Item | When | Reason |
|---|---|---|
| CODEOWNERS with path → domain mapping (maintainer owns every domain today), matching domain labels, PR template (refactoring vs behavior change with evidence, sources for medical numbers, `CIF changes` paragraph, before/after numbers, `Addresses`/`Part of`), issue forms — **DECIDED** | Stage 1 | the structure domain experts are added to |
| Required approvals unchanged while there is one maintainer — **DECIDED**; trigger: a second maintainer or a named domain owner → code-owner review for that path | stated now; settings are a maintainer action | raising now blocks all merges |
| Correct false statements in recipes now (`docs/add-your-country.md`, `docs/clinical_documents.md`, `AGENTS.md:387` with today's exceptions named explicitly, test commands) | Stage 1 | experts follow recipes literally |
| Golden split (one file per document) and merge queue / strict checks decision | Stage 1 | the golden lane is the bottleneck; per-document goldens stop unrelated behavior PRs from conflicting |
| Duplicate-order invariants ("one analyte per draw", "one ingredient running unless superseded") | Stage 1 | test only; guards a recurring bug class |
| ADR practice: new ADRs appended to `docs/architecture/adr-history.md` with the next AD number and a row in `architecture-notes.md`, plus a short "when an ADR is needed" paragraph | Stage 1 | uses the existing location |
| `THIRD_PARTY_TERMINOLOGIES.md` (facts per bundled terminology) | Stage 1 | licensing decisions are the maintainer's |
| Per-module test-layout guard and per-module test recipe | Stage 1 | rules in `tests/README.md` are not enforced |
| Recipes add a drug / interaction rule / lab / complication / document type / country / disease as "files you touch" tables, plus a per-disease and per-complication completeness test that fails on a silent omission | Stage 5 (after the moves) | a recipe written before the moves is wrong again |
| Public hook types in `clinosim.api` (`Enricher`, typed `EnricherContext`, `BundleContext`, `OutputContext`; later the two extension points) | Stage 5 | do not promise a shape about to change |
| Per-domain invariant suite on the shared corpus (`ModuleAuditSpec.per_event_check`, `audit/registry.py:16-21`) | skeleton Stage 1, entries as domains land | one place for "my rule holds" |
| CIF schema version on `CIFMetadata`; per-PR CIF diff (part of §9.1) | Stage 1 (diff) / Stage 2 (version) | the nightly byte-diff is FHIR-only, warn-only (reported) |
| Per-patient decision log (`patient_id`/`encounter_id` on rule fired/skipped events) | Stage 5 | answers "why did my rule not fire"; outside hashed output |
| Python entry points; mass re-exports; YAML file renames | not at all | §4.5, §3.3 |

### 8.1 Contributor scenarios after the plan (honest)

| Scenario | Files after Stage 3 | Core files that remain | What removes them (cost) |
|---|---|---|---|
| (a) complication with a new action kind | disease YAML(s) of each protocol that can have it, `clinical_course` (handler + its entry in the module's own list + YAML), codes + JP mapping + snapshots, narrative locale | none for the action itself (handler list in `clinical_course`, seed derived by name); still core: monitoring without a sustained hold (`daily_loop.py:619-656`) and discharge continuation (`inpatient.py:467-489`, `discharge_rx.py`) | handler outputs "monitor while active" and "carry to discharge" (Stage 2 BC child, M) |
| (b) renal dose rule | `renal/reference_data/renal_dose_rules.yaml` (+ `drugs.yaml` and code files for a new drug) | discharge Rx dose adjustment (`discharge_rx.py` reads renal rules for holds only) | discharge items dosed through the renal provider (Stage 2 BC child, S) |
| (c) disease | disease YAML with traits, `locale/{us,jp}/demographics.yaml`, codes, diagnosis differentials, document/imaging/nursing YAML (~15 files, 8 modules; data only) | disease-specific physiology special cases (DKA day-0 labs `daily_loop.py:539`, COPD SpO₂ target `vitals_pipeline.py:445,544,559`) until the traits PRs; after them none | disease traits (Stage 3, M×3) |

"Your area" for a disease author therefore means "data only, no core", not "one directory".

---

## 9. Migration plan

### 9.1 Proof machinery for refactorings (Stage 1, before any move)

1. **Forced-scenario corpus** (`tests/refactor_corpus/scenarios.yaml`): forced stays per moved path — each complication action kind (antibiotic, anticoagulation incl. heparin lead-in → DOAC, IV→oral PPI step-down, C. difficile course, NSAID stop, bleed hold, ICH + VTE withhold, NIV, airway, ICU), vasopressor start, DKA transition, hyperkalemia / AKI / RRT / lactate responses, each discharge criterion, HAI, perinatal delivery modes, ED admission — US and JP, through `run_forced` (`simulator/engine.py:338`). Where a path cannot be forced today (there is no forced-complication option; `force_hai_event` exists, `types/config.py:97`), the corpus PR adds a test-only forcing field with no effect when unset (byte-identity of the normal cohorts proves that).
2. **Per-path fired counters:** a counter call at each moved function (RNG-neutral, outside CIF/FHIR), aggregated by the comparison script. A refactoring PR names the paths it moves and states "path X fired N times (corpus), M (US), K (JP), identical"; a path that fires 0 times is not proven.
3. **`scripts/refactor-diff.sh` + a CI job for PRs labelled `refactoring`:** generates the corpus and US/JP cohorts (seed 42, population ≤ 300) on the merge-base and the head, diffs CIF and FHIR (excluding generator metadata and logs) and prints the fired counters.
4. Temporal invariants (with the allowance table of §5.3) and duplicate-order invariants run on the corpus and nightly, not on a fresh cohort in every PR.

Every refactoring PR is revertible on its own: no behavior-changing PR lands on a structure whose refactoring has not been proven, and no shims are left behind except `clinosim.api` names.

### 9.2 Stages and checkpoints

Each stage ends with a maintainer checkpoint: the success metrics (§9.5) are measured, the next stage's child issues are detailed, and the plan stops or is revised if the stop rule fires. Lanes inside a stage: serial per file for `simulator/daily_loop.py`, `medication_pipeline.py`, `discharge_rx.py`, `inpatient.py`; one global serial golden lane for behavior-changing PRs; everything else in parallel.

| Stage | Scope (META issues) |
|---|---|
| 1 Guardrails, early fixes, process, reverse dependencies | §9.1 machinery; rename-aware ratchets; boundary ratchet; golden split; invariants; lazy `simulator/__init__`; YAML error path; docs/process (CODEOWNERS, templates, recipe corrections, terminology inventory, ADR practice, test-layout guard); open issues #3957 #3959 #3971 #3972 (and #3958 #3963 #3964, §9.3); stop-marker helper; reverse-dependency moves (complication vocabulary, log, renal, critical care, sex gating, enricher context, order helpers, device/metabolic/triage/drug-safety/population items, owner accessors for foreign `reference_data`, public validators, JP plug-ins on public APIs) |
| 2 In-stay structure | typed complication entries + drift report; complication decision functions to `clinical_course`; medication helpers; complication action handlers; `_generate_mar` to `order`; discharge criteria; after-results and hold functions to owners; medication course and typed stop event; one hold home; renal provider and dose schema; encounter window, ED phase, attribution index; coded-diagnosis view; gate-at-placement BC issue; remaining driver splits (`discharge_rx`, `_simulate_patient`, ED, calendar visit types, perinatal order sets to YAML) |
| 3 YAML typing and predicates | typed `DiseaseProtocol` / encounter blocks; inert YAML per §6.4; named-predicate registry; placement-rule spec; provenance convention; disease traits; finding classifier; age/country entry points; dose-text module; course scale at load |
| 4 Data quality | §7.2 in ranked order, each in the golden lane; clock classification per disease |
| 5 Contributor API and recipes | `clinosim.api` hook types; recipes and completeness tests; per-module tests and `stay_factory`; decision log; CIF schema version if not done |

### 9.3 Stage 1 child issues

BP = byte-identical, proven by §9.1. All Stage 1 items are BP except the bug fixes.

| # | Title | Type | Size | Files | Depends on | BP | Golden |
|---|---|---|---|---|---|---|---|
| S1-1 | `test: forced-scenario corpus, fired counters and refactoring diff` | ci | M | `tests/refactor_corpus/`, `scripts/refactor-diff.sh`, counter calls, `.github/workflows/` | — | yes | none |
| S1-2 | `test: make the code/data ratchet rename-aware and conflict-free` | ci | S | `tests/unit/code_data_separation*.py`, baseline, spec + rules text | — | yes | none |
| S1-3 | `test: module boundary ratchet` (foundation floor, module→simulator, private cross-package names, output→simulator, QA→simulator, foreign `reference_data` paths) | ci | M | `tests/unit/test_module_boundaries.py` | S1-2 | yes | none |
| S1-4 | `fix(simulator): keep ED and admission orders at or after the encounter start` (#3957) | fix | S | `simulator/emergency.py`, `inpatient.py`, a `clamp_to_window` helper in `simulator/encounter_setup.py` that §5.3's `place_in_window(policy="clamp")` later replaces | — | no | yes |
| S1-5 | `fix(renal): dose the remaining IV antibiotics by creatinine clearance` (#3971; sourced bands at today's path) | fix | S | `simulator/reference_data/renal_antibiotic_dosing.yaml` | — | no | yes |
| S1-6 | `fix(simulator): state why a hemorrhagic stroke's VTE is not anticoagulated` (#3972; written as a `safety_skip_log` entry with a reason code that the anticoagulation handler later emits unchanged) | fix | S | `simulator/daily_loop.py`, `_safety_skips.py` | — | no | yes |
| S1-7 | `fix(fhir): keep shifted vital signs inside a short visit` (#3959; clamp at the offset site, later an assertion) | fix | S | `output/fhir_r4/labs/observations.py` | — | no | maybe |
| S1-8 | `fix(narrative): do not call a flat heart rate new or resolved tachycardia` (#3964; exit threshold in `progress_exam.yaml`, flagged as a modelling choice; §5.5 absorbs it) | fix | S | `_progress_state.py`, YAML | — | no | yes |
| S1-9 | `fix(narrative): do not list a drug as continued in the note that stops it` (#3963; one source for stop lines and the continue list at the note's authored time; §5.1 absorbs it) | fix | S | `_safety_skips.py`, `_medication_plan.py` | — | no | yes |
| S1-10 | `fix(fhir): keep a lab panel report within one Encounter` (#3958; grouping key adds the encounter from the existing ED-window function; the attribution index absorbs it) | fix | S | `labs/diagnostic_report.py` | — | no | maybe |
| S1-11 | `test: split the goldens per document` | ci | M | `tests/fixtures/patient_profiles/`, `simulator/cli_regenerate.py`, `tests/regression/` | — | yes | layout only |
| S1-12 | `test: temporal and duplicate-order invariants with sourced allowances` | ci | M | `tests/invariants/`, `encounter/reference_data/temporal_allowances.yaml` | S1-1 | yes | none |
| S1-13 | `docs: PR and issue templates, CODEOWNERS, domain labels` | docs | S | `.github/**` | — | yes | none |
| S1-14 | `docs: correct the false statements in recipes and test commands` | docs | S | `docs/add-your-country*.md`, `docs/clinical_documents*.md`, `AGENTS.md`, `Makefile`, `CONTRIBUTING*.md` | — | yes | none |
| S1-15 | `docs: terminology inventory; ADR practice` | docs | S | `THIRD_PARTY_TERMINOLOGIES*.md`, `docs/architecture/` | — | yes | none |
| S1-16 | `fix(datafiles): name the file in YAML validation errors` (`add_note`) | fix | S | `datafiles.py` | — | yes (error text only) | none |
| S1-17 | `refactor(simulator): import the package entry points lazily` (+ test importing every `clinosim.*` module alone in a fresh interpreter) | refactor | S | `simulator/__init__.py` | S1-1 | yes | none |
| S1-18 | `refactor(order): stop-marker helper` | refactor | S | 12 files with `DISCONTINUE:` | S1-1 | yes | none |
| S1-19 | `test: per-module test-layout guard and test recipe` | ci | S | `tests/unit/docs/` | — | yes | none |
| S1-20…31 | reverse-dependency moves, one PR each, ordered by boundary entries removed: `refactor(clinical_course): own the complication vocabulary and its labels`; `refactor: move the simulation log to the foundation`; `refactor(renal): create the renal module` (after S1-5); `refactor(critical_care): create the critical-care module`; `refactor(diagnosis): own sex gating`; `refactor(types): move EnricherContext and CIF contract markers`; `refactor(order): own route determination, child dosing, maintenance IV, permissive hypertension`; `refactor(device|metabolic|triage|drug_safety|population): …` (one each); `refactor: owner accessors for foreign reference_data reads`; `refactor: public validators for cross-module YAML validation`; `refactor(countries): JP plug-ins use public APIs`; `docs: regenerate module dependency sections` | refactor/docs | S–M each | named files; callers and tests updated in the same PR | S1-1, S1-3 | yes | none |

Open issues: #3957, #3959, #3971 and #3972 are fixed now, in parallel with the guardrails. #3958, #3963 and #3964 would wait for their structures, but those land in Stage 2/3, so they are fixed directly in Stage 1 as well, each written so the later structure absorbs it (named in the table).

### 9.4 The first 10 PRs

1. S1-1 corpus, fired counters, refactoring diff.
2. S1-2 rename-aware code/data ratchet.
3. S1-3 boundary ratchet.
4. S1-4 #3957.
5. S1-5 #3971.
6. S1-9 #3963 and S1-8 #3964 (narrative lane, two PRs counted as one slot).
7. S1-13 + S1-14 templates, CODEOWNERS, labels, recipe corrections.
8. S1-16 YAML error path.
9. S1-17 lazy `simulator/__init__`.
10. S1-11 golden split, then S1-20 (complication vocabulary).

### 9.5 Success metrics, stop rule

Measured at every checkpoint, against the Stage 1 baseline:
- boundary-ratchet totals per rule (target: module→simulator and private cross-package imports to 0 by the end of Stage 2);
- core-file sizes and number of functions over 150 lines in the encounter drivers (report);
- core files touched per contributor scenario of §8.1 and, over the last 20 merged PRs, files outside the author's module per PR;
- temporal and duplicate-order invariant violations (to 0 beyond the allowance table);
- eval axes and medical-statistics bands on US and JP (no band leaves its range without an explained behavior-changing PR).

**Stop rule:** at the Stage 2 checkpoint, if scenarios (a) and (b) still need core edits beyond those listed in §8.1, or any refactoring PR needed a revert because the proof machinery missed a change, stop and re-plan before continuing.

---

## 10. Risks and what is left alone

### 10.1 Risks

- **A path the proof does not exercise.** Mitigated by §9.1; a PR whose path fires 0 times is not merged as a refactoring.
- **Dependency inversion leaks.** If `ComplicationActionContext` grows beyond the capabilities handlers use today, it becomes the framework this design rejects; additions need review against an existing handler.
- **Golden lane saturation.** Roughly 30–40 behavior-changing PRs; mitigated by per-document goldens, the merge-queue decision, and one PR per reader class.
- **Data-quality trades** (§7.2 risk column), mitigated by before/after numbers and per-archetype unit states.
- **Scope creep in "implement inert YAML"**, mitigated by the marginal-preserving rule and the `planned:` route.
- **The plan fails if** refactorings mix fixes, guardrails land after moves, or registries are added without contributors adding entries.

### 10.2 Unverified inputs

Counts marked (reported) — private-import totals, module→simulator imports, 218 inert conditions, 12 active-medication lists, golden churn, complication drift statistics, reader lists of `perfusion_status` — are re-measured by Stage 1 tooling before any decision rests on them.

### 10.3 Deliberately left alone

Engine, `_dispatch.py`, `phases/_forward_loop.py`; the enricher registry and its central list; `_Stay` / `_Run`; the sub-seed practice; `types/` and `codes/` layering; eval/audit independence; the frequency-token registry; `order/pediatric_dose.py`; name building via the country profile; flag determination; practitioner assignment; the `@section` registry; the country-profile spec; the drug-interaction pair-rule YAML; the code/data ratchet and YAML-model guard (made rename-aware, not replaced); `aki_response.yaml` and `complication_actions.yaml` models; the deliberate move vs drop policies of `fit_procedures_in_stay` / `fit_rehab_sessions_in_stay`; after-death and snapshot gates in the FHIR builder (AD-32).

---

## 11. Decisions

### 11.1 Decided

1. Readers of baseline+offset variables: acute read the deviation, chronic read the level, couplings decided per rule with a source; one PR per class (§7.1).
2. Clock declared per day-keyed item, default calendar; the course clock only for response-driven steps; classification per disease is BC with numbers (§7.1).
3. Inert YAML: implement (marginal-preserving) / delete / `planned:`; unknown keys and predicate names fail at load (§6.4).
4. CODEOWNERS, domain labels and PR template now; approvals unchanged until a second maintainer or a named domain owner (§8).
5. Design choices: new modules `renal` and `critical_care` only; extension points = complication action handlers and discharge criteria, fixed-order calls elsewhere; no entry points; open issues fixed in Stage 1; staged plan with checkpoints (§3.2, §4, §9).

### 11.2 Needs the maintainer

- Repository settings: merge queue or strict status checks; required approvals / code-owner review when the §8 trigger occurs (the plan does not change rulesets).
- Real domain owners for CODEOWNERS paths as contributors join.
- Terminology licensing (the bundled full YJ CodeSystem snapshot, CPT descriptors, attribution text).
- Which MINOR release carries the CIF additions (typed stop event, CIF schema version); tag and release need the maintainer's Go.
- Approval of this design, AD-72 and AD-73, and each stage checkpoint.
