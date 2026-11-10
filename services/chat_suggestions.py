"""Will's suggestions for a new host's chat, the blank setup's choices
(N612 items 2 and 4, N616 items 1 and 2, N620's cost rules), word for word
from the locked prototype ``docs/design/the-blank-setup-2026-11-10/
the-blank-setup.html`` (its ``KNOWN``, ``generic``, ``PROMPT`` and
``clean``).

  * ``suggest``: what fits the work a host typed after "What do you do?":
    a profession the prototype knows answers from its built-in suggestions,
    with no provider call; any other asks the cheap model once, with the
    prototype's prompt and a maximum length, and whatever it gives is
    cleaned, every gap filled from the generic suggestions. With no
    provider answer the generic suggestions stand alone (FIRST-16). Nothing
    is copied from Artur's chat or anyone else's (N612 item 2).

The one provider call runs inside the caller's processing-authorization
scope (the route's ``phase1_provider_route``). Pure apart from it.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── The prototype's building blocks, word for word ─────────────────────
SEND = {'rec': ['A recording', 'They talk. You listen.'],
 'text': ['A message', 'They write to you.'],
 'photo': ['A photo', 'They show you something.'],
 'file': ['A file', 'A document or a clip.']}

OUT = {'answer': ['An answer', 'One message, in words.'],
 'words': ['Their own words, tidied', 'What they said, made clear.'],
 'todo': ['What to do next', 'A short list of steps.'],
 'mark': ['A mark on what they sent', 'You point at the spot.']}

WHO = [['I draft the answer. You check it and send it.', 'shadow'],
 ['Only you answer. I stay quiet.', 'you'],
 ['I answer at once. You correct me.', 'assistant']]

OPTS = [['Yes', 'Somewhat', 'No'], ['Yes', 'Not sure', 'No'], ['A lot', 'A little', 'None']]

PRICES = [2, 1, 3, 5]

KNOWN = {'speaking coach': {'line': ['People come to you to speak so others listen.',
                             'People come to you to feel sure when they talk.'],
                    'send': ['rec', 'text', 'file', 'photo'],
                    'out': ['words', 'answer', 'todo', 'mark'],
                    'hello': ["Hi. Record a short talk, and I'll tell you what worked.",
                              "Welcome. Say it out loud once. We'll make it better together."],
                    'qs': ['What talk are you getting ready for?',
                           'Who will be listening?',
                           'What is the one thing they should remember?'],
                    'taps': [['Practise a talk',
                              'Get ready for a pitch',
                              'Answer a hard question'],
                             ['Sound more sure', 'Stop rushing', 'Open strongly']],
                    'models': [{'q': 'Does the speaker sound sure?',
                                'opts': ['Yes', 'In between', 'No'],
                                'says': 'You sound sure at the start, and less sure near the '
                                        'numbers.'},
                               {'q': 'Do they pause before the main line?',
                                'opts': ['Yes', 'A little', 'No'],
                                'says': 'You ran through your main line. Stop before it.'},
                               {'q': 'Are they rushing?',
                                'opts': ['Yes', 'A little', 'No'],
                                'says': 'You speed up in the middle. Slow down there.'},
                               {'q': 'Is the opening clear?',
                                'opts': ['Yes', 'Somewhat', 'No'],
                                'says': 'Your opening is clear. People know what this is '
                                        'about.'}],
                    'sample_in': 'A two-minute talk about checking quotes.',
                    'sample_out': 'Every quote we publish is checked twice. First by the '
                                  'editor who found it, then by someone who was not in the '
                                  'room.'},
 'trichologist': {'line': ['People come to you with hair and scalp worries.',
                           'People come to you to keep their hair healthy.'],
                  'send': ['photo', 'text', 'rec', 'file'],
                  'out': ['answer', 'todo', 'mark', 'words'],
                  'hello': ['Hi. Send me a photo of your scalp, and tell me what worries you.',
                            "Welcome. Show me, and I'll tell you what I'd do first."],
                  'qs': ['What worries you about your hair?',
                         'How long has it been like this?',
                         'What do you wash it with?'],
                  'taps': [['Look at my scalp', 'My hair is falling out', 'Which shampoo'],
                           ['An itchy scalp', 'After colouring', 'Thin hair']],
                  'models': [{'q': 'Is this a dry scalp?',
                              'opts': ['Yes', 'Somewhat', 'No'],
                              'says': 'Your scalp looks dry here. That is a common place to '
                                      'start.'},
                             {'q': 'Is the hair thinning here?',
                              'opts': ['Yes', 'Somewhat', 'No'],
                              'says': 'The hair is thinner at the crown than around it.'},
                             {'q': 'Is the skin red?',
                              'opts': ['Yes', 'Somewhat', 'No'],
                              'says': 'The skin looks a little red. Go gently with what you '
                                      'put on it.'},
                             {'q': 'Are there flakes?',
                              'opts': ['A lot', 'A little', 'None'],
                              'says': 'There are some flakes near the roots.'}],
                  'sample_in': 'A photo of the top of my head.',
                  'sample_out': 'Thank you. I can see the crown clearly. Here is what I '
                                "notice, and what I'd do first."},
 'language teacher': {'line': ['People come to you to speak a new language.',
                               'People come to you to stop making the same mistakes.'],
                      'send': ['rec', 'text', 'file', 'photo'],
                      'out': ['words', 'answer', 'todo', 'mark'],
                      'hello': ["Hi. Say or write a few sentences. I'll show you the one thing "
                                'to fix.',
                                "Welcome. Tell me about your day, in the language you're "
                                'learning.'],
                      'qs': ['Which language are you learning?',
                             'Why do you want to learn it?',
                             'What is hardest for you?'],
                      'taps': [['Correct my sentence',
                                'How do I say this',
                                'Practise speaking'],
                               ['Explain a rule', 'Get ready for an exam', 'New words']],
                      'models': [{'q': 'Is there a mistake that changes the meaning?',
                                  'opts': ['Yes', 'Not sure', 'No'],
                                  'says': 'One word changes what you mean. Look at the verb.'},
                                 {'q': 'Is the past tense right?',
                                  'opts': ['Yes', 'Somewhat', 'No'],
                                  'says': 'Two past forms slipped: went, bought.'},
                                 {'q': 'Does it sound natural?',
                                  'opts': ['Yes', 'Somewhat', 'No'],
                                  'says': 'It is correct, and a native speaker would say it '
                                          'shorter.'}],
                      'sample_in': 'Yesterday I go to the shop and buyed bread.',
                      'sample_out': 'Yesterday I went to the shop and bought bread.'},
 'fitness coach': {'line': ['People come to you to move well and get stronger.',
                            'People come to you to train without getting hurt.'],
                   'send': ['file', 'photo', 'text', 'rec'],
                   'out': ['mark', 'todo', 'answer', 'words'],
                   'hello': ["Hi. Send a clip of one exercise. I'll tell you the first thing "
                             'to fix.',
                             'Welcome. Show me how you move.'],
                   'qs': ['What are you training for?',
                          'How often do you train?',
                          'Does anything hurt?'],
                   'taps': [['Check my form', 'Plan my week', 'Coming back after a break'],
                            ['What to eat before', 'A pain when I train', 'Get stronger']],
                   'models': [{'q': 'Do the heels stay down?',
                               'opts': ['Yes', 'Somewhat', 'No'],
                               'says': 'Your heels lift as you go down. Fix that first.'},
                              {'q': 'Is the back straight?',
                               'opts': ['Yes', 'Somewhat', 'No'],
                               'says': 'Your back rounds at the bottom.'},
                              {'q': 'Is the movement slow enough?',
                               'opts': ['Yes', 'Somewhat', 'No'],
                               'says': 'You drop fast. Count to three on the way down.'}],
                   'sample_in': 'A clip of my squat from the side.',
                   'sample_out': 'Look at the moment just before the bottom.'}}

GENERIC = {'line': ['People come to you for help from a {spec}.',
          'People come to you to learn what a {spec} knows.'],
 'send': ['text', 'rec', 'photo', 'file'],
 'out': ['answer', 'todo', 'words', 'mark'],
 'hello': ["Hi. Tell me what you need, and I'll help.",
           'Welcome. Ask me anything about what I do.'],
 'qs': ['What do you need help with?',
        'What have you tried so far?',
        'What would a good result look like?'],
 'taps': [['Ask for advice', 'Check my work', 'Show me how you do it'],
          ['Where do I start', 'A second opinion', 'Explain it simply']],
 'models': [{'q': 'Is the main thing clear?',
             'opts': ['Yes', 'Somewhat', 'No'],
             'says': 'Start here: this is the part that matters most.'},
            {'q': 'Is something missing?',
             'opts': ['Yes', 'Not sure', 'No'],
             'says': 'One thing is missing. Add it and send it again.'},
            {'q': 'Is this ready?',
             'opts': ['Yes', 'Somewhat', 'No'],
             'says': 'This is nearly ready. One more step.'}],
 'sample_in': 'A question for a {spec}.',
 'sample_out': 'Here is my answer, in plain words, from what you sent.'}

PROMPT = (
    "You help a specialist set up a chat in which people learn from them or ask them things. The specialist is: {spec}. Write for a 12-year-old: short, warm, plain words. No scores, numbers, grades or percentages about a person. For health, law or money never state a diagnosis or a final ruling.\n"
    "Reply with only a JSON object with these keys:\n"
    "\"line\": 2 different one-sentence versions of \"People come to you ...\" saying why people come to this specialist;\n"
    "\"send\": the ids \"rec\" (voice recording), \"text\" (typed message), \"photo\", \"file\", ordered from what people would most naturally send to least;\n"
    "\"out\": the ids \"answer\" (one message in words), \"words\" (the person's own words, tidied), \"todo\" (a short list of what to do next), \"mark\" (a mark on what they sent), ordered from the best first thing to get back to the least fitting;\n"
    "\"hello\": 2 different welcome messages the chat says first, 1 or 2 short sentences each, in the specialist's voice;\n"
    "\"qs\": 3 short questions the chat asks a new person first;\n"
    "\"taps\": 2 arrays, each with 3 things people would ask this specialist for, at most 5 words each;\n"
    "\"models\": 4 objects, each one thing a small model could learn to recognise in what the person sent (it must fit the first kind in \"send\": never ask about a picture when people send messages, or about a voice when they send photos): {\"q\": a short yes-or-no style question the specialist answers by looking or listening, \"opts\": exactly 3 short answers from yes to no, \"says\": one sentence the person reads when the answer is the first option};\n"
    "\"sample_in\": one sentence describing what a person might send;\n"
    "\"sample_out\": the first thing they get back, 1 or 2 sentences."
)

#: The longest a host's "What do you do?" is kept.
MAX_SPEC = 40


def _str(value: Any, most: int) -> Optional[str]:
    return value.strip()[:most] if isinstance(value, str) and value.strip() else None


def _strs(raw: Any, most: int, least: int, fallback: list) -> list:
    got = [s for s in (_str(x, most) for x in (raw if isinstance(raw, list) else [])) if s]
    return got if len(got) >= least else list(fallback)


def _ids(raw: Any, every: list[str]) -> list[str]:
    given = [x for x in (raw if isinstance(raw, list) else []) if x in every]
    return list(dict.fromkeys([*given, *every]))


def _fill(value: Any, spec: str) -> Any:
    if isinstance(value, str):
        return value.replace("{spec}", spec.lower())
    if isinstance(value, list):
        return [_fill(v, spec) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, spec) for k, v in value.items()}
    return value


def built_in(spec: str) -> Optional[dict]:
    """The prototype's own suggestions for a profession it knows, or None."""
    known = KNOWN.get(spec.strip().lower())
    return _fill(known, spec) if known else None


def generic(spec: str) -> dict:
    return _fill(GENERIC, spec)


def clean(spec: str, raw: Any) -> dict:
    """The prototype's ``clean``: a provider's suggestions kept only where
    they have the right shape, every gap filled from the profession's own
    suggestions or the generic ones."""
    base = built_in(spec) or generic(spec)
    got = raw if isinstance(raw, dict) else {}
    models = []
    for m in got.get("models") if isinstance(got.get("models"), list) else []:
        if isinstance(m, dict) and _str(m.get("q"), 90) and isinstance(m.get("opts"), list) \
                and len(m["opts"]) >= 3:
            models.append({"q": _str(m["q"], 90),
                           "opts": [_str(x, 22) or "?" for x in m["opts"][:3]],
                           "says": _str(m.get("says"), 200) or ""})
    taps = []
    for t in got.get("taps") if isinstance(got.get("taps"), list) else []:
        kept = _strs(t, 44, 3, [])
        if kept:
            taps.append(kept[:3])
    return {"line": _strs(got.get("line"), 160, 1, base["line"]),
            "send": _ids(got.get("send") or base["send"], list(SEND)),
            "out": _ids(got.get("out") or base["out"], list(OUT)),
            "hello": _strs(got.get("hello"), 220, 1, base["hello"]),
            "qs": _strs(got.get("qs"), 120, 2, base["qs"]),
            "taps": taps or base["taps"], "models": models or base["models"],
            "sample_in": _str(got.get("sample_in"), 200) or base["sample_in"],
            "sample_out": _str(got.get("sample_out"), 300) or base["sample_out"]}


def suggest(spec: str, *, user_id: Optional[str]) -> tuple[dict, int]:
    """Will's suggestions for ``spec`` and how many provider calls they
    took (0 or 1): built in first (N620), else one call to the cheap model,
    else the generic ones."""
    own = built_in(spec)
    if own:
        return own, 0
    from services.llm import chat_complete
    from services.llm_config import SPEC_CHAT_SETUP_SUGGEST
    try:
        result = chat_complete(spec=SPEC_CHAT_SETUP_SUGGEST, system=PROMPT.replace("{spec}", spec),
                               user=spec, surface="chat_setup_suggest", user_id=user_id)
    except Exception:  # noqa: BLE001 -- the generic suggestions stand
        logger.warning("chat_suggestions: no provider answer; generic suggestions", exc_info=True)
        result = None
    return clean(spec, getattr(result, "parsed", None) if result else None), 1
