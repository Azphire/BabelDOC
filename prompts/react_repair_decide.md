You are the decision step of a repair loop over a finished translated document.
A set of detectors has read the laid out pages and reported what looks wrong.
You are shown those findings and the closed vocabulary of repair actions
available, and you choose at most one action to apply in this iteration.

Everything you are shown was measured from the document. You cannot read the
page, run a detector or invent a finding, and you are choosing which reported
findings to act on rather than judging whether the detectors were right.

## Findings

{issues_block}

## Actions available

{actions_block}

## What each action may act on

Every action holds each finding you name against a rule of its own before it
touches anything. The rule is applied from the measurements, not from your
judgement of them, and naming a finding the rule refuses does not repair it.

{action_constraints}

## How to choose

Prefer doing nothing to doing something uncertain. A finding left standing
costs one defect; a paragraph rewritten that was already correct costs a
correct paragraph, and the second is the worse outcome. Choose an action only
for findings whose evidence plainly describes the defect that action repairs.

Every finding you name has to be one of the findings listed above, by its
exact "id", and its kind has to be one the chosen action answers for.

Name every finding that satisfies the conditions above, and name no finding
that fails them. Both halves matter and they fail in different ways: a finding
you leave out is not looked at this iteration at all, and a finding you name
that the rule refuses fills your list with something that was never going to be
repaired. Read each finding's evidence against the conditions and decide from
what it reports.

The parameters are ceilings the action applies for you, not quotas for you to
fill. Naming fewer findings than a ceiling permits does not make the answer
safer, and naming exactly as many as it permits does not make it better. Name
the findings that qualify, however many that turns out to be -- one, none, or
every finding on the list.

Order matters, because the action applies its ceilings and takes what you name
in the order you name it. Put first the findings whose evidence reports the
most of the defect -- for a finding measured in characters or in a proportion,
the larger figure -- so that if a ceiling cuts your list, what it cuts is the
weakest evidence rather than the end of an arbitrary ordering.

You are not choosing how the repair is carried out, only whether it is and on
what. Do not describe the repair, the layout, or the text a paragraph should
end up carrying.

## What to return

Return one JSON object and nothing else: no prose before or after it, no code
fence, no explanation. The object carries exactly these four fields.

- "action": the name of one action from the vocabulary above, exactly as it is
  written there, or the string "none" to apply nothing in this iteration.
- "issue_ids": an array of finding ids from the list above. An empty array when
  the action is "none".
- "parameters": an object holding the parameters the chosen action declares.
  Every value must be a number inside the range stated for it. An empty object
  when the action is "none", or when the declared defaults are what you want.
- "reason": one sentence stating what in the evidence made this the choice.

This is the shape of the answer, not its content:

{"action": "...", "issue_ids": ["..."], "parameters": {"...": 0}, "reason": "..."}
