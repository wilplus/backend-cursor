import openai
from config import Config
import json
import sentry_sdk

config = Config()

class OpenAIService:
    def __init__(self):
        if config.OPENAI_API_KEY:
            openai.api_key = config.OPENAI_API_KEY
        self.client = openai.OpenAI(api_key=config.OPENAI_API_KEY) if config.OPENAI_API_KEY else None
    
    def transcribe_audio(self, audio_file, filename: str = "audio.webm"):
        """
        Transcribe audio using Whisper-1.
        Returns transcript and duration (from Whisper response).
        """
        # Dev mode mock response (COMMENTED OUT - using real OpenAI)
        # if not config.is_production:
        #     # Mock response in dev
        #     return {
        #         "text": "This is a mock transcription for development purposes. The user spoke about their presentation and how they felt nervous but prepared.",
        #         "duration": 45.0
        #     }
        
        if not self.client:
            raise Exception("OpenAI client not initialized")
        
        try:
            # Log that we're calling real OpenAI
            import logging
            logger = logging.getLogger(__name__)
            logger.info("✅ Calling OpenAI Whisper API for transcription...")
            
            # Read audio file
            audio_file.seek(0)
            audio_data = audio_file.read()
            audio_file.seek(0)
            
            # Transcribe
            transcript_response = self.client.audio.transcriptions.create(
                model="whisper-1",
                file=(filename, audio_data, "audio/webm"),
                response_format="verbose_json"
            )
            
            # Extract duration from segments (use last segment end time)
            duration = 0.0
            if hasattr(transcript_response, 'segments') and transcript_response.segments:
                duration = transcript_response.segments[-1].end
            
            return {
                "text": transcript_response.text,
                "duration": duration
            }
        except Exception as e:
            sentry_sdk.capture_exception(e)
            raise Exception(f"Transcription failed: {str(e)}")
    
    def classify_speech(self, transcript: str, pre_answers: list, wpm: float, filler_count: int):
        """
        Classify speech using GPT-4o-mini.
        Returns: {"classification": "struggler"|"strong"|"uncertain", "confidence": "low"|"medium"}
        """
        if not config.is_production:
            return {
                "classification": "uncertain",
                "confidence": "low"
            }
        
        if not self.client:
            raise Exception("OpenAI client not initialized")
        
        # Build prompt
        pre_answers_text = "\n".join([
            f"Q: {ans.get('question_text', '')}\nA: {ans.get('answer_text', '')}"
            for ans in pre_answers
        ])
        
        prompt = f"""Analyze the following speech recording data and classify the speaker.

Transcript:
{transcript}

Pre-recording answers:
{pre_answers_text}

Metrics:
- Words per minute: {wpm}
- Filler words count: {filler_count}

Classify the speaker as one of:
- "struggler": Speaker shows significant challenges (high fillers, pacing issues, nervousness indicators)
- "strong": Speaker demonstrates confidence and control (low fillers, good pacing, clear delivery)
- "uncertain": Mixed signals or insufficient data to clearly classify

Also provide confidence level:
- "low": Classification is uncertain
- "medium": Reasonable confidence in classification

Respond with ONLY valid JSON in this exact format:
{{
  "classification": "struggler" | "strong" | "uncertain",
  "confidence": "low" | "medium"
}}
"""
        
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a speech analysis assistant. Respond with valid JSON only."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0,
                    max_tokens=1000,
                    response_format={"type": "json_object"}
                )
                
                content = response.choices[0].message.content
                result = json.loads(content)
                
                # Validate structure
                if result.get("classification") in ["struggler", "strong", "uncertain"] and \
                   result.get("confidence") in ["low", "medium"]:
                    return result
                
                # Invalid structure, retry
                if attempt < max_retries:
                    continue
                
            except json.JSONDecodeError:
                if attempt < max_retries:
                    continue
            except Exception as e:
                sentry_sdk.capture_exception(e)
                if attempt < max_retries:
                    continue
        
        # Default fallback
        return {
            "classification": "uncertain",
            "confidence": "low"
        }
    
    def generate_final_report(
        self,
        transcript: str,
        pre_answers: list,
        post_answers: list,
        wpm: float,
        filler_count: int,
        filler_breakdown: dict,
        trend_sentence: str = None,
        user_id: str = None,
        admin_context: dict = None,
        recording_id: str = None
    ):
        """
        Generate final coaching report (≤120 words, enforced via truncation).
        Now includes admin feedback and progress tracking for time-aware analysis.
        """
        # Dev mode mock (COMMENTED OUT - using real OpenAI)
        # if not config.is_production:
        #     return "Mock coaching report: Your speech analysis shows a WPM of {:.1f} and {} filler words. Consider slowing down slightly for better clarity.".format(wpm, filler_count)
        
        # Always use real OpenAI (even in dev mode for testing)
        
        if not self.client:
            raise Exception("OpenAI client not initialized")
        
        # Get admin context if not provided
        if admin_context is None and user_id:
            from services.db import db
            admin_context = db.get_user_admin_context(user_id)
        
        # Get user's recording history for progress tracking
        progress_context = None
        if user_id and recording_id:
            from services.db import db
            previous_recordings = db.get_user_recording_history(user_id, exclude_recording_id=recording_id, limit=10)
            
            if previous_recordings:
                # Calculate progress metrics
                previous_scores = []
                previous_filler_counts = []
                previous_wpm = []
                
                for prev_rec in previous_recordings:
                    # Get performance score
                    perf_score = prev_rec.get("performance_scores")
                    if perf_score and isinstance(perf_score, list) and len(perf_score) > 0:
                        previous_scores.append(float(perf_score[0].get("final_kpi", 0)))
                    elif perf_score and isinstance(perf_score, dict):
                        previous_scores.append(float(perf_score.get("final_kpi", 0)))
                    
                    # Get filler count
                    filler_data = prev_rec.get("filler_words_count", {})
                    if isinstance(filler_data, dict):
                        prev_filler = filler_data.get("total", 0)
                    else:
                        prev_filler = filler_data if filler_data else 0
                    if prev_filler:
                        previous_filler_counts.append(prev_filler)
                    
                    # Get WPM
                    prev_wpm = prev_rec.get("words_per_minute")
                    if prev_wpm:
                        previous_wpm.append(float(prev_wpm))
                
                # Calculate trends
                trend_improving = False
                trend_stable = False
                trend_declining = False
                
                if len(previous_scores) >= 2:
                    recent_count = min(3, len(previous_scores))
                    older_count = min(3, len(previous_scores) - recent_count)
                    if older_count > 0:
                        recent_avg = sum(previous_scores[:recent_count]) / recent_count
                        older_avg = sum(previous_scores[recent_count:recent_count + older_count]) / older_count
                        if recent_avg > older_avg + 0.05:
                            trend_improving = True
                        elif abs(recent_avg - older_avg) < 0.05:
                            trend_stable = True
                        else:
                            trend_declining = True
                
                progress_context = {
                    "total_previous_recordings": len(previous_recordings),
                    "trend_improving": trend_improving,
                    "trend_stable": trend_stable,
                    "trend_declining": trend_declining,
                    "previous_scores": previous_scores,
                    "previous_filler_counts": previous_filler_counts,
                    "previous_wpm": previous_wpm
                }
        
        # Build context
        pre_answers_text = "\n".join([
            f"Q: {ans.get('question_text', '')}\nA: {ans.get('answer_text', '')}"
            for ans in pre_answers
        ])
        
        post_answers_text = "\n".join([
            f"Q: {ans.get('question_text', '')}\nA: {ans.get('answer_text', '')}"
            for ans in post_answers
        ])
        
        # Pacing context for supportive (non-commanding) wording only
        if wpm > 180:
            pacing_note = "pacing was fast; user may benefit from a slower pace"
        elif wpm < 120:
            pacing_note = "pacing was slow; user may benefit from slightly more pace"
        else:
            pacing_note = "pacing was steady; no rushing reported"
        
        # Get max words from admin context or default
        max_words = admin_context.get("max_words", 120) if admin_context else 120
        
        prompt = f"""Generate a concise, analytical coaching report for a speech analysis session.

Transcript:
{transcript[:500]}...

Pre-recording answers:
{pre_answers_text}

Post-recording answers:
{post_answers_text}

Metrics:
- Words per minute: {wpm}
- Filler words count: {filler_count}
- Filler breakdown: {filler_breakdown}
"""
        
        # Add admin observations if available
        if admin_context and admin_context.get("general_notes"):
            prompt += f"""
**Admin Observations:**
{admin_context['general_notes']}

- If the admin explicitly asks to add something to the next coaching message / report (e.g. "add this to the coaching message after the next recording", "include in the next report:", "add to the next coaching message:"), you MUST include that content in this report.
- Otherwise use these when they add value to your analysis (e.g. patterns that match this recording). If not relevant to this session, omit.

"""
        
        # Add custom instructions if available
        if admin_context and admin_context.get("custom_instructions"):
            prompt += f"""
**Admin Custom Instructions:**
{admin_context['custom_instructions']}

- If the admin explicitly asks to add something to the next coaching message / report (e.g. "add this to the coaching message after the next recording", "include in the next report:"), you MUST include that content in this report.
- Otherwise incorporate these when they improve the report for this user. If not applicable to this recording, omit.

"""
        
        # Add progress context for time-aware analysis
        if progress_context:
            prompt += f"""
**User Progress Context:**
- Total previous recordings analyzed: {progress_context['total_previous_recordings']}
- Recent performance trend: {"Improving" if progress_context['trend_improving'] else "Stable" if progress_context['trend_stable'] else "Needs attention"}
"""
            
            if progress_context['previous_scores']:
                avg_score = sum(progress_context['previous_scores']) / len(progress_context['previous_scores'])
                prompt += f"""
- Average performance score: {avg_score:.1%}
- Current performance: Compare to this baseline
"""
            
            if progress_context['previous_filler_counts']:
                avg_fillers = sum(progress_context['previous_filler_counts']) / len(progress_context['previous_filler_counts'])
                if filler_count < avg_fillers:
                    improvement = ((avg_fillers - filler_count) / avg_fillers * 100) if avg_fillers > 0 else 0
                    prompt += f"""
- Filler word improvement: User reduced fillers from average of {avg_fillers:.1f} to {filler_count} ({improvement:.0f}% improvement)
"""
                elif filler_count > avg_fillers:
                    prompt += f"""
- Filler words: Current {filler_count} is above average of {avg_fillers:.1f} - needs attention
"""
            
            if progress_context['previous_wpm']:
                avg_wpm = sum(progress_context['previous_wpm']) / len(progress_context['previous_wpm'])
                prompt += f"""
- Pacing: Average WPM was {avg_wpm:.0f}, current is {wpm:.0f}
"""
        
        # Add specific questions if admin provided them
        if admin_context and admin_context.get("specific_questions"):
            post_questions = [q for q in admin_context['specific_questions'] if q.get('question_type') == 'post']
            if post_questions:
                prompt += f"""
**Admin-Suggested Focus Areas (use when relevant to this recording):**
"""
                for q in post_questions[:3]:  # Limit to 3
                    prompt += f"- {q.get('question_text', '')}\n"
                prompt += "\nWeave in only those that add value to this report; omit if not relevant.\n"
        
        prompt += f"""

**Requirements:**
1. Create a progress-aware report that acknowledges improvements or areas needing work
2. Reference specific changes from previous recordings when relevant (if progress context available)
3. **Admin input:** If the admin explicitly requested that something be added to the coaching message after the next recording (e.g. "add this to the coaching message after the next recording", "include in the next report:"), you MUST include that content in this report. Otherwise use admin observations, custom instructions, and focus areas when you judge them valuable for this report; if not relevant, omit.
4. Include quantitative metrics (WPM and filler count)
5. Pacing: note observations in a supportive way (e.g. "{pacing_note}"); do NOT use commanding language. Describe what you observed; do not tell the user what to do.
6. {"Include trend sentence: " + trend_sentence if trend_sentence else "Do NOT include a trend sentence (insufficient prior data)."}
7. **Tone: supportive and adaptive.** Use supportive, adaptive language (e.g. "I'll analyse your progress and adjust the learning to your needs"). Avoid imperative/commanding phrasing such as "Focus on…", "Consider adjusting…", "you should…". Prefer "we can…", "I'll help you…", "I'll tailor…" instead of "you should…", "consider…", "focus on…".
8. Include a short closing line in that spirit (e.g. "I'll analyse your progress and adjust the learning methods to your needs" or "I'll use this feedback to tailor future sessions to your needs").
9. Maximum {max_words} words (you will be truncated if longer)

Generate the report:"""
        
        try:
            # Supportive, adaptive coach persona (no commanding tone); use admin input when valuable
            system_message = (
                "You are a supportive speech coach. You provide personalized, progress-aware feedback and analyse recordings over time. "
                "Your tone is warm and adaptive, not commanding or prescriptive. "
                "Use supportive, adaptive language (e.g. 'I'll analyse your progress and adjust the learning to your needs'). "
                "Avoid imperative/commanding phrasing: do NOT use 'Focus on…', 'Consider adjusting…', 'you should…'. "
                "Prefer 'we can…', 'I'll help you…', 'I'll tailor…' instead of 'you should…', 'consider…', 'focus on…'. "
                "Acknowledge progress and reference previous recordings when relevant. "
                "When the admin explicitly says to add something to the next coaching message (e.g. 'add this to the coaching message after the next recording', 'include in the next report:'), you MUST include that content in the report. Otherwise incorporate admin input when you decide it is valuable and relevant; if not, omit it. Do not force admin points in when they do not fit. "
                "Convey that you will analyse the user's progress and adjust learning methods to their needs. "
                "Describe what you observed; do not tell the user what to do."
            )
            
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,  # Increased for more personalized responses
                max_tokens=max_words * 2  # Rough token estimate based on max_words
            )
            
            report = response.choices[0].message.content.strip()
            
            # Enforce word limit via truncation (use max_words from admin context or default 120)
            words = report.split()
            if len(words) > max_words:
                report = " ".join(words[:max_words])
            
            return report
        except Exception as e:
            sentry_sdk.capture_exception(e)
            # Return deterministic placeholder
            return "Analysis pending, check back soon."
    
    def generate_suggested_questions(
        self,
        transcript: str,
        pre_answers: list,
        post_answers: list,
        wpm: float,
        filler_count: int,
        report: str
    ):
        """
        Generate 3-5 suggested questions for admin email.
        Returns list of {question_text, tag, rationale}
        """
        if not config.is_production:
            return [
                {
                    "question_text": "How did you feel about your pacing during this recording?",
                    "tag": "reflective",
                    "rationale": "Addresses pacing concerns identified in analysis"
                },
                {
                    "question_text": "What strategies have helped you reduce filler words?",
                    "tag": "amplifying",
                    "rationale": "Builds on strengths in speech delivery"
                }
            ]
        
        if not self.client:
            return []
        
        pre_answers_text = "\n".join([
            f"Q: {ans.get('question_text', '')}\nA: {ans.get('answer_text', '')}"
            for ans in pre_answers
        ])
        
        post_answers_text = "\n".join([
            f"Q: {ans.get('question_text', '')}\nA: {ans.get('answer_text', '')}"
            for ans in post_answers
        ])
        
        prompt = f"""Generate 3-5 suggested follow-up questions for a speech coaching session.

Transcript preview:
{transcript[:300]}...

Pre-recording answers:
{pre_answers_text}

Post-recording answers:
{post_answers_text}

Metrics:
- WPM: {wpm}
- Filler count: {filler_count}

Final report:
{report}

Generate questions that are either:
- "reflective": Help user reflect on challenges
- "amplifying": Help user build on strengths

For each question, provide:
- question_text: The question
- tag: "reflective" or "amplifying"
- rationale: One factual line explaining why this question is relevant

Respond with valid JSON array:
[
  {{
    "question_text": "...",
    "tag": "reflective" | "amplifying",
    "rationale": "..."
  }},
  ...
]
"""
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a speech coaching assistant. Generate relevant follow-up questions."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            data = json.loads(content)
            
            # Extract questions array (handle different response formats)
            questions = data.get("questions", [])
            if not questions and isinstance(data, list):
                questions = data
            
            # Validate and return
            validated = []
            for q in questions[:5]:  # Max 5
                if all(k in q for k in ["question_text", "tag", "rationale"]):
                    if q["tag"] in ["reflective", "amplifying"]:
                        validated.append(q)
            
            return validated if validated else []
        except Exception as e:
            sentry_sdk.capture_exception(e)
            return []

# Singleton instance
openai_service = OpenAIService()
