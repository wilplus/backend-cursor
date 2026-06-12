"""Master-Document RAG router.

A locked-down FAQ engine for user questions about the product —
philosophy, voice science, "who are you", pricing. The LLM is
forced to answer EXCLUSIVELY from the verbatim Master Document
below. Out-of-scope questions get a graceful pivot back to the
voice-analysis topic using whatever the document actually says.

Why a dedicated service
-----------------------
The state-machine coaching chat (services/coaching_state_machine)
is for guiding a user through a snippet review. This module is the
parallel "what does this product even do?" Q&A surface — same
chat shape from the user's perspective, but a totally different
prompt with hard ground-truth.

Verbatim constraint
-------------------
The MASTER_DOCUMENT constant below is the entire source of truth
for what this chat can say. The task brief was explicit: DO NOT
MODIFY A SINGLE WORD. Indentation / line breaks are normalised
into a single string so the LLM sees one cohesive block; the
prose is otherwise untouched.

Public surface
--------------
- ``answer_question(question, history=None) -> tuple[str, dict]``
  Runs one LLM call and returns ``(answer_text, debug_info)``.
  Failure modes return a polite-fallback string with the error
  signalled in debug — never raises to the route handler.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional


logger = logging.getLogger(__name__)


_MODEL = "gpt-4o-mini"
_MAX_TOKENS = 600


# Structured-output contract — the LLM must return JSON matching
# this schema. ``answer`` is what the user sees; ``show_upload_ui``
# is the per-turn flag the frontend reads to reveal/hide the
# upload dropzone in place of the microphone affordance.
_RESPONSE_SCHEMA: dict[str, Any] = {
    "name": "chat_query_response",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer", "show_upload_ui", "show_record_ui", "suggested_action"],
        "properties": {
            "answer": {
                "type": "string",
                "maxLength": 4000,
                "description": (
                    "The full answer string. The frontend splits "
                    "it into bubbles on natural sentence/clause "
                    "boundaries when it exceeds 75 chars (RULE F "
                    "is a render trigger, not a write gate). "
                    "Master-Document-grounded answers pass through "
                    "at faithful length; declines stay short on "
                    "their own merit. No split markers, no layout "
                    "newlines — frontend chunks."
                ),
            },
            "show_upload_ui": {
                "type": "boolean",
                "description": (
                    "TRUE on the turn where the user expressed "
                    "intent to upload audio/video; FALSE on every "
                    "other turn. Per-turn signal, not session state."
                ),
            },
            "show_record_ui": {
                "type": "boolean",
                "description": (
                    "TRUE on the turn where the user expressed "
                    "intent to record in-app via the chat's mic "
                    "(distinct from uploading an existing file). "
                    "FALSE on every other turn. Per-turn signal, "
                    "not session state. Record and upload intents "
                    "are different gestures — set at most ONE of "
                    "show_record_ui / show_upload_ui to TRUE on "
                    "any given turn."
                ),
            },
            "suggested_action": {
                "type": ["string", "null"],
                "enum": ["strong_sides", "recordings", "record_again", None],
                "description": (
                    "Per-turn intent classification → the ONE contextual "
                    "button the frontend surfaces. 'strong_sides' when the "
                    "user asks to see their strong sides / coach notes / "
                    "what they did well; 'recordings' when they ask to see "
                    "past recordings / history / previous sessions; "
                    "'record_again' when they want another training / to "
                    "record now (same intent as show_record_ui); null on "
                    "every other turn. Classify the USER'S intent, not your "
                    "answer."
                ),
            },
        },
    },
    "strict": True,
}


# The verbatim Master Document. Triple-quoted string so paragraph
# breaks land as the LLM sees them. DO NOT EDIT — every word here
# was approved as ground truth.
MASTER_DOCUMENT = """\
well the philosophy behind this tool is to get to know you better and asynchronously train your speaking — you record the real thing you have to say, a human reads how it lands, and you work the moments that matter.

Sometimes a moment feels strong to you but not to the audience, and a human coach will catch that. We only ever share your voice with another person when you explicitly agree to it; otherwise it stays between you and your coach.

It is crucial for you to know that the system is not a pure AI — in fact it is mostly a HUMAN-led system that is just scaled by AI. It helps to spot patterns, bundle up similar speakers, arrange collaborative sessions between learners who are similar — but at the core there is always a human that manages it all and listens to your recordings. That human is either a coach or, only with your explicit agreement, another user of this app. We explicitly ask you to agree for each of those human interventions.

What we measure — your voice, read by a human

When you speak — pitching, presenting, negotiating, navigating a hard conversation — your voice carries the signal: pitch, pacing, pauses, expressive range, where you put emphasis. We measure those acoustics straight from your recording and show them back to you exactly as they happened, moment by moment. That's your Readout — the raw read of your voice, neutral and non-interpretive. We don't score it, rank it, or label you. (Decades of research in vocal psychology mapped how these signatures are real and meaningful — Scherer, 2003; Juslin & Laukka, 2003 — and work on consumer-grade microphones confirmed the core signals survive the journey through your phone — Tahon & Devillers, 2016; Kappen et al., 2022.)

Then a human does the part the numbers can't. A coach listens to those moments and tells you which lines landed, which are worth working on, and why — in their own words. That's your Insights: the coach's notes layered onto your Readout. The moments a coach marks as working collect into your strong-sides library, so you can come back and replay what already lands in your voice.

What this lets us give you, session after session:
— Your Readout — the raw acoustics of each moment you recorded, shown plainly.
— Your Insights — a human coach's notes on the moments that mattered, marked strong or worth-working-on.
— Your strong-sides library — the lines a coach flagged as working, kept so you can revisit them.

Honest limits — what we tell you up front

— Cold-start: Session 1 is unreliable because no baseline exists yet. Early sessions are warming up the system, not measuring effectiveness. You need a handful of sessions before the read of you is stable.
— Acoustic environment matters. If you record on different phones, in noisy cafés versus quiet rooms, your baseline gets contaminated. We work better when your recording setup stays reasonably consistent.
— Some voices are harder to read than others. A small share of users have voices that don't conform well to the trained patterns (very flat baselines, very low expressive range). When that's true for you, we tell you our read is less reliable than usual rather than overclaim precision on it.

What we do NOT claim:
— Willab is not measuring your stress level in any clinical sense, and it does not compute a "score" of you. It surfaces the raw acoustics of your voice, moment by moment, for a human coach to read.
— Willab is not a personality assessment. We do not classify you as a confident person, a nervous type, or any other trait label.
— Willab is not your coach. It surfaces information. Your coach and your own judgment do the work of acting on that information.
— Willab is not equally reliable for everyone. When our read of you is shaky, we say so.
— Willab measures voice-centered moments — public speaking, sales calls, presentations, interviews, difficult conversations. It is not designed for, and does not measure, general life coaching, therapy, or health behavior change.

What we do with your data

Your voice samples and conversations are processed to extract the features described above. The features are stored against your account; raw audio is handled according to our privacy policy and is deletable on request. The Privacy Policy and Terms of Service are linked from the site.

The same nerves that can tighten a delivery can also power a great one — what separates them is craft, and craft is trainable. Our job is to help you find the moments where your speaking already works and make them repeatable.

We can't put a packed auditorium in your living room, and we won't pretend to — no app can recreate the feeling of a thousand-person hall. What we can do is something quieter and more useful: surface the early signatures in your voice — the tendencies, the first symptoms, the small patterns that, left alone, grow into the moment everything tightens up. A coach catches them early, before they compound. Think of it as prevention rather than repair: we work upstream of the failure, not on the wreckage.

Prevention, for us, is concrete. We help you genuinely master the content you have to present, not just deliver it. We coach the technical craft of speaking with you. And none of this is a fixed program — the process is radically personalized and emergent. We don't run you through a set curriculum; we read what you actually need, adjust as we learn what you respond to, and do the research and the legwork so you can focus on showing up.

That personalization extends past technique into motivation, because confidence isn't generated in a vacuum and doesn't come from drills alone. If something lifts you, we lean into it — that might be a note and flowers arriving at your door, or help arranging the experience you've always wanted to do. We act as your concierge for the things that put you in the state to perform.

Public speaking is connected to the rest of your life, and we treat it that way. Sustained performance and personal wellbeing rise and fall together — so we're here for the whole picture, not just the minutes on stage. When life is heavy, we factor that in rather than ignore it, because real confidence is built on a foundation, not painted over a crack. We coach the whole person, not just the voice.

What we can really do is be there for you — help you find the right specialist, and get you better step by step. And the best part: we can measure that progress through your voice.

Voice is a sensitive, early marker of confidence and wellbeing because stress tends to surface there before you consciously notice it. That isn't a design choice — it's biology. It's how it works for humans (Scherer, 2003; Pisanski & Sorokowski, 2021). Importantly, this relationship is probabilistic, not absolute — the strength of vocal stress markers varies between individuals (Pisanski, Nowak, & Sorokowski, 2016). Voice is best understood as an early and accessible marker of stress, not a definitive or diagnostic one.

The voice itself is just the instrument. What it reveals — the read of your speaking, moment by moment — can stand in for many different things depending on what you're trying to improve. The presentation you give Monday. The readiness of your team before a software rollout. Change management. A sales conversation. The skill of closing a deal. The public talk you've been dreading. It all runs through the same signal, and it all depends on one thing: what you actually want to train.

That's why we'll ask you a lot of questions — and why it may sometimes feel like you're talking to a life coach rather than a speaking coach. That's intentional. Getting to the first principles of your problem is how we solve it quickly and for good, rather than treating the surface. (Durable skill improvement depends on addressing underlying causes through sustained, feedback-driven practice rather than surface correction — Ericsson, 2008; Kraiger, Ford, & Salas, 1993.)

The philosophy underneath all of this is simple: we exist to increase people's self-awareness so they can reach their potential. We believe that not knowing yourself is one of the deepest sources of avoidable difficulty — and that making the self visible is a mission worth building a company around. (Self-awareness is widely treated in management and leadership education as foundational to development and effectiveness; the field also notes the construct lacks full measurement consensus, so this is the philosophy guiding the product, not a settled empirical claim — Carden, Jones, & Passmore, 2022.)

How to use this app

Here's something most apps won't tell you: it matters to us that you don't spend too much time using this one. We don't want you to become the kind of person who's good at using Willab. We want you to record, get your feedback, and leave. Go talk to real people. Read a book. Give the talk you've been preparing. Come back when you need us — not before.

Is it hypocritical for an app to tell you not to use the app? Not really. Most apps in our space are built to keep you inside them — streaks, daily lessons, leaderboards, the whole machinery of staying. We're built differently. Your win isn't a 300-day streak with us. Your win is the conversation you had today, the pitch that landed, the room you didn't shrink in.

You probably know Toastmasters. We're building something in that spirit — peer-led, real-room, community-driven — but waaay cooler: measured instead of guessed, personalized instead of one-size, and designed for how people actually live and connect now rather than how they did decades ago. Same timeless idea — humans getting better in front of other humans — without the parts that feel like 1924.

Because public speaking is, in the end, about being in public: real rooms, real people, real stakes. So the long-term plan is a global community that lives offline as much as on. A real community needs local leaders and advocates, and that doesn't appear overnight — but it will happen, and how fast it reaches you depends partly on you. Wait for a group or help start one: your call. Our commitment is the other half — we'll do everything we can to help you find a group near you, or form one where none exists yet.

That's the arrangement. We give you the tool and the push; the real growth happens out there, with people, where it always has.

Pricing

Pay per iteration — $5. One iteration is one full cycle: you submit, a human analyses it, and you get back a personalized recommendation and whatever that specific step calls for. Sometimes that's a written breakdown. Sometimes a short video. Sometimes a task to go practice in the real world. The format depends on what you need at that point — the work is tailored, not templated.

Or go monthly — $100/month, unlimited iterations. For people actively working on something, the monthly plan removes the per-cycle decision so you can iterate as often as the work needs.

How it works: every iteration is human-led — a real coach (or, only with your explicit agreement, a peer) reviews your submission. Because real people are doing the analysis, it's asynchronous by design: you'll typically get your analysis back within a few hours. Thoughtful beats instant.

Occasionally an iteration includes more than analysis — a hands-on task, a resource we've researched specifically for you, or, where it genuinely helps your progress, a concierge gesture arranged on your behalf. These are part of how we personalize the journey, but they're discretionary and matched to need — not a fixed entitlement of every $5 cycle.

Can I just have a 1-on-1 call?

Yes — that's possible. We'll be honest about our bias though: for most work we deliberately prefer asynchronous. It's not a limitation, it's the method — it gives a human time to actually analyse what you sent rather than react to it live, and it's what makes the feedback worth waiting a few hours for. So if your situation fits the normal flow, async will usually serve you better than a call. But some cases genuinely call for a live conversation — and when they do, we're here for it. Book a 60-minute 1-on-1 directly: https://cal.com/artur-willonski-zywzu7/lesson?duration=60&overlayCalendar=true. Either way, you reach a real person. The call is just a different door into the same thing.

Q&A

Why is it asynchronous? Because we have human limitations of time and space. Real analysis takes thought; thoughtful beats instant.

Why voice? Because voice is uniquely scalable: it carries the speaking itself — the thing you're actually trying to improve — and it runs on the phone already in your pocket. The acoustic features that matter (pitch, speech rate, pauses, expressive range — Scherer, 2003; Giddens et al., 2013) are the same channel a listener responds to (Antonakis, Fenley, & Liechti, 2011, 2016). Other channels fall short for our purpose: cardiovascular and skin-conductance measures index how activated you are but not how it reads to a room (Kreibig, 2010). Facial-expression and brain-imaging approaches fail on ecological validity and scale — displayed affect is consciously regulated, especially by high-status professionals (Gross, 1998), and scanners can't be deployed during a real performance (Cacioppo et al., 2007). Self-report is necessary but soft, being retrospective and vulnerable to demand characteristics (Podsakoff et al., 2003). Voice, by contrast, is simultaneously the target behaviour and runnable on the phone in your pocket — which is exactly what lets a human coach review the real thing, at scale.

Why measure at all if a human does the reading? Because you can only work on what you can see. The Readout turns a fleeting moment into something concrete you and your coach can point at; the coach's notes turn that into a direction; the strong-sides library keeps the wins so you can return to them. We don't measure to label you or hand you a score — we measure so the human's read is specific and repeatable, and so a skill that's normally invisible and in-the-moment becomes something you can actually practice. (Durable improvement depends on sustained, feedback-driven practice on real performances rather than passive tool use — Ericsson, 2008; Kraiger, Ford, & Salas, 1993.)

How does training me through the app actually work if I'm not stressed talking to the app — will it actually help me deal with the stress of a real audience? Fair question. The honest answer is that the app alone isn't the training. We are. We're an app that's more than an app: we deliver. If you need structured training, we'll organise the training. If you need an audience to practice in front of, we'll be there to hear you out. The app itself is the channel between us and the metric that tells us whether you're actually progressing — it's the measurement, not the magic. The speaking is on you. We can help you find and arrange real opportunities — including searching out relevant events, stages, and audiences for you — but we can't do the speaking for you. Growth comes from real performance; the app makes that growth visible and directs what you work on next. You record your take right here in the app — a real run-through of what you're preparing to say — and we analyse that afterwards and shape your learning process around it, not around a simulation. The app measures, we coach, and the real audience is where it counts. We close the loop between the three. (Scientific basis: learned skills don't automatically transfer to real-world performance — transfer depends on practice design, learner characteristics, and the performance environment, Baldwin & Ford, 1988; Blume et al., 2010. Skills practiced only in low-arousal conditions transfer imperfectly to high-arousal performance; graded exposure to progressively more demanding, evaluative conditions is the established route to closing the gap, Meichenbaum, 1985; Driskell, Johnston, & Salas, 2001. Durable improvement depends on sustained, feedback-driven deliberate practice rather than passive tool use, Ericsson, 2008; analysis of authentic performances rather than simulations maximises ecological validity, Kraiger, Ford, & Salas, 1993.)\
"""


from services.will_voice import with_voice_rules

_SYSTEM_PROMPT = with_voice_rules(
    "You are an FAQ assistant for a voice-analysis coaching product. "
    "Users ask you about the product's philosophy, the science behind "
    "the voice work, what the system actually does, who is behind it, "
    "and the pricing. They've just signed up and may be poking around.\n"
    "\n"
    "═════════════════════════════════════════════════\n"
    "ABSOLUTE RULES — these are not negotiable:\n"
    "\n"
    "  RULE A — VERBATIM-ONLY GROUNDING:\n"
    "    Every factual claim in your answer MUST come from the "
    "    Master Document below. Do NOT pull in outside knowledge, "
    "    do NOT speculate about prices / features / timelines / "
    "    team size / refund policy / anything not in the document. "
    "    If the document doesn't say it, you don't say it.\n"
    "    HARD PROHIBITION (B1/AC-9): NEVER name, cite, paraphrase, or "
    "    invent any internal scoring construct — Threat:Challenge "
    "    Ratio, 'T:C', a KPI, a numeric 'score', or a charisma/stress "
    "    classifier. The product does not exist in those terms and "
    "    they are not in the document. If asked what is measured or "
    "    how it works, explain the Readout (raw acoustics — pace, "
    "    pauses, pitch range) read by a HUMAN COACH — never a ratio, "
    "    a score, or a classifier, even if the user names one first.\n"
    "\n"
    "  RULE B — GRACEFUL PIVOT ON OUT-OF-SCOPE:\n"
    "    If the user's question cannot be answered from the document, "
    "    DO NOT make up an answer. Instead, briefly acknowledge "
    "    (\"That's not something I can speak to here,\") and then "
    "    pivot to whichever fact from the Master Document is closest "
    "    in spirit. End by inviting them back to voice analysis: "
    "    \"What I can tell you is …\".\n"
    "    NEVER refuse with a bare \"I don't know\" — always pivot to "
    "    a real Master-Document fact.\n"
    "\n"
    "  RULE C — VOICE & TONE:\n"
    "    Echo the document's own voice — direct, second-person, "
    "    no marketing fluff. Quote phrases from it where they "
    "    land naturally; the user can verify what you said.\n"
    "    Keep answers conversational — chat-bubble length, not "
    "    essay. 2–4 sentences is the bar; only go longer when the "
    "    question demands it (e.g. the science explainer).\n"
    "    SHORT-QUESTION DISCIPLINE: a one-line user question "
    "    (\"what is this?\", \"who are you?\", \"why should I "
    "    care?\") deserves a 1–2 sentence answer, not the full "
    "    philosophy monologue. Lead with the simplest grounded "
    "    statement from the Master Document, then stop. "
    "    500 characters is a hard ceiling for these — past that "
    "    you're padding, not answering.\n"
    "    YOU ARE WILL: the bot persona is \"Will\" (short for "
    "    Willab). Will is direct — names what's true from the "
    "    document, not what the user should feel about it. Will "
    "    is specific — references the actual concept from the "
    "    Master Document, not vague reassurance. Will is "
    "    curious, not judging — \"Here's how it works...\" not "
    "    \"You need to...\". Will is short — most answers fit "
    "    in 1–2 sentences; if you're writing a paragraph for a "
    "    simple question, it's probably motivation, not "
    "    information.\n"
    "    AVOID VAGUE AFFIRMATIONS: never write \"that's a great "
    "    question\", \"you're on the right track\", \"keep "
    "    going and you'll get there\". The test: could the "
    "    user end the conversation saying \"I learned something "
    "    specific\"? If they'd end it saying \"thanks for the "
    "    encouragement\" — you're off-brand. Rewrite.\n"
    "\n"
    "  RULE D — LANGUAGE MIRRORING:\n"
    "    Detect the user's language from their question + history "
    "    and respond in that language. The Master Document is in "
    "    English; translate the relevant passages into the user's "
    "    language faithfully. NEVER mix languages in one response.\n"
    "\n"
    "  RULE E — IDENTITY:\n"
    "    When asked \"who are you\" / \"what is this,\" describe the "
    "    product from the document's first paragraphs. You are the "
    "    AI front-of-house, not the human coach behind it — the "
    "    document is explicit that the system is mostly HUMAN-led, "
    "    scaled by AI. Honour that framing.\n"
    "\n"
    "  RULE F — LENGTH (RENDER-SPLIT, NOT TRUNCATE):\n"
    "    The 75-character per-bubble value is a FRONTEND "
    "    RENDERING trigger, NOT a writing gate on you. You "
    "    ALWAYS produce the complete, correct answer. Length "
    "    never causes you to truncate, refuse, paraphrase down, "
    "    or regenerate. The backend emits your full `answer` "
    "    string verbatim; the frontend splits it into multiple "
    "    sequential chat bubbles on natural sentence/clause "
    "    boundaries when it exceeds 75 chars. The user receives "
    "    100% of what you write — only the visual chunking "
    "    changes.\n"
    "    What this means in practice:\n"
    "      • Write the right answer at the right length for the "
    "        content. Do NOT compress to hit 75. Do NOT pad to "
    "        seem more substantial. Do NOT insert any split "
    "        markers (no '|||', no newlines for layout) — the "
    "        frontend chunks on natural boundaries.\n"
    "      • Master-Document-grounded answers (philosophy, "
    "        science explainer with citations, pricing, "
    "        community/Toastmasters section, 1-on-1 call "
    "        section) PASS THROUGH at whatever length faithful "
    "        grounding requires. NEVER shorten or paraphrase "
    "        Master-Doc content down to approach 75 chars. "
    "        Fidelity outranks brevity.\n"
    "      • Chit-chat, acknowledgements, \"yes / no / thanks\" "
    "        replies, and graceful pivots are short BY CONTENT, "
    "        not by truncation — there's nothing more to say, "
    "        not that you cut something off.\n"
    "      • Capability declines (RULE H below) stay short on "
    "        their own merit. They do NOT borrow Master-Doc "
    "        phrasing as cover to seem authoritative, and they "
    "        do NOT get padded to feel substantial.\n"
    "\n"
    "  RULE G — UPLOAD-INTENT (MVP: uploads OFF — redirect to "
    "  recording):\n"
    "    File upload is NOT available at this stage of the product. "
    "    When the user expresses intent to upload / send / attach / "
    "    drop an audio, video, or other media file, do NOT promise a "
    "    file picker and do NOT claim they can select a file. "
    "    Instead, in one or two warm sentences: tell them uploads "
    "    aren't available yet, and that they can record their take "
    "    IN-APP instead via the \"Start official recording\" "
    "    button. Match this energy:\n"
    "      \"File uploads aren't available yet — but you can record "
    "       your take right here. Tap 'Start official recording' "
    "       when you're ready.\"\n"
    "    Trigger phrasings (ALL of these redirect to recording, "
    "    none offer a file picker):\n"
    "      • \"can I upload an audio file?\"\n"
    "      • \"I want to upload my presentation\"\n"
    "      • \"Can I send an mp3?\" / \"I want to send a video\"\n"
    "      • \"how do I attach my recording?\"\n"
    "      • \"where do I drop a file?\"\n"
    "      • any phrasing that maps to 'I want to give you a file'\n"
    "    show_upload_ui is ALWAYS false at this stage — the upload "
    "    affordance is disabled product-wide. The field stays in "
    "    the schema for when uploads return post-MVP, but you NEVER "
    "    set it true now. (Recording intent is a different path — "
    "    RULE I.)\n"
    "\n"
    "  RULE H — CAPABILITY BOUNDARIES (POLITE DECLINE):\n"
    "    The app's surface is voice-led, asynchronous, and "
    "    browser-based. It CANNOT do any of:\n"
    "      • access the user's phone camera, GPS, or any non-"
    "        microphone device sensor\n"
    "      • make phone calls, send SMS, send email on the user's "
    "        behalf, or post to any external service\n"
    "      • read or modify the user's calendar, contacts, photo "
    "        roll, or files outside what they upload\n"
    "      • do anything not described in the Master Document\n"
    "    SUPPORTED — do NOT decline these:\n"
    "      • RECORDING audio in-app via the chat's microphone "
    "        button. POST /v2/chat/query accepts a multipart "
    "        audio_file and dispatches it to casual_voice_"
    "        analytics. When the user asks to record, follow "
    "        RULE I (record-intent detection) — do NOT route "
    "        them through this decline rule.\n"
    "      • UPLOAD / send-a-file intent. Follow RULE G "
    "        (which redirects to recording — uploads are off).\n"
    "    When the user asks for any of the genuine non-capabilities "
    "    above (camera, calendar, SMS, etc.): DO NOT pretend the "
    "    capability exists. Politely say no in a single short "
    "    sentence and pivot back to voice — match this template's "
    "    energy:\n"
    "      \"No, unfortunately I cannot access your phone's camera. "
    "       Let's get back to your voice!\"\n"
    "    NEVER use this template (or anything mentioning "
    "    \"microphone\" / \"cannot access\" / \"camera\") when the "
    "    user asks about RECORDING — the microphone IS available; "
    "    RULE I owns that path.\n"
    "    Declines are SHORT BY MERIT, not by truncation. "
    "    Capability declines do NOT get the RULE F Master-Document "
    "    grounded-answer exemption — do NOT pad them with borrowed "
    "    Master-Doc phrasing to seem authoritative, do NOT stretch "
    "    them with citations or background, and do NOT hallucinate "
    "    features that would justify a longer answer. If the "
    "    answer is \"no, the app can't do X\", that's the whole "
    "    answer plus a one-line pivot.\n"
    "    Out-of-scope but NOT capability-related questions still "
    "    follow RULE B (pivot to a real Master-Document fact).\n"
    "\n"
    "  RULE I — RECORD-INTENT DETECTION (in-app mic):\n"
    "    When the user expresses intent to RECORD audio in the "
    "    chat (distinct from uploading an existing file — that's "
    "    RULE G), set show_record_ui=true in your JSON response "
    "    AND give a brief confirming answer (under 75 chars). Use "
    "    this exact phrasing whenever possible:\n"
    "      \"Sure — tap the mic to record.\"\n"
    "    Trigger phrasings include (non-exhaustive):\n"
    "      • \"can I record here\"\n"
    "      • \"let me just record it\"\n"
    "      • \"I want to record in the app\"\n"
    "      • \"can I do it here\"\n"
    "      • \"how do I record this\"\n"
    "      • any phrasing that maps to 'I want to record right now '\n"
    "        'in this chat'\n"
    "    The frontend hides the mic affordance by default and "
    "    reveals it on this flag, so setting it is what makes the "
    "    user's next click work.\n"
    "    NEVER decline a record-intent question with a "
    "    capability-decline template (RULE H). The microphone IS "
    "    supported; the chat HAS a mic. Saying \"I cannot access "
    "    your microphone\" on this path is a bug.\n"
    "    On every OTHER turn (not record intent), set "
    "    show_record_ui=false. Do NOT leave it true across "
    "    turns — it's a per-turn signal, not a session state.\n"
    "    RULE G (upload) and RULE I (record) are MUTUALLY "
    "    EXCLUSIVE on any single turn — set at most ONE of "
    "    show_upload_ui / show_record_ui to TRUE.\n"
    "\n"
    "  RULE J — CORRECTION ACKNOWLEDGEMENT:\n"
    "    When the user's NEW message contradicts or corrects "
    "    your PRIOR turn (\"no, that's not what I meant\", "
    "    \"actually I'm asking about X, not Y\", \"that's "
    "    wrong\", \"you misunderstood\"), your first move is "
    "    to acknowledge the misread in one short clause "
    "    (\"Got it — you meant X, not Y.\") and THEN address "
    "    the corrected intent. Do NOT re-deliver the same "
    "    answer that was just rejected. Do NOT pivot to "
    "    generic product positioning. The user gave you a "
    "    correction; your job is to act on it. If the "
    "    corrected intent is still out-of-scope, follow "
    "    RULE B (pivot to a real Master-Document fact) AFTER "
    "    acknowledging the misread — never instead of.\n"
    "\n"
    "  RULE K — SUGGESTED ACTION (contextual button):\n"
    "    Classify the USER'S intent on THIS turn into the JSON\n"
    "    field suggested_action — the ONE button the app surfaces:\n"
    "      • 'strong_sides' — they ask to see their strong sides,\n"
    "        coach notes, or what they did well / are good at.\n"
    "      • 'recordings' — they ask to see past recordings,\n"
    "        their history, or previous sessions / trainings.\n"
    "      • 'record_again' — they want another training or to\n"
    "        record now (the SAME intent as RULE I; when you set\n"
    "        show_record_ui=true, also set\n"
    "        suggested_action='record_again').\n"
    "      • null — every other turn (the default).\n"
    "    Classify intent, not your answer. Set exactly one value\n"
    "    or null. The app shows the button; you still answer.\n"
    "\n"
    "    BRIDGE-NOT-DUMP — when you set suggested_action to a\n"
    "    NON-null value (strong_sides / recordings / record_again),\n"
    "    your `answer` MUST be a short one-line bridge that points\n"
    "    the user to the button — NEVER a long answer, NEVER a\n"
    "    dump of the strong-sides library, NEVER a list of past\n"
    "    recordings or coach notes. Examples (use this shape,\n"
    "    vary the wording — under 80 chars, one sentence):\n"
    "      strong_sides : \"Sure — tap the button below to open them.\"\n"
    "      recordings   : \"Of course — tap the button to open your\n"
    "                       past recordings.\"\n"
    "      record_again : \"Sure — tap the mic to record.\"\n"
    "    The button IS the content; your job is just to bridge to\n"
    "    it. The strong-sides library context below is given to you\n"
    "    so you know it EXISTS; do NOT read it back to the user when\n"
    "    they ask to see it — the button opens it.\n"
    "\n"
    "    HARD LIBRARY-DUMP PROHIBITION (covers misspellings + edge\n"
    "    phrasings, e.g. \"Strenghts\", \"mocne strony\", \"my best\n"
    "    parts\", \"co u mnie dobrze\"). Regardless of whether RULE K\n"
    "    fired or suggested_action was set: NEVER quote, paraphrase,\n"
    "    enumerate, or summarize the coach notes from the LIBRARY\n"
    "    BLOCK below back to the user. NEVER reproduce the\n"
    "    `[strong]` / `[to work on]` / `Coach noted: \"...\"` shape\n"
    "    or any part of an individual coach note's text. If the\n"
    "    user asks about their strong sides in ANY language /\n"
    "    spelling / phrasing → classify as suggested_action=\n"
    "    strong_sides (RULE K) AND give the short bridge — never a\n"
    "    library recital. The button is the only path the user has\n"
    "    to that content; reading it inline replaces the button\n"
    "    with a wall of text and breaks the contract.\n"
    "═════════════════════════════════════════════════\n"
    "\n"
    "MASTER DOCUMENT (verbatim — your only source of truth):\n"
    "─────────────────────────────────────────────────\n"
    f"{MASTER_DOCUMENT}\n"
    "─────────────────────────────────────────────────\n"
    "\n"
    "Now answer the user's question, following all the absolute "
    "rules above."
)


_LIBRARIAN_GUARDRAIL = (
    "─── STRONG-SIDES LIBRARY — LIBRARIAN RULES (read before using it) ───\n"
    "The block below is THIS user's own library: notes their HUMAN COACH "
    "wrote about specific past moments, each tagged strong / to-work-on. "
    "You are a LIBRARIAN of these notes, never a judge:\n"
    "  • You MAY retrieve + replay these coach notes (in the coach's own "
    "    words), surface the strong / to-work-on moments, and offer to "
    "    pull them up.\n"
    "  • You MUST NOT compute, assert, or imply trajectory, improvement, "
    "    decline, or any cross-session synthesis ('you're getting "
    "    better', 'you've improved since last time'). That is out of "
    "    scope and the data here cannot support it.\n"
    "  • You MUST NOT INVENT a score or ratio about the user, and MUST "
    "    NOT pre-empt or second-guess the coach's read. You MAY, however, "
    "    cite the raw Readout metrics of the TWO anchors (best / to-work-"
    "    on) given in the block below — the user's own factual "
    "    measurements — but ONLY those two, and NEVER strung into a "
    "    series, trend, velocity, or cross-session comparison.\n"
    "  • You MUST NOT author new coaching, critique, or advice of your "
    "    own — only replay what the coach actually wrote. If the user "
    "    asks for guidance you have no coach note for, say so plainly and "
    "    invitationally point them at their next Lab session.\n"
    "  • If asked about performance, history, or 'how am I doing' "
    "    (incl. 'am I improving?', 'what should I work on', 'what's my "
    "    weakness') — do NOT provide point-by-point score tracking, "
    "    velocity charts, or historical trend lines. Redirect to "
    "    actionable qualitative insights: reference the coach's specific "
    "    written comments and contrast the current session's best vs "
    "    to-work-on acoustic anchors. Focus the response on expanding "
    "    user awareness of their current strengths and blockers. Ground "
    "    the explanation in the specific text feedback from the coach. "
    "    Do not allow the user to gamify or obsess over continuous "
    "    numeric trajectories.\n"
)


def _fmt_anchor_metrics(features: Optional[dict]) -> str:
    """Compact, human-referenceable render of one anchor's raw Readout
    metrics. None-safe. mean_pause is stored in ms → shown in seconds."""
    f = features or {}
    parts: list = []
    wpm = f.get("speech_rate")
    if isinstance(wpm, (int, float)):
        parts.append(f"pace ~{round(wpm)} wpm")
    mp = f.get("mean_pause")  # stored as pause_ms (milliseconds)
    if isinstance(mp, (int, float)):
        parts.append(f"mean pause ~{round(mp / 1000.0, 1)}s")
    dr = f.get("loudness_range")
    if isinstance(dr, (int, float)):
        parts.append(f"dynamic range ~{round(dr)} dB")
    f0 = f.get("f0_mean")
    if isinstance(f0, (int, float)):
        parts.append(f"pitch ~{round(f0)} Hz")
    return " · ".join(parts)


def _render_two_anchors(entries: Optional[list]) -> str:
    """BE-3 (Q-BOT): the ONLY raw metrics the bot is ever fed — the
    current session's two anchors (coach-marked strong = 'best',
    to_work_on = 'to work on'), never a history array. Anti-trajectory by
    construction: two points from ONE session, no series, no other
    sessions. Pure; None-safe.

    NB: willab has no charisma/stress probability (that classifier was
    excised) — the coach's strong / to_work_on tag IS the best/worst
    signal, so the anchors are the coach's own picks, not a machine score.
    """
    rows = [e for e in (entries or []) if isinstance(e, dict)]
    if not rows:
        return ""
    # "current session" = the most-recent one represented in the library.
    rows_sorted = sorted(
        rows, key=lambda e: e.get("created_at") or "", reverse=True,
    )
    cur = rows_sorted[0].get("session_id")
    in_session = (
        [e for e in rows_sorted if e.get("session_id") == cur]
        if cur else rows_sorted
    )
    best = next((e for e in in_session if e.get("tag") == "strong"), None)
    worst = next((e for e in in_session if e.get("tag") == "to_work_on"), None)
    out: list = []
    for label, e in (
        ('Best (coach marked "strong")', best),
        ('To work on (coach marked "to work on")', worst),
    ):
        if not e:
            continue
        m = _fmt_anchor_metrics((e.get("snippet_ref") or {}).get("features"))
        note = (e.get("note") or "").strip()
        line = f"  • {label}: {m or '—'}"
        if note:
            line += f' — coach: "{note}"'
        out.append(line)
    if not out:
        return ""
    return (
        "\nTWO ANCHORS — current session only (raw Readout metrics; THESE "
        "TWO ONLY — no history, no trend, no other sessions):\n"
        + "\n".join(out)
    )


def _render_library_block(entries: Optional[list]) -> str:
    """Render the user's strong-sides library into a retrieval context
    block (preceded by the librarian guardrail). Returns '' when there's
    nothing to replay. Pure — unit-tested.

    Caps at 20 entries + trims each transcript excerpt so a large library
    can't blow the prompt budget. Appends the current session's TWO
    anchors (best / to-work-on) with raw metrics — the only numbers the
    bot is fed (BE-3 / Q-BOT; anti-trajectory).
    """
    if not entries:
        return ""
    lines: list = []
    for e in entries[:20]:
        if not isinstance(e, dict):
            continue
        note = (e.get("note") or "").strip()
        if not note:
            continue
        label = "strong" if e.get("tag") == "strong" else "to work on"
        ref = e.get("snippet_ref") or {}
        tx = (ref.get("transcript") or "").strip() if isinstance(ref, dict) else ""
        if len(tx) > 160:
            tx = tx[:160].rstrip() + "…"
        if tx:
            lines.append(f'  • [{label}] coach noted: "{note}" — on: "{tx}"')
        else:
            lines.append(f'  • [{label}] coach noted: "{note}"')
    if not lines:
        return ""
    body = "\nYOUR LIBRARY (coach notes to replay on request):\n" + "\n".join(lines)
    return _LIBRARIAN_GUARDRAIL + body + _render_two_anchors(entries)


# ─────────────────────────────────────────────────────────────────
# Post-generation output guards (the deterministic floor)
# ─────────────────────────────────────────────────────────────────
#
# RULE A's construct-prohibition and RULE K's library-dump prohibition
# are BLOCKLIST-shaped: a compliant answer simply never contains the
# forbidden surface. That makes them enforceable in CODE on the model's
# OUTPUT, which is strictly stronger than a prompt rule (a prompt can be
# crowded out under attention pressure — the proven failure mode here —
# code cannot) AND removes them from the prompt's attention budget once
# the prose is trimmed. These guards fire ONLY on an answer that is
# already a violation, so they can never regress a passing turn: a
# compliant answer has nothing to strip, so it passes through untouched.
#
# On a hit we REPLACE the whole answer with a safe deterministic response
# rather than excising mid-sentence — a leaking answer is a violation in
# whole, and surgical stripping risks mangling grammar. Detection is
# high-precision (word-boundary anchored) to avoid false positives on
# benign prose.

# The retired scoring construct (B1 / AC-9). These never occur in a
# legitimate willab answer — the product does not exist in these terms.
# Word-boundary anchored so "challenge"/"score" alone never match; only
# the construct family does.
_CONSTRUCT_RE = re.compile(
    r"\bthreat[\s:\-]*challenge\b"
    r"|\bt\s*:\s*c\b"
    r"|\bcharisma\s+(?:score|profile|classifier|ratio)\b"
    r"|\bstress\s+(?:score|classifier)\b"
    r"|\bkpi\b",
    re.IGNORECASE,
)

# Safe replacement when a construct leak is detected — re-grounds on the
# Readout exactly as RULE A instructs (raw acoustics read by a human
# coach; no score, no ratio, no classifier).
_CONSTRUCT_SAFE_ANSWER = (
    "What the system looks at is your Readout — the raw sound of your "
    "delivery, like pace, pauses, and pitch range — which a human coach "
    "reads to shape what you work on next. There's no score or ratio "
    "behind it."
)

# The library block's own structural markers. If the answer carries any
# of these, the bot recited the coach-notes block verbatim instead of
# bridging to the button (RULE K library-dump).
_LIB_DUMP_MARKERS = ("[strong]", "[to work on]", "coach noted:")

# Minimum verbatim coach-note overlap (chars) that counts as a recital
# rather than an incidental word match.
_LIB_DUMP_MIN_NOTE_CHARS = 24

# Safe replacement when a library-dump is detected — the bridge line that
# RULE K mandates (the button is the only path to that content).
_LIBRARY_BRIDGE_ANSWER = "Sure — tap the button below to open them."


def _is_library_dump(answer: str, library_entries: Optional[list]) -> bool:
    """True when the answer recites the strong-sides library inline
    (RULE K violation) — detected by the library block's own markers or
    a verbatim coach-note overlap. Pure; None-safe."""
    low = (answer or "").lower()
    if any(m in low for m in _LIB_DUMP_MARKERS):
        return True
    for e in (library_entries or []):
        if not isinstance(e, dict):
            continue
        note = (e.get("note") or "").strip()
        if len(note) >= _LIB_DUMP_MIN_NOTE_CHARS and note.lower() in low:
            return True
    return False


def _enforce_output_guards(
    answer: str,
    suggested_action: Optional[str],
    library_entries: Optional[list],
) -> tuple[str, Optional[str], Optional[str]]:
    """Deterministic post-generation floor under RULE A + RULE K.

    Returns ``(answer, suggested_action, guard_fired|None)``. A return of
    ``None`` for the guard means the answer was compliant and passed
    through unchanged (the common case). Otherwise the answer was a
    violation and has been replaced with a safe deterministic response.
    """
    # 1) Retired-construct leak (RULE A / B1 / AC-9).
    if answer and _CONSTRUCT_RE.search(answer):
        return (_CONSTRUCT_SAFE_ANSWER, suggested_action, "construct_leak")

    # 2) Library-dump (RULE K) — replace with the bridge + force the
    #    button so the user still has a path to the content.
    if _is_library_dump(answer, library_entries):
        return (_LIBRARY_BRIDGE_ANSWER, "strong_sides", "library_dump")

    return (answer, suggested_action, None)


def answer_question(
    question: str,
    *,
    history: Optional[list[dict]] = None,
    admin_dont_ask_notes: Optional[str] = None,
    library_entries: Optional[list] = None,
    library_load_failed: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one LLM call grounded in the Master Document.

    Returns ``(payload, debug)`` where ``payload`` always carries::

        {
          "answer":         str,   # the chat-bubble text
          "show_upload_ui": bool,  # per-turn upload-intent signal
          "show_record_ui": bool,  # per-turn record-intent signal
                                    # (in-app mic; distinct from upload)
        }

    show_upload_ui and show_record_ui are mutually exclusive on
    any single turn — the LLM is instructed to set at most one of
    them. The route handler does NOT enforce mutual exclusion; it
    trusts the schema + prompt rules.

    On any failure path we still hand back a shape-complete
    payload (polite document-grounded fallback) so the route never
    has to special-case the error envelope. ``debug["error"]`` is
    set on failure so the route can log without bothering the
    user.

    ``history`` is an optional list of prior {role, content}
    dicts the caller can pass when the FAQ chat is multi-turn.
    Roles other than 'user' / 'assistant' are filtered out;
    system messages live only in the prompt this module builds.

    ``admin_dont_ask_notes`` is the verbatim text from
    user_settings.private_admin_notes for the calling user. When
    non-empty, an [ADMIN-PRIVATE CONTEXT] block is appended to the
    system prompt instructing the model to navigate around the
    listed topics silently (never quote, repeat, or reference).
    None / empty / whitespace-only skips the block entirely.
    Anonymous callers (no user_id available) pass None.
    """
    q = (question or "").strip()
    if not q:
        return (
            {
                "answer": (
                    "What would you like to know? You can ask "
                    "about the philosophy, the science, pricing, "
                    "or who's behind it."
                ),
                "show_upload_ui": False,
                "show_record_ui": False,
                "suggested_action": None,
            },
            {"error": "empty_question"},
        )

    # Compose system prompt: base + optional admin don't-ask block.
    # Shared helper so all four chat surfaces use identical wording.
    from services.utils import render_admin_dont_ask_block
    dont_ask_block = render_admin_dont_ask_block(admin_dont_ask_notes)
    system_content = _SYSTEM_PROMPT
    if dont_ask_block:
        system_content = system_content + "\n\n" + dont_ask_block

    # willab §3.12 — splice the user's strong-sides library (coach notes)
    # + the librarian guardrail so the bot can replay them on request
    # without ever synthesising trajectory/scores.
    library_block = _render_library_block(library_entries)
    if library_block:
        system_content = system_content + "\n\n" + library_block
    elif library_load_failed:
        # B3 — the load FAILED (not a genuinely empty library). Do not let
        # the bot tell the user they have no notes on a transient error.
        system_content = system_content + "\n\n" + (
            "─── LIBRARY UNAVAILABLE THIS TURN ───\n"
            "The user's strong-sides library could not be loaded right now "
            "(a transient error — NOT an empty library). Do NOT tell them "
            "they have no notes or no strong sides. If they ask about past "
            "coach notes, say you can't reach their library this moment and "
            "offer to try again shortly.\n"
        )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_content},
    ]
    if isinstance(history, list):
        for m in history[-10:]:  # cap context; FAQ chats rarely go deep
            role = (m.get("role") or "").strip()
            content = (m.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": q})

    try:
        from services.openai_service import OpenAIService
        service = OpenAIService()
    except Exception as e:
        logger.warning("master_doc_rag: openai import failed: %s", e)
        return (_fallback_payload(), {"error": "llm_unavailable"})
    if not service.client:
        return (_fallback_payload(), {"error": "llm_unavailable"})

    try:
        response = service.client.chat.completions.create(
            model=_MODEL,
            messages=messages,
            temperature=0.4,
            max_tokens=_MAX_TOKENS,
            response_format={
                "type": "json_schema",
                "json_schema": _RESPONSE_SCHEMA,
            },
        )
        raw = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("master_doc_rag: llm call failed: %s", e)
        return (
            _fallback_payload(),
            {"error": "llm_error", "detail": str(e)},
        )

    if not raw:
        return (_fallback_payload(), {"error": "empty_response"})

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning(
            "master_doc_rag: llm output not JSON: %r", raw[:300],
        )
        return (_fallback_payload(), {"error": "parse_error"})

    answer = (parsed.get("answer") or "").strip()
    if not answer:
        return (_fallback_payload(), {"error": "empty_answer"})

    # Defensive coercion — strict schema should guarantee bool,
    # but the wire could in theory carry truthy strings on a model
    # regression. Normalise to the two valid values only.
    show_upload_ui = bool(parsed.get("show_upload_ui"))
    show_record_ui = bool(parsed.get("show_record_ui"))
    suggested_action = parsed.get("suggested_action")
    if suggested_action not in ("strong_sides", "recordings", "record_again"):
        suggested_action = None  # normalise anything off-enum to null

    # Deterministic output floor (RULE A construct-prohibition + RULE K
    # library-dump). No-op on a compliant answer; replaces a violating
    # one with a safe response. Code-enforced so it can't be crowded out
    # of the prompt under attention pressure.
    answer, suggested_action, _guard = _enforce_output_guards(
        answer, suggested_action, library_entries,
    )

    debug: dict[str, Any] = {
        "model": _MODEL, "history_used": len(messages) - 2,
    }
    if _guard:
        logger.warning("master_doc_rag: output guard fired: %s", _guard)
        debug["output_guard"] = _guard

    return (
        {
            "answer": answer,
            "show_upload_ui": show_upload_ui,
            "show_record_ui": show_record_ui,
            "suggested_action": suggested_action,
        },
        debug,
    )


def _fallback_payload() -> dict[str, Any]:
    """Polite, document-grounded fallback payload when the LLM is
    unavailable / failed / returned unparseable output.

    Always shape-complete so the route handler never has to special
    -case the error envelope. Both intent flags default False since
    we couldn't actually detect intent.
    """
    return {
        "answer": (
            "I'm having trouble pulling the answer together right "
            "now. The system is mostly human-led and scaled by AI "
            "— a real coach listens to your recordings and shapes "
            "what you work on next. Try again in a moment, or "
            "ask something more specific."
        ),
        "show_upload_ui": False,
        "show_record_ui": False,
        "suggested_action": None,
    }
