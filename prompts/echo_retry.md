You are finishing a magazine translation into {target_language}. One short
unit of the page came back from translation exactly as it went in, and a
person reviewing the page needs to know whether that was right.

The unit:

{unit}

Rules.

1. If the unit is a personal name, render it the way {target_language}
   ordinarily writes a foreign personal name: sounded out for a language
   written in characters, and in the established form where one exists.
2. If the unit is a role, a title, a caption or a short phrase, translate it
   into {target_language}.
3. If the unit genuinely stands as it is in a {target_language} publication --
   a product or brand name, an acronym, a URL, an e-mail address, a postal
   code or a line of code -- return it exactly unchanged. Returning it
   unchanged is a correct and useful answer.
4. Return the text alone. No quotation marks around it, no explanation, no
   note about which rule applied.

Answer with JSON and nothing else, in exactly this shape:

```json
{"output": "..."}
```
