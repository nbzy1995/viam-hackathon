# Final holdout v2 author note

Frozen file: `config/text-generalization-holdout-v2.json`

SHA-256: `c64e5472b5d4bee3619e6320eb171f94b1be0c864e88faf536fbeca2419b33a0`

Authored independently from the supplied task contract; the only project source read was `config/text-task.schema.json`. No production prompt, implementation, current evaluation result, model execution, or robot action was accessed during authoring. The earlier holdout authoring context was available, so independence does not mean absence of all earlier evaluation context.

Twelve synthetic cases were frozen before model access: seven actionable and five non-actionable. Structured translation tolerance is 0.2 mm. Explanatory prose is assessed by semantic factual rubrics, not exact wording.

| Family | Cases |
| --- | ---: |
| camera_frame | 2 |
| measured_geometry | 2 |
| stacking_roles | 2 |
| sequential_correction_restore | 1 |
| missing_evidence | 2 |
| ambiguity | 1 |
| status_evidence | 1 |
| unsupported_operation | 1 |

Ambiguity risks: corrected multi-step language intentionally requires ordered interpretation and reference resolution. Relative-distance synonyms use the supplied default. The ambiguous-target case must not acquire facts absent from its scene. Physical support feasibility, grasp validation, and path safety are outside this language-only oracle. Paired cases are dependent and should not be counted as twelve statistically independent samples; one multi-feature case limits diagnosis. Status and unsupported-operation prose require manual review. This compact synthetic holdout does not estimate field reliability.

Preserve the frozen file and first-run record. Do not tune against these cases or treat reruns after inspection as unseen evaluation.
