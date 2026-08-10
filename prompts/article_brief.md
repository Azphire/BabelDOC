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
- "names": an array of the personal, place and organisation names occurring in
  the text above, each written exactly as it appears there. Source form only:
  do not translate them here. An empty array when the text carries none.

Judge only from the text above. Do not add a name, a claim or a subject that
does not appear in it, and do not describe the brief itself.

This is the shape of the answer, not its content:

{"title_translation": "...", "register": "...", "names": ["...", "..."]}
