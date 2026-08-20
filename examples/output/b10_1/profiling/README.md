# run_all cost, measured on b10.1

The log beside this file is one interrupted `python spec_checks/run_all.py` over
the whole history: started 16:03, stopped by hand at 18:30 with 27 of 34 gates
finished and the 28th still running, 147 minutes of gate time spent. It is kept
because it is the measurement W-B10-04 rests on, and because the number is not
recoverable from a run nobody let finish twice.

The split the waiver introduces is not a stopwatch reading. A gate is `sweep`
where it asks `spec_checks/artifacts.py` for a built document, because a cold
slot means re-running the pipeline over a sample to answer one assertion; it is
`fast` where every document it asserts on is a stub it builds itself or evidence
a batch froze. Each gate declares its own `GATE_SET`, `run_all --set` selects on
it, and a gate that declares nothing is refused rather than defaulted.

The declaration and the clock agree: every gate over two and a half minutes is
in the sweep set bar two, and both of those (`b3_3`, `b8_4`) spend their time on
their own computation rather than on a build.

## sweep: 18 gates declared, 18 measured, 140.9 min

| gate | minutes |
| --- | --- |
| `spec_check_b2.py` | 20.88 |
| `spec_check_b6.py` | 16.09 |
| `spec_check_b7_5.py` | 15.43 |
| `spec_check_b5.py` | 12.71 |
| `spec_check_b2_5.py` | 12.56 |
| `spec_check_b6_2.py` | 9.94 |
| `spec_check_b7_2.py` | 9.58 |
| `spec_check_b2_2.py` | 9.15 |
| `spec_check_b4.py` | 6.85 |
| `spec_check_b2_3.py` | 5.23 |
| `spec_check_b3.py` | 4.67 |
| `spec_check_b8_2.py` | 3.93 |
| `spec_check_b8.py` | 3.83 |
| `spec_check_b2_1.py` | 3.66 |
| `spec_check_b2_7.py` | 2.73 |
| `spec_check_b7.py` | 2.39 |
| `spec_check_b0.py` | 0.65 |
| `spec_check_b1.py` | 0.60 |


## fast: 16 gates declared, 9 measured, 6.4 min

| gate | minutes |
| --- | --- |
| `spec_check_b3_3.py` | 2.96 |
| `spec_check_b8_4.py` | 2.34 |
| `spec_check_e2.py` | 0.40 |
| `spec_check_b9_1.py` | 0.22 |
| `spec_check_b9_2.py` | 0.19 |
| `spec_check_e1.py` | 0.08 |
| `spec_check_b7_3.py` | 0.07 |
| `spec_check_b8_3.py` | 0.06 |
| `spec_check_e0.py` | 0.06 |


Seven fast-set gates are unmeasured here: the run was stopped inside
`spec_check_b9_2r.py` and never reached `b9_3`, `b9_4`, `b9_5`, `b9_6`, `b9_7`
or `b10_1`. From the `--fast` tier sweep of the same day they are seconds each,
which puts the whole fast set under ten minutes.

The fast set was then run end to end and is the other log beside this file:
16 of 16 gates green in 12.7 minutes, which is the per-batch condition W-B10-04
puts in place of the full sweep.
