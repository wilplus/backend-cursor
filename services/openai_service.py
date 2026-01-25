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
        admin_context: dict = None
    ):
        """
        Generate final coaching report (≤120 words, enforced via truncation).
        Now includes admin feedback if available.
        """
        if not config.is_production:
            return "Mock coaching report: Your speech analysis shows a WPM of {:.1f} and {} filler words. Consider slowing down slightly for better clarity.".format(wpm, filler_count)
        
        if not self.client:
            raise Exception("OpenAI client not initialized")
        
        # Get admin context if not provided
        if admin_context is None and user_id:
            from services.db import db
            admin_context = db.get_user_admin_context(user_id)
        
        # Build context
        pre_answers_text = "\n".join([
            f"Q: {ans.get('question_text', '')}\nA: {ans.get('answer_text', '')}"
            for ans in pre_answers
        ])
        
        post_answers_text = "\n".join([
            f"Q: {ans.get('question_text', '')}\nA: {ans.get('answer_text', '')}"
            for ans in post_answers
        ])
        
        # Determine pacing adjustment
        if wpm > 180:
            pacing_instruction = "slow down slightly"
        elif wpm < 120:
            pacing_instruction = "speed up slightly"
        else:
            pacing_instruction = "keep current pace"
        
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
Admin Observations:
{admin_context['general_notes']}

"""
        
        # Add custom instructions if available
        if admin_context and admin_context.get("custom_instructions"):
            prompt += f"""
Custom Analysis Instructions:
{admin_context['custom_instructions']}

"""
        
        prompt += f"""
Requirements:
1. Include quantitative metrics (WPM and filler count)
2. Include exactly ONE pacing adjustment sentence with: "{pacing_instruction}"
3. {"Include trend sentence: " + trend_sentence if trend_sentence else "Do NOT include a trend sentence (insufficient prior data)."}
4. Keep report analytical and neutral (not motivational)
5. Maximum {max_words} words (you will be truncated if longer)

Generate the report:"""
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a speech analysis coach. Generate analytical, neutral reports."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=200
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
