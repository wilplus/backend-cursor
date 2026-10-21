# The signed line bank (founder, 6 October 2026)

Every line the app may say after a praise moment, a clearer version, a
practise try and on the sharing screen, as the founder signed them on the
Navigation Panel (fifth export, 20:03 UTC; decisions log N54). The words
are exact: the code reads them from here and nothing else. A line not in
this file does not ship.

Rotation: within one bank the app never shows the same line twice in a
row. A "later" line shows only from Take 2 on, with the real Take number,
and only when it is true. No number other than the Take number ever
appears (AC-9). Each praise bank fires only on the cue it names; B09 is
the gentle line for when no single cue stands out.

## Praise

**B01 · sounded surer (general)**
- Sounded more confident than usual!
- You sounded more sure of yourself than usual!
- There it is: more confidence than usual!
- That came out bold and sure. More than usual!
- You sounded like you really believed it this time!
- Later: This sounded more confident than on Take {n}.

**B02 · voice moved up and down**
- Your voice danced up and down. That kept it alive!
- No flat line here: your voice went up and down and pulled me in!
- Your voice had real melody. It sounded alive!
- Up and down, like music. That's how a confident voice moves!
- Later: Your voice moved more here than on Take {n}.

**B03 · louder and softer words**
- You made some words loud and some soft. That gave it shape!
- You pushed the big words and let the small ones rest. Great!
- Loud where it mattered, soft where it didn't. That landed!
- Your volume moved with your meaning. Very strong!
- Later: You used loud and soft more than on Take {n}.

**B04 · fewer stops**
- You kept going without stopping. It flowed like a river!
- Hardly any stops. You just kept talking, sure of yourself!
- Smooth and steady, no stumbling. That sounded confident!
- You didn't stop to search for words. You just knew!
- Later: Fewer stops here than on Take {n}.

**B05 · lower, calmer voice**
- This delivery was calm and steady
- Calm and grounded. Your voice sat low and steady here!
- Your voice was calm and smooth. It sounded like you were in charge!
- Nice and steady. Nothing could shake you here!
- Grounded and calm, like someone who knows exactly what they mean.
- Later: Your voice sat lower than on Take {n}. It sounded calm.

**B06 · kept the speed**
- You weren't rushing, but your pace was good and rhythmic. This part sounded confident and right on time.
- Good rhythm! You kept your pace and didn't drag.
- Right on time: no rushing, no dragging, just the right pace!
- Your pace held steady all through this part. Confident!
- You moved like a clock here: steady and sure!
- Later: You kept your pace better than on Take {n}.

**B07 · ending went down**
- That was great. You weren't asking me, you were simply saying what you mean. At the end you were just saying it straight!
- You ended it like a statement, not a question. Straight and sure!
- No question mark at the end. You just said it!
- You landed the ending. It sounded like you meant every word!
- You finished strong, like you were sure of it!
- Later: Your ending came down more than on Take {n}.

**B08 · started with energy**
- The energy at the beginning was great. It was like the North Star of your presentation.
- What a start! That energy set the tone for what came after.
- You came in with energy from the very first word!
- Strong opening! That energy pulls people right in.
- You started with fire. Everyone would want to keep listening!
- Later: You started with more energy than on Take {n}.

**B09 · the general line**
- Wow, it was one of the most confident moments of your presentation
- This was one of your more confident moments. There's more in you!
- Good moment! You're heading the right way.
- This one sounded surer. Keep building on it!
- I can hear your confident voice starting to come through here!
- Later: This keeps getting surer. Keep going.

## Clearer version

**B10 · drop the word in front** (the founder's favourite: the last one)
- Say what you mean. Don't dance around it, just say it straight.
- Skip the warm-up. Go straight to your point!
- Start with what matters. No run-up needed!
- Get right to it. Your point is strong enough on its own.
- Drop the extra words and say the thing. It hits harder!

**B11 · split in two**
- Try saying it as two short sentences, with a small pause between.
- Two short sentences land better than one long one.
- Break it in two and pause in the middle.
- Two short sentences hit harder than one long one. Try it!
- Cut it in two and take a breath between. Let each part land!
- Say the first part, pause, then the second. Much clearer!
- Give each idea its own sentence. People can follow you easily!

**B12 · join into one**
- Don't cut it into pieces. Say it as one whole thing, so it lands all together and makes an impact.
- Keep it in one go, so the idea hits all at once.
- One sentence, one breath. Let it land together!
- Don't break it up. Say it whole and it lands harder.
- Put the pieces together so your idea comes out as one strong thought!

**B13 · the opening line, above the new text**
- Here is a slightly more polished option:
- Here's a clearer way to say it:
- Try it this way:
- Here's a way to say it even clearer:
- Try saying it like this:
- This version might land even better:
- Here's a stronger way to say it:

**B14 · the question, under the new text** (the founder's note: "5th is real good")
- Do you accept and want to practise it?
- Want to take it and practise?
- Shall we practise this version?
- Do you want to try saying it this way?
- Shall we practise this one together?
- Ready to practise this version?
- Want to give this version a go?

## Practising

**After a try where something moved (not yet praise)** (N52.5, NX3 A)
- It was better, and I have yet another practice for you to try!

**After a try where nothing moved** (NX3a)
- Let's try it once more. I have another practice for you!
- Let's give it another go. I have one more practice for you!
- Not quite yet. Here's another practice to try!
- Keep going! I have another practice for you to try.

**After the third try that isn't praise** (CM3a A: up to 3 tries; CM3b A,
sixth export, 20:11 UTC); the app then moves on to "Judgement time!"
- Great effort! Let's move on and come back to this one later.
- Thanks for giving it your all. On to the next step!
- You worked hard on this one. Let's keep going!
- Nice persistence! We'll move on for now.

**The button when personalised practice is off** (WQ3c A, 20:14 UTC): the
clearer version can be taken into the text but not practised.
- Accept
- (below it, unchanged) Keep my words

## The machine's reading lines, after a practise try (founder 2026-10-13, option A; signed into this file 2026-10-21, N94)

The walk reads each try against the speaker's own voice and says the line for the reading that moved: under "Good job" when it is better, under the not-yet when it is not. Three lines a reading, taken in turn. Copied exactly from frontend `src/components/willab/idealEditCopy.ts` `PRACTISE_LINES`, which ships them.

### Better: under "Good job"

**wide_range** (the voice moved up and down)
- I liked the variety in your voice. It sounded alive! 🎶
- Up and down, high and low. Your voice sounded alive! 🎶
- So much colour in your voice. That's what alive sounds like! ✨

**full_volume** (louder and softer words)
- It wasn't too quiet. It was the volume that pulled me in. 🔊
- Loud where it mattered. That's what pulled me in! 🔊
- Your volume rose and fell, and it pulled me right in. 🔊

**no_hesitation** (fewer stops)
- It flowed like a river. Without the pauses, it was great 😏
- Smooth as a river. No stopping, no doubting. 🌊
- No pauses, just flow. That was great 😏

**settled_pitch** (a lower, calmer voice)
- Good: calm and smooth, a low voice, a nice sound. 😌
- Low and calm. That's the sound of someone who's sure. 😌
- Your voice settled down low. Calm, smooth and nice to hear. 🎧

**kept_moving** (kept the pace)
- You shot it out fast like a machine gun, and it was good. Exactly what we wanted! 🔥
- Rat-a-tat! You kept the pace and never slowed down. Exactly what we wanted. 🔥
- No slowing down at all. You kept it moving, just like we wanted! ⚡

**landed_ending** (the ending came down)
- You nailed it. Calm and smooth, like you know you're the boss here. 😎
- That ending landed. Calm, smooth, the boss's voice. 😎
- You brought the last word down like you own the room. 👑

**opened_strong** (started with energy)
- You started this like a rocket launching into outer space! 🚀
- Liftoff! What a strong start. 🚀
- That opening had rocket fuel in it! 🚀

**general** (when no single reading stands out)
- You know that I know that you know: that was freaking confident! 💪
- No doubt about it, that was freaking confident! 💪
- That one? Pure confidence. You know it, I know it. 💪

### Not yet: the reading that went the other way

**wide_range** (the voice stayed on one note)
- Hey, I know you're trying. Let your voice go up and down. Let it go crazy, I know you can! 🎢
- Your voice stayed on one note. Take it on a rollercoaster this time! 🎢
- Flat like a pancake 🥞 Let it go up and down, I know you've got it in you.

**full_volume** (too quiet)
- Come on, you can scream a little! 📣
- Turn it up! Let a few words come out loud. 🔊
- Don't be shy. Give it some volume this time! 📣

**no_hesitation** (more stops)
- I know you like the strategic pause 😏 But what if we went through this one like a blast? 💥
- Pauses are your thing, I get it 😏 This time, blast through it in one go! 💥
- No brakes this time 🚀 Just blast through it, start to finish!

**settled_pitch** (the pitch went higher)
- You know Flo Rida? "Low, low, low"? Yeah, so go that low! 🎵
- Your voice climbed up a bit. Bring it down low and calm. ⬇️
- Think deep and low, like a late-night radio host. 📻

**kept_moving** (slowed down)
- It's okay. If you're tired, you can slow down. But if you're not, give it a little speed boost! 🏎️
- You slowed down there. Put your foot on the gas this time! 🏎️
- A bit sleepy that time 😴 Wake it up and keep it moving.

**landed_ending** (the ending went up)
- If that's a question, I can answer it. But if it's not, try again. Lol 😄
- That ended like a question ❓ Bring the last word down like a statement.
- Was that a question or an answer? 🤔 Land the last word low.

**opened_strong** (a slow start)
- You know, like an engine in cold weather. I know you have this heat inside, you just need to warm it up. Try it again! 🔥
- Slow start there 🥶 Kick it off with energy from the very first word.
- The first words were a bit shy. Start it like you mean it! 🚀

**general** (when no single reading stands out)
- You know Whiplash? It's not quite my tempo yet. Lol, try again! 🥁
- Not quite my tempo 🥁 One more time!
- Close, but not there yet. Give it another go! 💪

## The judgements

**The answer toast** (WQ4 A): the answer the speaker chose, with a tick:
"Yes ✓", "In-between ✓", "No ✓", "Not sure ✓", "Audio unclear ✓".

## Sharing (WQ5 A, WQ6 A)

Choices (consent words: they never rotate):
- General community · Fastest improvement in speaking publicly
- Only my community · Slower but steady growth · field: Pass code
- Set up my own community · fields: Community name, Pass code
- None · Slowest progress, but safe

Messages:
- That pass code is taken. Try another one.
- No community has that pass code.
- Please accept the updated Terms and Privacy first.
- Couldn't share this take. Try again.

## The coach's work list (P26c A)

On a moment the coach is asked to listen to again; they never say why or
what the speaker answered, so the coach stays blind:
- Please listen to this moment once more.
- A second listen, please.
- This moment needs another listen.
