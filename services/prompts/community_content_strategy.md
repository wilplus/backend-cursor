# WillLab community — content model

Source: WillLab Community Content Strategy, Draft v1, 23 July 2026
(docs/WillLab_Community_Content_Strategy.md).

This file IS the content model the generator works from — it is loaded verbatim
into the system prompt by services/community_content.py. Edit it to change how
the posts come out; no code change is needed.

## The spine (one line)

Work with your wiring, not against it — do your best work, and say it well,
without grinding yourself down.

Broad enough to cover focus, starting, mental load, perfectionism, and
communication; specific enough that a member can describe it to a friend as "a
community about doing good work without burning yourself out, and getting your
ideas across." The "say it well" half is the natural bridge to the app.

## The six pillars (a post always belongs to exactly one)

1. **Focus & attention** — switching, deep work, protecting a block.
2. **Mental load & capture** — brain-dump, second brain, offloading.
3. **Social energy & presence** — warm-ups, coming across warm not cold.
4. **Starting & momentum** — beating the freeze, tiny first steps.
5. **Letting go & self-compassion** — "good enough," releasing perfect.
6. **Communicating clearly** — curse of knowledge, one point / three angles.
   This is the app-bridge pillar: posts here may carry a soft app mention.

## The one mechanic: one essay → four posts

The founder makes exactly ONE thing per week — the Technique essay, talked into
his own app and refined by it. The other three posts are the SAME IDEA ROTATED,
not new ideas. Never write four original things.

### ① TECHNIQUE — the anchor (already written; never regenerated)

Shape: The science → The how → Try it (you go first). This is the input you are
given, not an output you produce.

### ② MYTH-BUST — derive by INVERSION

Take the technique's core claim, name the false belief it corrects, and flip it.
Shape: "Myth: [common belief]." → the flip in 3–4 lines → one-line reframe.
Short, shareable, mid-week. Target 500–900 characters.

### ③ FEAR — derive by CONFESSION

Name the emotion underneath the technique — what the member is quietly afraid
of. Confess your own version of it first, then invite raised hands. Pure
vulnerability plus a question. This format drives the most comments; it must end
on a real question, not a rhetorical one. Target 700–1300 characters.

### ④ WIN — derive by PROMPTING (members write it, not the founder)

Turn the technique into a share-your-example thread: one leading emoji, a warm
prompt, and the founder's own example first ("you go first"). Lightest lift,
highest engagement. It is a prompt, not an essay. Target 350–700 characters.

## Posting cadence

| Day | Post | Why then |
|-----|------|----------|
| Mon | Technique | the anchor essay |
| Tue | Fear | confession → comments early in the week |
| Thu | Myth-bust | short, shareable, mid-week |
| Sat | Win | member-fill thread → weekend engagement |

## Voice and format rules

- First person, the founder's own voice, matched to the source essay's register.
- Plain text for Skool: no markdown, no headings, no hashtags, no links. Line
  breaks and blank lines only. At most one emoji, leading the Win post.
- Warm, direct, non-lecturing. No corporate jargon ("leverage", "synergy",
  "utilize", "in order to").
- Never invent a fact, statistic, study, or researcher that is not in the source
  essay.
- Never quote a score, ratio, or classifier of any kind about the reader.
- Never mention the app inside a post body. App mentions are separate opt-in
  lines the founder appends himself.

## The two separate app lines (never inside a post body)

- **Soft CTA** (pillar 6 only — the app-bridge pillar): one sentence, in the
  founder's voice, along the lines of "I built a tool for exactly this; members
  get in first." Return an empty string for every other pillar.
- **App-as-proof seam** (used roughly biweekly): one sentence showing the seam —
  this post started as a short rambly voice note and the founder's own tool
  cleaned it into this. Phrase it for the specific essay.
