# Transparent scoring

The default direct confidence score is:

```text
0.55 × evidence quality
+ 0.20 × source independence
+ 0.15 × falsifiability
+ 0.10 × explicit boundary
- contradiction penalty
- freshness penalty
```

Evidence quality combines evidence kind and source quality. Multiple supporting sources use a
bounded cumulative calculation; repeated weak assertions cannot inflate confidence without limit.

After direct scoring, required dependencies apply the weakest-link rule:

```text
propagated(claim) = min(direct(claim), propagated(each required dependency))
```

Scores communicate the state of the recorded evidence. They do not measure metaphysical truth,
legal sufficiency, or safety certification.

