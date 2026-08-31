You are finishing a magazine translation into {target_language}. One unit of
the page was translated, but a human editor has ruled how one term in it must
be rendered, and the translation on the page does not honour that ruling.

The unit, in its source language:

{unit}

The ruling: wherever this unit's source says

{term_source}

the {target_language} text must render it, letter for letter, as

{term_target}

Rules.

1. Translate the whole unit into {target_language} again, naturally and
   completely.
2. The ruled rendering must appear in your output exactly as given above.
   Do not decline it, vary its spelling, or substitute your own rendering.
3. Everything outside the ruled term is yours to translate as well as you
   can; only the ruled term is pinned.
4. Return the translation alone. No quotation marks around it, no
   explanation.

Answer with JSON and nothing else, in exactly this shape:

```json
{"output": "..."}
```
