You are preparing a short brief for a translator who is about to translate one
magazine article into {target_language}. The article will be translated in
batches of a few paragraphs at a time, and each batch will be shown this brief,
so that the whole article comes out in one voice and with one set of names.

You are shown the article's heading and the opening of its body text. Either may
be empty, and the body excerpt may stop mid-sentence.

## Heading

{title_paragraph}

## Opening of the body text

{first_body_excerpt}

## What to return

Return one JSON object and nothing else: no prose before or after it, no code
fence, no explanation. The object carries exactly these three fields.

- "title_translation": the heading rendered in {target_language}. If no heading
  was shown, render a short title in {target_language} for the subject the
  opening text is about.
- "register": one sentence, in {target_language}, describing the register the
  article should be translated in -- how formal it is, whether it addresses the
  reader, whether it is reportage, argument, interview or narrative, and
  anything about its voice a translator would otherwise have to guess at
  separately for every batch.
- "names": the proper names -- of people, places, organisations, peoples,
  species and anything else that names one particular thing -- which occur in
  the text above and will have to read the same way everywhere in the article.
  Each entry is an object with two fields: "source", the name exactly as it
  appears above, and "suggested_translation", how that name should read in
  {target_language} every time it occurs. Give a {target_language} rendering
  wherever one is idiomatic; where the convention in {target_language} is to
  leave the name in its original script, repeat the source form as the
  suggested translation. An empty array when the text carries no such name.

Judge only from the text above. Do not add a name, a claim or a subject that
does not appear in it, and do not describe the brief itself.

This is the shape of the answer, not its content:

{"title_translation": "...", "register": "...", "names": [{"source": "...", "suggested_translation": "..."}]}
